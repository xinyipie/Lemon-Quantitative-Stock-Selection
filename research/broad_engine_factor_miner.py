from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from v45_engine_exit_backtest import _group_metrics, _metrics
from v45_engine_exit_optimizer import _strong_engine_trades


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
CANDIDATES = REPORTS / "engine_all_entry_bucket_candidate_exits_20260706.csv"
RULES_OUT = REPORTS / "broad_engine_factor_miner_rules_20260706.csv"
TRADES_OUT = REPORTS / "broad_engine_factor_miner_best_trades_20260706.csv"
DOC_OUT = DOCS / "BROAD_ENGINE_FACTOR_MINER_20260706.md"


def _load_candidates() -> pd.DataFrame:
    df = pd.read_csv(CANDIDATES, encoding="utf-8-sig")
    df["ret"] = pd.to_numeric(df["ret"], errors="coerce").fillna(0.0)
    df["win"] = df["ret"] > 0
    for col in df.columns:
        if col.startswith("factor_") or col in [
            "best_rank",
            "avg_rank",
            "n_versions",
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
        ]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _predicates(df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    preds: list[tuple[str, pd.Series]] = []
    for col in ["entry_bucket", "macro_mode", "market_style"]:
        if col in df.columns:
            for value in sorted(df[col].dropna().astype(str).unique()):
                preds.append((f"{col}={value}", df[col].astype(str).eq(value)))
    numeric_specs = {
        "best_rank": ("<=", [1.0, 2.0]),
        "avg_rank": ("<=", [1.5, 2.0]),
        "n_versions": (">=", [2.0, 3.0]),
        "factor_pattern": (">=", [40.0, 50.0, 60.0]),
        "factor_wyckoff": (">=", [55.0, 65.0, 75.0]),
        "factor_inflow": (">=", [50.0, 80.0, 100.0]),
        "factor_sector": (">=", [30.0, 50.0, 70.0]),
        "factor_volume_ratio": (">=", [45.0, 55.0, 65.0]),
        "sector_ma10_ratio": (">=", [50.0, 70.0, 90.0]),
        "limit_down_count": ("<=", [4.0, 8.0, 12.0]),
        "limit_up_count": (">=", [20.0, 50.0, 80.0]),
        "pre_T3_low_pct": (">", [-3.0, -2.0, -1.0, -0.5]),
        "pre_T5_low_pct": (">", [-3.0, -2.0, -1.0, -0.5]),
        "pre_T7_low_pct": (">", [-4.0, -3.0, -2.0, -1.0]),
        "pre_T3_close_min_pct": (">", [-2.0, -1.0, -0.5, 0.0]),
        "pre_T5_close_min_pct": (">", [-2.0, -1.0, -0.5, 0.0]),
        "pre_T7_close_min_pct": (">", [-3.0, -2.0, -1.0, 0.0]),
    }
    for col, (op, values) in numeric_specs.items():
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        for value in values:
            if op == ">=":
                mask = series >= value
            elif op == "<=":
                mask = series <= value
            else:
                mask = series > value
            preds.append((f"{col}{op}{value:g}", mask.fillna(False)))
    return preds


def _select(df: pd.DataFrame, mask: pd.Series, daily_topn: int, score_profile: str) -> pd.DataFrame:
    work = df[mask].copy()
    if work.empty:
        return work
    if score_profile == "hybrid":
        score = pd.to_numeric(work.get("hybrid_score", 0), errors="coerce").fillna(0)
    elif score_profile == "quality":
        score = pd.to_numeric(work.get("hybrid_score", 0), errors="coerce").fillna(0)
        for col, weight in [
            ("factor_pattern", 1.0),
            ("factor_wyckoff", 0.7),
            ("factor_sector", 0.5),
            ("factor_inflow", 0.25),
        ]:
            if col in work.columns:
                score = score + pd.to_numeric(work[col], errors="coerce").fillna(0) * weight
    else:
        score = pd.to_numeric(work.get("consensus_score", 0), errors="coerce").fillna(0)
    work["research_score"] = score
    work = work.sort_values(["select_date", "research_score", "ts_code"], ascending=[True, False, True])
    work = work.drop_duplicates(["buy_date", "ts_code"], keep="first")
    return work.groupby("select_date", group_keys=False).head(daily_topn).reset_index(drop=True)


def _required_entry_bucket(names: list[str]) -> str | None:
    if any("pre_T7_" in name for name in names):
        return "T7"
    if any("pre_T5_" in name for name in names):
        return "T5"
    if any("pre_T3_" in name for name in names):
        return "T3"
    return None


def mine_rules() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = _load_candidates()
    strong = _strong_engine_trades().copy()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    strong_pairs = set(zip(strong["buy_date"].astype(str), strong["ts_code"].astype(str)))
    df = df[~df.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in strong_pairs, axis=1)]

    predicates = _predicates(df)
    rows = []
    best = pd.DataFrame()
    best_score = -10**9
    predicate_map = {name: pred for name, pred in predicates}

    def evaluate_combo(combo: tuple[tuple[str, pd.Series], ...]) -> None:
        nonlocal best, best_score
        names = [name for name, _ in combo]
        mask = pd.Series(True, index=df.index)
        for _, pred in combo:
            mask &= pred
        required_bucket = _required_entry_bucket(names)
        explicit_buckets = [name.split("=", 1)[1] for name in names if name.startswith("entry_bucket=")]
        if required_bucket is not None:
            if explicit_buckets and required_bucket not in explicit_buckets:
                return
            mask &= df["entry_bucket"].astype(str).eq(required_bucket)
        if int(mask.sum()) < 30:
            return
        for daily_topn in [1, 2]:
            for score_profile in ["hybrid", "quality", "consensus"]:
                expansion = _select(df, mask, daily_topn, score_profile)
                if not (25 <= len(expansion) <= 180):
                    continue
                combined = pd.concat([strong, expansion], ignore_index=True, sort=False)
                combined = combined.drop_duplicates(["buy_date", "ts_code"], keep="first").copy()
                combined["ret"] = pd.to_numeric(combined["ret"], errors="coerce").fillna(0.0)
                combined["win"] = combined["ret"] > 0
                metrics = _metrics(combined)
                expansion_metrics = _metrics(expansion)
                target_pass = metrics["trades"] > 80 and metrics["win_rate"] >= 65.0
                score = (
                    metrics["win_rate"] * 2.0
                    + min(metrics["trades"], 150) * 0.35
                    + min(metrics["total_ret"], 360) * 0.12
                    - metrics["loss_years"] * 7.0
                    - abs(min(metrics["worst_year"], 0.0)) * 1.3
                )
                if target_pass:
                    score += 250
                if score > best_score:
                    best_score = score
                    best = combined.copy()
                rows.append(
                    {
                        "rule": " & ".join(names),
                        "condition_count": len(names),
                        "daily_topn": daily_topn,
                        "score_profile": score_profile,
                        "trades": metrics["trades"],
                        "win_rate": metrics["win_rate"],
                        "total_ret": metrics["total_ret"],
                        "avg_ret": metrics["avg_ret"],
                        "positive_years": metrics["positive_years"],
                        "loss_years": metrics["loss_years"],
                        "worst_year": metrics["worst_year"],
                        "target_pass": target_pass,
                        "expansion_trades": expansion_metrics["trades"],
                        "expansion_win_rate": expansion_metrics["win_rate"],
                        "expansion_total_ret": expansion_metrics["total_ret"],
                        "score": score,
                    }
                )

    for size in [1, 2]:
        for combo in combinations(predicates, size):
            evaluate_combo(combo)

    rough = pd.DataFrame(rows)
    if not rough.empty:
        useful_names: list[str] = []
        rough = rough.sort_values(["score", "win_rate", "trades"], ascending=[False, False, False])
        near = rough[(rough["trades"] >= 70) | (rough["win_rate"] >= 62)].head(80)
        for rule in near["rule"]:
            for name in str(rule).split(" & "):
                if name in predicate_map and name not in useful_names:
                    useful_names.append(name)
        useful_names = useful_names[:18]
        focused = [(name, predicate_map[name]) for name in useful_names]
        for combo in combinations(focused, 3):
            evaluate_combo(combo)
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            ["target_pass", "score", "win_rate", "trades", "total_ret"],
            ascending=[False, False, False, False, False],
        ).reset_index(drop=True)
    return result, best


