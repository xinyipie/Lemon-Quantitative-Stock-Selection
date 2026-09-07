from __future__ import annotations

import argparse
import collections
from pathlib import Path

import pandas as pd


DATASETS = ("daily", "daily_basic", "moneyflow", "index_daily")


def collect_dates(cache_dir: Path, dataset: str) -> list[str]:
    folder = cache_dir / dataset
    if not folder.exists():
        return []
    return sorted(path.stem for path in folder.glob("*.parquet") if len(path.stem) == 8)


def build_rows(cache_dir: Path) -> list[dict]:
    rows = []
    for dataset in DATASETS:
        dates = collect_dates(cache_dir, dataset)
        counts = collections.Counter(date[:4] for date in dates)
        for year in sorted(counts):
            year_dates = [date for date in dates if date.startswith(year)]
            rows.append(
                {
                    "dataset": dataset,
                    "year": year,
                    "trading_days": counts[year],
                    "first_date": min(year_dates),
                    "last_date": max(year_dates),
                }
            )
        if not dates:
            rows.append(
                {
                    "dataset": dataset,
                    "year": "",
                    "trading_days": 0,
                    "first_date": "",
                    "last_date": "",
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit local ten-year cache coverage.")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output", default="backtest_results/ten_year_cache_coverage.csv")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    rows = build_rows(cache_dir)
    df = pd.DataFrame(rows)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False, encoding="utf-8-sig")
    print(df.to_string(index=False))
    print(f"saved: {output}")


if __name__ == "__main__":
    main()
