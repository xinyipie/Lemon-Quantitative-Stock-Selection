"""
批量回测 + IC 品质报告
======================
对短线和波段两种策略，分别在多个时间段跑回测，
然后输出 IC 分析汇总表，评估选股品质。

用法：
  python batch_backtest.py             # 默认：2024 / 2025 / 全段，短线+波段
  python batch_backtest.py --mode short      # 只跑短线
  python batch_backtest.py --mode longterm   # 只跑波段
  python batch_backtest.py --skip-backtest   # 只做 IC 分析（跳过耗时的回测，用已有CSV）

输出：
  backtest_results/batch_summary_YYYYMMDD_HHMMSS.csv   ← IC汇总表
  （每次回测生成各自的 trades_*.csv、equity_*.csv）
"""

import os
import sys
import glob
import json
import logging
import argparse
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd
import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger("batch_backtest")

CACHE_DIR   = os.path.join("data", "cache")
OUTPUT_DIR  = "backtest_results"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ==================== 数据范围探测 ====================

def detect_data_range() -> Tuple[str, str]:
    """从本地 daily parquet 文件探测最早/最晚可用日期"""
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "daily", "*.parquet")))
    if not files:
        logger.error("data/cache/daily/ 下没有 parquet 文件，请先运行 data_downloader.py")
        sys.exit(1)
    dates = sorted([os.path.splitext(os.path.basename(f))[0] for f in files])
    return dates[0], dates[-1]


def build_periods(data_start: str, data_end: str) -> List[dict]:
    """
    根据可用数据范围自动构建回测区间列表。
    规则：
      - 若数据覆盖整年 → 加该年全年
      - 若只有部分年 → 加实际覆盖区间
      - 最后加"全段"
    保证每段至少 40 个交易日（否则样本太少，IC 无意义）。
    """
    start_y = int(data_start[:4])
    end_y   = int(data_end[:4])

    periods = []

    for y in range(start_y, end_y + 1):
        y_start = max(data_start, f"{y}0101")
        y_end   = min(data_end,   f"{y}1231")
        label   = f"{y}年"
        periods.append({'label': label, 'start': y_start, 'end': y_end})

    # 全段（仅在超过 1 个自然年时才有意义）
    if end_y > start_y:
        periods.append({'label': '全段', 'start': data_start, 'end': data_end})

    return periods


# ==================== 回测调用（调用 backtest_v2.py 的接口）====================

def _get_offline_pro():
    """初始化 LocalDataProxy 并注入到 main.py，返回 proxy 实例（仅初始化一次）"""
    import backtest_v2 as bv2
    from local_data_proxy import LocalDataProxy
    proxy = LocalDataProxy(cache_dir=CACHE_DIR)
    bv2.stock_main.set_pro(proxy)
    logger.info("✅ 已注入 LocalDataProxy（离线模式）")
    return proxy


_offline_pro = None   # 模块级单例，避免重复初始化


