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
    df = df[df["entry_bucket"].astype(str).eq("T3")].copy()
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
        "limit_up_count",
        "limit_down_count",
        "hybrid_score",
        "consensus_score",
        "pre_T3_low_pct",
        "pre_T3_close_min_pct",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if {"pre_T3_close_min_pct", "pre_T3_low_pct"}.issubset(df.columns):
        df["support_gap_T3"] = df["pre_T3_close_min_pct"] - df["pre_T3_low_pct"]
    if {"factor_pattern", "factor_wyckoff"}.issubset(df.columns):
        df["pattern_structure_mix"] = df["factor_pattern"] * 0.55 + df["factor_wyckoff"] * 0.45
    if {"factor_inflow", "factor_volume_ratio"}.issubset(df.columns):
        df["flow_volume_mix"] = df["factor_inflow"] * 0.6 + df["factor_volume_ratio"] * 0.4
    if {"factor_sector", "sector_ma10_ratio"}.issubset(df.columns):
        df["sector_quality_mix"] = df["factor_sector"] * 0.5 + df["sector_ma10_ratio"] * 0.5
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


def _apply_rule(df: pd.DataFrame, rule: dict) -> pd.DataFrame:
    work = df.copy()
    for col, op, value in rule["conditions"]:
        series = pd.to_numeric(work[col], errors="coerce") if col in work.columns else pd.Series(False, index=work.index)
        if op == ">=":
            work = work[series >= value]
        elif op == "<=":
            work = work[series <= value]
        elif op == ">":
            work = work[series > value]
        elif op == "<":
            work = work[series < value]
    if rule["macro_mode"] is not None:
        work = work[work["macro_mode"].astype(str).eq(rule["macro_mode"])]
    if rule["market_style"] is not None:
        work = work[work["market_style"].astype(str).eq(rule["market_style"])]
    if work.empty:
        return work
    return (
        work.sort_values(["select_date", rule["score_col"], "ts_code"], ascending=[True, False, True])
        .groupby("select_date", group_keys=False)
        .head(rule["topn"])
        .reset_index(drop=True)
    )


def _condition_sets() -> list[tuple[str, list[tuple[str, str, float]]]]:
    base_sets = []
    rank_sets = [
        [("best_rank", "<=", 2.0), ("avg_rank", "<=", 2.5)],
        [("best_rank", "<=", 1.0), ("avg_rank", "<=", 2.0)],
        [("avg_rank", "<=", 1.5)],
    ]
    quality_sets = [
        [("factor_pattern", ">=", 50.0), ("factor_sector", ">=", 30.0)],
        [("factor_pattern", ">=", 60.0), ("factor_sector", ">=", 30.0)],
        [("pattern_structure_mix", ">=", 62.0), ("sector_quality_mix", ">=", 55.0)],
        [("hybrid_score", ">=", 3120.0)],
        [("consensus_score", ">=", 3020.0)],
    ]
    path_sets = [
        [("pre_T3_low_pct", ">", -1.0), ("pre_T3_close_min_pct", ">", -0.5)],
        [("pre_T3_low_pct", ">", -1.5), ("pre_T3_close_min_pct", ">", -0.5)],
        [("pre_T3_low_pct", ">", -2.0), ("pre_T3_close_min_pct", ">", -1.0)],
        [("support_gap_T3", ">=", 1.0), ("pre_T3_close_min_pct", ">", -0.5)],
    ]
    market_sets = [
        [],
        [("sector_ma10_ratio", ">=", 70.0)],
        [("sector_ma10_ratio", ">=", 90.0)],
        [("limit_down_count", "<=", 4.0)],
        [("limit_down_count", "<=", 8.0), ("sector_ma10_ratio", ">=", 70.0)],
    ]
    for rank, quality, path, market in product(rank_sets, quality_sets, path_sets, market_sets):
        conds = rank + quality + path + market
        name = " & ".join(f"{col}{op}{value:g}" for col, op, value in conds)
        base_sets.append((name, conds))
    return base_sets


