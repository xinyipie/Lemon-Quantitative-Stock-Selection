from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from broad_engine_factor_miner import _load_candidates, _predicates, _required_entry_bucket, _select
from v45_engine_exit_backtest import _group_metrics, _metrics
from v45_engine_exit_optimizer import _strong_engine_trades


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
RULES_IN = REPORTS / "broad_engine_factor_miner_rules_20260706.csv"
RULES_OUT = REPORTS / "broad_engine_rule_union_search_20260706.csv"
TRADES_OUT = REPORTS / "broad_engine_rule_union_best_trades_20260706.csv"
DOC_OUT = DOCS / "BROAD_ENGINE_RULE_UNION_SEARCH_20260706.md"


def _mask_for_rule(df: pd.DataFrame, rule: str, predicate_map: dict[str, pd.Series]) -> pd.Series:
    names = [part.strip() for part in str(rule).split(" & ") if part.strip()]
    mask = pd.Series(True, index=df.index)
    for name in names:
        pred = predicate_map.get(name)
        if pred is None:
            return pd.Series(False, index=df.index)
        mask &= pred
    required_bucket = _required_entry_bucket(names)
    explicit_buckets = [name.split("=", 1)[1] for name in names if name.startswith("entry_bucket=")]
    if required_bucket is not None:
        if explicit_buckets and required_bucket not in explicit_buckets:
            return pd.Series(False, index=df.index)
        mask &= df["entry_bucket"].astype(str).eq(required_bucket)
    return mask


def search_unions() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = _load_candidates()
    strong = _strong_engine_trades().copy()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    strong_pairs = set(zip(strong["buy_date"].astype(str), strong["ts_code"].astype(str)))
    df = df[~df.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in strong_pairs, axis=1)]
    predicate_map = {name: pred for name, pred in _predicates(df)}

    rules = pd.read_csv(RULES_IN, encoding="utf-8-sig")
    candidates = rules[
        (rules["trades"] >= 45)
        & (rules["win_rate"] >= 58)
        & (rules["expansion_trades"] >= 20)
    ].head(80).copy()

    selected = {}
    for idx, row in candidates.iterrows():
        mask = _mask_for_rule(df, row["rule"], predicate_map)
        sel = _select(df, mask, int(row["daily_topn"]), str(row["score_profile"]))
        if 20 <= len(sel) <= 180:
            selected[idx] = sel

    rows = []
    best = pd.DataFrame()
    best_score = -10**9
    for left, right in combinations(list(selected), 2):
        expansion = pd.concat([selected[left], selected[right]], ignore_index=True, sort=False)
        expansion = expansion.drop_duplicates(["buy_date", "ts_code"], keep="first").copy()
        if not (50 <= len(expansion) <= 180):
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
            + min(metrics["trades"], 150) * 0.4
            + min(metrics["total_ret"], 400) * 0.12
            - metrics["loss_years"] * 8.0
            - abs(min(metrics["worst_year"], 0.0)) * 1.2
        )
        if target_pass:
            score += 300
        if score > best_score:
            best_score = score
            best = combined.copy()
        rows.append(
            {
                "rule_a": candidates.loc[left, "rule"],
                "topn_a": int(candidates.loc[left, "daily_topn"]),
                "score_a": candidates.loc[left, "score_profile"],
                "rule_b": candidates.loc[right, "rule"],
                "topn_b": int(candidates.loc[right, "daily_topn"]),
                "score_b": candidates.loc[right, "score_profile"],
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
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            ["target_pass", "score", "win_rate", "trades", "total_ret"],
            ascending=[False, False, False, False, False],
        ).reset_index(drop=True)
    return result, best


def _write_doc(result: pd.DataFrame, best: pd.DataFrame) -> None:
    lines = [
        "# 全候选规则并集搜索（2026-07-06）",
        "",
        "## 口径",
        "",
        "- 保留 `strong_T1`。",
        "- 从合法单/双/三条件规则 Top80 中搜索两个扩展规则的并集。",
        "- 每个子规则仍按自己的 Top1/Top2 与评分口径选股，不使用未来收益排序。",
        "",
        "## Top40",
        "",
        result.head(40).to_markdown(index=False, floatfmt=".2f") if not result.empty else "无候选规则",
        "",
        "## 当前最佳年度分布",
        "",
        _group_metrics(best, "year").sort_values("year").to_markdown(index=False, floatfmt=".2f") if not best.empty else "无",
        "",
    ]
    DOC_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    result, best = search_unions()
    result.to_csv(RULES_OUT, index=False, encoding="utf-8-sig")
    best.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    _write_doc(result, best)
    print(result.head(50).to_string(index=False) if not result.empty else "no unions")
    print()
    print(_group_metrics(best, "year").sort_values("year").to_string(index=False) if not best.empty else "no best")


if __name__ == "__main__":
    main()
