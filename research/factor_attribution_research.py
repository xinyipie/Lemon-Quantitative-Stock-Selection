from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

ENGINE_EXITS = REPORTS / "engine_all_entry_bucket_candidate_exits_20260706.csv"
OUTCOMES = REPORTS / "entry_timing_outcomes_T1_T3_T5_T7_20260706.csv"


BASE_NUMERIC_FACTORS = [
    "n_versions",
    "best_rank",
    "avg_rank",
    "factor_pattern",
    "factor_inflow",
    "factor_sector",
    "factor_wyckoff",
    "factor_volume_ratio",
    "sector_ma10_ratio",
    "limit_up_count",
    "limit_down_count",
    "hybrid_score",
    "consensus_score",
    "pre_T3_low_pct",
    "pre_T3_close_min_pct",
    "pre_T5_low_pct",
    "pre_T5_close_min_pct",
    "pre_T7_low_pct",
    "pre_T7_close_min_pct",
]

CATEGORICAL_FACTORS = [
    "entry_bucket",
    "market_style",
    "macro_mode",
    "regime",
    "operation_mode",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing input: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ret"] = pd.to_numeric(out["ret"], errors="coerce").fillna(0.0)
    out["win"] = out["ret"] > 0
    out["year"] = out["year"].astype(str)
    for col in BASE_NUMERIC_FACTORS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # 路径承接因子：低点到收盘最弱点的距离越大，说明下探后有承接。
    if {"pre_T3_close_min_pct", "pre_T3_low_pct"}.issubset(out.columns):
        out["support_gap_T3"] = out["pre_T3_close_min_pct"] - out["pre_T3_low_pct"]
    if {"pre_T5_close_min_pct", "pre_T5_low_pct"}.issubset(out.columns):
        out["support_gap_T5"] = out["pre_T5_close_min_pct"] - out["pre_T5_low_pct"]
    if {"pre_T7_close_min_pct", "pre_T7_low_pct"}.issubset(out.columns):
        out["support_gap_T7"] = out["pre_T7_close_min_pct"] - out["pre_T7_low_pct"]

    # 回踩是否继续恶化：T7 低点比 T5 低点更低，通常说明等待中结构变坏。
    if {"pre_T7_low_pct", "pre_T5_low_pct"}.issubset(out.columns):
        out["late_low_deterioration_T7_vs_T5"] = out["pre_T7_low_pct"] - out["pre_T5_low_pct"]
    if {"pre_T5_low_pct", "pre_T3_low_pct"}.issubset(out.columns):
        out["mid_low_deterioration_T5_vs_T3"] = out["pre_T5_low_pct"] - out["pre_T3_low_pct"]

    # 市场温度因子：涨停多但跌停也多，容易是分歧行情。
    if {"limit_up_count", "limit_down_count"}.issubset(out.columns):
        out["limit_up_down_spread"] = out["limit_up_count"] - out["limit_down_count"]
        out["limit_down_pressure"] = out["limit_down_count"] / (out["limit_up_count"].abs() + 1.0)

    if {"factor_sector", "sector_ma10_ratio"}.issubset(out.columns):
        out["sector_quality_mix"] = out["factor_sector"] * 0.5 + out["sector_ma10_ratio"] * 0.5
    if {"factor_pattern", "factor_wyckoff"}.issubset(out.columns):
        out["pattern_structure_mix"] = out["factor_pattern"] * 0.55 + out["factor_wyckoff"] * 0.45
    if {"factor_inflow", "factor_volume_ratio"}.issubset(out.columns):
        out["flow_volume_mix"] = out["factor_inflow"] * 0.6 + out["factor_volume_ratio"] * 0.4

    return out


def _metrics(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "avg_ret": 0.0,
            "total_ret": 0.0,
            "positive_years": 0,
            "loss_years": 0,
            "worst_year": 0.0,
        }
    yearly = df.groupby("year")["ret"].sum()
    return {
        "trades": int(len(df)),
        "win_rate": float(df["win"].mean() * 100),
        "avg_ret": float(df["ret"].mean()),
        "total_ret": float(df["ret"].sum()),
        "positive_years": int((yearly > 0).sum()),
        "loss_years": int((yearly < 0).sum()),
        "worst_year": float(yearly.min()),
    }


def _segment_numeric(df: pd.DataFrame, factor: str, side: str) -> tuple[pd.DataFrame, float]:
    series = pd.to_numeric(df[factor], errors="coerce")
    if series.notna().sum() < 20 or series.nunique(dropna=True) < 4:
        return df.iloc[0:0].copy(), np.nan
    if side == "high":
        threshold = float(series.quantile(0.75))
        return df[series >= threshold].copy(), threshold
    threshold = float(series.quantile(0.25))
    return df[series <= threshold].copy(), threshold


def _is_live_usable(scope: str, factor: str) -> bool:
    # T1 只能使用选股日已知因子，不能偷看 T3/T5/T7 路径。
    if scope == "T1" and factor.startswith(("pre_T", "support_gap_", "mid_low_", "late_low_")):
        return False
    if scope == "T3" and factor.startswith(("pre_T5", "pre_T7", "support_gap_T5", "support_gap_T7", "mid_low_", "late_low_")):
        return False
    if scope == "T5" and factor.startswith(("pre_T7", "support_gap_T7", "late_low_")):
        return False
    # ALL 里混有不同入场桶，路径因子先当诊断线索，不直接当全局实盘规则。
    if scope == "ALL" and factor.startswith(("pre_T", "support_gap_", "mid_low_", "late_low_")):
        return False
    return True


def numeric_attribution(df: pd.DataFrame) -> pd.DataFrame:
    factors = [c for c in BASE_NUMERIC_FACTORS + [
        "support_gap_T3",
        "support_gap_T5",
        "support_gap_T7",
        "late_low_deterioration_T7_vs_T5",
        "mid_low_deterioration_T5_vs_T3",
        "limit_up_down_spread",
        "limit_down_pressure",
        "sector_quality_mix",
        "pattern_structure_mix",
        "flow_volume_mix",
    ] if c in df.columns]

    rows = []
    scopes = [("ALL", df)]
    scopes.extend((str(bucket), part) for bucket, part in df.groupby("entry_bucket"))
    for scope, base in scopes:
        if len(base) < 30:
            continue
        base_metrics = _metrics(base)
        for factor in factors:
            for side in ["high", "low"]:
                selected, threshold = _segment_numeric(base, factor, side)
                if len(selected) < max(15, min(40, len(base) * 0.12)):
                    continue
                selected_metrics = _metrics(selected)
                rows.append({
                    "scope": scope,
                    "factor": factor,
                    "side": side,
                    "threshold": threshold,
                    "live_usable": _is_live_usable(scope, factor),
                    **selected_metrics,
                    "base_trades": base_metrics["trades"],
                    "base_win_rate": base_metrics["win_rate"],
                    "base_avg_ret": base_metrics["avg_ret"],
                    "base_total_ret": base_metrics["total_ret"],
                    "win_edge": selected_metrics["win_rate"] - base_metrics["win_rate"],
                    "avg_ret_edge": selected_metrics["avg_ret"] - base_metrics["avg_ret"],
                    "score": (
                        (selected_metrics["win_rate"] - base_metrics["win_rate"]) * 1.5
                        + (selected_metrics["avg_ret"] - base_metrics["avg_ret"]) * 10.0
                        + min(selected_metrics["trades"], 120) * 0.08
                        - selected_metrics["loss_years"] * 4.0
                        - abs(min(selected_metrics["worst_year"], 0.0)) * 0.8
                    ),
                })
    return pd.DataFrame(rows).sort_values(["score", "win_rate", "total_ret"], ascending=False).reset_index(drop=True)


def categorical_attribution(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base_metrics = _metrics(df)
    for factor in [c for c in CATEGORICAL_FACTORS if c in df.columns]:
        for value, selected in df.groupby(factor):
            if len(selected) < 15:
                continue
            selected_metrics = _metrics(selected)
            rows.append({
                "factor": factor,
                "value": value,
                **selected_metrics,
                "base_win_rate": base_metrics["win_rate"],
                "base_avg_ret": base_metrics["avg_ret"],
                "win_edge": selected_metrics["win_rate"] - base_metrics["win_rate"],
                "avg_ret_edge": selected_metrics["avg_ret"] - base_metrics["avg_ret"],
                "score": (
                    (selected_metrics["win_rate"] - base_metrics["win_rate"]) * 1.4
                    + (selected_metrics["avg_ret"] - base_metrics["avg_ret"]) * 10.0
                    + min(selected_metrics["trades"], 150) * 0.06
                    - selected_metrics["loss_years"] * 4.0
                    - abs(min(selected_metrics["worst_year"], 0.0)) * 0.8
                ),
            })
    return pd.DataFrame(rows).sort_values(["score", "win_rate", "total_ret"], ascending=False).reset_index(drop=True)


def yearly_for_top_segments(df: pd.DataFrame, numeric: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    rows = []
    for row in numeric.head(limit).itertuples(index=False):
        base = df if row.scope == "ALL" else df[df["entry_bucket"].astype(str).eq(str(row.scope))]
        selected, _ = _segment_numeric(base, row.factor, row.side)
        if selected.empty:
            continue
        yearly = selected.groupby("year").agg(
            trades=("ret", "size"),
            win_rate=("win", "mean"),
            total_ret=("ret", "sum"),
        ).reset_index()
        yearly["win_rate"] = yearly["win_rate"] * 100
        yearly.insert(0, "segment", f"{row.scope}:{row.factor}:{row.side}@{row.threshold:.2f}")
        rows.append(yearly)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _write_doc(
    base: dict[str, float],
    numeric: pd.DataFrame,
    categorical: pd.DataFrame,
    yearly: pd.DataFrame,
    output: Path,
) -> None:
    top_numeric_cols = [
        "scope",
        "factor",
        "side",
        "threshold",
        "live_usable",
        "trades",
        "win_rate",
        "avg_ret",
        "total_ret",
        "positive_years",
        "loss_years",
        "worst_year",
        "win_edge",
        "avg_ret_edge",
        "score",
    ]
    top_cat_cols = [
        "factor",
        "value",
        "trades",
        "win_rate",
        "avg_ret",
        "total_ret",
        "positive_years",
        "loss_years",
        "worst_year",
        "win_edge",
        "avg_ret_edge",
        "score",
    ]
    lines = [
        "# 新因子归因研究（2026-07-07）",
        "",
        "## 研究口径",
        "",
        "- 数据源使用已生成的 `engine_all_entry_bucket_candidate_exits_20260706.csv`，收益口径为 BacktestV2 真实退出后的 `ret`。",
        "- 不搜索复杂组合，只做单因子上下四分位分组与类别分组，观察胜率、平均收益、年度稳定性。",
        "- 新派生因子集中在回踩承接、低点恶化、涨跌停分歧、板块质量、形态结构、资金量能混合。",
        "",
        "## 全样本基准",
        "",
        f"- 笔数：{base['trades']}",
        f"- 胜率：{base['win_rate']:.2f}%",
        f"- 平均收益：{base['avg_ret']:.2f}%",
        f"- 总收益：{base['total_ret']:.2f}%",
        f"- 亏损年份：{base['loss_years']}",
        f"- 最差年份：{base['worst_year']:.2f}%",
        "",
        "## 数值因子 Top30",
        "",
        numeric[[c for c in top_numeric_cols if c in numeric.columns]].head(30).to_markdown(index=False, floatfmt=".2f") if not numeric.empty else "无",
        "",
        "## 实盘可用数值因子 Top30",
        "",
        numeric[numeric["live_usable"]][[c for c in top_numeric_cols if c in numeric.columns]].head(30).to_markdown(index=False, floatfmt=".2f") if not numeric.empty else "无",
        "",
        "## 类别因子 Top20",
        "",
        categorical[[c for c in top_cat_cols if c in categorical.columns]].head(20).to_markdown(index=False, floatfmt=".2f") if not categorical.empty else "无",
        "",
        "## Top 数值分组年度拆分",
        "",
        yearly.to_markdown(index=False, floatfmt=".2f") if not yearly.empty else "无",
        "",
        "## 初步读法",
        "",
        "- 排名靠前的单因子只能作为候选线索，不能直接当策略上线。",
        "- 如果某个因子在 ALL 和多个入场桶里都有效，优先进入下一轮无年份规则组合。",
        "- 如果某个因子只在单一年份或单一入场桶有效，要先做避坑解释，再决定是否纳入。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    df = _normalise(_read_csv(ENGINE_EXITS))
    base = _metrics(df)
    numeric = numeric_attribution(df)
    categorical = categorical_attribution(df)
    yearly = yearly_for_top_segments(df, numeric)

    numeric.to_csv(REPORTS / "factor_attribution_numeric_20260707.csv", index=False, encoding="utf-8-sig")
    categorical.to_csv(REPORTS / "factor_attribution_categorical_20260707.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(REPORTS / "factor_attribution_top_yearly_20260707.csv", index=False, encoding="utf-8-sig")
    _write_doc(base, numeric, categorical, yearly, DOCS / "FACTOR_ATTRIBUTION_RESEARCH_20260707.md")

    print("base", base)
    print()
    print(numeric.head(25).to_string(index=False))
    print()
    print(categorical.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
