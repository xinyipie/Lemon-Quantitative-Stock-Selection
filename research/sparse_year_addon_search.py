from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from broad_engine_factor_miner import _load_candidates, _predicates, _select
from live_base_filter_optimizer import _strong, _select_rule
from live_readiness_optimizer import _mask_for_names
from live_readiness_postmortem import _readiness, _recent_win_rate
from v45_engine_exit_backtest import _group_metrics, _metrics


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
RESULT_OUT = REPORTS / "sparse_year_addon_search_20260707.csv"
TRADES_OUT = REPORTS / "sparse_year_addon_best_trades_20260707.csv"
DOC_OUT = DOCS / "SPARSE_YEAR_ADDON_SEARCH_20260707.md"


BASE_RULE = "market_style=weak_momentum & sector_ma10_ratio>=90 & factor_sector>=30 & factor_pattern>=50"
BASE_ADDON = "market_style=bear & factor_sector>=50 & pre_T5_close_min_pct>0"
SPARSE_YEARS = {"2018", "2019", "2021", "2022", "2023", "2026H1"}


def _baseline(df: pd.DataFrame, predicate_map: dict[str, pd.Series]) -> pd.DataFrame:
    strong = _strong()
    strong_pairs = set(zip(strong["buy_date"].astype(str), strong["ts_code"].astype(str)))
    work = df[~df.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in strong_pairs, axis=1)]
    base = _select_rule(work, predicate_map, BASE_RULE, 1, "quality")
    base["candidate_layer"] = "base_expansion"
    pairs = strong_pairs | set(zip(base["buy_date"].astype(str), base["ts_code"].astype(str)))
    addon = _select_rule(work, predicate_map, BASE_ADDON, 2, "quality")
    addon = addon[~addon.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in pairs, axis=1)].copy()
    addon["candidate_layer"] = "readiness_addon"
    trades = pd.concat([strong, base, addon], ignore_index=True, sort=False).drop_duplicates(["buy_date", "ts_code"], keep="first")
    trades["ret"] = pd.to_numeric(trades["ret"], errors="coerce").fillna(0.0)
    trades["win"] = trades["ret"] > 0
    return trades


