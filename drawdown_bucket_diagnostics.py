"""Diagnose drawdown position buckets from trades_*.csv files.

Usage:
  python drawdown_bucket_diagnostics.py --trades backtest_results/trades_a.csv backtest_results/trades_b.csv --labels 2025,2026Q1
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from trade_diagnostics import RETURN_CANDIDATES, pick_return_col


DRAW_BUCKET_ORDER = ["0-3%", "3-6%", "6-9%", "9-12%", "12%+", "NA"]
FACTOR_BUCKET_ORDER = ["<60", "60-75", "75-90", "90+", "NA"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bucket trades by drawdown_from_high and factor_drawdown.")
    parser.add_argument("--trades", nargs="+", required=True, help="One or more trades_*.csv files.")
    parser.add_argument("--labels", default=None, help="Comma-separated labels matching --trades.")
    parser.add_argument("--output", default=None, help="Markdown report path.")
    parser.add_argument("--top", type=int, default=30, help="Rows to show in tables.")
    return parser.parse_args()


def bucketize_drawdown(value: float) -> str:
    if pd.isna(value):
        return "NA"
    value = float(value)
    if value < 3.0:
        return "0-3%"
    if value < 6.0:
        return "3-6%"
    if value < 9.0:
        return "6-9%"
    if value < 12.0:
        return "9-12%"
    return "12%+"


def bucketize_factor_drawdown(value: float) -> str:
    if pd.isna(value):
        return "NA"
    value = float(value)
    if value < 60.0:
        return "<60"
    if value < 75.0:
        return "60-75"
    if value < 90.0:
        return "75-90"
    return "90+"


def load_trade_file(path: str | Path, label: str | None = None) -> tuple[str, pd.DataFrame]:
    trade_path = Path(path)
    return label or trade_path.stem, pd.read_csv(trade_path, encoding="utf-8-sig")


def normalize_trade_files(frames: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    data = []
    for label, frame in frames:
        df = frame.copy()
        df["source_label"] = label
        data.append(df)
    if not data:
        return pd.DataFrame()
    return normalize_trades(pd.concat(data, ignore_index=True))


def normalize_trades(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    numeric_cols = set(
        RETURN_CANDIDATES
        + [
            "drawdown_from_high",
            "factor_drawdown",
            "mfe_pct",
            "mae_pct",
            "window_end_pct",
            "best_close_pct",
            "worst_close_pct",
            "factor_inflow",
            "factor_sector",
            "factor_pattern",
            "factor_volume_ratio",
            "volume_ratio",
        ]
    )
    for col in numeric_cols:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")

    return_col = pick_return_col(data)
    data["_return_pct"] = pd.to_numeric(data[return_col], errors="coerce").fillna(0.0)
    data["_is_win"] = data["_return_pct"] > 0

    if "drawdown_from_high" in data.columns:
        data["drawdown_bucket"] = data["drawdown_from_high"].apply(bucketize_drawdown)
    else:
        data["drawdown_bucket"] = "NA"
    if "factor_drawdown" in data.columns:
        data["factor_drawdown_bucket"] = data["factor_drawdown"].apply(bucketize_factor_drawdown)
    else:
        data["factor_drawdown_bucket"] = "NA"

    for col in ["source_label", "market_style", "macro_mode", "industry", "ts_code", "name", "exit_reason"]:
        if col in data.columns:
            data[col] = data[col].fillna("NA").astype(str)
    return data


def summarize_bucket(df: pd.DataFrame, bucket_col: str, extra_group_cols: list[str] | None = None) -> pd.DataFrame:
    data = df.copy() if "_return_pct" in df.columns else normalize_trades(df)
    if bucket_col not in data.columns:
        return pd.DataFrame()
    group_cols = list(extra_group_cols or []) + [bucket_col]
    rows = []
    for group_key, part in data.groupby(group_cols, dropna=False):
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = {col: value for col, value in zip(group_cols, group_key)}
        row["bucket"] = row.pop(bucket_col)
        row.update(
            {
                "trades": int(len(part)),
                "win_rate_pct": round(float(part["_is_win"].mean() * 100), 2) if len(part) else 0.0,
                "return_sum_pct": round(float(part["_return_pct"].sum()), 2),
                "avg_return_pct": round(float(part["_return_pct"].mean()), 2) if len(part) else 0.0,
                "avg_mfe_pct": _mean(part, "mfe_pct"),
                "avg_mae_pct": _mean(part, "mae_pct"),
                "avg_window_end_pct": _mean(part, "window_end_pct"),
            }
        )
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    order = DRAW_BUCKET_ORDER if bucket_col == "drawdown_bucket" else FACTOR_BUCKET_ORDER
    result["_order"] = result["bucket"].map({name: idx for idx, name in enumerate(order)}).fillna(999)
    sort_cols = [col for col in ["source_label", "market_style", "_order"] if col in result.columns]
    return result.sort_values(sort_cols or ["_order"]).drop(columns=["_order"]).reset_index(drop=True)


def _mean(df: pd.DataFrame, col: str) -> float | None:
    if col not in df.columns:
        return None
    val = df[col].mean()
    if pd.isna(val):
        return None
    return round(float(val), 2)


def build_plain_summary(data: pd.DataFrame) -> str:
    draw_summary = summarize_bucket(data, "drawdown_bucket")
    factor_summary = summarize_bucket(data, "factor_drawdown_bucket")
    lines = [
        f"- 共分析 `{len(data)}` 笔交易，覆盖 `{data['source_label'].nunique() if 'source_label' in data else 1}` 个结果文件。",
    ]
    if not draw_summary.empty:
        worst = draw_summary.sort_values("avg_return_pct").iloc[0]
        best = draw_summary.sort_values("avg_return_pct", ascending=False).iloc[0]
        lines.append(f"- `drawdown_from_high` 最弱分桶：`{worst.bucket}`，均收益 `{worst.avg_return_pct}`%，胜率 `{worst.win_rate_pct}`%。")
        lines.append(f"- `drawdown_from_high` 最强分桶：`{best.bucket}`，均收益 `{best.avg_return_pct}`%，胜率 `{best.win_rate_pct}`%。")
    if not factor_summary.empty:
        worst_factor = factor_summary.sort_values("avg_return_pct").iloc[0]
        lines.append(f"- `factor_drawdown` 最弱分桶：`{worst_factor.bucket}`，均收益 `{worst_factor.avg_return_pct}`%。")
    lines.append("- 如果高 `factor_drawdown` 或深回撤桶持续偏弱，下一轮优先考虑保护条件，而不是继续加权。")
    return "\n".join(lines)


def build_markdown_report(df: pd.DataFrame, source: str = "", top: int = 30) -> str:
    data = df.copy() if "_return_pct" in df.columns else normalize_trades(df)
    sections = [
        "# Drawdown Bucket Diagnostics",
        "",
        f"- Source: {source or 'in-memory dataframe'}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 先看结论",
        build_plain_summary(data),
        "",
        "## drawdown_from_high 分桶",
        _table(summarize_bucket(data, "drawdown_bucket"), top),
        "",
        "## factor_drawdown 分桶",
        _table(summarize_bucket(data, "factor_drawdown_bucket"), top),
        "",
        "## 按 market_style 拆分",
        "### drawdown_from_high",
        _table(summarize_bucket(data, "drawdown_bucket", ["market_style"]), top),
        "",
        "### factor_drawdown",
        _table(summarize_bucket(data, "factor_drawdown_bucket", ["market_style"]), top),
    ]
    if "source_label" in data.columns:
        sections.extend(
            [
                "",
                "## 按文件拆分",
                "### drawdown_from_high",
                _table(summarize_bucket(data, "drawdown_bucket", ["source_label"]), top),
                "",
                "### factor_drawdown",
                _table(summarize_bucket(data, "factor_drawdown_bucket", ["source_label"]), top),
            ]
        )
    return "\n".join(sections) + "\n"


def _table(df: pd.DataFrame, top: int) -> str:
    if df.empty:
        return "_No data._"
    return df.head(top).to_markdown(index=False)


def default_output_path(paths: list[Path]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(paths) == 1:
        return Path("reports") / f"drawdown_bucket_{paths[0].stem.replace('trades_', '')}.md"
    return Path("reports") / f"drawdown_bucket_diagnostics_{stamp}.md"


def main() -> None:
    args = parse_args()
    paths = [Path(path) for path in args.trades]
    labels = [label.strip() for label in args.labels.split(",")] if args.labels else [path.stem for path in paths]
    if len(labels) != len(paths):
        raise SystemExit("--labels count must match --trades count")
    frames = [load_trade_file(path, label) for path, label in zip(paths, labels)]
    data = normalize_trade_files(frames)
    report = build_markdown_report(data, source=", ".join(str(path) for path in paths), top=args.top)
    output_path = Path(args.output) if args.output else default_output_path(paths)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written: {output_path}")
    print("\n".join(report.splitlines()[5:12]))


if __name__ == "__main__":
    main()
