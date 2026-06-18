#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose whether longterm pool ranking scores are useful inside admitted pools."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd


FACTOR_COLUMNS = [
    "pool_rank_score",
    "quality_rank_score",
    "longterm_score",
    "industry_rs",
    "price_vs_ma60",
    "drawdown_from_high",
    "ma20_slope",
    "turnover",
    "volume_ratio",
    "roe",
    "debt_ratio",
    "netprofit_yoy",
    "main_net_inflow",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "dv_ratio",
    "total_mv",
    "circ_mv",
]

DISPLAY_COLUMNS = [
    "stage",
    "select_date",
    "ts_code",
    "name",
    "industry",
    "rank_layer",
    "pool_rank_score",
    "quality_rank_score",
    "ret_h",
    "mfe_h",
    "mae_h",
    "industry_rs",
    "pb",
    "turnover",
    "price_vs_ma60",
    "drawdown_from_high",
    "v16_lifecycle_reasons",
]

LAYER_ORDER = ["Top10%", "Top20%", "Middle60%", "Bottom20%"]


def _fmt_pct(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):+.2f}%"


def _table(df: pd.DataFrame, max_rows: int = 40, columns: list[str] | None = None) -> str:
    if df.empty:
        return "无样本\n"
    view = df.copy()
    if columns:
        view = view[[col for col in columns if col in view.columns]]
    return view.head(max_rows).to_markdown(index=False) + "\n"


def _score_column(df: pd.DataFrame) -> str:
    for col in ["pool_rank_score", "quality_rank_score", "winner_profile_score", "longterm_score"]:
        if col in df.columns and pd.to_numeric(df[col], errors="coerce").notna().any():
            return col
    raise ValueError("Missing usable score column.")