def search() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = _load_candidates()
    strong = _load_strong()
    strong_dates = set(strong["select_date"].astype(str))
    df = df[~df["select_date"].astype(str).isin(strong_dates)].copy()
    rows = []
    best_trades = pd.DataFrame()
    best_score = -999999.0
    for name, conditions in _condition_sets():
        for macro_mode, market_style, score_col in product(
            [None, "active", "cautious"],
            [None, "weak_momentum", "sideways", "momentum"],
            ["hybrid_score", "consensus_score"],
        ):
            for topn in [1, 2]:
                rule = {
                    "rule": name,
                    "conditions": conditions,
                    "macro_mode": macro_mode,
                    "market_style": market_style,
                    "score_col": score_col,
                    "topn": topn,
                }
                expansion = _apply_rule(df, rule)
                if not (18 <= len(expansion) <= 140):
                    continue
                expansion_metrics = _metrics(expansion)
                min_win = 52.0 if topn == 1 else 50.0
                if expansion_metrics["win_rate"] < min_win or expansion_metrics["avg_ret"] <= 0:
                    continue
                combo = pd.concat([strong, expansion], ignore_index=True, sort=False)
                combo = combo.sort_values(["select_date", "ts_code"]).drop_duplicates(["year", "select_date", "ts_code"])
                combo_metrics = _metrics(combo)
                score = (
                    expansion_metrics["win_rate"] * 1.4
                    + min(expansion_metrics["total_ret"], 160.0) * 0.22
                    + min(expansion_metrics["trades"], 120) * 0.18
                    + combo_metrics["win_rate"] * 0.9
                    + min(combo_metrics["total_ret"], 380.0) * 0.08
                    - expansion_metrics["loss_years"] * 5.0
                    - combo_metrics["loss_years"] * 7.0
                    - abs(min(combo_metrics["worst_year"], 0.0)) * 1.1
                )
                rows.append({
                    "rule": name,
                    "macro_mode": macro_mode,
                    "market_style": market_style,
                    "score_col": score_col,
                    "topn": topn,
                    **{f"expansion_{k}": v for k, v in expansion_metrics.items()},
                    **{f"combo_{k}": v for k, v in combo_metrics.items()},
                    "score": score,
                })
                if score > best_score:
                    best_score = score
                    best_trades = combo.copy()

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["score", "expansion_win_rate", "combo_total_ret"], ascending=False).reset_index(drop=True)
    yearly = pd.DataFrame()
    if not best_trades.empty:
        yearly = best_trades.groupby("year").agg(
            trades=("ret", "size"),
            win_rate=("win", "mean"),
            total_ret=("ret", "sum"),
        ).reset_index()
        yearly["win_rate"] = yearly["win_rate"] * 100
    return result, best_trades, yearly


def _write_doc(result: pd.DataFrame, yearly: pd.DataFrame, output: Path) -> None:
    lines = [
        "# T3 确认质量门搜索（2026-07-07）",
        "",
        "## 研究口径",
        "",
        "- 只研究 T3 延迟确认扩容层，且只使用 T3 开盘前已经知道的路径因子。",
        "- 优先要求扩容层自身质量：胜率至少 52%，平均收益为正。",
        "- 再与 strong_T1 合并看总笔数、胜率、收益、年度稳定性。",
        "- 这是研究候选，不改线上逻辑，不含任何下单执行。",
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
        "- 如果扩容层自身胜率过线但合并后年份仍亏，说明它只能做研究线索，不能上线。",
        "- 如果扩容层笔数太少，优先作为观察标签而非主策略。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    result, best_trades, yearly = search()
    result.to_csv(REPORTS / "t3_confirmation_quality_search_20260707.csv", index=False, encoding="utf-8-sig")
    best_trades.to_csv(REPORTS / "t3_confirmation_quality_best_trades_20260707.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(REPORTS / "t3_confirmation_quality_best_yearly_20260707.csv", index=False, encoding="utf-8-sig")
    _write_doc(result, yearly, DOCS / "T3_CONFIRMATION_QUALITY_SEARCH_20260707.md")
    print(result.head(40).to_string(index=False) if not result.empty else "no candidates")
    print()
    print(yearly.to_string(index=False) if not yearly.empty else "no yearly")


if __name__ == "__main__":
    main()
