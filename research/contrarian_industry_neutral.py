#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将全市场逆向候选转换为每日行业分散候选池。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


INPUT = ROOT / "reports" / "research" / "full_market_contrarian_top50_20260808.csv"
OUTPUT = ROOT / "reports" / "research" / "full_market_contrarian_industry_neutral_20260808.csv"


def build_industry_neutral_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    """每个交易日每个行业只保留逆向基础分最高的一只股票。"""
    result = frame.copy()
    result["trade_date"] = result["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    result["industry_bucket"] = result.get("industry", pd.Series(index=result.index, dtype=object)).fillna("未知行业").astype(str)
    result["contrarian_score"] = pd.to_numeric(result["contrarian_score"], errors="coerce")
    result = result.sort_values(
        ["trade_date", "industry_bucket", "contrarian_score", "ts_code"],
        ascending=[True, True, False, True],
    )
    result = result.drop_duplicates(["trade_date", "industry_bucket"], keep="first")
    result["engine"] = "contrarian_industry_neutral"
    result["engine_score"] = result["contrarian_score"]
    result["engine_rank"] = result.groupby("trade_date")["engine_score"].rank(method="first", ascending=False)
    return result.sort_values(["trade_date", "engine_rank", "ts_code"]).reset_index(drop=True)


def run(input_path: Path = INPUT, output_path: Path = OUTPUT) -> None:
    frame = pd.read_csv(input_path, encoding="utf-8-sig", low_memory=False)
    result = build_industry_neutral_candidates(frame)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"input_rows={len(frame)} output_rows={len(result)} dates={result['trade_date'].nunique()}")
    print(f"wrote={output_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
