#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Supplement cache fields required by long-horizon value/quality research."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pandas as pd


FINA_FIELDS = (
    "ts_code,ann_date,end_date,roe,roe_dt,roa,netprofit_yoy,"
    "grossprofit_margin,netprofit_margin,debt_to_assets,current_ratio,"
    "quick_ratio,ocfps,ocf_to_or,ocf_to_profit"
)
INCOME_FIELDS = "ts_code,ann_date,end_date,revenue,n_income,total_profit,operate_profit"
DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,turnover_rate,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,"
    "dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv"
)


def quarter_periods(start_year: int, end_year: int) -> list[str]:
    periods = []
    for year in range(start_year, end_year + 1):
        for suffix in ["0331", "0630", "0930", "1231"]:
            periods.append(f"{year}{suffix}")
    return periods


def read_parquet_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def save_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")


def merge_static_cache(old: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if old is None or old.empty:
        merged = new.copy()
    elif new is None or new.empty:
        merged = old.copy()
    else:
        merged = pd.concat([old, new], ignore_index=True, sort=False)
    if merged.empty:
        return merged
    for key in ["ann_date", "end_date", "period", "f_ann_date"]:
        if key in merged.columns:
            merged[key] = merged[key].astype(str).str.replace("-", "").str[:8]
    merged = merged.drop_duplicates(subset=[k for k in keys if k in merged.columns], keep="last")
    sort_cols = [c for c in ["ts_code", "end_date", "ann_date"] if c in merged.columns]
    return merged.sort_values(sort_cols).reset_index(drop=True) if sort_cols else merged.reset_index(drop=True)


def merge_daily_basic_cache(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if old is None or old.empty:
        return new.copy()
    if new is None or new.empty:
        return old.copy()
    base = old.set_index("ts_code")
    extra = new.set_index("ts_code")
    merged = base.combine_first(extra)
    merged.update(extra)
    return merged.reset_index()


def retry_call(fn, retries: int = 3, wait: float = 3.0):
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == retries:
                print(f"ERROR: failed after {retries} retries: {exc}")
                return pd.DataFrame()
            print(f"WARN: call failed ({attempt}/{retries}): {exc}; retry in {wait}s")
            time.sleep(wait)
    return pd.DataFrame()


def get_pro():
    import main as stock_main

    return stock_main.pro


def download_period_financials(pro, api_name: str, fields: str, periods: list[str], sleep_seconds: float) -> pd.DataFrame:
    frames = []
    api = getattr(pro, api_name)
    for idx, period in enumerate(periods, 1):
        print(f"[{idx:03d}/{len(periods):03d}] {api_name} period={period}")
        df = retry_call(lambda p=period: api(period=p, fields=fields))
        if df is not None and not df.empty:
            frames.append(df)
            print(f"  rows={len(df)}")
        else:
            print("  rows=0")
        time.sleep(sleep_seconds)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def load_trade_dates(cache_dir: Path, start: str, end: str) -> list[str]:
    trade_cal = read_parquet_or_empty(cache_dir / "trade_cal.parquet")
    if trade_cal.empty:
        raise SystemExit("缺少 trade_cal.parquet，请先用 data_downloader.py 下载基础行情。")
    dates = trade_cal["cal_date"].astype(str).str.replace("-", "").str[:8]
    if "is_open" in trade_cal.columns:
        trade_cal = trade_cal[trade_cal["is_open"].astype(int) == 1]
        dates = trade_cal["cal_date"].astype(str).str.replace("-", "").str[:8]
    return sorted(d for d in dates.tolist() if start <= d <= end)


def supplement_daily_basic(pro, cache_dir: Path, start: str, end: str, force: bool, sleep_seconds: float) -> None:
    dates = load_trade_dates(cache_dir, start, end)
    out_dir = cache_dir / "daily_basic"
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, date in enumerate(dates, 1):
        path = out_dir / f"{date}.parquet"
        old = read_parquet_or_empty(path)
        has_valuation = not old.empty and {"pe", "pb", "total_mv", "circ_mv"}.issubset(old.columns)
        if has_valuation and not force:
            continue
        print(f"[{idx:03d}/{len(dates):03d}] daily_basic {date}")
        new = retry_call(lambda d=date: pro.daily_basic(trade_date=d, fields=DAILY_BASIC_FIELDS))
        if new is None or new.empty:
            print("  rows=0")
            continue
        merged = merge_daily_basic_cache(old, new)
        save_parquet(merged, path)
        print(f"  saved rows={len(merged)} cols={len(merged.columns)}")
        time.sleep(sleep_seconds)


def supplement_financials(
    pro,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    force: bool,
    sleep_seconds: float,
) -> None:
    periods = quarter_periods(start_year, end_year)

    fina_path = cache_dir / "fina_indicator.parquet"
    old_fina = pd.DataFrame() if force else read_parquet_or_empty(fina_path)
    new_fina = download_period_financials(pro, "fina_indicator", FINA_FIELDS, periods, sleep_seconds)
    merged_fina = merge_static_cache(old_fina, new_fina, keys=["ts_code", "end_date", "ann_date"])
    save_parquet(merged_fina, fina_path)
    print(f"fina_indicator saved: rows={len(merged_fina)} stocks={merged_fina['ts_code'].nunique() if not merged_fina.empty else 0}")

    income_path = cache_dir / "income.parquet"
    old_income = pd.DataFrame() if force else read_parquet_or_empty(income_path)
    new_income = download_period_financials(pro, "income", INCOME_FIELDS, periods, sleep_seconds)
    merged_income = merge_static_cache(old_income, new_income, keys=["ts_code", "end_date", "ann_date"])
    save_parquet(merged_income, income_path)
    print(f"income saved: rows={len(merged_income)} stocks={merged_income['ts_code'].nunique() if not merged_income.empty else 0}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Supplement long-term value/quality research data.")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--financial-start-year", type=int, default=2021)
    parser.add_argument("--financial-end-year", type=int, default=2026)
    parser.add_argument("--daily-basic-start", default=None)
    parser.add_argument("--daily-basic-end", default=None)
    parser.add_argument("--skip-financial", action="store_true")
    parser.add_argument("--skip-daily-basic", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite old financial files and redownload daily_basic valuation fields.")
    parser.add_argument("--sleep", type=float, default=0.35)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cache_dir = Path(args.cache_dir)
    if not cache_dir.exists():
        raise SystemExit(f"缓存目录不存在：{cache_dir}")
    pro = get_pro()
    if not args.skip_financial:
        supplement_financials(
            pro=pro,
            cache_dir=cache_dir,
            start_year=args.financial_start_year,
            end_year=args.financial_end_year,
            force=args.force,
            sleep_seconds=args.sleep,
        )
    if not args.skip_daily_basic:
        if not args.daily_basic_start or not args.daily_basic_end:
            raise SystemExit("补 daily_basic 估值字段时必须传 --daily-basic-start 和 --daily-basic-end")
        supplement_daily_basic(
            pro=pro,
            cache_dir=cache_dir,
            start=args.daily_basic_start,
            end=args.daily_basic_end,
            force=args.force,
            sleep_seconds=args.sleep,
        )


if __name__ == "__main__":
    main()