def _write_doc(rules: pd.DataFrame, best: pd.DataFrame) -> None:
    lines = [
        "# 全候选真实退出因子挖掘（2026-07-06）",
        "",
        "## 口径",
        "",
        "- 保留 `strong_T1`，扩展层来自 `engine_all_entry_bucket_candidate_exits`。",
        "- 只搜索选股日或入场前已经知道的字段，不使用未来收益排序。",
        "- 每个选股日扩展层 Top1/Top2，目标为十年真实退出胜率 >= 65%、总笔数 > 80。",
        "",
        "## Top40",
        "",
        rules.head(40).to_markdown(index=False, floatfmt=".2f") if not rules.empty else "无候选规则",
        "",
        "## 当前最佳年度分布",
        "",
        _group_metrics(best, "year").sort_values("year").to_markdown(index=False, floatfmt=".2f") if not best.empty else "无",
        "",
    ]
    DOC_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rules, best = mine_rules()
    rules.to_csv(RULES_OUT, index=False, encoding="utf-8-sig")
    best.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    _write_doc(rules, best)
    print(rules.head(60).to_string(index=False) if not rules.empty else "no rules")
    print()
    print(_group_metrics(best, "year").sort_values("year").to_string(index=False) if not best.empty else "no best")


if __name__ == "__main__":
    main()