def load_rank_csv(path: str | Path, label: str | None = None) -> pd.DataFrame:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        data = pd.read_csv(p, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if data.empty:
        return pd.DataFrame()
    if "stage" not in data.columns:
        data["stage"] = label or p.stem
    if "source_label" not in data.columns:
        data["source_label"] = label or p.stem
    return normalize_rank_data(data)


def normalize_rank_data(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    if "longterm_score" not in data.columns and "score" in data.columns:
        data["longterm_score"] = data["score"]
    for col in FACTOR_COLUMNS:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    for prefix in ["ret_", "mfe_", "mae_", "excess_ret_", "benchmark_ret_"]:
        for col in [c for c in data.columns if c.startswith(prefix)]:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    for col in ["stage", "source_label", "select_date", "ts_code", "name", "industry", "pool_type"]:
        if col in data.columns:
            data[col] = data[col].fillna("NA").astype(str)
    return data


def add_rank_layers(df: pd.DataFrame, score_col: str | None = None) -> pd.DataFrame:
    data = normalize_rank_data(df)
    if data.empty:
        return data
    score_col = score_col or _score_column(data)
    sort_cols = ["select_date", score_col]
    data = data.sort_values(sort_cols, ascending=[True, False]).copy()
    data["rank_score_used"] = score_col
    data["daily_rank"] = data.groupby("select_date")[score_col].rank(method="first", ascending=False)
    data["daily_count"] = data.groupby("select_date")[score_col].transform("count")
    data["top10_cutoff"] = data["daily_count"].apply(lambda n: max(1, math.ceil(float(n) * 0.10)))
    data["top20_cutoff"] = data["daily_count"].apply(lambda n: max(1, math.ceil(float(n) * 0.20)))
    data["bottom20_cutoff"] = data["daily_count"].apply(lambda n: max(1, math.floor(float(n) * 0.80) + 1))
    data["rank_layer"] = "Middle60%"
    data.loc[data["daily_rank"] >= data["bottom20_cutoff"], "rank_layer"] = "Bottom20%"
    data.loc[data["daily_rank"] <= data["top20_cutoff"], "rank_layer"] = "Top20%"
    data.loc[data["daily_rank"] <= data["top10_cutoff"], "rank_layer"] = "Top10%"
    data["rank_layer"] = pd.Categorical(data["rank_layer"], LAYER_ORDER, ordered=True)
    return data


def score_layer_summary(df: pd.DataFrame, horizon: int = 80) -> pd.DataFrame:
    data = df.copy() if "rank_layer" in df.columns else add_rank_layers(df)
    ret_col = f"ret_{horizon}d"
    mfe_col = f"mfe_{horizon}d"
    mae_col = f"mae_{horizon}d"
    if ret_col not in data.columns:
        return pd.DataFrame()
    rows = []
    for layer in LAYER_ORDER:
        sub = data[data["rank_layer"].astype(str) == layer].dropna(subset=[ret_col])
        if sub.empty:
            continue
        rows.append(
            {
                "rank_layer": layer,
                "count": int(len(sub)),
                "avg_score": round(float(sub[_score_column(sub)].mean()), 2),
                "avg_ret": round(float(sub[ret_col].mean()), 2),
                "median_ret": round(float(sub[ret_col].median()), 2),
                "win_rate": round(float((sub[ret_col] > 0).mean() * 100), 2),
                "avg_mfe": round(float(sub[mfe_col].mean()), 2) if mfe_col in sub.columns else None,
                "avg_mae": round(float(sub[mae_col].mean()), 2) if mae_col in sub.columns else None,
            }
        )
    return pd.DataFrame(rows)


def factor_layer_diff(df: pd.DataFrame, factors: list[str] | None = None) -> pd.DataFrame:
    data = df.copy() if "rank_layer" in df.columns else add_rank_layers(df)
    factors = [col for col in (factors or FACTOR_COLUMNS) if col in data.columns]
    top = data[data["rank_layer"].astype(str) == "Top10%"]
    bottom = data[data["rank_layer"].astype(str) == "Bottom20%"]
    rows = []
    for factor in factors:
        top_avg = pd.to_numeric(top[factor], errors="coerce").mean()
        bottom_avg = pd.to_numeric(bottom[factor], errors="coerce").mean()
        if pd.isna(top_avg) or pd.isna(bottom_avg):
            continue
        rows.append(
            {
                "factor": factor,
                "top10_avg": round(float(top_avg), 4),
                "bottom20_avg": round(float(bottom_avg), 4),
                "bottom_minus_top": round(float(bottom_avg - top_avg), 4),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["factor", "top10_avg", "bottom20_avg", "bottom_minus_top"])
    return pd.DataFrame(rows).sort_values("bottom_minus_top", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def factor_correlations(df: pd.DataFrame, horizon: int = 80, factors: list[str] | None = None) -> pd.DataFrame:
    data = normalize_rank_data(df)
    target = f"ret_{horizon}d"
    if target not in data.columns:
        return pd.DataFrame()
    factors = [col for col in (factors or FACTOR_COLUMNS) if col in data.columns]
    rows = []
    group_cols = ["stage"] if "stage" in data.columns else []
    groups = data.groupby(group_cols, dropna=False) if group_cols else [("all", data)]
    for key, group in groups:
        stage = key if isinstance(key, str) else key[0] if isinstance(key, tuple) else str(key)
        for factor in factors:
            sub = group[[factor, target]].dropna()
            if len(sub) < 10 or sub[factor].nunique() < 2:
                continue
            rows.append(
                {
                    "stage": str(stage),
                    "factor": factor,
                    "corr": round(float(sub[factor].corr(sub[target])), 4),
                    "n": int(len(sub)),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["stage", "factor", "corr", "n"])
    return pd.DataFrame(rows).sort_values("corr", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def inversion_cases(df: pd.DataFrame, horizon: int = 80, top: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = df.copy() if "rank_layer" in df.columns else add_rank_layers(df)
    ret_col = f"ret_{horizon}d"
    mfe_col = f"mfe_{horizon}d"
    mae_col = f"mae_{horizon}d"
    data = data.copy()
    data["ret_h"] = data[ret_col] if ret_col in data.columns else pd.NA
    data["mfe_h"] = data[mfe_col] if mfe_col in data.columns else pd.NA
    data["mae_h"] = data[mae_col] if mae_col in data.columns else pd.NA
    high_bad = data[data["rank_layer"].astype(str).isin(["Top10%", "Top20%"])].sort_values("ret_h", ascending=True)
    low_good = data[data["rank_layer"].astype(str) == "Bottom20%"].sort_values("ret_h", ascending=False)
    return high_bad.head(top).reset_index(drop=True), low_good.head(top).reset_index(drop=True)


def _diagnosis_notes(layers: pd.DataFrame, diffs: pd.DataFrame, corrs: pd.DataFrame, horizon: int) -> list[str]:
    notes = []
    if layers.empty:
        return ["- 样本不足，不能判断排序质量。"]
    top = layers[layers["rank_layer"] == "Top10%"]
    bottom = layers[layers["rank_layer"] == "Bottom20%"]
    if not top.empty and not bottom.empty:
        top_ret = float(top.iloc[0]["avg_ret"])
        bottom_ret = float(bottom.iloc[0]["avg_ret"])
        if top_ret < bottom_ret:
            notes.append(
                f"- 排序倒挂：Top10% {horizon}日均收益 `{_fmt_pct(top_ret)}`，低于 Bottom20% `{_fmt_pct(bottom_ret)}`，当前分数不宜直接用于池内排序。"
            )
        else:
            notes.append(
                f"- 排序略有效：Top10% {horizon}日均收益 `{_fmt_pct(top_ret)}`，高于 Bottom20% `{_fmt_pct(bottom_ret)}`，但仍需跨阶段确认。"
            )
    if not corrs.empty:
        score_corr = corrs[corrs["factor"].isin(["pool_rank_score", "quality_rank_score", "longterm_score"])]
        if not score_corr.empty:
            best = score_corr.iloc[0]
            notes.append(f"- 分数与收益相关性最强观测：`{best['stage']}` 的 `{best['factor']}` corr `{best['corr']}`，只作诊断线索，不单独调参。")
    if not diffs.empty:
        top_diff = diffs.iloc[0]
        notes.append(
            f"- Top/Bottom 差异最大的字段是 `{top_diff['factor']}`，Bottom20 比 Top10 高 `{top_diff['bottom_minus_top']}`。"
        )
    notes.append("- 建议：v18 可继续当入池门槛；池内展示先用“核心/观察/谨慎”标签，暂不按单一分数做强排序。")
    return notes


def build_report(df: pd.DataFrame, horizon: int = 80, title: str = "长线池内排序诊断", top: int = 25) -> str:
    data = df.copy() if "rank_layer" in df.columns else add_rank_layers(df)
    layers = score_layer_summary(data, horizon=horizon)
    diffs = factor_layer_diff(data)
    corrs = factor_correlations(data, horizon=horizon)
    high_bad, low_good = inversion_cases(data, horizon=horizon, top=top)
    complete = int(data.get(f"ret_{horizon}d", pd.Series(dtype=float)).notna().sum())
    score_col = _score_column(data) if not data.empty else "NA"
    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 共分析 `{complete}` 个有 {horizon}日前瞻收益的入池样本，使用排序字段 `{score_col}`。\n",
        *[note + "\n" for note in _diagnosis_notes(layers, diffs, corrs, horizon)],
        "\n## 排序有效性\n",
        _table(layers, max_rows=20),
        "\n## Top10% vs Bottom20% 因子差异\n",
        _table(diffs, max_rows=40),
        "\n## 因子与前瞻收益相关性\n",
        _table(corrs, max_rows=60),
        "\n## 高分低收益样本\n",
        _table(high_bad, max_rows=top, columns=DISPLAY_COLUMNS),
        "\n## 低分高收益样本\n",
        _table(low_good, max_rows=top, columns=DISPLAY_COLUMNS),
    ]
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose longterm admitted-pool ranking quality.")
    parser.add_argument("--inputs", nargs="+", required=True, help="One or more longterm_pool_quality CSV files.")
    parser.add_argument("--labels", default=None, help="Comma-separated labels, matching --inputs.")
    parser.add_argument("--horizon", type=int, default=80, help="Forward horizon to diagnose.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--csv-output", default=None, help="Optional combined layered CSV output path.")
    parser.add_argument("--top", type=int, default=25, help="Number of inversion cases to show.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labels = args.labels.split(",") if args.labels else [None] * len(args.inputs)
    if len(labels) != len(args.inputs):
        raise SystemExit("--labels 数量必须和 --inputs 文件数量一致")

    frames = [load_rank_csv(path, label) for path, label in zip(args.inputs, labels)]
    data = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
    layered = add_rank_layers(data) if not data.empty else data
    report = build_report(layered, horizon=args.horizon, top=args.top)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if args.csv_output:
        csv_out = Path(args.csv_output)
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        layered.to_csv(csv_out, index=False, encoding="utf-8-sig")
    print(f"Report written: {out}")


if __name__ == "__main__":
    main()
