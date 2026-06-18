#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit stable longterm factor differences across profiles and periods."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from longterm_pool_path_diagnostics import (
    FACTOR_COLUMNS,
    classify_paths,
    load_pool_paths,
)


def _fmt(value, digits: int = 2) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):.{digits}f}"


def _table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df.empty:
        return "无样本\n"
    return df.head(max_rows).to_markdown(index=False) + "\n"


def _direction(diff: float, neutral_band: float = 0.01) -> str:
    if pd.isna(diff) or abs(float(diff)) <= neutral_band:
        return "flat"
    return "bad_higher" if diff > 0 else "bad_lower"


def make_observation_table(
    df: pd.DataFrame,
    horizon: int = 40,
    factors: list[str] | None = None,
    min_group_size: int = 1,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    data = classify_paths(df, horizon=horizon)
    factors = [col for col in (factors or FACTOR_COLUMNS) if col in data.columns]
    rows = []
    for (source_label, stage), group in data.groupby(["source_label", "stage"], dropna=False):
        smooth = group[group["path_group"] == "smooth_winner"]
        bad = group[group["path_group"] == "bad_selection"]
        if len(smooth) < min_group_size or len(bad) < min_group_size:
            continue
        for factor in factors:
            smooth_avg = pd.to_numeric(smooth[factor], errors="coerce").mean()
            bad_avg = pd.to_numeric(bad[factor], errors="coerce").mean()
            if pd.isna(smooth_avg) or pd.isna(bad_avg):
                continue
            diff = float(bad_avg - smooth_avg)
            rows.append(
                {
                    "source_label": str(source_label),
                    "stage": str(stage),
                    "factor": factor,
                    "smooth_count": int(len(smooth)),
                    "bad_count": int(len(bad)),
                    "smooth_avg": round(float(smooth_avg), 4),
                    "bad_avg": round(float(bad_avg), 4),
                    "bad_minus_smooth": round(diff, 4),
                    "direction": _direction(diff),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "source_label",
                "stage",
                "factor",
                "smooth_count",
                "bad_count",
                "smooth_avg",
                "bad_avg",
                "bad_minus_smooth",
                "direction",
            ]
        )
    return pd.DataFrame(rows)


def factor_stability(observations: pd.DataFrame, min_observations: int = 3) -> pd.DataFrame:
    if observations.empty:
        return pd.DataFrame()
    rows = []
    useful = observations[observations["direction"].ne("flat")].copy()
    for factor, group in useful.groupby("factor", sort=False):
        counts = group["direction"].value_counts()
        dominant = str(counts.index[0])
        consistent = int(counts.iloc[0])
        total = int(len(group))
        if total < min_observations:
            continue
        dominant_rows = group[group["direction"] == dominant]
        rows.append(
            {
                "factor": factor,
                "dominant_direction": dominant,
                "consistent_count": consistent,
                "observation_count": total,
                "consistency_rate": round(consistent / total * 100, 2),
                "avg_abs_diff": round(float(dominant_rows["bad_minus_smooth"].abs().mean()), 4),
                "avg_signed_diff": round(float(dominant_rows["bad_minus_smooth"].mean()), 4),
                "stages": ", ".join(sorted(set(dominant_rows["stage"].astype(str)))),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "factor",
                "dominant_direction",
                "consistent_count",
                "observation_count",
                "consistency_rate",
                "avg_abs_diff",
                "avg_signed_diff",
                "stages",
            ]
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["consistency_rate", "consistent_count", "avg_abs_diff"], ascending=[False, False, False])
        .reset_index(drop=True)
    )


def stage_quality(df: pd.DataFrame, horizon: int = 40) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    data = classify_paths(df, horizon=horizon)
    result = (
        data.groupby(["source_label", "stage"], dropna=False)
        .agg(
            count=("ts_code", "size"),
            smooth=("path_group", lambda s: (s == "smooth_winner").sum()),
            bad=("path_group", lambda s: (s == "bad_selection").sum()),
            giveback=("path_group", lambda s: (s == "profit_giveback").sum()),
            early=("path_group", lambda s: (s == "early_entry").sum()),
            avg_ret=("ret_h", "mean"),
            avg_mfe=("mfe_h", "mean"),
            avg_mae=("mae_h", "mean"),
        )
        .reset_index()
    )
    for col in ["avg_ret", "avg_mfe", "avg_mae"]:
        result[col] = result[col].round(2)
    return result


