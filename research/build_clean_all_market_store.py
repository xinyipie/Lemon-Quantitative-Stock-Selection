#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建T日信号与未来结果分离的全市场研究特征库。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.all_market_multi_engine_research import _available_dates, _build_regimes, _load_stock_info, build_year_panel  # noqa: E402
from research.no_future_signal_pipeline import signal_eligible_mask  # noqa: E402


CACHE = ROOT / "data" / "cache"
OUTPUT_DIR = ROOT / "data" / "research" / "clean_all_market"
STORE_COLUMNS = [
    "ts_code", "name", "industry", "trade_date", "open", "high", "low", "close", "synthetic_close", "pct_chg", "amount",
    "history_count", "ret_5", "ret_10", "ret_20", "ret_60", "ma_5", "ma_10", "ma_20", "ma_60",
    "prior_high_20", "drawdown_20", "rsi_14", "volatility_20", "turnover_rate", "volume_ratio",
    "industry_rs_20", "regime", "entry_open", "entry_gap_pct", "ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d",
]


def clean_panel(panel: pd.DataFrame) -> pd.DataFrame:
    work = panel.loc[signal_eligible_mask(panel, min_history=120)].copy()
    missing = [column for column in STORE_COLUMNS if column not in work.columns]
    for column in missing:
        work[column] = pd.NA
    return work[STORE_COLUMNS].sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建干净全市场特征库")
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2021)
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # 起始年度也需要完整预热，不能从当年第一天才开始累计 history_count。
    dates = _available_dates(CACHE, f"{args.start_year - 1}0101", "20260807")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    for year in range(args.start_year, args.end_year + 1):
        path = OUTPUT_DIR / f"{year}.parquet"
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", f"{year}1231")
        clean = clean_panel(panel)
        clean.to_parquet(path, index=False)
        print(f"year={year} panel={len(panel)} clean={len(clean)} saved={path}")


if __name__ == "__main__":
    main()
