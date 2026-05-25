"""
IC 分析（信息系数）— 评估选股评分的预测能力
==========================================================
原理：
  IC = rank(score) 与 rank(未来N日涨幅) 的 Spearman 相关系数
  评分列自动识别：short_score（短线）> longterm_score（波段）> profit_after_fee

  IC > 0.05：选股评分有实用价值
  IC > 0.10：优秀，行业前列
  IC ≈ 0   ：评分几乎是随机的，需要重新设计

用法：
  # 分析最新一次回测结果（自动选最新CSV，自动识别评分列）
  python ic_analysis.py

  # 指定某次回测
  python ic_analysis.py --trades backtest_results/trades_20260417_183114.csv

  # 使用固定持有期（不用实际出场时间），更纯粹地评估选股质量
  python ic_analysis.py --forward 5 10 20

  # 批量分析 backtest_results/ 下所有 CSV，输出汇总表
  python ic_analysis.py --batch
  python ic_analysis.py --batch --forward 5 10 20
"""

import os
import sys
import glob
import argparse
import logging
from typing import List, Optional

import pandas as pd
import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger("ic_analysis")

CACHE_DIR = os.path.join("data", "cache")


# ==================== 工具函数 ====================

def find_latest_trades_csv() -> Optional[str]:
    """自动找最新的 trades_*.csv"""
    pattern = os.path.join("backtest_results", "trades_*.csv")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files)   # 文件名含时间戳，最大值即最新


def load_trades(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={'buy_date': str, 'sell_date': str, 'ts_code': str})
    logger.info(f"读取交易记录：{len(df)} 笔  来自 {csv_path}")
    return df


def pick_score_col(df: pd.DataFrame, use_profit: bool = False) -> str:
    """自动选评分列：short_score（短线）> longterm_score（波段）> profit_after_fee"""
    if use_profit:
        return 'profit_after_fee'
    if 'short_score' in df.columns and df['short_score'].gt(0).any():
        return 'short_score'
    if 'longterm_score' in df.columns and df['longterm_score'].gt(0).any():
        return 'longterm_score'
    logger.warning("未找到有效评分列（short_score/longterm_score均为0），降级使用 profit_after_fee")
    return 'profit_after_fee'


