#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按报告期批量下载历史财务快照，供无未来函数研究使用。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


FIELDS = "ts_code,ann_date,end_date,roe,debt_to_assets,netprofit_yoy"
QUARTER_ENDS = ("0331", "0630", "0930", "1231")


def periods(start_year: int, end_year: int, end_period: str) -> list[str]:
    result = []
    for year in range(start_year, end_year + 1):
        for suffix in QUARTER_ENDS:
            value = f"{year}{suffix}"
            if value <= end_period:
                result.append(value)
    return result


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    required = FIELDS.split(",")
    if frame is None or frame.empty:
        return pd.DataFrame(columns=required)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"财务接口缺少字段: {missing}")
    work = frame[required].copy()
    for column in ("ann_date", "end_date"):
        work[column] = work[column].astype("string").str.replace(r"\.0$", "", regex=True)
    work = work[
        work["ann_date"].str.fullmatch(r"\d{8}", na=False)
        & work["end_date"].str.fullmatch(r"\d{8}", na=False)
    ]
    return work.drop_duplicates(["ts_code", "ann_date", "end_date"], keep="last").reset_index(drop=True)


def download(pro, requested: list[str], output_dir: Path, retries: int = 3, pause: float = 0.25) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, period in enumerate(requested, 1):
        path = output_dir / f"{period}.parquet"
        if path.exists() and path.stat().st_size > 100:
            frame = normalize(pd.read_parquet(path))
            print(f"[{index}/{len(requested)}] cached {period}: {len(frame)}")
            frames.append(frame)
            continue
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                frame = normalize(pro.fina_indicator(period=period, fields=FIELDS))
                if frame.empty:
                    raise RuntimeError("接口返回空数据")
                frame.to_parquet(path, index=False)
                print(f"[{index}/{len(requested)}] downloaded {period}: {len(frame)}")
                frames.append(frame)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(attempt * 2)
        if last_error is not None:
            raise RuntimeError(f"报告期 {period} 下载失败") from last_error
        time.sleep(pause)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FIELDS.split(","))
    return normalize(combined)


def main() -> None:
    parser = argparse.ArgumentParser(description="批量下载历史财务指标快照")
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--end-period", default="20260630")
    parser.add_argument("--pause", type=float, default=0.25)
    args = parser.parse_args()

    import main as stock_main

    output_dir = ROOT / "data" / "cache" / "fina_indicator_history"
    requested = periods(args.start_year, args.end_year, args.end_period)
    combined = download(stock_main.pro, requested, output_dir, pause=args.pause)
    output = ROOT / "data" / "cache" / "fina_indicator_history.parquet"
    combined.to_parquet(output, index=False)
    print(
        f"saved={output} rows={len(combined)} stocks={combined['ts_code'].nunique()} "
        f"ann={combined['ann_date'].min()}..{combined['ann_date'].max()}"
    )


if __name__ == "__main__":
    main()
