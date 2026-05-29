"""Audit factor quality from ic_short_*.csv candidate pools.

Usage:
  python factor_audit.py --candidates backtest_results/ic_short_xxx.csv
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from trade_diagnostics import factor_label


DEFAULT_FACTORS = [
    "score",
    "original_score",
    "score_base",
    "factor_pattern",
    "factor_sector",
    "factor_counter_trend",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_volume_ratio",
    "factor_wyckoff",
    "drawdown_from_high",
    "volume_ratio",
    "turnover",
]
DEFAULT_TARGETS = ["ret_5d", "ret_10d", "ret_20d", "mfe_pct", "mae_pct", "window_end_pct"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit factor IC, quantile spread, and regime stability.")
    parser.add_argument("--candidates", required=True, help="Path to ic_short_*.csv candidate file.")
    parser.add_argument("--compare", default=None, help="Optional second ic_short_*.csv file for stability comparison.")
    parser.add_argument("--left-label", default="left", help="Label for --candidates when --compare is used.")
    parser.add_argument("--right-label", default="right", help="Label for --compare when used.")
    parser.add_argument("--output", default=None, help="Markdown report path.")
    parser.add_argument("--top", type=int, default=30, help="Rows to show in audit tables.")
    return parser.parse_args()


def load_candidates(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    return normalize_frame(df)


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in DEFAULT_FACTORS + DEFAULT_TARGETS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "market_style" in df.columns:
        df["market_style"] = df["market_style"].fillna("NA").astype(str)
    if "macro_mode" in df.columns:
        df["macro_mode"] = df["macro_mode"].fillna("NA").astype(str)
    return df


def available_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [col for col in columns if col in df.columns]


def audit_factors(df: pd.DataFrame, factors: list[str] | None = None, targets: list[str] | None = None) -> pd.DataFrame:
    data = normalize_frame(df)
    factors = available_columns(data, factors or DEFAULT_FACTORS)
    targets = available_columns(data, targets or DEFAULT_TARGETS)
    rows = []

    for factor in factors:
        for target in targets:
            valid = data[[factor, target]].dropna()
            if len(valid) < 4 or valid[factor].nunique() < 2:
                continue
            ic = float(valid[factor].corr(valid[target], method="spearman"))
            q = factor_quantile_summary(valid, factor, target)
            if len(q) >= 2:
                bottom = float(q.iloc[0]["avg_target"])
                top = float(q.iloc[-1]["avg_target"])
                spread = top - bottom
            else:
                bottom = top = spread = 0.0
            rows.append(
                {
                    "factor": factor,
                    "meaning": factor_label(factor),
                    "target": target,
                    "ic": round(ic, 4),
                    "bottom_avg": round(bottom, 2),
                    "top_avg": round(top, 2),
                    "top_minus_bottom": round(spread, 2),
                    "direction": infer_factor_direction(ic, spread),
                    "n": int(len(valid)),
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=["factor", "meaning", "target", "ic", "bottom_avg", "top_avg", "top_minus_bottom", "direction", "n"]
        )
    result = pd.DataFrame(rows)
    result["abs_ic"] = result["ic"].abs()
    return result.sort_values(["target", "abs_ic"], ascending=[True, False]).drop(columns=["abs_ic"]).reset_index(drop=True)


def factor_quantile_summary(df: pd.DataFrame, factor: str, target: str, buckets: int = 5) -> pd.DataFrame:
    valid = normalize_frame(df)[[factor, target]].dropna()
    if valid.empty or valid[factor].nunique() < 2:
        return pd.DataFrame(columns=["bucket", "count", "avg_factor", "avg_target"])

    bucket_count = min(buckets, valid[factor].nunique(), len(valid))
    ranked = valid[factor].rank(method="first")
    valid = valid.copy()
    valid["bucket"] = pd.qcut(ranked, q=bucket_count, labels=[f"Q{i+1}" for i in range(bucket_count)])
    grouped = valid.groupby("bucket", observed=True).agg(
        count=(target, "count"),
        avg_factor=(factor, "mean"),
        avg_target=(target, "mean"),
    )
    return grouped.reset_index().round(4)


def infer_factor_direction(ic: float, spread: float, min_ic: float = 0.03, min_spread: float = 0.5) -> str:
    if abs(ic) < min_ic or abs(spread) < min_spread:
        return "flat"
    if ic > 0 and spread > 0:
        return "higher_is_better"
    if ic < 0 and spread < 0:
        return "lower_is_better"
    return "mixed"


def regime_audit(df: pd.DataFrame, factor: str, target: str = "ret_5d") -> pd.DataFrame:
    data = normalize_frame(df)
    if "market_style" not in data.columns or factor not in data.columns or target not in data.columns:
        return pd.DataFrame()
    rows = []
    for style, part in data.groupby("market_style", dropna=False):
        result = audit_factors(part, [factor], [target])
        if result.empty:
            continue
        row = result.iloc[0].to_dict()
        row["market_style"] = style
        rows.append(row)
    return pd.DataFrame(rows)


def build_plain_chinese_summary(audit: pd.DataFrame) -> str:
    if audit.empty:
        return "- 没有足够数据做因子体检。"
    ret5 = audit[audit["target"] == "ret_5d"].copy()
    if ret5.empty:
        ret5 = audit.copy()
    useful = ret5[ret5["direction"].isin(["higher_is_better", "lower_is_better"])].copy()
    flat = ret5[ret5["direction"] == "flat"].copy()

    lines = []
    if not useful.empty:
        best = useful.sort_values("top_minus_bottom", key=lambda s: s.abs(), ascending=False).head(3)
        names = [f"{row.meaning}（`{row.factor}`，{_direction_text(row.direction)}）" for row in best.itertuples()]
        lines.append("- 当前最值得继续研究的因子：" + "、".join(names) + "。")
    if not flat.empty:
        weak = flat.head(3)
        names = [f"{row.meaning}（`{row.factor}`）" for row in weak.itertuples()]
        lines.append("- 当前方向不明显的因子：" + "、".join(names) + "，暂时不适合大幅加权。")
    lines.append("- 下一步应优先检查这些因子在不同 market_style 下是否同向，避免只在某一年有效。")
    return "\n".join(lines)


def _direction_text(direction: str) -> str:
    mapping = {
        "higher_is_better": "越高越好",
        "lower_is_better": "越低越好",
        "flat": "方向不明显",
        "mixed": "信号冲突",
    }
    return mapping.get(direction, direction)


def build_markdown_report(df: pd.DataFrame, source: str = "", top: int = 30) -> str:
    data = normalize_frame(df)
    audit = audit_factors(data)
    ret5 = audit[audit["target"] == "ret_5d"].copy()
    ret5 = ret5.sort_values("top_minus_bottom", key=lambda s: s.abs(), ascending=False)

    sections = [
        "# Factor Audit",
        "",
        f"- Source: {source or 'in-memory dataframe'}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 先看结论",
        build_plain_chinese_summary(audit),
        "",
        "## 单因子体检",
        ret5.head(top).to_markdown(index=False) if not ret5.empty else "_No data._",
    ]

    for style_col in ["market_style", "macro_mode"]:
        if style_col not in data.columns:
            continue
        rows = []
        for group, part in data.groupby(style_col, dropna=False):
            group_audit = audit_factors(part, targets=["ret_5d"])
            if group_audit.empty:
                continue
            best = group_audit.sort_values("top_minus_bottom", key=lambda s: s.abs(), ascending=False).head(5)
            best.insert(0, style_col, group)
            rows.append(best)
        if rows:
            sections.extend(
                [
                    "",
                    f"## 按 {style_col} 拆分",
                    pd.concat(rows, ignore_index=True).head(top).to_markdown(index=False),
                ]
            )

    return "\n".join(sections) + "\n"


def compare_factor_stability(
    left_audit: pd.DataFrame,
    right_audit: pd.DataFrame,
    left_label: str = "left",
    right_label: str = "right",
    target: str = "ret_5d",
) -> pd.DataFrame:
    left = left_audit[left_audit["target"] == target].copy()
    right = right_audit[right_audit["target"] == target].copy()
    merged = left.merge(right, on=["factor", "target"], suffixes=(f"_{left_label}", f"_{right_label}"))
    if merged.empty:
        return pd.DataFrame()

    rows = []
    for _, row in merged.iterrows():
        left_direction = row[f"direction_{left_label}"]
        right_direction = row[f"direction_{right_label}"]
        left_spread = row[f"top_minus_bottom_{left_label}"]
        right_spread = row[f"top_minus_bottom_{right_label}"]
        left_ic = row[f"ic_{left_label}"]
        right_ic = row[f"ic_{right_label}"]

        if left_direction == right_direction and left_direction in ("higher_is_better", "lower_is_better"):
            stability = "consistent"
        elif "flat" in (left_direction, right_direction):
            stability = "weak_or_unclear"
        else:
            stability = "conflicting"

        rows.append(
            {
                "factor": row.factor,
                "meaning": row[f"meaning_{left_label}"],
                "target": row.target,
                f"ic_{left_label}": left_ic,
                f"ic_{right_label}": right_ic,
                f"spread_{left_label}": left_spread,
                f"spread_{right_label}": right_spread,
                f"direction_{left_label}": left_direction,
                f"direction_{right_label}": right_direction,
                "stability": stability,
                "action": recommend_action(stability, left_direction, right_direction),
            }
        )
    return pd.DataFrame(rows).sort_values(["stability", f"spread_{left_label}"], ascending=[True, False]).reset_index(drop=True)


def recommend_action(stability: str, left_direction: str, right_direction: str) -> str:
    if stability == "consistent":
        return "candidate_weight_or_filter"
    if stability == "weak_or_unclear":
        return "keep_as_reference"
    return "avoid_global_weight"


def build_stability_report(
    left_audit: pd.DataFrame,
    right_audit: pd.DataFrame,
    left_label: str = "2025",
    right_label: str = "Q1",
    target: str = "ret_5d",
) -> str:
    comparison = compare_factor_stability(left_audit, right_audit, left_label=left_label, right_label=right_label, target=target)
    lines = [
        "# Factor Stability",
        "",
        f"- Target: `{target}`",
        f"- Left: {left_label}",
        f"- Right: {right_label}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 稳定性结论",
    ]
    if comparison.empty:
        lines.append("- 没有足够数据做稳定性对比。")
    else:
        consistent = comparison[comparison["stability"] == "consistent"]
        conflicting = comparison[comparison["stability"] == "conflicting"]
        if not consistent.empty:
            names = [
                f"{row['meaning']}（`{row['factor']}`，{_direction_text(row[f'direction_{left_label}'])}）"
                for _, row in consistent.iterrows()
            ]
            lines.append("- 跨区间方向一致的因子：" + "、".join(names) + "。")
        if not conflicting.empty:
            names = [f"{row['meaning']}（`{row['factor']}`）" for _, row in conflicting.iterrows()]
            lines.append("- 跨区间方向冲突的因子：" + "、".join(names) + "，不要做全局加权。")
        lines.extend(["", "## Stability Table", comparison.to_markdown(index=False)])
    return "\n".join(lines) + "\n"


def default_output_path(candidates_path: Path) -> Path:
    stem = candidates_path.stem.replace("ic_short_", "factor_audit_")
    return Path("reports") / f"{stem}.md"


def default_stability_output_path(left_path: Path, right_path: Path) -> Path:
    left = left_path.stem.replace("ic_short_", "")
    right = right_path.stem.replace("ic_short_", "")
    return Path("reports") / f"factor_stability_{left}_vs_{right}.md"


def main() -> None:
    args = parse_args()
    path = Path(args.candidates)
    df = load_candidates(path)
    if args.compare:
        right_path = Path(args.compare)
        left_audit = audit_factors(df)
        right_audit = audit_factors(load_candidates(right_path))
        report = build_stability_report(left_audit, right_audit, left_label=args.left_label, right_label=args.right_label)
        default_path = default_stability_output_path(path, right_path)
    else:
        report = build_markdown_report(df, source=str(path), top=args.top)
        default_path = default_output_path(path)

    output_path = Path(args.output) if args.output else default_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written: {output_path}")
    print("\n".join(report.splitlines()[6:12]))


if __name__ == "__main__":
    main()
