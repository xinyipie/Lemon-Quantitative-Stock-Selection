"""
event_study_catchup.py — 补涨效应事件研究

验证核心假设：板块出现≥2只涨停后，当日滞涨股（涨幅<2%）在T+1/T+2的实际收益。
扣除跳开幅度后，补涨效应是否仍然存在？

运行：python event_study_catchup.py
输出：event_study_result.json + 控制台汇总
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime

CACHE_DIR = 'data/cache'
DAILY_DIR = os.path.join(CACHE_DIR, 'daily')

# ── 参数 ──
LIMIT_UP_THRESHOLD = 9.5   # 涨停定义：涨幅≥9.5%
LEADER_MIN_COUNT   = 2     # 板块至少有N只涨停才算"启动"
LAG_MAX_CHANGE     = 2.0   # 滞涨股：当日涨幅<2%
LAG_MIN_CHANGE     = -5.0  # 排除大跌股（可能有个股利空）
START_DATE         = '20230101'
END_DATE           = '20251231'


def load_stock_basic():
    """加载行业映射"""
    path = os.path.join(CACHE_DIR, 'stock_basic.parquet')
    sb = pd.read_parquet(path)
    if 'industry' not in sb.columns:
        raise ValueError("stock_basic 无 industry 列")
    # ts_code 可能在列里也可能在index里
    if 'ts_code' in sb.columns:
        return sb.set_index('ts_code')['industry'].to_dict()
    else:
        return sb['industry'].to_dict()


def get_sorted_dates():
    """获取缓存中所有交易日，过滤到研究区间"""
    files = [f[:-8] for f in os.listdir(DAILY_DIR) if f.endswith('.parquet')]
    dates = sorted([d for d in files if START_DATE <= d <= END_DATE])
    return dates


def load_daily(date):
    """加载某日daily数据，返回DataFrame或None"""
    path = os.path.join(DAILY_DIR, f'{date}.parquet')
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        return df
    except Exception:
        return None


def get_price_map(df, col):
    """安全地从df提取 {ts_code: value} 映射"""
    if df is None or df.empty or col not in df.columns or 'ts_code' not in df.columns:
        return {}
    return df.set_index('ts_code')[col].to_dict()


def main():
    print("=" * 60)
    print("  补涨效应事件研究（2023~2025）")
    print(f"  参数：涨停≥{LIMIT_UP_THRESHOLD}%，板块≥{LEADER_MIN_COUNT}只")
    print(f"       滞涨定义：{LAG_MIN_CHANGE}%~{LAG_MAX_CHANGE}%")
    print("=" * 60)

    # 加载行业映射
    print("\n[1] 加载行业映射...", end=' ')
    ind_map = load_stock_basic()
    print(f"{len(ind_map)} 只股票")

    # 获取所有交易日
    dates = get_sorted_dates()
    print(f"[2] 交易日：{dates[0]} ~ {dates[-1]}，共 {len(dates)} 天")

    # ── 遍历每个交易日，收集补涨事件 ──
    events = []
    skipped_no_open = 0

    for i, date in enumerate(dates[:-2]):  # 需要T+1、T+2
        t1_date = dates[i + 1]
        t2_date = dates[i + 2]

        # 加载T日数据
        df_t = load_daily(date)
        if df_t is None or df_t.empty:
            continue
        if 'pct_chg' not in df_t.columns or 'ts_code' not in df_t.columns:
            continue
        if 'close' not in df_t.columns:
            continue

        # 打行业标签
        df_t = df_t.copy()
        df_t['industry'] = df_t['ts_code'].map(ind_map)
        df_t = df_t.dropna(subset=['industry', 'pct_chg', 'close'])
        df_t = df_t[df_t['close'] > 0]

        # 找有≥N只涨停的板块
        limit_up_df = df_t[df_t['pct_chg'] >= LIMIT_UP_THRESHOLD]
        sector_leader_cnt = limit_up_df.groupby('industry').size()
        active_sectors = sector_limit_counts = sector_leader_cnt[
            sector_leader_cnt >= LEADER_MIN_COUNT
        ].to_dict()

        if not active_sectors:
            continue

        # 找滞涨股（在活跃板块里、未涨停、涨幅在区间内）
        laggards = df_t[
            (df_t['industry'].isin(active_sectors.keys())) &
            (df_t['pct_chg'] < LAG_MAX_CHANGE) &
            (df_t['pct_chg'] >= LAG_MIN_CHANGE)
        ]

        if laggards.empty:
            continue

        # 加载T+1、T+2价格
        df_t1 = load_daily(t1_date)
        df_t2 = load_daily(t2_date)

        t_close_map  = get_price_map(df_t,  'close')
        t1_open_map  = get_price_map(df_t1, 'open')
        t1_close_map = get_price_map(df_t1, 'close')
        t2_open_map  = get_price_map(df_t2, 'open')
        t2_close_map = get_price_map(df_t2, 'close')

        # 检查open列是否存在（第一次时打印提示）
        if not t1_open_map and i == 0:
            print("\n⚠️  T+1 open 列缺失，将用 pct_chg 反推开盘价")

        for _, row in laggards.iterrows():
            code = row['ts_code']
            t_close  = t_close_map.get(code)
            t1_open  = t1_open_map.get(code)
            t1_close = t1_close_map.get(code)
            t2_open  = t2_open_map.get(code)
            t2_close = t2_close_map.get(code)

            # open列若缺失则跳过（需要开盘价才能计算"扣跳开后"的收益）
            if t1_open is None:
                skipped_no_open += 1
                continue
            if not all([t_close, t1_open, t1_close]):
                continue
            if t_close <= 0 or t1_open <= 0:
                continue

            # ── 核心计算 ──
            gap_pct            = (t1_open  - t_close)  / t_close  * 100  # T+1跳开幅度
            ret_intraday_t1    = (t1_close - t1_open)  / t1_open  * 100  # T+1日内（买开盘→收盘）
            ret_t1_total       = (t1_close - t_close)  / t_close  * 100  # T收盘→T+1收盘（含跳开）
            ret_2d             = (t2_close - t1_open)  / t1_open  * 100 if t2_close else None  # 持2天
            ret_t2_open        = (t2_open  - t1_open)  / t1_open  * 100 if t2_open  else None  # T+2开盘

            # T+1是否涨停（涨停则实际可能买不到或高价成交）
            t1_pct = df_t1.set_index('ts_code')['pct_chg'].to_dict().get(code, 0) if df_t1 is not None else 0

            events.append({
                'date':           date,
                't1_date':        t1_date,
                'code':           code,
                'industry':       row['industry'],
                'n_leaders':      int(active_sectors.get(row['industry'], 0)),
                'today_chg':      round(float(row['pct_chg']), 2),
                'gap_pct':        round(gap_pct, 2),
                'ret_intraday_t1': round(ret_intraday_t1, 2),
                'ret_t1_total':   round(ret_t1_total, 2),
                'ret_2d':         round(ret_2d, 2) if ret_2d is not None else None,
                'ret_t2_open':    round(ret_t2_open, 2) if ret_t2_open is not None else None,
                't1_limit_up':    t1_pct >= 9.5,   # T+1是否涨停（补涨成功的极端情况）
                'year':           date[:4],
                'month':          date[:6],
            })

        if (i + 1) % 100 == 0:
            print(f"  进度：{i+1}/{len(dates)-2} 天，事件 {len(events)} 个")

    print(f"\n[3] 事件收集完成：共 {len(events)} 个补涨候选事件")
    if skipped_no_open:
        print(f"    ⚠️  因缺少open价格跳过：{skipped_no_open} 条")

    if not events:
        print("❌ 无事件，检查数据格式")
        return

    df = pd.DataFrame(events)

    # ── 汇总函数 ──
    def summarize(subset, label):
        if subset.empty:
            print(f"\n【{label}】无数据")
            return {}
        n = len(subset)

        gap        = subset['gap_pct']
        intra      = subset['ret_intraday_t1'].dropna()
        two_d      = subset['ret_2d'].dropna()
        t1_total   = subset['ret_t1_total'].dropna()

        win_intra  = (intra > 0).mean() * 100
        win_2d     = (two_d > 0).mean() * 100
        limit_rate = subset['t1_limit_up'].mean() * 100

        print(f"\n{'─'*55}")
        print(f"【{label}】  N={n:,}")
        print(f"  ① 跳开幅度    均值={gap.mean():+.2f}%  中位数={gap.median():+.2f}%"
              f"  >2%占比={( gap>=2.0).mean()*100:.1f}%  >0%占比={(gap>=0).mean()*100:.1f}%")
        print(f"  ② T+1涨停率  {limit_rate:.1f}%（补涨极端成功，但往往买不到）")
        print(f"  ③ 买T+1开→T+1收（日内）")
        print(f"     均值={intra.mean():+.2f}%  中位数={intra.median():+.2f}%"
              f"  胜率={win_intra:.1f}%"
              f"  P25={np.percentile(intra,25):+.2f}%  P75={np.percentile(intra,75):+.2f}%")
        print(f"  ④ 买T+1开→T+2收（持2天）")
        print(f"     均值={two_d.mean():+.2f}%  中位数={two_d.median():+.2f}%"
              f"  胜率={win_2d:.1f}%"
              f"  P25={np.percentile(two_d,25):+.2f}%  P75={np.percentile(two_d,75):+.2f}%")
        print(f"  ⑤ T收盘→T+1收盘（含跳开，参考）  均值={t1_total.mean():+.2f}%")

        return {
            'n':                n,
            'avg_gap':          round(gap.mean(), 3),
            'median_gap':       round(gap.median(), 3),
            'gap_over2_pct':    round((gap >= 2.0).mean() * 100, 1),
            'gap_positive_pct': round((gap >= 0).mean() * 100, 1),
            't1_limit_rate':    round(limit_rate, 1),
            'intraday_t1': {
                'mean':    round(intra.mean(), 3),
                'median':  round(intra.median(), 3),
                'win_rate': round(win_intra, 1),
                'p25':     round(np.percentile(intra, 25), 3),
                'p75':     round(np.percentile(intra, 75), 3),
            },
            'two_day': {
                'mean':    round(two_d.mean(), 3),
                'median':  round(two_d.median(), 3),
                'win_rate': round(win_2d, 1),
                'p25':     round(np.percentile(two_d, 25), 3),
                'p75':     round(np.percentile(two_d, 75), 3),
            },
        }

    # ── 输出汇总 ──
    print("\n" + "=" * 55)
    print("  事件研究结果")
    print("=" * 55)

    all_results = {}

    # 全量
    all_results['全部（2023~2025）'] = summarize(df, '全部事件（2023~2025）')

    # 按年
    for year in ['2023', '2024', '2025']:
        sub = df[df['year'] == year]
        all_results[year] = summarize(sub, f'{year}年')

    # 按板块领涨强度分层
    for n_lead in [2, 3, 5]:
        key = f'板块≥{n_lead}只涨停'
        all_results[key] = summarize(df[df['n_leaders'] >= n_lead], key)

    # 按今日个股涨幅分层（最核心的细分）
    splits = [
        ('今日微跌（<0%）',         df['today_chg'] <  0),
        ('今日几乎没动（0%~1%）',   (df['today_chg'] >= 0)  & (df['today_chg'] <  1)),
        ('今日小涨（1%~2%）',       (df['today_chg'] >= 1)  & (df['today_chg'] <  2)),
    ]
    for label, mask in splits:
        all_results[label] = summarize(df[mask], label)

    # 关键结论：扣除跳开的真实可得收益
    gap_ok = df[df['gap_pct'] < 1.0]
    all_results['跳开<1%（低开/平开，真实可买）'] = summarize(gap_ok, '跳开<1%（低开/平开，实际可买）')

    # 按年×是否低开 交叉分析
    for year in ['2023', '2024', '2025']:
        sub = df[(df['year'] == year) & (df['gap_pct'] < 1.0)]
        key = f'{year}年 且 跳开<1%'
        all_results[key] = summarize(sub, key)

    # ── 结论性提示 ──
    print("\n" + "=" * 55)
    print("  核心判断标准")
    print("=" * 55)
    overall = all_results.get('全部（2023~2025）', {})
    avg_gap  = overall.get('avg_gap', 0)
    avg_2d   = overall.get('two_day', {}).get('mean', 0)
    win_2d   = overall.get('two_day', {}).get('win_rate', 0)

    print(f"  平均跳开：{avg_gap:+.2f}%")
    print(f"  买入开盘持2天均值：{avg_2d:+.2f}%  胜率：{win_2d:.1f}%")
    print()
    if avg_2d > 0.5 and win_2d > 45:
        print("  ✅ 补涨效应存在，扣跳开后仍有正收益 → 继续优化选股")
    elif avg_2d > 0 and win_2d > 42:
        print("  ⚠️  补涨效应微弱，边际有效 → 需要精选信号，否则手续费会吃光收益")
    else:
        print("  ❌ 补涨效应不显著或为负 → 建议换策略方向")

    # 保存 JSON
    output = {
        'run_time':     datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'params': {
            'limit_up_threshold': LIMIT_UP_THRESHOLD,
            'leader_min_count':   LEADER_MIN_COUNT,
            'lag_max_change':     LAG_MAX_CHANGE,
            'lag_min_change':     LAG_MIN_CHANGE,
            'date_range':         f'{START_DATE}~{END_DATE}',
        },
        'total_events': len(events),
        'results':      all_results,
    }
    with open('event_study_result.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完整结果已保存：event_study_result.json")


if __name__ == '__main__':
    main()
