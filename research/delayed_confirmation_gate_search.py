from __future__ import annotations

from itertools import product
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

ENGINE_EXITS = REPORTS / "engine_all_entry_bucket_candidate_exits_20260706.csv"
STRONG_TRADES = REPORTS / "v45_engine_exit_trades_20260706.csv"


def _load_candidates() -> pd.DataFrame:
    df = pd.read_csv(ENGINE_EXITS, encoding="utf-8-sig")
    df["ret"] = pd.to_numeric(df["ret"], errors="coerce").fillna(0.0)
    df["win"] = df["ret"] > 0
    df["year"] = df["year"].astype(str)
    for col in [
        "best_rank",
        "avg_rank",
        "factor_pattern",
        "factor_sector",
        "factor_wyckoff",
        "factor_inflow",
        "factor_volume_ratio",
        "sector_ma10_ratio",
        "limit_down_count",
        "hybrid_score",
        "consensus_score",
        "pre_T3_low_pct",
        "pre_T3_close_min_pct",
        "pre_T5_low_pct",
        "pre_T5_close_min_pct",
        "pre_T7_low_pct",
        "pre_T7_close_min_pct",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if {"pre_T5_low_pct", "pre_T3_low_pct"}.issubset(df.columns):
        df["mid_low_deterioration_T5_vs_T3"] = df["pre_T5_low_pct"] - df["pre_T3_low_pct"]
    if {"pre_T7_low_pct", "pre_T5_low_pct"}.issubset(df.columns):
        df["late_low_deterioration_T7_vs_T5"] = df["pre_T7_low_pct"] - df["pre_T5_low_pct"]
    if {"pre_T5_close_min_pct", "pre_T5_low_pct"}.issubset(df.columns):
        df["support_gap_T5"] = df["pre_T5_close_min_pct"] - df["pre_T5_low_pct"]
    if {"pre_T7_close_min_pct", "pre_T7_low_pct"}.issubset(df.columns):
        df["support_gap_T7"] = df["pre_T7_close_min_pct"] - df["pre_T7_low_pct"]
    return df


def _load_strong() -> pd.DataFrame:
    trades = pd.read_csv(STRONG_TRADES, encoding="utf-8-sig")
    strong = trades[trades["entry_rule"].astype(str).eq("strong_T1")].copy()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    strong["year"] = strong["year"].astype(str)
    return strong


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
            "recent_trades": 0,
            "recent_win_rate": 0.0,
        }
    yearly = df.groupby("year")["ret"].sum()
    recent = df[df["year"].isin(["2025", "2026H1"])]
    return {
        "trades": int(len(df)),
        "win_rate": float(df["win"].mean() * 100),
        "avg_ret": float(df["ret"].mean()),
        "total_ret": float(df["ret"].sum()),
        "positive_years": int((yearly > 0).sum()),
        "loss_years": int((yearly < 0).sum()),
        "worst_year": float(yearly.min()),
        "recent_trades": int(len(recent)),
        "recent_win_rate": float(recent["win"].mean() * 100) if len(recent) else 0.0,
    }


def _path_cols(bucket: str) -> tuple[str, str, str | None, str | None]:
    if bucket == "T3":
        return "pre_T3_low_pct", "pre_T3_close_min_pct", None, None
    if bucket == "T5":
        return "pre_T5_low_pct", "pre_T5_close_min_pct", "mid_low_deterioration_T5_vs_T3", "support_gap_T5"
    return "pre_T7_low_pct", "pre_T7_close_min_pct", "late_low_deterioration_T7_vs_T5", "support_gap_T7"


def _select(df: pd.DataFrame, rule: dict) -> pd.DataFrame:
    bucket = rule["entry_bucket"]
    low_col, close_col, deterioration_col, support_col = _path_cols(bucket)
    work = df[df["entry_bucket"].astype(str).eq(bucket)].copy()
    work = work[
        (work["best_rank"] <= rule["best_rank"])
        & (work["avg_rank"] <= rule["avg_rank"])
        & (work["factor_pattern"] >= rule["pattern"])
        & (work["factor_sector"] >= rule["sector"])
        & (work["sector_ma10_ratio"] >= rule["sector_ma10"])
        & (work["limit_down_count"] <= rule["limit_down"])
        & (work[low_col] > rule["pre_low"])
        & (work[close_col] > rule["pre_close"])
    ].copy()
    if deterioration_col is not None:
        work = work[work[deterioration_col] >= rule["deterioration"]]
    if support_col is not None and rule["support_gap"] is not None:
        work = work[work[support_col] >= rule["support_gap"]]
    if rule["macro_mode"] is not None:
        work = work[work["macro_mode"].astype(str).eq(rule["macro_mode"])]
    if rule["market_style"] is not None:
        work = work[work["market_style"].astype(str).eq(rule["market_style"])]
    if work.empty:
        return work
    score_col = "hybrid_score" if "hybrid_score" in work.columns else "consensus_score"
    return (
        work.sort_values(["select_date", score_col, "ts_code"], ascending=[True, False, True])
        .groupby("select_date", group_keys=False)
        .head(rule["topn"])
        .reset_index(drop=True)
    )


