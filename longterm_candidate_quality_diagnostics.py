#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose longterm candidate path quality before trade execution."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


FACTOR_COLUMNS = [
    "longterm_score",
    "score_momentum",
    "score_flow",
    "score_rs",
    "score_fin",
    "score_entry",
    "score_risk_penalty",
    "industry_rs",
    "price_vs_ma60",
    "drawdown_from_high",
    "turnover",
    "volume_ratio",
    "ma20_slope",
    "main_net_inflow",
    "roe",
    "debt_ratio",
    "netprofit_yoy",
]
TARGET_COLUMNS = [
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
    "ret_5d",
    "ret_10d",
    "ret_20d",
]
DISPLAY_COLUMNS = [
    "source_label",
    "select_date",
    "ts_code",
    "quality_group",
    "longterm_score",
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
    "price_vs_ma60",
    "turnover",
    "industry_rs",
]
GROUP_ORDER = ["smooth_winner", "volatile_winner", "trap", "dead_money", "other"]


def load_candidates(path: str | Path, label: str | None = None) -> pd.DataFrame:
    p = Path(path)
    df = pd.read_csv(p, encoding="utf-8-sig")
    return normalize_candidates(df, label or p.stem)


def normalize_candidates(df: pd.DataFrame, label: str = "data") -> pd.DataFrame:
    work = df.copy()
    if "source_label" not in work.columns or label != "data":
        work["source_label"] = label
    for col in set(FACTOR_COLUMNS + TARGET_COLUMNS + ["score", "original_score"]):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    if "longterm_score" not in work.columns and "score" in work.columns:
        work["longterm_score"] = work["score"]
    for col in ["select_date", "buy_date", "ts_code", "source_file", "source_label"]:
        if col in work.columns:
            work[col] = work[col].fillna("NA").astype(str)
    return work


