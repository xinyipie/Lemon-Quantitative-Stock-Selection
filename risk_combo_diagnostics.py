"""Diagnose cross-factor risk combinations from trades_*.csv files.

Usage:
  python risk_combo_diagnostics.py --trades backtest_results/trades_a.csv --labels 2024H2
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from trade_diagnostics import RETURN_CANDIDATES, pick_return_col


NUMERIC_COLUMNS = [
    "factor_sector",
    "volume_ratio",
    "drawdown_from_high",
    "factor_inflow",
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_pattern",
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
] + RETURN_CANDIDATES

COMBO_RULES = [
    ("low_sector", "板块低分"),
    ("high_volume", "高量比"),
    ("mid_deep_drawdown", "中深回撤"),
    ("low_inflow", "资金流弱"),
    ("low_sector_high_volume", "板块低分 + 高量比"),
    ("low_sector_mid_deep_drawdown", "板块低分 + 中深回撤"),
    ("high_volume_mid_deep_drawdown", "高量比 + 中深回撤"),
    ("low_sector_high_volume_mid_deep_drawdown", "板块低分 + 高量比 + 中深回撤"),
    ("low_sector_high_volume_low_inflow", "板块低分 + 高量比 + 资金流弱"),
]

SHOW_COLUMNS = [
    "source_label",
    "select_date",
    "buy_date",
    "ts_code",
    "name",
    "_return_pct",
    "factor_sector",
    "volume_ratio",
    "drawdown_from_high",
    "factor_inflow",
    "market_style",
    "exit_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose cross-factor risk combinations.")
    parser.add_argument("--trades", nargs="+", required=True, help="One or more trades_*.csv files.")
    parser.add_argument("--labels", default=None, help="Comma-separated labels matching --trades.")
    parser.add_argument("--output", default=None, help="Markdown report path.")
    parser.add_argument("--top", type=int, default=30, help="Rows to show in tables.")
    return parser.parse_args()


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
    for col in NUMERIC_COLUMNS:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")

    return_col = pick_return_col(data)
    data["_return_pct"] = pd.to_numeric(data[return_col], errors="coerce").fillna(0.0)
    data["_is_win"] = data["_return_pct"] > 0

    sector = data["factor_sector"] if "factor_sector" in data.columns else pd.Series(pd.NA, index=data.index)
    volume = data["volume_ratio"] if "volume_ratio" in data.columns else pd.Series(pd.NA, index=data.index)
    drawdown = data["drawdown_from_high"] if "drawdown_from_high" in data.columns else pd.Series(pd.NA, index=data.index)
    inflow = data["factor_inflow"] if "factor_inflow" in data.columns else pd.Series(pd.NA, index=data.index)

    data["low_sector"] = sector < 30
    data["high_volume"] = volume >= 3.0
    data["mid_deep_drawdown"] = (drawdown >= 9.0) & (drawdown < 12.0)
    data["low_inflow"] = inflow < 45
    data["low_sector_high_volume"] = data["low_sector"] & data["high_volume"]
    data["low_sector_mid_deep_drawdown"] = data["low_sector"] & data["mid_deep_drawdown"]
    data["high_volume_mid_deep_drawdown"] = data["high_volume"] & data["mid_deep_drawdown"]
    data["low_sector_high_volume_mid_deep_drawdown"] = (
        data["low_sector"] & data["high_volume"] & data["mid_deep_drawdown"]
    )
    data["low_sector_high_volume_low_inflow"] = data["low_sector"] & data["high_volume"] & data["low_inflow"]

    for col in ["source_label", "market_style", "macro_mode", "industry", "ts_code", "name", "exit_reason"]:
        if col in data.columns:
            data[col] = data[col].fillna("NA").astype(str)
    return data


def summarize_combo_rules(df: pd.DataFrame, group_cols: list[str] | None = None) -> pd.DataFrame:
    data = df.copy() if "_return_pct" in df.columns else normalize_trades(df)
    groups = group_cols or []
    rows = []
    grouped = [((), data)] if not groups else data.groupby(groups, dropna=False)
    for group_key, part in grouped:
        if groups and not isinstance(group_key, tuple):
            group_key = (group_key,)
        group_values = {col: value for col, value in zip(groups, group_key)}
        for rule, meaning in COMBO_RULES:
            if rule not in part.columns:
                continue
            matched = part[part[rule].fillna(False)]
            unmatched = part[~part[rule].fillna(False)]
            if matched.empty:
                continue
            matched_avg = _avg_return(matched)
            unmatched_avg = _avg_return(unmatched)
            row = {
                **group_values,
                "rule": rule,
                "meaning": meaning,
                "matched_trades": int(len(matched)),
                "matched_win_rate_pct": _win_rate(matched),
                "matched_return_sum_pct": round(float(matched["_return_pct"].sum()), 2),
                "matched_avg_return_pct": matched_avg,
                "unmatched_trades": int(len(unmatched)),
                "unmatched_avg_return_pct": unmatched_avg,
                "avg_return_gap_pct": round(float(matched_avg - unmatched_avg), 2),
                "avg_mfe_pct": _mean(matched, "mfe_pct"),
                "avg_mae_pct": _mean(matched, "mae_pct"),
                "avg_window_end_pct": _mean(matched, "window_end_pct"),
            }
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    sort_cols = [col for col in groups if col in rows[0]] + ["avg_return_gap_pct", "matched_trades"]
    return pd.DataFrame(rows).sort_values(sort_cols, ascending=[True] * len(groups) + [True, False]).reset_index(drop=True)


def build_plain_summary(data: pd.DataFrame, combo_summary: pd.DataFrame) -> str:
    lines = [
        f"- 共分析 `{len(data)}` 笔交易，覆盖 `{data['source_label'].nunique() if 'source_label' in data else 1}` 个结果文件。",
    ]
    if not combo_summary.empty:
        worst = combo_summary.sort_values(["avg_return_gap_pct", "matched_trades"], ascending=[True, False]).iloc[0]
        lines.append(
            f"- 当前最弱组合：`{worst.rule}`（{worst.meaning}），匹配 `{int(worst.matched_trades)}` 笔，"
            f"均收益 `{worst.matched_avg_return_pct}`%，相对未匹配 `{worst.avg_return_gap_pct}`%。"
        )
        risky = combo_summary[
            (combo_summary["matched_trades"] >= 2)
            & (combo_summary["matched_avg_return_pct"] < 0)
            & (combo_summary["avg_return_gap_pct"] < 0)
        ]
        if risky.empty:
            lines.append("- 暂未看到样本数足够且稳定偏弱的组合，下一步不宜直接加权。")
        else:
            lines.append("- 已看到负收益组合，可优先作为下一轮小幅保护扣分候选，而不是扩大单因子惩罚。")
    else:
        lines.append("- 没有组合规则命中样本，暂不建议做组合扣分实验。")
    return "\n".join(lines)


def build_markdown_report(df: pd.DataFrame, source: str = "", top: int = 30) -> str:
    data = df.copy() if "_return_pct" in df.columns else normalize_trades(df)
    combo_summary = summarize_combo_rules(data)
    sections = [
        "# Risk Combo Diagnostics",
        "",
        f"- Source: {source or 'in-memory dataframe'}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 先看结论",
        build_plain_summary(data, combo_summary),
        "",
        "## 组合规则表现",
        _table(combo_summary, top),
        "",
        "## 按 market_style 拆分",
        _table(summarize_combo_rules(data, ["market_style"]) if "market_style" in data.columns else pd.DataFrame(), top),
        "",
        "## 组合命中样本",
        _sample_hits(data, top),
    ]
    if "source_label" in data.columns:
        sections.extend(
            [
                "",
                "## 按文件拆分",
                _table(summarize_combo_rules(data, ["source_label"]), top),
            ]
        )
    return "\n".join(sections) + "\n"


def _avg_return(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return round(float(df["_return_pct"].mean()), 2)


def _win_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return round(float(df["_is_win"].mean() * 100), 2)


def _mean(df: pd.DataFrame, col: str) -> float | None:
    if col not in df.columns:
        return None
    value = df[col].mean()
    if pd.isna(value):
        return None
    return round(float(value), 2)


def _table(df: pd.DataFrame, top: int) -> str:
    if df.empty:
        return "_No data._"
    return df.head(top).to_markdown(index=False)


def _sample_hits(data: pd.DataFrame, top: int) -> str:
    key_rule = "low_sector_high_volume_mid_deep_drawdown"
    hits = data[data[key_rule].fillna(False)].sort_values("_return_pct")
    if hits.empty:
        return "_No samples hit low_sector_high_volume_mid_deep_drawdown._"
    cols = [col for col in SHOW_COLUMNS if col in hits.columns]
    return hits[cols].head(top).to_markdown(index=False)


def default_output_path(paths: list[Path]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(paths) == 1:
        return Path("reports") / f"risk_combo_{paths[0].stem.replace('trades_', '')}.md"
    return Path("reports") / f"risk_combo_diagnostics_{stamp}.md"


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