def load_daily_for_date(date: str) -> pd.DataFrame:
    """从本地 daily parquet 读取全市场日线"""
    path = os.path.join(CACHE_DIR, "daily", f"{date}.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, columns=['ts_code', 'close'])
    except Exception:
        # 空文件或列不存在
        try:
            df = pd.read_parquet(path)
            return df[['ts_code', 'close']] if 'ts_code' in df.columns and 'close' in df.columns else pd.DataFrame()
        except Exception:
            return pd.DataFrame()


def get_trade_calendar() -> List[str]:
    """获取已下载的所有交易日（升序）"""
    daily_dir = os.path.join(CACHE_DIR, "daily")
    files = glob.glob(os.path.join(daily_dir, "*.parquet"))
    dates = sorted([os.path.splitext(os.path.basename(f))[0] for f in files])
    return dates


def get_close_after_n_days(ts_code: str, buy_date: str,
                           n: int, all_dates: List[str],
                           daily_cache: dict) -> Optional[float]:
    """
    获取 buy_date 之后第 n 个交易日的收盘价。
    daily_cache: {date_str: DataFrame}，全量日线，按需加载。
    """
    try:
        buy_idx = all_dates.index(buy_date)
    except ValueError:
        # buy_date 不在交易日历（可能是数据缺失），退化到最近日
        candidates = [d for d in all_dates if d >= buy_date]
        if not candidates:
            return None
        buy_idx = all_dates.index(candidates[0])

    target_idx = buy_idx + n
    if target_idx >= len(all_dates):
        return None

    target_date = all_dates[target_idx]

    if target_date not in daily_cache:
        daily_cache[target_date] = load_daily_for_date(target_date)

    df = daily_cache[target_date]
    if df.empty or 'ts_code' not in df.columns:
        return None

    row = df[df['ts_code'] == ts_code]
    if row.empty:
        return None
    return float(row.iloc[0]['close'])


def get_buy_close(ts_code: str, buy_date: str, daily_cache: dict) -> Optional[float]:
    """获取买入日收盘价（作为基准价，避免用 buy_price 引入滑点偏差）"""
    if buy_date not in daily_cache:
        daily_cache[buy_date] = load_daily_for_date(buy_date)
    df = daily_cache[buy_date]
    if df.empty or 'ts_code' not in df.columns:
        return None
    row = df[df['ts_code'] == ts_code]
    if row.empty:
        return None
    return float(row.iloc[0]['close'])


# ==================== 核心计算 ====================

def compute_ic_for_horizon(df: pd.DataFrame, n: int, all_dates: List[str],
                            score_col: str = 'longterm_score') -> pd.DataFrame:
    """
    计算每笔交易 n 日后的实际涨幅，返回含 forward_ret_N 列的 DataFrame。
    """
    daily_cache: dict = {}
    logger.info(f"  计算 {n} 日前瞻收益...")

    forward_rets = []
    for _, row in df.iterrows():
        ts_code  = row['ts_code']
        buy_date = str(row['buy_date'])

        base_close = get_buy_close(ts_code, buy_date, daily_cache)
        fwd_close  = get_close_after_n_days(ts_code, buy_date, n, all_dates, daily_cache)

        if base_close and fwd_close and base_close > 0:
            ret = (fwd_close - base_close) / base_close * 100
        else:
            ret = np.nan
        forward_rets.append(ret)

    return forward_rets


def spearman_ic(scores: pd.Series, forward_rets: pd.Series) -> float:
    """计算 Spearman IC，自动去除 NaN"""
    mask = scores.notna() & forward_rets.notna()
    if mask.sum() < 5:
        return np.nan
    corr, _ = stats.spearmanr(scores[mask], forward_rets[mask])
    return corr


def hit_rate(forward_rets: pd.Series, threshold: float = 0.0) -> float:
    """涨幅 > threshold 的比例（hit rate）"""
    valid = forward_rets.dropna()
    if len(valid) == 0:
        return np.nan
    return (valid > threshold).sum() / len(valid)


def compute_benchmark_ret(n: int, all_dates: List[str], start: str, end: str) -> float:
    """CSI300（000300.SH）同期收益率（简单近似：取区间首尾）"""
    index_path = os.path.join(CACHE_DIR, "index_daily")
    dfs = []
    for d in all_dates:
        if d < start or d > end:
            continue
        p = os.path.join(index_path, f"{d}.parquet")
        if os.path.exists(p):
            df = pd.read_parquet(p)
            if not df.empty:
                row = df[df['ts_code'] == '000300.SH']
                if not row.empty:
                    dfs.append({'date': d, 'close': float(row.iloc[0]['close'])})
    if len(dfs) < 2:
        return np.nan
    idx_df = pd.DataFrame(dfs).sort_values('date')
    return (idx_df.iloc[-1]['close'] - idx_df.iloc[0]['close']) / idx_df.iloc[0]['close'] * 100


# ==================== 主分析 ====================

def run_analysis(trades_csv: str, horizons: List[int], use_profit: bool = False):
    df = load_trades(trades_csv)
    score_col = pick_score_col(df, use_profit)
    logger.info(f"使用评分列：{score_col}")

    all_dates = get_trade_calendar()
    if not all_dates:
        logger.error("找不到 data/cache/daily/*.parquet，请先运行 data_downloader.py")
        sys.exit(1)
    logger.info(f"交易日历：{all_dates[0]} ~ {all_dates[-1]}  共{len(all_dates)}天")

    # 添加月份列（用于按月分组）
    df['month'] = pd.to_datetime(df['buy_date'].astype(str), format='%Y%m%d').dt.to_period('M')

    print("\n" + "=" * 68)
    print("  IC 分析报告（信息系数 — 评估选股评分预测能力）")
    print("=" * 68)
    print(f"  样本数：{len(df)} 笔  评分列：{score_col}")
    print(f"  评分统计：min={df[score_col].min():.1f}  max={df[score_col].max():.1f}"
          f"  均值={df[score_col].mean():.1f}  中位数={df[score_col].median():.1f}")
    print("=" * 68)

    for n in horizons:
        col = f'fwd_{n}d'
        df[col] = compute_ic_for_horizon(df, n, all_dates, score_col)

        valid_mask = df[col].notna()
        valid_n = valid_mask.sum()

        ic_val  = spearman_ic(df[score_col], df[col])
        hit_0   = hit_rate(df.loc[valid_mask, col], threshold=0.0)
        hit_csi = None   # CSI300 同期
        mean_ret = df.loc[valid_mask, col].mean()
        median_ret = df.loc[valid_mask, col].median()

        # t检验 IC 显著性
        if valid_n > 5 and not np.isnan(ic_val):
            t_stat = ic_val * np.sqrt(valid_n - 2) / np.sqrt(1 - ic_val**2 + 1e-9)
            p_val  = 2 * (1 - stats.t.cdf(abs(t_stat), df=valid_n - 2))
        else:
            t_stat, p_val = np.nan, np.nan

        # 评级
        if np.isnan(ic_val):
            grade = "N/A"
        elif ic_val >= 0.10:
            grade = "★★★ 优秀"
        elif ic_val >= 0.05:
            grade = "★★  良好"
        elif ic_val >= 0.02:
            grade = "★   可用"
        else:
            grade = "✗   无效"

        print(f"\n── {n} 日持有期 ─────────────────────────────────────────")
        print(f"  样本数（有前瞻数据）：{valid_n}")
        print(f"  IC（Spearman）：  {ic_val:+.4f}   {grade}")
        if not np.isnan(p_val):
            print(f"  显著性：          t={t_stat:.2f}  p={p_val:.4f}  {'显著(p<0.05)' if p_val<0.05 else '不显著'}")
        print(f"  平均前瞻涨幅：    {mean_ret:+.2f}%")
        print(f"  中位数前瞻涨幅：  {median_ret:+.2f}%")
        print(f"  胜率（涨幅>0）：  {hit_0*100:.1f}%")

        # 按月份计算 IC
        monthly_ics = []
        for month, grp in df[valid_mask].groupby('month'):
            m_ic = spearman_ic(grp[score_col], grp[col])
            monthly_ics.append({'month': str(month), 'ic': m_ic, 'n': len(grp)})

        if monthly_ics:
            m_df = pd.DataFrame(monthly_ics).dropna(subset=['ic'])
            if not m_df.empty:
                ic_mean = m_df['ic'].mean()
                ic_std  = m_df['ic'].std()
                ir = ic_mean / ic_std if ic_std > 0 else np.nan  # IC 信息比率
                pos_months = (m_df['ic'] > 0).sum()
                print(f"\n  按月 IC 统计（共{len(m_df)}月）：")
                print(f"    月均IC = {ic_mean:+.4f}   IC标准差 = {ic_std:.4f}   IC_IR = {ir:.2f}")
                print(f"    IC>0 月份比例 = {pos_months}/{len(m_df)} = {pos_months/len(m_df)*100:.0f}%")
                print(f"\n  月度明细：")
                print(f"  {'月份':<10} {'样本':>4} {'IC':>8}")
                print(f"  {'-'*26}")
                for _, mrow in m_df.iterrows():
                    flag = "✓" if mrow['ic'] > 0 else "✗"
                    print(f"  {mrow['month']:<10} {mrow['n']:>4} {mrow['ic']:>+8.4f}  {flag}")

        # 分位数分析（高分 vs 低分）
        if valid_n >= 10:
            score_vals = df.loc[valid_mask, score_col]
            n_unique = score_vals.nunique()
            n_bins = min(3, n_unique)   # 唯一值不足3个时降级
            labels_map = {1: ['全部'], 2: ['低分', '高分'], 3: ['低分', '中分', '高分']}
            try:
                q_col = pd.qcut(score_vals, q=n_bins,
                                labels=labels_map[n_bins], duplicates='drop')
                quintile_stats = df.loc[valid_mask].copy()
                quintile_stats['分位'] = q_col
                qt = quintile_stats.groupby('分位', observed=True)[col].agg(['mean', 'count'])
                print(f"\n  评分分位 vs 涨幅（{n}日）：")
                for q_name, q_row in qt.iterrows():
                    print(f"    {q_name}：样本{int(q_row['count'])}笔  平均涨幅 {q_row['mean']:+.2f}%")
            except ValueError:
                print(f"\n  评分分位 vs 涨幅：唯一值不足，跳过")

    # 输出增强后的 CSV（去掉已有 _ic 后缀再加，避免叠加）
    base = trades_csv.replace('_ic.csv', '.csv').replace('.csv', '')
    out_path = base + '_ic.csv'
    df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n{'='*68}")
    print(f"  详细数据已保存：{out_path}")
    print("=" * 68)


# ==================== 批量分析 ====================

def run_batch(horizons: List[int]):
    """批量分析 backtest_results/ 下所有 trades_*.csv，输出汇总表"""
    pattern = os.path.join("backtest_results", "trades_*.csv")
    all_files = sorted([f for f in glob.glob(pattern) if '_ic.csv' not in f])
    if not all_files:
        print("未找到任何 trades_*.csv，请先运行回测。")
        sys.exit(1)

    print(f"\n找到 {len(all_files)} 个CSV文件，开始批量IC分析...\n")

    all_dates = get_trade_calendar()
    if not all_dates:
        print("找不到本地日线数据，请先运行 data_downloader.py")
        sys.exit(1)

    all_rows: list = []
    for fpath in all_files:
        fname = os.path.basename(fpath)
        print(f"  分析：{fname}")
        try:
            df = pd.read_csv(fpath, dtype={'buy_date': str, 'ts_code': str})
        except Exception as e:
            print(f"  ⚠️  读取失败：{fname}  ({e})")
            continue

        score_col = pick_score_col(df)
        if score_col == 'profit_after_fee':
            print(f"  ⏭️  跳过（无有效评分列）：{fname}")
            continue

        n_trades = len(df)
        daily_cache: dict = {}
        row_base = {'文件': fname, '评分列': score_col, '笔数': n_trades}

        for n in horizons:
            fwd_rets = []
            for _, r in df.iterrows():
                base = get_buy_close(r['ts_code'], str(r['buy_date']), daily_cache)
                fwd  = get_close_after_n_days(r['ts_code'], str(r['buy_date']), n, all_dates, daily_cache)
                fwd_rets.append((fwd - base) / base * 100 if base and fwd and base > 0 else np.nan)

            fwd_s = pd.Series(fwd_rets)
            valid_n = fwd_s.notna().sum()
            ic_val  = spearman_ic(df[score_col], fwd_s)
            hr_val  = hit_rate(fwd_s)
            avg_val = fwd_s.dropna().mean()

            spread = np.nan
            if valid_n >= 9:
                tmp = df[[score_col]].copy()
                tmp['fwd'] = fwd_s
                tmp = tmp.dropna()
                n3 = len(tmp) // 3
                if n3 > 0:
                    spread = tmp.nlargest(n3, score_col)['fwd'].mean() - \
                             tmp.nsmallest(n3, score_col)['fwd'].mean()

            row_base[f'有效样本_{n}d'] = valid_n
            row_base[f'IC_{n}d']     = round(ic_val, 4) if not np.isnan(ic_val) else None
            row_base[f'胜率_{n}d']   = round(hr_val * 100, 1) if not np.isnan(hr_val) else None
            row_base[f'均涨_{n}d']   = round(avg_val, 2) if not np.isnan(avg_val) else None
            row_base[f'高低分差_{n}d'] = round(spread, 2) if not np.isnan(spread) else None

        all_rows.append(row_base)

    if not all_rows:
        print("没有有效结果。")
        sys.exit(1)

    result_df = pd.DataFrame(all_rows).sort_values('文件').reset_index(drop=True)

    print("\n" + "=" * 100)
    print("  批量IC分析汇总")
    print("=" * 100)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    print(result_df.to_string(index=False))

    print("\n" + "=" * 100)
    print("  IC评级参考：> 0.10=优秀  0.05~0.10=良好  0.02~0.05=可用  < 0.02=无效")
    for n in horizons:
        col = f'IC_{n}d'
        if col in result_df.columns:
            valid = result_df[col].dropna()
            if len(valid) > 0:
                print(f"  {n}日IC — 均值：{valid.mean():+.4f}  中位：{valid.median():+.4f}"
                      f"  最高：{valid.max():+.4f}  最低：{valid.min():+.4f}")

    out_path = os.path.join("backtest_results", "ic_batch_summary.csv")
    result_df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n  结果已保存：{out_path}")
    print("=" * 100)


# ==================== 入口 ====================

def main():
    parser = argparse.ArgumentParser(description='IC分析 — 评估选股评分的预测能力（自动识别 short_score/longterm_score）')
    parser.add_argument('--trades', type=str, default=None,
                        help='trades CSV 路径（默认自动选最新）')
    parser.add_argument('--forward', type=int, nargs='+', default=[5, 10, 20],
                        metavar='N', help='前瞻持有天数（默认：5 10 20）')
    parser.add_argument('--use-profit', action='store_true',
                        help='强制用 profit_after_fee 代替评分列（兼容旧CSV）')
    parser.add_argument('--batch', action='store_true',
                        help='批量分析 backtest_results/ 下所有 CSV，输出汇总表')
    args = parser.parse_args()

    if args.batch:
        run_batch(args.forward)
        return

    csv_path = args.trades or find_latest_trades_csv()
    if not csv_path:
        logger.error("未找到 backtest_results/trades_*.csv，请先运行 backtest_v2.py")
        sys.exit(1)

    logger.info(f"分析文件：{csv_path}")
    run_analysis(csv_path, args.forward, args.use_profit)


if __name__ == '__main__':
    main()