def run_one_backtest(mode: str, start: str, end: str, label: str) -> Optional[str]:
    """
    在当前进程内直接调用 BacktestV2 / BacktestLongterm（离线模式），
    返回生成的 trades CSV 路径，失败返回 None。
    """
    global _offline_pro
    import backtest_v2 as bv2

    if _offline_pro is None:
        _offline_pro = _get_offline_pro()
    pro = _offline_pro

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    try:
        if mode == 'short':
            engine = bv2.BacktestV2(
                pro                  = pro,
                start_date           = start,
                end_date             = end,
                hold_days            = 5,
                top_n                = 3,
                fallback_stop_pct    = -7.0,
                fallback_profit_pct  = 15.0,
                trailing_stop_pct    = 7.0,
                use_market_timing    = False,   # 纯验证选股质量，不叠加大盘择时
                min_open_ratio       = 0.0,     # 允许低开买入，不过滤任何信号
            )
        else:  # longterm
            engine = bv2.BacktestLongterm(
                pro                  = pro,
                start_date           = start,
                end_date             = end,
                max_hold_days        = 60,
                top_n                = 3,
                fallback_stop_pct    = -12.0,
                fallback_profit_pct  = 50.0,
                trailing_stop_pct    = 10.0,
                trailing_activate_pct= 25.0,
                time_stop_days       = 20,
                time_stop_threshold  = -3.0,
                use_market_timing    = False,   # 纯验证选股质量
                min_open_ratio       = 0.0,     # 允许低开买入
            )

        trades_df, metrics, equity_df = engine.run()

        if trades_df.empty:
            logger.warning(f"  [{label} {mode}] 无交易记录")
            return None

        # 保存 CSV
        trades_path = os.path.join(OUTPUT_DIR, f"trades_{mode}_{label}_{ts}.csv")
        trades_df.to_csv(trades_path, index=False, encoding='utf-8-sig')

        equity_path = os.path.join(OUTPUT_DIR, f"equity_{mode}_{label}_{ts}.csv")
        equity_df.to_csv(equity_path, index=False, encoding='utf-8-sig')

        metrics_path = os.path.join(OUTPUT_DIR, f"metrics_{mode}_{label}_{ts}.json")
        with open(metrics_path, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)

        logger.info(
            f"  [{label} {mode}] 完成：{len(trades_df)}笔  "
            f"胜率{metrics.get('win_rate',0):.1f}%  "
            f"总收益{metrics.get('total_return_pct',0):+.2f}%  "
            f"→ {trades_path}"
        )
        return trades_path

    except Exception as e:
        logger.error(f"  [{label} {mode}] 回测失败：{e}", exc_info=True)
        return None


# ==================== IC 计算（从 ic_analysis.py 复用核心逻辑）====================

def _load_daily(date: str, cache: dict) -> pd.DataFrame:
    if date not in cache:
        path = os.path.join(CACHE_DIR, "daily", f"{date}.parquet")
        if not os.path.exists(path):
            cache[date] = pd.DataFrame()
        else:
            try:
                df = pd.read_parquet(path, columns=['ts_code', 'close'])
            except Exception:
                # 空文件或列不存在（无数据的交易日）
                try:
                    df = pd.read_parquet(path)
                    if 'ts_code' not in df.columns or 'close' not in df.columns:
                        df = pd.DataFrame()
                except Exception:
                    df = pd.DataFrame()
            cache[date] = df
    return cache[date]


def _get_trade_dates_local() -> List[str]:
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "daily", "*.parquet")))
    return [os.path.splitext(os.path.basename(f))[0] for f in files]