def search() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = _load_candidates()
    strong = _load_strong()
    strong_dates = set(strong["select_date"].astype(str))
    candidates = candidates[~candidates["select_date"].astype(str).isin(strong_dates)].copy()

    grids = {
        "entry_bucket": ["T3", "T5", "T7"],
        "best_rank": [1.0, 2.0],
        "avg_rank": [1.5, 2.5],
        "pattern": [50.0, 60.0],
        "sector": [30.0, 50.0],
        "sector_ma10": [70.0, 90.0],
        "limit_down": [4.0, 8.0],
        "pre_low": [-1.0, -1.5, -2.0],
        "pre_close": [-0.5, -1.0],
        "deterioration": [-1.0, 0.0],
        "support_gap": [None, 1.0],
        "macro_mode": [None, "cautious"],
        "market_style": [None, "weak_momentum", "sideways"],
        "topn": [1],
    }
    keys = list(grids)
    rows = []
    best_trades = pd.DataFrame()
    for values in product(*(grids[key] for key in keys)):
        rule = dict(zip(keys, values))
        expansion = _select(candidates, rule)
        if not (20 <= len(expansion) <= 120):
            continue
        expansion_metrics = _metrics(expansion)
        if expansion_metrics["win_rate"] < 45 or expansion_metrics["avg_ret"] <= 0:
            continue
        combo = pd.concat([strong, expansion], ignore_index=True, sort=False)
        combo = combo.sort_values(["select_date", "ts_code"]).drop_duplicates(["year", "select_date", "ts_code"])
        metrics = _metrics(combo)
        if metrics["trades"] < 60:
            continue
        score = (
            metrics["win_rate"] * 1.2
            + min(metrics["total_ret"], 360.0) * 0.11
            + min(metrics["trades"], 140) * 0.12
            + metrics["recent_win_rate"] * 0.25
            - metrics["loss_years"] * 8.0
            - abs(min(metrics["worst_year"], 0.0)) * 1.2
        )
        rows.append({
            **rule,
            **{f"combo_{k}": v for k, v in metrics.items()},
            **{f"expansion_{k}": v for k, v in expansion_metrics.items()},
            "score": score,
        })
        if best_trades.empty or score > float(best_trades.attrs.get("score", -999999)):
            best_trades = combo.copy()
            best_trades.attrs["score"] = score

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["score", "combo_win_rate", "combo_total_ret"], ascending=False).reset_index(drop=True)
    yearly = pd.DataFrame()
    if not best_trades.empty:
        yearly = best_trades.groupby("year").agg(
            trades=("ret", "size"),
            win_rate=("win", "mean"),
            total_ret=("ret", "sum"),
        ).reset_index()
        yearly["win_rate"] = yearly["win_rate"] * 100
    return result, best_trades, yearly


def _write_doc(result: pd.DataFrame, best_trades: pd.DataFrame, yearly: pd.DataFrame, output: Path) -> None:
    lines = [
        "# 延迟确认门搜索（2026-07-07）",
        "",
        "## 研究口径",
        "",
        "- 使用真实退出收益 `engine_all_entry_bucket_candidate_exits_20260706.csv`。",
        "- 只搜索 T3/T5/T7 延迟入场，路径因子严格限制为入场前已经发生的信息。",
        "- 每个选股日最多 Top1，先排除 strong_T1 已占用日期，再与 strong_T1 合并评估。",
        "- 这是研究候选，不是线上策略变更。",
        "",
        "## Top30",
        "",
        result.head(30).to_markdown(index=False, floatfmt=".2f") if not result.empty else "无候选",
        "",
        "## 最优候选年度拆分",
        "",
        yearly.to_markdown(index=False, floatfmt=".2f") if not yearly.empty else "无",
        "",
        "## 初步读法",
        "",
        "- 如果 Top 规则集中在 T5/T7 且 `pre_close`、`pre_low` 较高，说明等待后的确认更像过滤器，不是越跌越买。",
        "- 如果规则依赖 `sector_ma10>=90` 且 2020/2024 仍亏，要继续加市场分歧避坑。",
        "- 若扩容层自身胜率低于 50%，即使合并后好看也不应进入上线候选。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    result, best_trades, yearly = search()
    result.to_csv(REPORTS / "delayed_confirmation_gate_search_20260707.csv", index=False, encoding="utf-8-sig")
    best_trades.to_csv(REPORTS / "delayed_confirmation_gate_best_trades_20260707.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(REPORTS / "delayed_confirmation_gate_best_yearly_20260707.csv", index=False, encoding="utf-8-sig")
    _write_doc(result, best_trades, yearly, DOCS / "DELAYED_CONFIRMATION_GATE_SEARCH_20260707.md")
    print(result.head(40).to_string(index=False) if not result.empty else "no candidates")
    print()
    print(yearly.to_string(index=False) if not yearly.empty else "no yearly")


if __name__ == "__main__":
    main()
