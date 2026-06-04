"""Diagnose factor gaps between winning and losing trades.

Usage:
  python winner_loser_factor_diagnostics.py --trades backtest_results/trades_a.csv backtest_results/trades_b.csv --labels v6,v9
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from trade_diagnostics import FACTOR_COLUMNS, RETURN_CANDIDATES, factor_label, pick_return_col


FOCUS_FACTORS = [
    "factor_pattern",
    "factor_inflow",
    "factor_sector",
    "factor_drawdown",
    "factor_volume_ratio",
    "volume_ratio",
    "drawdown_from_high",
    "factor_counter_trend",
    "factor_wyckoff",
    "turnover",
    "short_score",
    "original_score",
    "score_base",
]
SHOW_COLUMNS = [
    "source_label",
    "select_date",
    "buy_date",
    "ts_code",
    "name",
    "industry",
    "market_style",
    "macro_mode",
    "_return_pct",
    "factor_pattern",
    "factor_inflow",
    "factor_sector",
    "factor_volume_ratio",
    "volume_ratio",
    "drawdown_from_high",
    "exit_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare winner/loser factor signatures across trade files.")
    parser.add_argument("--trades", nargs="+", required=True, help="One or more trades_*.csv files.")
    parser.add_argument("--labels", default=None, help="Comma-separated labels matching --trades, e.g. v6,v9.")
    parser.add_argument("--output", default=None, help="Markdown report path.")
    parser.add_argument("--top", type=int, default=20, help="Rows to show in sample tables.")
    return parser.parse_args()


def load_trade_file(path: str | Path, label: str | None = None) -> tuple[str, pd.DataFrame]:
    trade_path = Path(path)
    return label or trade_path.stem, pd.read_csv(trade_path, encoding="utf-8-sig")


def normalize_trade_frames(frames: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    normalized = []
    numeric_cols = set(RETURN_CANDIDATES + FACTOR_COLUMNS + FOCUS_FACTORS + ["hold_days"])
    for label, frame in frames:
        df = frame.copy()
        df["source_label"] = label
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return_col = pick_return_col(df)
        df["_return_pct"] = pd.to_numeric(df[return_col], errors="coerce").fillna(0.0)
        df["_is_win"] = df["_return_pct"] > 0
        for col in ["ts_code", "name", "industry", "market_style", "macro_mode", "exit_reason"]:
            if col in df.columns:
                df[col] = df[col].fillna("NA").astype(str)
        normalized.append(df)
    if not normalized:
        return pd.DataFrame()
    return pd.concat(normalized, ignore_index=True)


def compare_factors_by_label(df: pd.DataFrame, factors: list[str] | None = None) -> pd.DataFrame:
    data = df.copy() if "_is_win" in df.columns else normalize_trade_frames([("data", df)])
    factors = [col for col in (factors or FOCUS_FACTORS) if col in data.columns]
    rows = []
    for label, part in data.groupby("source_label", dropna=False):
        winners = part[part["_is_win"]]
        losers = part[~part["_is_win"]]
        for factor in factors:
            winner_avg = winners[factor].mean()
            loser_avg = losers[factor].mean()
            if pd.isna(winner_avg) or pd.isna(loser_avg):
                continue
            rows.append(
                {
                    "source_label": str(label),
                    "factor": factor,
                    "meaning": factor_label(factor),
                    "winner_avg": round(float(winner_avg), 2),
                    "loser_avg": round(float(loser_avg), 2),
                    "winner_minus_loser": round(float(winner_avg - loser_avg), 2),
                    "winner_count": int(winners[factor].notna().sum()),
                    "loser_count": int(losers[factor].notna().sum()),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "source_label",
                "factor",
                "meaning",
                "winner_avg",
                "loser_avg",
                "winner_minus_loser",
                "winner_count",
                "loser_count",
            ]
        )
    result = pd.DataFrame(rows)
    return result.sort_values(["source_label", "winner_minus_loser"], key=lambda s: s.abs() if s.name == "winner_minus_loser" else s, ascending=[True, False]).reset_index(drop=True)


def loss_group_summary(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    data = df.copy() if "_is_win" in df.columns else normalize_trade_frames([("data", df)])
    if group_col not in data.columns:
        return pd.DataFrame()
    losses = data[~data["_is_win"]]
    if losses.empty:
        return pd.DataFrame(columns=[group_col, "loss_count", "loss_return_sum", "avg_loss_pct"])
    result = losses.groupby(group_col, dropna=False).agg(
        loss_count=("_return_pct", "count"),
        loss_return_sum=("_return_pct", "sum"),
        avg_loss_pct=("_return_pct", "mean"),
    )
    return result.reset_index().round(2).sort_values(["loss_return_sum", "loss_count"], ascending=[True, False]).reset_index(drop=True)


def overall_by_label(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy() if "_is_win" in df.columns else normalize_trade_frames([("data", df)])
    rows = []
    for label, part in data.groupby("source_label", dropna=False):
        rows.append(
            {
                "source_label": str(label),
                "trades": int(len(part)),
                "wins": int(part["_is_win"].sum()),
                "losses": int((~part["_is_win"]).sum()),
                "win_rate_pct": round(float(part["_is_win"].mean() * 100), 2) if len(part) else 0.0,
                "return_sum_pct": round(float(part["_return_pct"].sum()), 2),
                "avg_return_pct": round(float(part["_return_pct"].mean()), 2) if len(part) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def build_plain_summary(df: pd.DataFrame, factor_diff: pd.DataFrame) -> str:
    overall = overall_by_label(df)
    lines = [
        f"- 共分析 `{len(df)}` 笔交易，覆盖 `{df['source_label'].nunique()}` 个结果文件。",
    ]
    if not overall.empty:
        best = overall.sort_values("return_sum_pct", ascending=False).iloc[0]
        lines.append(f"- 收益最高文件：`{best.source_label}`，交易 `{int(best.trades)}` 笔，合计 `{best.return_sum_pct}`%。")
    if not factor_diff.empty:
        top = factor_diff.sort_values("winner_minus_loser", key=lambda s: s.abs(), ascending=False).head(5)
        names = [
            f"{row.meaning}（`{row.factor}`，赢家-输家 {row.winner_minus_loser:+.2f}，{row.source_label}）"
            for row in top.itertuples()
        ]
        lines.append("- 当前最明显的赢家/输家差异：" + "、".join(names) + "。")
    lines.append("- 下一步优先找跨文件、跨月份都稳定的坏票特征，再考虑保护条件或小幅重排。")
    return "\n".join(lines)


def build_markdown_report(df: pd.DataFrame, source: str = "", top: int = 20) -> str:
    data = df.copy() if "_is_win" in df.columns else normalize_trade_frames([("data", df)])
    factor_diff = compare_factors_by_label(data)
    sections = [
        "# Winner Loser Factor Diagnostics",
        "",
        f"- Source: {source or 'in-memory dataframe'}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 先看结论",
        build_plain_summary(data, factor_diff),
        "",
        "## Overall By File",
        overall_by_label(data).to_markdown(index=False),
        "",
        "## 赚钱票 vs 亏钱票因子差异",
        factor_diff.head(top).to_markdown(index=False) if not factor_diff.empty else "_No data._",
        "",
        "## 亏损集中度",
        "### market_style",
        _table(loss_group_summary(data, "market_style"), top),
        "",
        "### industry",
        _table(loss_group_summary(data, "industry"), top),
        "",
        "## 亏损样例",
        _sample_losses(data, top),
    ]
    return "\n".join(sections) + "\n"


def _table(df: pd.DataFrame, top: int) -> str:
    if df.empty:
        return "_No data._"
    return df.head(top).to_markdown(index=False)


def _sample_losses(df: pd.DataFrame, top: int) -> str:
    losses = df[~df["_is_win"]].sort_values("_return_pct")
    if losses.empty:
        return "_No losses._"
    cols = [col for col in SHOW_COLUMNS if col in losses.columns]
    return losses.head(top)[cols].to_markdown(index=False)


def default_output_path(paths: list[Path]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(paths) == 1:
        stem = paths[0].stem.replace("trades_", "winner_loser_")
        return Path("reports") / f"{stem}.md"
    return Path("reports") / f"winner_loser_factor_diagnostics_{stamp}.md"


def main() -> None:
    args = parse_args()
    paths = [Path(path) for path in args.trades]
    labels = [label.strip() for label in args.labels.split(",")] if args.labels else [path.stem for path in paths]
    if len(labels) != len(paths):
        raise SystemExit("--labels count must match --trades count")
    frames = [load_trade_file(path, label) for path, label in zip(paths, labels)]
    data = normalize_trade_frames(frames)
    report = build_markdown_report(data, source=", ".join(str(path) for path in paths), top=args.top)
    output_path = Path(args.output) if args.output else default_output_path(paths)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written: {output_path}")
    print("\n".join(report.splitlines()[5:12]))


if __name__ == "__main__":
    main()