def compute_ic_summary(trades_csv: str, horizons: List[int] = (10, 20)) -> dict:
    """
    给定一个 trades CSV，计算各持有期的 IC 及相关指标，返回汇总字典。
    """
    df = pd.read_csv(trades_csv, dtype={'buy_date': str, 'ts_code': str})
    if df.empty or len(df) < 5:
        return {'n_trades': 0}

    # 确定评分列
    score_col = 'longterm_score' if 'longterm_score' in df.columns else None
    if score_col is None:
        # 无评分列时用 rank 占位（IC 值无意义，但其余指标仍有效）
        score_col = '_dummy'
        df[score_col] = range(len(df))

    all_dates = _get_trade_dates_local()
    daily_cache: dict = {}

    result = {'n_trades': len(df), 'has_score': score_col != '_dummy'}

    for n in horizons:
        fwd_col = f'fwd_{n}d'
        rets = []
        for _, row in df.iterrows():
            ts_code  = row['ts_code']
            buy_date = str(row['buy_date'])

            # 找 buy_date 在交易日历中的位置
            try:
                idx = all_dates.index(buy_date)
            except ValueError:
                cands = [d for d in all_dates if d >= buy_date]
                if not cands:
                    rets.append(np.nan); continue
                idx = all_dates.index(cands[0])

            # 基准收盘价（买入日）
            base_df = _load_daily(all_dates[idx], daily_cache)
            row_b   = base_df[base_df['ts_code'] == ts_code] if not base_df.empty and 'ts_code' in base_df.columns else pd.DataFrame()
            if row_b.empty:
                rets.append(np.nan); continue
            base_close = float(row_b.iloc[0]['close'])

            # 前瞻收盘价
            fwd_idx = idx + n
            if fwd_idx >= len(all_dates):
                rets.append(np.nan); continue
            fwd_df  = _load_daily(all_dates[fwd_idx], daily_cache)
            row_f   = fwd_df[fwd_df['ts_code'] == ts_code] if not fwd_df.empty and 'ts_code' in fwd_df.columns else pd.DataFrame()
            if row_f.empty:
                rets.append(np.nan); continue
            fwd_close = float(row_f.iloc[0]['close'])

            rets.append((fwd_close - base_close) / base_close * 100)

        df[fwd_col] = rets
        valid = df[fwd_col].notna()
        n_valid = valid.sum()

        if n_valid < 5:
            result[f'ic_{n}d'] = np.nan
            result[f'hit_{n}d'] = np.nan
            result[f'avg_ret_{n}d'] = np.nan
            continue

        # Spearman IC
        scores = df.loc[valid, score_col]
        fwds   = df.loc[valid, fwd_col]
        if scores.nunique() > 1:
            ic, pval = stats.spearmanr(scores, fwds)
        else:
            ic, pval = np.nan, np.nan

        result[f'ic_{n}d']      = round(ic, 4) if not np.isnan(ic) else np.nan
        result[f'pval_{n}d']    = round(pval, 4) if not np.isnan(pval) else np.nan
        result[f'hit_{n}d']     = round((fwds > 0).sum() / n_valid * 100, 1)
        result[f'avg_ret_{n}d'] = round(fwds.mean(), 2)

        # 分位差（高分组 - 低分组平均涨幅，只在有评分时有意义）
        if score_col != '_dummy' and n_valid >= 10:
            try:
                terciles = pd.qcut(df.loc[valid, score_col], q=3,
                                   labels=['低', '中', '高'], duplicates='drop')
                g = df.loc[valid].copy()
                g['q'] = terciles
                grp = g.groupby('q', observed=True)[fwd_col].mean()
                if '高' in grp.index and '低' in grp.index:
                    result[f'spread_{n}d'] = round(grp['高'] - grp['低'], 2)
                else:
                    result[f'spread_{n}d'] = np.nan
            except Exception:
                result[f'spread_{n}d'] = np.nan
        else:
            result[f'spread_{n}d'] = np.nan

    return result


# ==================== 汇总打印 ====================

def print_summary_table(rows: List[dict]):
    """打印汇总对比表"""
    if not rows:
        print("  无有效数据")
        return

    horizons = [10, 20]

    header_cols = ['策略', '时间段', '交易笔数']
    for n in horizons:
        header_cols += [f'{n}日IC', f'{n}日胜率%', f'{n}日均涨幅%', f'{n}日高低分差%']

    print("\n" + "=" * 100)
    print("  批量回测 IC 品质汇总")
    print("=" * 100)
    print(f"  {'策略':<8} {'时间段':<10} {'笔数':>5}", end='')
    for n in horizons:
        print(f"  {n}日IC{'':<4} {n}日胜率 {n}日均收益 {n}日高低差", end='')
    print()
    print("  " + "-" * 96)

    for r in rows:
        n_trades = r.get('n_trades', 0)
        if n_trades == 0:
            print(f"  {r.get('mode','?'):<8} {r.get('label','?'):<10} {'无数据':>5}")
            continue
        print(f"  {r.get('mode','?'):<8} {r.get('label','?'):<10} {n_trades:>5}", end='')
        for n in horizons:
            ic   = r.get(f'ic_{n}d', np.nan)
            hit  = r.get(f'hit_{n}d', np.nan)
            avgr = r.get(f'avg_ret_{n}d', np.nan)
            sprd = r.get(f'spread_{n}d', np.nan)

            ic_str   = f"{ic:+.4f}" if not (isinstance(ic, float) and np.isnan(ic)) else "  N/A "
            hit_str  = f"{hit:.1f}%" if not (isinstance(hit, float) and np.isnan(hit)) else " N/A  "
            avgr_str = f"{avgr:+.2f}%" if not (isinstance(avgr, float) and np.isnan(avgr)) else "  N/A  "
            sprd_str = f"{sprd:+.2f}%" if not (isinstance(sprd, float) and np.isnan(sprd)) else "  N/A  "

            print(f"  {ic_str:<8} {hit_str:<8} {avgr_str:<9} {sprd_str:<8}", end='')
        print()

    print("=" * 100)
    print("  说明：高低分差 = 高分1/3组平均涨幅 - 低分1/3组平均涨幅（正值=评分有效）")
    print("        IC > 0.05 = 选股有实质预测力  |  IC > 0.10 = 优秀")


