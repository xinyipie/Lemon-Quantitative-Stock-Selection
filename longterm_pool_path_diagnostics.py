#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose longterm pool path quality from pool-quality audit CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


FACTOR_COLUMNS = [
    "winner_profile_score",
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
    "total_mv",
    "circ_mv",
]

DISPLAY_COLUMNS = [
    "source_label",
    "stage",
    "select_date",
    "ts_code",
    "name",
    "industry",
    "path_group",
    "ret_h",
    "mfe_h",
    "mae_h",
    "giveback_h",
    "longterm_score",
    "pool_rank_score",
    "quality_rank_score",
    "industry_rs",
    "price_vs_ma60",
    "drawdown_from_high",
    "turnover",
    "roe",
]

GROUP_ORDER = [
    "smooth_winner",
    "profit_giveback",
    "early_entry",
    "bad_selection",
    "unfinished",
    "other",
]


def _fmt_pct(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):+.2f}%"


def _table(df: pd.DataFrame, cols: list[str] | None = None, max_rows: int = 30) -> str:
    if df.empty:
        return "无样本\n"
    view = df.copy()
    if cols:
        view = view[[col for col in cols if col in view.columns]]
    return view.head(max_rows).to_markdown(index=False) + "\n"


def load_pool_paths(path: str | Path, label: str | None = None) -> pd.DataFrame:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(p, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    return normalize_pool_paths(df, label or p.stem)


def normalize_pool_paths(df: pd.DataFrame, label: str = "data") -> pd.DataFrame:
    work = df.copy()
    if "source_label" not in work.columns or label != "data":
        work["source_label"] = label
    if "stage" not in work.columns:
        work["stage"] = label
    if "longterm_score" not in work.columns and "score" in work.columns:
        work["longterm_score"] = work["score"]
    numeric_cols = set(FACTOR_COLUMNS)
    for prefix in ("ret", "mfe", "mae", "excess_ret", "benchmark_ret"):
        numeric_cols.update(col for col in work.columns if col.startswith(f"{prefix}_"))
    for col in numeric_cols:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    for col in ["source_label", "stage", "select_date", "ts_code", "name", "industry", "pool_type"]:
        if col in work.columns:
            work[col] = work[col].fillna("NA").astype(str)
    return work


def classify_paths(
    df: pd.DataFrame,
    horizon: int = 80,
    high_mfe: float = 15.0,
    low_mfe: float = 8.0,
    shallow_mae: float = -8.0,
    deep_mae: float = -12.0,
    positive_ret: float = 0.0,
) -> pd.DataFrame:
    data = normalize_pool_paths(df)
    ret_col = f"ret_{horizon}d"
    mfe_col = f"mfe_{horizon}d"
    mae_col = f"mae_{horizon}d"
    missing = {ret_col, mfe_col, mae_col} - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    data["ret_h"] = data[ret_col]
    data["mfe_h"] = data[mfe_col]
    data["mae_h"] = data[mae_col]
    data["giveback_h"] = data["mfe_h"] - data["ret_h"]
    data["path_group"] = "other"
    data.loc[data["ret_h"].isna() | data["mfe_h"].isna() | data["mae_h"].isna(), "path_group"] = "unfinished"

    complete = data["path_group"].ne("unfinished")
    smooth = complete & (data["mfe_h"] >= high_mfe) & (data["mae_h"] >= shallow_mae) & (data["ret_h"] >= positive_ret)
    giveback = complete & (data["mfe_h"] >= high_mfe) & (data["ret_h"] < positive_ret)
    early = complete & (data["mfe_h"] >= high_mfe) & (data["mae_h"] <= deep_mae) & (data["ret_h"] >= positive_ret)
    bad = complete & (data["mfe_h"] < low_mfe) & (data["mae_h"] <= deep_mae) & (data["ret_h"] < positive_ret)

    data.loc[smooth, "path_group"] = "smooth_winner"
    data.loc[giveback, "path_group"] = "profit_giveback"
    data.loc[early, "path_group"] = "early_entry"
    data.loc[bad, "path_group"] = "bad_selection"
    data["path_group"] = pd.Categorical(data["path_group"], GROUP_ORDER, ordered=True)
    return data


def path_summary(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy() if "path_group" in df.columns else classify_paths(df)
    result = (
        data.groupby(["source_label", "path_group"], observed=False)
        .agg(
            count=("ts_code", "size"),
            avg_ret=("ret_h", "mean"),
            avg_mfe=("mfe_h", "mean"),
            avg_mae=("mae_h", "mean"),
            avg_giveback=("giveback_h", "mean"),
        )
        .reset_index()
        .round(2)
    )
    return result[result["count"] > 0].reset_index(drop=True)


def factor_group_diff(df: pd.DataFrame, factors: list[str] | None = None) -> pd.DataFrame:
    data = df.copy() if "path_group" in df.columns else classify_paths(df)
    factors = [col for col in (factors or FACTOR_COLUMNS) if col in data.columns]
    smooth = data[data["path_group"] == "smooth_winner"]
    bad = data[data["path_group"] == "bad_selection"]
    giveback = data[data["path_group"] == "profit_giveback"]
    early = data[data["path_group"] == "early_entry"]
    rows = []
    for factor in factors:
        smooth_avg = smooth[factor].mean()
        bad_avg = bad[factor].mean()
        giveback_avg = giveback[factor].mean()
        early_avg = early[factor].mean()
        if pd.isna(smooth_avg) or pd.isna(bad_avg):
            continue
        rows.append(
            {
                "factor": factor,
                "smooth_winner_avg": round(float(smooth_avg), 3),
                "bad_selection_avg": round(float(bad_avg), 3),
                "bad_minus_smooth": round(float(bad_avg - smooth_avg), 3),
                "profit_giveback_avg": round(float(giveback_avg), 3) if not pd.isna(giveback_avg) else None,
                "early_entry_avg": round(float(early_avg), 3) if not pd.isna(early_avg) else None,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "factor",
                "smooth_winner_avg",
                "bad_selection_avg",
                "bad_minus_smooth",
                "profit_giveback_avg",
                "early_entry_avg",
            ]
        )
    return pd.DataFrame(rows).sort_values("bad_minus_smooth", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def stage_summary(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy() if "path_group" in df.columns else classify_paths(df)
    result = (
        data.groupby("stage", dropna=False)
        .agg(
            count=("ts_code", "size"),
            complete=("ret_h", lambda s: s.notna().sum()),
            avg_ret=("ret_h", "mean"),
            avg_mfe=("mfe_h", "mean"),
            avg_mae=("mae_h", "mean"),
            win_rate=("ret_h", lambda s: (s.dropna() > 0).mean() * 100 if s.notna().any() else None),
        )
        .reset_index()
        .round(2)
    )
    return result


def _decision_notes(df: pd.DataFrame) -> list[str]:
    complete = df[df["path_group"] != "unfinished"]
    if complete.empty:
        return ["- 有效样本不足，不能据此调整策略。"]
    counts = complete["path_group"].astype(str).value_counts()
    total = len(complete)
    giveback_rate = counts.get("profit_giveback", 0) / total
    bad_rate = counts.get("bad_selection", 0) / total
    early_rate = counts.get("early_entry", 0) / total
    notes = []
    if giveback_rate >= 0.35:
        notes.append("- 高MFE回吐样本占比较高：优先研究止盈/移动止损，而不是继续加选股因子。")
    if bad_rate >= 0.35:
        notes.append("- 坏票样本占比较高：优先研究入池过滤，尤其是坏票与顺滑赢家的稳定差异。")
    if early_rate >= 0.25:
        notes.append("- 买早样本占比较高：优先研究入场确认或分批入池，不宜直接提高综合分门槛。")
    if not notes:
        notes.append("- 没有单一问题占主导：下一步应先扩大样本或按市场阶段分开诊断。")
    return notes


def build_report(df: pd.DataFrame, horizon: int = 80, title: str = "长线股票池路径诊断", top: int = 30) -> str:
    data = df.copy() if "path_group" in df.columns else classify_paths(df, horizon=horizon)
    summary = path_summary(data)
    by_stage = stage_summary(data)
    diff = factor_group_diff(data)
    complete_count = int(data["ret_h"].notna().sum())
    unfinished_count = int(data["ret_h"].isna().sum())
    group_counts = data["path_group"].astype(str).value_counts()
    smooth_count = int(group_counts.get("smooth_winner", 0))
    giveback_count = int(group_counts.get("profit_giveback", 0))
    early_count = int(group_counts.get("early_entry", 0))
    bad_count = int(group_counts.get("bad_selection", 0))

    high_giveback = data[data["path_group"] == "profit_giveback"].sort_values("mfe_h", ascending=False)
    bad_samples = data[data["path_group"] == "bad_selection"].sort_values("mae_h")
    smooth_samples = data[data["path_group"] == "smooth_winner"].sort_values("ret_h", ascending=False)
    early_samples = data[data["path_group"] == "early_entry"].sort_values("mae_h")

    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 共分析 `{len(data)}` 个入池样本，`{horizon}`日有效样本 `{complete_count}` 个，未满窗口 `{unfinished_count}` 个。\n",
        f"- 路径分类：好票好持有 `{smooth_count}`，好票没守住 `{giveback_count}`，买早了 `{early_count}`，坏票 `{bad_count}`。\n",
    ]
    if complete_count:
        avg_ret = data["ret_h"].mean()
        avg_mfe = data["mfe_h"].mean()
        avg_mae = data["mae_h"].mean()
        lines.append(f"- 有效样本均值：最终收益 `{_fmt_pct(avg_ret)}`，MFE `{_fmt_pct(avg_mfe)}`，MAE `{_fmt_pct(avg_mae)}`。\n")
    lines.extend(_decision_notes(data))
    lines.extend(
        [
            "\n## 路径质量分组\n",
            _table(summary, max_rows=80),
            "\n## 分阶段表现\n",
            _table(by_stage, max_rows=80),
            "\n## bad_selection vs smooth_winner 因子差异\n",
            _table(diff, max_rows=40),
            "\n## 好票没守住样本\n",
            _table(high_giveback, DISPLAY_COLUMNS, max_rows=top),
            "\n## 买早了样本\n",
            _table(early_samples, DISPLAY_COLUMNS, max_rows=top),
            "\n## 坏票样本\n",
            _table(bad_samples, DISPLAY_COLUMNS, max_rows=top),
            "\n## 好票好持有样本\n",
            _table(smooth_samples, DISPLAY_COLUMNS, max_rows=top),
            "\n## 下一步判断\n",
            "- 若“好票没守住”占主导，下一轮只做出场/止盈诊断，不调选股因子。\n",
            "- 若“坏票”占主导，下一轮才考虑选股过滤，但只使用跨阶段稳定差异。\n",
            "- 若“买早了”占主导，下一轮研究入场确认，不把某个时间段的结果硬写成行业或个股规则。\n",
        ]
    )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose longterm pool MFE/MAE path quality.")
    parser.add_argument("--inputs", nargs="+", required=True, help="One or more longterm_pool_quality_*.csv files.")
    parser.add_argument("--labels", default=None, help="Comma separated labels. Defaults to file stems.")
    parser.add_argument("--horizon", type=int, default=80, help="Forward horizon to diagnose, e.g. 40 or 80.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--top", type=int, default=30, help="Max sample rows per section.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labels = args.labels.split(",") if args.labels else [None] * len(args.inputs)
    if len(labels) != len(args.inputs):
        raise SystemExit("--labels 数量必须与 --inputs 文件数量一致")
    frames = [load_pool_paths(path, label) for path, label in zip(args.inputs, labels)]
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    labeled = classify_paths(data, horizon=args.horizon) if not data.empty else data
    report = build_report(labeled, horizon=args.horizon, top=args.top)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
