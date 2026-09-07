#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""只为前瞻研究补齐最小行情缓存，避免完整下载器请求无关接口。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import data_downloader as dl  # noqa: E402
import main as stock_main  # noqa: E402
from research.fill_index_daily_range import fill_index_daily  # noqa: E402


def _valid(path: str, minimum_rows: int) -> bool:
    file_path = Path(path)
    if not file_path.exists():
        return False
    try:
        return len(pd.read_parquet(file_path)) >= minimum_rows
    except Exception:
        return False


def download_forward_cache(start_date: str, end_date: str, pause: float = 0.2) -> None:
    pro = stock_main.pro
    dl._ensure_dirs()
    trade_dates = dl._get_trade_dates(pro, start_date, end_date)
    if not trade_dates:
        raise RuntimeError("没有取得目标区间交易日")
    print(f"trade_dates={len(trade_dates)} {trade_dates[0]}..{trade_dates[-1]}")
    for index, trade_date in enumerate(trade_dates, 1):
        daily_path = dl._daily_path("daily", trade_date)
        basic_path = dl._daily_path("daily_basic", trade_date)
        if not _valid(daily_path, 1000):
            daily = dl._retry(lambda date=trade_date: pro.daily(trade_date=date), retries=3, wait=2.0)
            if daily is not None and len(daily) >= 1000:
                dl._save(daily, daily_path)
        if not _valid(basic_path, 1000):
            basic = dl._retry(
                lambda date=trade_date: pro.daily_basic(
                    trade_date=date,
                    fields="ts_code,trade_date,turnover_rate,volume_ratio,total_mv,circ_mv",
                ),
                retries=3,
                wait=2.0,
            )
            if basic is not None and len(basic) >= 1000:
                dl._save(basic, basic_path)
        print(f"[{index:02d}/{len(trade_dates):02d}] {trade_date} daily={_valid(daily_path, 1000)} basic={_valid(basic_path, 1000)}")
        time.sleep(pause)
    fill_index_daily(start_date, end_date, force=False, buffer_days=0, pause=pause)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--pause", type=float, default=0.2)
    args = parser.parse_args()
    download_forward_cache(args.start, args.end, args.pause)


if __name__ == "__main__":
    main()