# ==================== 主流程 ====================

def main():
    parser = argparse.ArgumentParser(description='批量回测 + IC 品质分析')
    parser.add_argument('--mode',  choices=['short', 'longterm', 'both'],
                        default='both', help='回测模式（默认 both）')
    parser.add_argument('--skip-backtest', action='store_true',
                        help='跳过回测，直接对 backtest_results/ 下已有 CSV 做 IC 分析')
    parser.add_argument('--forward', type=int, nargs='+', default=[10, 20],
                        metavar='N', help='IC 前瞻天数（默认 10 20）')
    args = parser.parse_args()

    modes = ['short', 'longterm'] if args.mode == 'both' else [args.mode]

    # ── 探测数据范围 ──
    data_start, data_end = detect_data_range()
    logger.info(f"可用数据：{data_start} ~ {data_end}")

    periods = build_periods(data_start, data_end)
    logger.info(f"回测区间：{[p['label'] for p in periods]}")

    rows = []  # 用于最终汇总表

    if not args.skip_backtest:
        # ── 逐区间、逐模式运行回测 ──
        total = len(periods) * len(modes)
        done  = 0
        for period in periods:
            for mode in modes:
                done += 1
                label = period['label']
                start = period['start']
                end   = period['end']
                logger.info(f"\n[{done}/{total}] === {mode} | {label} ({start}~{end}) ===")

                trades_csv = run_one_backtest(mode, start, end, label)
                row = {'mode': mode, 'label': label, 'start': start, 'end': end,
                       'trades_csv': trades_csv or ''}

                if trades_csv:
                    ic_data = compute_ic_summary(trades_csv, horizons=args.forward)
                    row.update(ic_data)

                rows.append(row)
    else:
        # ── 仅 IC 分析：扫描已有 CSV ──
        logger.info("跳过回测，扫描 backtest_results/ 下已有 trades_*.csv ...")
        csv_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "trades_*.csv")))
        # 过滤掉 _ic.csv 结尾的衍生文件
        csv_files = [f for f in csv_files if not f.endswith('_ic.csv')]
        logger.info(f"找到 {len(csv_files)} 个 trades CSV")

        for csv_path in csv_files:
            fname = os.path.basename(csv_path)
            # 从文件名猜测模式和标签
            if 'short' in fname:
                mode = 'short'
            elif 'longterm' in fname:
                mode = 'longterm'
            else:
                mode = 'unknown'
            label = fname.replace('trades_', '').replace('.csv', '')

            logger.info(f"  分析 {fname} ...")
            ic_data = compute_ic_summary(csv_path, horizons=args.forward)
            row = {'mode': mode, 'label': label, 'trades_csv': csv_path}
            row.update(ic_data)
            rows.append(row)

    # ── 打印汇总表 ──
    print_summary_table(rows)

    # ── 保存汇总 CSV ──
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    summary_path = os.path.join(OUTPUT_DIR, f"batch_summary_{ts}.csv")
    pd.DataFrame(rows).to_csv(summary_path, index=False, encoding='utf-8-sig')
    logger.info(f"\n汇总已保存：{summary_path}")


if __name__ == '__main__':
    main()
