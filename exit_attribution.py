"""Trade attribution for conditional exit research.

Usage:
  python exit_attribution.py
  python exit_attribution.py --trades backtest_results/trades_YYYYMMDD_HHMMSS.csv
  python exit_attribution.py --exit-profile baseline --label 2025
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


NUMERIC_COLUMNS = [
    "profit_pct",
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
    "short_score",
    "original_score",
    "score_base",
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_counter_trend",
    "factor_wyckoff",
    "factor_accel",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze baseline trades for conditional exit research.")
    parser.add_argument("--result", default="test_result.json", help="Path to test_result.json.")
    parser.add_argument("--trades", default=None, help="Explicit trades_*.csv path.")
    parser.add_argument("--exit-profile", default="baseline", help="Exit profile to select from test_result.json.")
    parser.add_argument("--label", default=None, help="Substring of result label, e.g. 2025 or 2026Q1.")
    parser.add_argument("--scenario", default="profile_v4_adaptive_quality", help="Scenario to select.")
    parser.add_argument("--top", type=int, default=10, help="Rows to print for top examples.")
    return parser.parse_args()


def load_result(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").replace("Infinity", "null")
    return json.loads(text)


def pick_trades_file(args: argparse.Namespace) -> Path:
    if args.trades:
        return Path(args.trades)

    result = load_result(Path(args.result))
    candidates = []
    for item in result.get("results", []):
        if args.scenario and item.get("scenario") != args.scenario:
            continue
        if args.exit_profile and item.get("exit_profile", "baseline") != args.exit_profile:
            continue
        if args.label and args.label not in item.get("label", ""):
            continue
        if item.get("trades_file"):
            candidates.append(item)

    if not candidates:
        raise SystemExit("No matching trades_file found in test_result.json.")
    return Path("backtest_results") / candidates[-1]["trades_file"]


def load_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "mfe_pct" in df.columns and "profit_pct" in df.columns:
        df["giveback_pct"] = df["mfe_pct"] - df["profit_pct"]
    else:
        df["giveback_pct"] = pd.NA
    return df


def summarize_group(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if group_col not in df.columns or df.empty:
        return pd.DataFrame()
    grouped = df.groupby(group_col, dropna=False).agg(
        trades=("profit_pct", "count"),
        win_rate=("profit_pct", lambda x: round(float((x > 0).mean() * 100), 2)),
        avg_profit=("profit_pct", "mean"),
        avg_mfe=("mfe_pct", "mean"),
        avg_mae=("mae_pct", "mean"),
        avg_giveback=("giveback_pct", "mean"),
    )
    return grouped.round(2).sort_values("trades", ascending=False)


def compare_sets(df: pd.DataFrame, left_mask: pd.Series, right_mask: pd.Series, left_name: str, right_name: str) -> pd.DataFrame:
    cols = [col for col in NUMERIC_COLUMNS if col in df.columns]
    rows = []
    left = df[left_mask]
    right = df[right_mask]
    for col in cols:
        if left[col].dropna().empty or right[col].dropna().empty:
            continue
        rows.append(
            {
                "field": col,
                left_name: round(float(left[col].mean()), 2),
                right_name: round(float(right[col].mean()), 2),
                "diff": round(float(left[col].mean() - right[col].mean()), 2),
            }
        )
    return pd.DataFrame(rows).sort_values("diff", key=lambda s: s.abs(), ascending=False)


def print_table(title: str, df: pd.DataFrame, max_rows: int = 20) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    if df.empty:
        print("(empty)")
    else:
        print(df.head(max_rows).to_string())


def main() -> None:
    args = parse_args()
    trades_path = pick_trades_file(args)
    df = load_trades(trades_path)
    if df.empty:
        raise SystemExit("Trades file is empty.")

    high_mfe = df["mfe_pct"] >= 5
    high_mfe_loser = high_mfe & (df["profit_pct"] <= 0)
    big_giveback = (df["mfe_pct"] >= 8) & (df["giveback_pct"] >= 6)
    profitable_runner = (df["profit_pct"] >= 5) | ((df["mfe_pct"] >= 10) & (df["profit_pct"] > 0))
    trailing_bad = (df.get("exit_reason", "") == "trailing_stop") & (df["profit_pct"] <= 0)
    take_profit_good = df.get("exit_reason", "").isin(["take_profit", "take_profit_next_open"])

    print(f"Trades file: {trades_path}")
    print(f"Trades: {len(df)}")
    print(f"Win rate: {(df['profit_pct'] > 0).mean() * 100:.2f}%")
    print(f"Avg profit: {df['profit_pct'].mean():.2f}%")
    print(f"Avg MFE/MAE/giveback: {df['mfe_pct'].mean():.2f}% / {df['mae_pct'].mean():.2f}% / {df['giveback_pct'].mean():.2f}%")
    print(f"High MFE losers: {int(high_mfe_loser.sum())}/{int(high_mfe.sum())}")
    print(f"Big giveback trades: {int(big_giveback.sum())}")

    print_table("By Exit Reason", summarize_group(df, "exit_reason"))
    print_table("By Market Style", summarize_group(df, "market_style"))
    print_table("By Macro Mode", summarize_group(df, "macro_mode"))

    print_table(
        "High-MFE Losers vs Profitable Runners",
        compare_sets(df, high_mfe_loser, profitable_runner, "high_mfe_loser", "profitable_runner"),
    )
    print_table(
        "Bad Trailing Stop vs Good Take Profit",
        compare_sets(df, trailing_bad, take_profit_good, "bad_trailing", "good_take_profit"),
    )

    show_cols = [
        c
        for c in [
            "ts_code",
            "name",
            "select_date",
            "profit_pct",
            "mfe_pct",
            "mae_pct",
            "giveback_pct",
            "exit_reason",
            "market_style",
            "macro_mode",
            "short_score",
            "factor_pattern",
            "factor_sector",
            "volume_ratio",
            "drawdown_from_high",
        ]
        if c in df.columns
    ]
    print_table("Worst High-MFE Losers", df[high_mfe_loser].sort_values("profit_pct")[show_cols], args.top)
    print_table("Largest Givebacks", df[big_giveback].sort_values("giveback_pct", ascending=False)[show_cols], args.top)

    print("\nNext research hint:")
    print("- If bad trailing names have weaker pattern/sector/volume than good take-profit names, test conditional trailing only for that subset.")
    print("- If they are similar, keep baseline exit and focus on entry/factor quality instead.")


if __name__ == "__main__":
    main()
