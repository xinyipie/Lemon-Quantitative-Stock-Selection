"""在干净全市场面板上追加无未来函数的主力资金流特征。"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PRICE_DIR = ROOT / "data" / "research" / "clean_all_market"
MONEYFLOW_DIR = ROOT / "data" / "cache" / "moneyflow"
OUTPUT_DIR = ROOT / "data" / "research" / "clean_moneyflow"
WARMUP_ROWS_PER_STOCK = 10
FLOW_COLUMNS = [
    "net_mf_amount",
    "flow_ratio_1d",
    "flow_ratio_3d",
    "flow_ratio_5d",
    "flow_positive_days_5d",
    "flow_acceleration_3v5",
]


def load_moneyflow_for_dates(dates: list[str]) -> pd.DataFrame:
    """批量读取指定交易日的主力净流入，并显式补交易日字段。"""

    frames: list[pd.DataFrame] = []
    for trade_date in dates:
        path = MONEYFLOW_DIR / f"{trade_date}.parquet"
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path, columns=["ts_code", "net_mf_amount"])
        except Exception:
            continue
        if frame.empty:
            continue
        frame = frame.copy()
        frame["trade_date"] = trade_date
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ts_code", "net_mf_amount", "trade_date"]
    )


def add_moneyflow_features(panel: pd.DataFrame) -> pd.DataFrame:
    """按股票时间升序计算 1/3/5 日资金流特征。"""

    work = panel.sort_values(["ts_code", "trade_date"], kind="mergesort").copy()
    work["net_mf_amount"] = pd.to_numeric(work["net_mf_amount"], errors="coerce")
    work["amount"] = pd.to_numeric(work["amount"], errors="coerce")
    work["flow_amount_cny_thousand"] = work["net_mf_amount"] * 10.0
    valid_amount = work["amount"].where(work["amount"] > 0)
    work["flow_ratio_1d"] = work["flow_amount_cny_thousand"] / valid_amount
    grouped = work.groupby("ts_code", sort=False, group_keys=False)
    flow_3 = grouped["flow_amount_cny_thousand"].rolling(3, min_periods=3).sum().reset_index(level=0, drop=True)
    amount_3 = grouped["amount"].rolling(3, min_periods=3).sum().reset_index(level=0, drop=True)
    flow_5 = grouped["flow_amount_cny_thousand"].rolling(5, min_periods=5).sum().reset_index(level=0, drop=True)
    amount_5 = grouped["amount"].rolling(5, min_periods=5).sum().reset_index(level=0, drop=True)
    positive = work["net_mf_amount"].gt(0).astype(float)
    work["flow_ratio_3d"] = flow_3 / amount_3.where(amount_3 > 0)
    work["flow_ratio_5d"] = flow_5 / amount_5.where(amount_5 > 0)
    work["flow_positive_days_5d"] = (
        positive.groupby(work["ts_code"], sort=False)
        .rolling(5, min_periods=5)
        .sum()
        .reset_index(level=0, drop=True)
    )
    work["flow_acceleration_3v5"] = work["flow_ratio_3d"] - work["flow_ratio_5d"]
    return work.drop(columns=["flow_amount_cny_thousand"])


def build_year(year: int) -> pd.DataFrame:
    """带前一年末尾预热构建单年资金流面板。"""

    current_path = PRICE_DIR / f"{year}.parquet"
    if not current_path.exists():
        raise FileNotFoundError(current_path)
    current = pd.read_parquet(current_path)
    current["trade_date"] = current["trade_date"].astype(str)
    frames = [current]
    previous_path = PRICE_DIR / f"{year - 1}.parquet"
    if previous_path.exists():
        previous = pd.read_parquet(previous_path)
        previous["trade_date"] = previous["trade_date"].astype(str)
        previous = (
            previous.sort_values(["ts_code", "trade_date"], kind="mergesort")
            .groupby("ts_code", group_keys=False)
            .tail(WARMUP_ROWS_PER_STOCK)
        )
        frames.insert(0, previous)
    combined = pd.concat(frames, ignore_index=True)
    dates = sorted(combined["trade_date"].unique().tolist())
    moneyflow = load_moneyflow_for_dates(dates)
    combined = combined.merge(
        moneyflow, on=["trade_date", "ts_code"], how="left", validate="one_to_one"
    )
    enriched = add_moneyflow_features(combined)
    return enriched[enriched["trade_date"].str[:4].astype(int).eq(year)].reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建干净资金流研究库")
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2024)
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for year in range(args.start_year, args.end_year + 1):
        output = OUTPUT_DIR / f"{year}.parquet"
        panel = build_year(year)
        panel.to_parquet(output, index=False)
        coverage = float(panel["net_mf_amount"].notna().mean()) if len(panel) else 0.0
        print(
            f"year={year} rows={len(panel)} flow_coverage={coverage:.2%} saved={output}",
            flush=True,
        )


if __name__ == "__main__":
    main()