def build_report(
    data: pd.DataFrame,
    observations: pd.DataFrame,
    stable: pd.DataFrame,
    horizon: int = 40,
    title: str = "长线稳定因子审计",
) -> str:
    quality = stage_quality(data, horizon=horizon)
    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 本报告只比较 `smooth_winner` 与 `bad_selection`，目标是找跨阶段稳定差异，不用单一区间结果调参。\n",
        f"- 共读取 `{len(data)}` 个样本，生成 `{len(observations)}` 条因子观察，评估窗口 `{horizon}` 日。\n",
    ]
    if stable.empty:
        lines.append("- 暂未发现满足最小观察次数的稳定因子，下一步应扩大阶段或降低最小组样本要求，而不是直接写 v10。\n")
    else:
        best = stable.iloc[0]
        direction_text = "坏票更高" if best["dominant_direction"] == "bad_higher" else "坏票更低"
        lines.append(
            f"- 最稳定线索：`{best['factor']}`，方向 `{direction_text}`，一致 `{best['consistent_count']}/{best['observation_count']}`，平均差 `{_fmt(best['avg_signed_diff'])}`。\n"
        )
        lines.append("- 只有同时具备跨阶段一致性、经济含义清楚、不会把样本打到过少的因子，才适合进入 v10。\n")
    lines.extend(
        [
            "\n## 各阶段路径质量\n",
            _table(quality, max_rows=80),
            "\n## 稳定因子候选\n",
            _table(stable, max_rows=50),
            "\n## 单阶段观察明细\n",
            _table(observations.sort_values(["factor", "stage", "source_label"]), max_rows=120),
            "\n## 为什么长线难做\n",
            "- 长线样本少：一年真正可用的严格入池样本可能只有几十个，单个大牛股会显著影响均值。\n",
            "- 市场阶段差异大：2024 防守、2025 牛市、2026Q1 波动，赚钱因子可能不是同一组。\n",
            "- 分数不一定单调：此前多次出现 Top10% 不如 Bottom20%，说明综合分更多是“入池门槛”，还不是可靠排序器。\n",
            "- 出场和选股混在一起：有些票 MFE 很高但最终回吐，问题不是选错，而是持有/止盈规则没处理好。\n",
            "- 过拟合风险高：每加一个门槛都可能解释过去 5 只票，却过滤掉未来真正的大票。\n",
        ]
    )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit stable longterm factor differences.")
    parser.add_argument("--inputs", nargs="+", required=True, help="One or more longterm_pool_quality_*.csv files.")
    parser.add_argument("--labels", default=None, help="Comma separated labels. Defaults to file stems.")
    parser.add_argument("--horizon", type=int, default=40, help="Forward horizon, e.g. 40 or 80.")
    parser.add_argument("--min-observations", type=int, default=3, help="Minimum cross-stage observations per factor.")
    parser.add_argument("--min-group-size", type=int, default=1, help="Minimum smooth/bad samples per stage.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--csv-output", default=None, help="Optional observation CSV output path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labels = args.labels.split(",") if args.labels else [None] * len(args.inputs)
    if len(labels) != len(args.inputs):
        raise SystemExit("--labels 数量必须和 --inputs 文件数量一致")

    frames = [load_pool_paths(path, label) for path, label in zip(args.inputs, labels)]
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    observations = make_observation_table(data, horizon=args.horizon, min_group_size=args.min_group_size)
    stable = factor_stability(observations, min_observations=args.min_observations)

    if args.csv_output:
        csv_out = Path(args.csv_output)
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        observations.to_csv(csv_out, index=False, encoding="utf-8-sig")

    report = build_report(data, observations, stable, horizon=args.horizon)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