def _candidate_predicates(df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    all_preds = _predicates(df)
    prefixes = (
        "entry_bucket=",
        "market_style=",
        "macro_mode=",
        "factor_sector",
        "factor_pattern",
        "factor_wyckoff",
        "factor_volume_ratio",
        "sector_ma10_ratio",
        "limit_up_count",
        "limit_down_count",
        "pre_T5_low_pct",
        "pre_T5_close_min_pct",
        "pre_T7_low_pct",
        "pre_T7_close_min_pct",
        "best_rank",
        "avg_rank",
    )
    return [(name, pred) for name, pred in all_preds if any(name.startswith(prefix) for prefix in prefixes)]


def search() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_raw = _load_candidates()
    predicate_map = {name: pred for name, pred in _predicates(df_raw)}
    baseline = _baseline(df_raw, predicate_map)
    used_pairs = set(zip(baseline["buy_date"].astype(str), baseline["ts_code"].astype(str)))
    df = df_raw[
        ~df_raw.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in used_pairs, axis=1)
    ].copy()
    df = df[df["year"].astype(str).isin(SPARSE_YEARS)].copy()

    predicates = _candidate_predicates(df)
    combos = []
    for size in [1, 2]:
        combos.extend(combinations(predicates, size))

    rows = []
    best = pd.DataFrame()
    best_score = -10**9
    def evaluate(combo) -> None:
        nonlocal best, best_score
        names = [name for name, _ in combo]
        mask = _mask_for_names(df, names, predicate_map)
        if int(mask.sum()) < 5:
            return
        for topn in [1, 2]:
            for score_profile in ["quality", "hybrid", "consensus"]:
                add = _select(df, mask, topn, score_profile)
                if not (3 <= len(add) <= 35):
                    continue
                add = add.copy()
                add["candidate_layer"] = "sparse_year_addon"
                combined = pd.concat([baseline, add], ignore_index=True, sort=False).drop_duplicates(
                    ["buy_date", "ts_code"], keep="first"
                )
                combined["ret"] = pd.to_numeric(combined["ret"], errors="coerce").fillna(0.0)
                combined["win"] = combined["ret"] > 0
                metrics = _metrics(combined)
                status, blockers = _readiness(metrics, combined)
                yearly = _group_metrics(combined, "year")
                sparse_year_counts = yearly[yearly["year"].astype(str).isin(SPARSE_YEARS)]["trades"].sum()
                add_metrics = _metrics(add)
                score = (
                    (1000 if status == "ready" else 0)
                    + metrics["win_rate"] * 3
                    + min(metrics["trades"], 110) * 0.8
                    + min(metrics["total_ret"], 430) * 0.12
                    - metrics["loss_years"] * 25
                    - abs(min(metrics["worst_year"], 0.0)) * 3
                    + sparse_year_counts * 1.2
                    + add_metrics["win_rate"] * 0.4
                )
                if score > best_score:
                    best_score = score
                    best = combined.copy()
                rows.append(
                    {
                        "status": status,
                        "blockers": ";".join(blockers),
                        "addon_rule": " & ".join(names),
                        "addon_topn": topn,
                        "addon_score": score_profile,
                        "addon_trades": add_metrics["trades"],
                        "addon_win_rate": add_metrics["win_rate"],
                        "addon_total_ret": add_metrics["total_ret"],
                        "trades": metrics["trades"],
                        "win_rate": metrics["win_rate"],
                        "total_ret": metrics["total_ret"],
                        "avg_ret": metrics["avg_ret"],
                        "positive_years": metrics["positive_years"],
                        "loss_years": metrics["loss_years"],
                        "worst_year": metrics["worst_year"],
                        "recent_win_rate": _recent_win_rate(combined),
                        "sparse_year_trades": int(sparse_year_counts),
                        "score": score,
                    }
                )

    for combo in combos:
        evaluate(combo)

    rough = pd.DataFrame(rows)
    if not rough.empty:
        useful = []
        rough = rough.sort_values(["score", "addon_win_rate", "addon_trades"], ascending=[False, False, False])
        for rule in rough.head(80)["addon_rule"]:
            for name in str(rule).split(" & "):
                if name and name not in useful:
                    useful.append(name)
        useful = useful[:20]
        pred_map = dict(predicates)
        focused = [(name, pred_map[name]) for name in useful if name in pred_map]
        for combo in combinations(focused, 3):
            evaluate(combo)
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            ["status", "score", "win_rate", "trades", "total_ret"],
            ascending=[True, False, False, False, False],
        ).reset_index(drop=True)
    return result, best


def _write_doc(result: pd.DataFrame, best: pd.DataFrame) -> None:
    yearly = _group_metrics(best, "year").sort_values("year") if not best.empty else pd.DataFrame()
    layers = _group_metrics(best, "candidate_layer") if not best.empty else pd.DataFrame()
    lines = [
        "# 稀少年份补强搜索（2026-07-07）",
        "",
        "## 目标",
        "",
        "- 只在 2018/2019/2021/2022/2023/2026H1 寻找额外补强票。",
        "- 不使用未来收益排序，路径条件仍按 T3/T5/T7 合法入场。",
        "",
        "## Top30",
        "",
        result.head(30).to_markdown(index=False, floatfmt=".2f") if not result.empty else "无",
        "",
        "## 当前最佳分层",
        "",
        layers.to_markdown(index=False, floatfmt=".2f") if not layers.empty else "无",
        "",
        "## 当前最佳年度",
        "",
        yearly.to_markdown(index=False, floatfmt=".2f") if not yearly.empty else "无",
        "",
    ]
    DOC_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    result, best = search()
    result.to_csv(RESULT_OUT, index=False, encoding="utf-8-sig")
    best.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    _write_doc(result, best)
    print(result.head(40).to_string(index=False) if not result.empty else "no result")
    print()
    print(_group_metrics(best, "year").sort_values("year").to_string(index=False) if not best.empty else "no best")


if __name__ == "__main__":
    main()