def classify_quality(
    df: pd.DataFrame,
    high_mfe: float = 15.0,
    shallow_mae: float = -8.0,
    deep_mae: float = -12.0,
    positive_end: float = 0.0,
    low_mfe: float = 8.0,
) -> pd.DataFrame:
    data = normalize_candidates(df)
    required = {"mfe_pct", "mae_pct", "window_end_pct"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    data["quality_group"] = "other"
    smooth = (
        (data["mfe_pct"] >= high_mfe)
        & (data["mae_pct"] >= shallow_mae)
        & (data["window_end_pct"] >= positive_end)
    )
    volatile = (
        (data["mfe_pct"] >= high_mfe)
        & (data["mae_pct"] < shallow_mae)
        & (data["window_end_pct"] >= positive_end)
    )
    trap = (
        (data["mfe_pct"] < low_mfe)
        & (data["mae_pct"] <= deep_mae)
        & (data["window_end_pct"] < positive_end)
    )
    dead_money = (
        (data["mfe_pct"] < low_mfe)
        & (data["mae_pct"] > deep_mae)
        & (data["window_end_pct"] < positive_end)
    )
    data.loc[smooth, "quality_group"] = "smooth_winner"
    data.loc[volatile, "quality_group"] = "volatile_winner"
    data.loc[trap, "quality_group"] = "trap"
    data.loc[dead_money, "quality_group"] = "dead_money"
    data["quality_group"] = pd.Categorical(data["quality_group"], GROUP_ORDER, ordered=True)
    return data


def group_summary(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy() if "quality_group" in df.columns else classify_quality(df)
    result = (
        data.groupby(["source_label", "quality_group"], observed=False)
        .agg(
            count=("ts_code", "size"),
            avg_score=("longterm_score", "mean"),
            avg_mfe=("mfe_pct", "mean"),
            avg_mae=("mae_pct", "mean"),
            avg_end=("window_end_pct", "mean"),
        )
        .reset_index()
        .round(2)
    )
    return result[result["count"] > 0]


def compare_quality_groups(df: pd.DataFrame, factors: list[str] | None = None) -> pd.DataFrame:
    data = df.copy() if "quality_group" in df.columns else classify_quality(df)
    factors = [col for col in (factors or FACTOR_COLUMNS) if col in data.columns]
    rows = []
    smooth = data[data["quality_group"] == "smooth_winner"]
    trap = data[data["quality_group"] == "trap"]
    volatile = data[data["quality_group"] == "volatile_winner"]
    dead = data[data["quality_group"] == "dead_money"]
    for factor in factors:
        smooth_avg = smooth[factor].mean()
        trap_avg = trap[factor].mean()
        volatile_avg = volatile[factor].mean()
        dead_avg = dead[factor].mean()
        if pd.isna(smooth_avg) or pd.isna(trap_avg):
            continue
        rows.append(
            {
                "factor": factor,
                "smooth_winner_avg": round(float(smooth_avg), 3),
                "trap_avg": round(float(trap_avg), 3),
                "trap_minus_smooth": round(float(trap_avg - smooth_avg), 3),
                "volatile_winner_avg": round(float(volatile_avg), 3) if not pd.isna(volatile_avg) else None,
                "dead_money_avg": round(float(dead_avg), 3) if not pd.isna(dead_avg) else None,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["factor", "smooth_winner_avg", "trap_avg", "trap_minus_smooth", "volatile_winner_avg", "dead_money_avg"]
        )
    return pd.DataFrame(rows).sort_values("trap_minus_smooth", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def rank_quality_by_score(df: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    data = df.copy() if "quality_group" in df.columns else classify_quality(df)
    if "select_date" not in data.columns or "longterm_score" not in data.columns:
        return pd.DataFrame()
    ranked = data.sort_values(["select_date", "longterm_score"], ascending=[True, False]).copy()
    ranked["candidate_rank"] = ranked.groupby("select_date")["longterm_score"].rank(method="first", ascending=False).astype(int)
    top = ranked[ranked["candidate_rank"] <= top_n]
    return (
        top.groupby(["source_label", "quality_group"], observed=False)
        .agg(count=("ts_code", "size"))
        .reset_index()
        .query("count > 0")
        .sort_values(["source_label", "quality_group"])
    )


def _table(df: pd.DataFrame, cols: list[str] | None = None, max_rows: int = 30) -> str:
    if df.empty:
        return "无样本\n"
    view = df.copy()
    if cols:
        view = view[[col for col in cols if col in view.columns]]
    return view.head(max_rows).to_markdown(index=False) + "\n"


def _v7_suggestions(diff: pd.DataFrame) -> list[str]:
    suggestions = []
    rows = {row.factor: row for row in diff.itertuples()}
    price = rows.get("price_vs_ma60")
    turnover = rows.get("turnover")
    slope = rows.get("ma20_slope")
    entry = rows.get("score_entry")
    score = rows.get("longterm_score")
    if price is not None and price.trap_minus_smooth > 3:
        suggestions.append("- `price_vs_ma60`：陷阱票明显更远离MA60，v7可测试更严格的位置护栏。")
    if turnover is not None and turnover.trap_minus_smooth > 2:
        suggestions.append("- `turnover`：陷阱票换手更高，v7可测试过热换手降权。")
    if slope is not None and slope.trap_minus_smooth < -0.05:
        suggestions.append("- `ma20_slope`：陷阱票短期趋势更弱，v7可加入趋势斜率底线。")
    if entry is not None and entry.trap_minus_smooth < -0.3:
        suggestions.append("- `score_entry`：顺滑赢家入场质量更高，v7应强化入场质量而非财务分。")
    if score is not None and abs(score.trap_minus_smooth) < 1:
        suggestions.append("- `longterm_score`：总分区分度不足，v7应使用局部护栏，不宜只提高分数门槛。")
    if not suggestions:
        suggestions.append("- 暂未发现单一稳定护栏，建议按市场阶段拆分后再设计v7。")
    return suggestions


def build_report(df: pd.DataFrame, title: str = "波段候选质量诊断", top: int = 30) -> str:
    data = df.copy() if "quality_group" in df.columns else classify_quality(df)
    summary = group_summary(data)
    diff = compare_quality_groups(data)
    top_quality = rank_quality_by_score(data, top_n=3)
    smooth = data[data["quality_group"] == "smooth_winner"].sort_values("mfe_pct", ascending=False)
    traps = data[data["quality_group"] == "trap"].sort_values("mae_pct")

    group_counts = data["quality_group"].astype(str).value_counts()
    smooth_count = int(group_counts.get("smooth_winner", 0))
    trap_count = int(group_counts.get("trap", 0))
    volatile_count = int(group_counts.get("volatile_winner", 0))
    dead_count = int(group_counts.get("dead_money", 0))

    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 共分析 `{len(data)}` 个波段候选：顺滑赢家 `{smooth_count}`、波动赢家 `{volatile_count}`、陷阱票 `{trap_count}`、弱机会 `{dead_count}`。\n",
    ]
    if not diff.empty:
        top_diff = diff.head(5)
        text = "、".join(f"`{r.factor}` trap-smooth {r.trap_minus_smooth:+.2f}" for r in top_diff.itertuples())
        lines.append(f"- trap vs smooth_winner 最明显差异：{text}。\n")
    lines.extend(_v7_suggestions(diff))
    lines.extend(
        [
            "\n## 路径质量分组\n",
            _table(summary, max_rows=80),
            "\n## Top3实际选中的路径类型\n",
            _table(top_quality, max_rows=80),
            "\n## trap vs smooth_winner：买入前因子差异\n",
            _table(diff, max_rows=40),
            "\n## 顺滑赢家样本\n",
            _table(smooth, DISPLAY_COLUMNS, max_rows=top),
            "\n## 陷阱票样本\n",
            _table(traps, DISPLAY_COLUMNS, max_rows=top),
            "\n## v7选股质量线索\n",
            "- 优先把稳定区分 `trap` 和 `smooth_winner` 的买入前特征做成选股护栏。\n",
            "- 不建议引入复杂盘中执行条件；v7 应保持实盘可执行，仍以选股质量为主。\n",
        ]
    )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze longterm candidate path quality from ic_longterm CSV files.")
    parser.add_argument("--candidates", nargs="+", required=True, help="One or more ic_longterm_*.csv files.")
    parser.add_argument("--labels", default=None, help="Comma-separated labels matching candidates.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--title", default="波段候选质量诊断", help="Report title.")
    parser.add_argument("--top", type=int, default=30, help="Rows to show in sample tables.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labels = args.labels.split(",") if args.labels else [None] * len(args.candidates)
    if len(labels) != len(args.candidates):
        raise SystemExit("--labels 数量必须与 --candidates 文件数量一致")
    frames = [load_candidates(path, label) for path, label in zip(args.candidates, labels)]
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    report = build_report(data, title=args.title, top=args.top)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
