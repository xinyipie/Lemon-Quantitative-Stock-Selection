"""Compare two backtest trade files and explain changed selections.

Usage:
  python trade_diff_diagnostics.py --base backtest_results/trades_x.csv --experiment backtest_results/trades_y.csv
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


RETURN_COLS = ["profit_after_fee", "profit_pct", "return_pct", "pnl_pct", "profit"]
SHOW_COLS = [
    "select_date",
    "buy_date",
    "ts_code",
    "name",
    "profit_after_fee",
    "short_score",
    "original_score",
    "score_base",
    "factor_pattern",
    "factor_sector",
    "drawdown_from_high",
    "volume_ratio",
    "exit_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare changed trades between two backtest CSV files.")
    parser.add_argument("--base", required=True, help="Baseline trades_*.csv file.")
    parser.add_argument("--experiment", required=True, help="Experiment trades_*.csv file.")
    parser.add_argument("--output", default=None, help="Markdown report path.")
    parser.add_argument("--top", type=int, default=20, help="Rows to show in changed-trade tables.")
    return parser.parse_args()


def load_trades(path: str | Path) -> pd.DataFrame:
    return normalize_trades(pd.read_csv(path, encoding="utf-8-sig"))


def normalize_trades(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "ts_code" not in out.columns:
        raise ValueError("Trade file must contain ts_code.")

    if "select_date" in out.columns:
        date_col = "select_date"
    elif "buy_date" in out.columns:
        date_col = "buy_date"
    else:
        raise ValueError("Trade file must contain select_date or buy_date.")

    out["_diff_date"] = out[date_col].astype(str)
    out["ts_code"] = out["ts_code"].astype(str)
    out["_trade_key"] = out["_diff_date"] + "|" + out["ts_code"]
    out["_return_pct"] = pd.to_numeric(out[pick_return_col(out)], errors="coerce").fillna(0.0)

    for col in [
        "profit_after_fee",
        "short_score",
        "original_score",
        "score_base",
        "factor_pattern",
        "factor_sector",
        "drawdown_from_high",
        "volume_ratio",
    ]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def pick_return_col(df: pd.DataFrame) -> str:
    for col in RETURN_COLS:
        if col in df.columns:
            return col
    raise ValueError(f"No return column found. Expected one of: {', '.join(RETURN_COLS)}")


def compare_trades(base: pd.DataFrame, experiment: pd.DataFrame) -> dict[str, pd.DataFrame | dict[str, float | int]]:
    base_df = normalize_trades(base)
    exp_df = normalize_trades(experiment)
    base_keys = set(base_df["_trade_key"])
    exp_keys = set(exp_df["_trade_key"])

    removed = base_df[base_df["_trade_key"].isin(base_keys - exp_keys)].copy()
    added = exp_df[exp_df["_trade_key"].isin(exp_keys - base_keys)].copy()
    common_base = base_df[base_df["_trade_key"].isin(base_keys & exp_keys)].copy()

    summary = {
        "base_trades": int(len(base_df)),
        "experiment_trades": int(len(exp_df)),
        "common_trades": int(len(common_base)),
        "removed_trades": int(len(removed)),
        "added_trades": int(len(added)),
        "removed_total_return_pct": sum_return(removed),
        "added_total_return_pct": sum_return(added),
        "replacement_delta_pct": round(sum_return(added) - sum_return(removed), 2),
        "removed_win_rate_pct": win_rate(removed),
        "added_win_rate_pct": win_rate(added),
    }
    return {"summary": summary, "removed": removed, "added": added, "common": common_base}


def sum_return(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return round(float(df["_return_pct"].sum()), 2)


def win_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return round(float((df["_return_pct"] > 0).mean() * 100), 2)


def changed_trade_table(df: pd.DataFrame, top: int = 20, worst_first: bool = True) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    cols = [col for col in SHOW_COLS if col in df.columns]
    ordered = df.sort_values("_return_pct", ascending=worst_first)
    return ordered.head(top)[cols].reset_index(drop=True)


def build_markdown_report(base: pd.DataFrame, experiment: pd.DataFrame, base_name: str, experiment_name: str, top: int = 20) -> str:
    result = compare_trades(base, experiment)
    summary = result["summary"]
    removed = result["removed"]
    added = result["added"]

    lines = [
        "# Trade Diff Diagnostics",
        "",
        f"- Base: {base_name}",
        f"- Experiment: {experiment_name}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 先看结论",
        f"- 基准交易 {summary['base_trades']} 笔，实验交易 {summary['experiment_trades']} 笔，共同交易 {summary['common_trades']} 笔。",
        f"- 实验少买 {summary['removed_trades']} 笔，少买部分合计收益 {summary['removed_total_return_pct']}%。",
        f"- 实验多买 {summary['added_trades']} 笔，多买部分合计收益 {summary['added_total_return_pct']}%。",
        f"- 替换收益差：{summary['replacement_delta_pct']}%。正数表示实验换得更好，负数表示实验换差了。",
        "",
        "## Summary",
        pd.DataFrame([summary]).to_markdown(index=False),
        "",
        "## 实验少买的票",
        table_to_markdown(changed_trade_table(removed, top=top, worst_first=False)),
        "",
        "## 实验多买的票",
        table_to_markdown(changed_trade_table(added, top=top, worst_first=True)),
        "",
    ]
    return "\n".join(lines)


def table_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No changed trades._"
    return df.to_markdown(index=False)


def default_output_path(base_path: Path, experiment_path: Path) -> Path:
    base = base_path.stem.replace("trades_", "")
    exp = experiment_path.stem.replace("trades_", "")
    return Path("reports") / f"trade_diff_{base}_vs_{exp}.md"


def main() -> None:
    args = parse_args()
    base_path = Path(args.base)
    exp_path = Path(args.experiment)
    report = build_markdown_report(
        load_trades(base_path),
        load_trades(exp_path),
        base_name=str(base_path),
        experiment_name=str(exp_path),
        top=args.top,
    )
    output_path = Path(args.output) if args.output else default_output_path(base_path, exp_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written: {output_path}")
    print("\n".join(report.splitlines()[7:13]))


if __name__ == "__main__":
    main()
