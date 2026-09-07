from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from broad_engine_factor_miner import _load_candidates, _predicates, _required_entry_bucket, _select
from live_readiness_postmortem import LIVE_CRITERIA, _readiness, _recent_win_rate
from v45_engine_exit_backtest import _group_metrics, _metrics
from v45_engine_exit_optimizer import _strong_engine_trades


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
RESULT_OUT = REPORTS / "live_readiness_optimizer_20260707.csv"
TRADES_OUT = REPORTS / "live_ready_candidate_trades_20260707.csv"
DOC_OUT = DOCS / "LIVE_READY_CANDIDATE_OPTIMIZATION_20260707.md"


BASE_RULE = "market_style=weak_momentum & sector_ma10_ratio>=90 & factor_sector>=30"
BASE_TOPN = 1
BASE_SCORE = "quality"


def _mask_for_names(df: pd.DataFrame, names: list[str], predicate_map: dict[str, pd.Series]) -> pd.Series:
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


def _build_base(df: pd.DataFrame, predicate_map: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    strong = _strong_engine_trades().copy()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    strong_pairs = set(zip(strong["buy_date"].astype(str), strong["ts_code"].astype(str)))
    df = df[~df.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in strong_pairs, axis=1)]
    base_mask = _mask_for_names(df, BASE_RULE.split(" & "), predicate_map)
    base_expansion = _select(df, base_mask, BASE_TOPN, BASE_SCORE)
    base_expansion["candidate_layer"] = "base_expansion"
    strong["candidate_layer"] = "strong_T1"
    base = pd.concat([strong, base_expansion], ignore_index=True, sort=False).drop_duplicates(["buy_date", "ts_code"], keep="first")
    base["ret"] = pd.to_numeric(base["ret"], errors="coerce").fillna(0.0)
    base["win"] = base["ret"] > 0
    return df, strong, base


def _candidate_predicates(df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    all_preds = _predicates(df)
    keep = []
    preferred_prefixes = (
        "entry_bucket=",
        "market_style=",
        "macro_mode=",
        "factor_sector",
        "factor_pattern",
        "factor_volume_ratio",
        "factor_wyckoff",
        "sector_ma10_ratio",
        "limit_up_count",
        "limit_down_count",
        "pre_T5_low_pct",
        "pre_T5_close_min_pct",
        "pre_T7_low_pct",
        "pre_T7_close_min_pct",
    )
    for name, pred in all_preds:
        if any(name.startswith(prefix) for prefix in preferred_prefixes):
            keep.append((name, pred))
    return keep


def search_optimizer() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_raw = _load_candidates()
    predicate_map = {name: pred for name, pred in _predicates(df_raw)}
    df, _strong, base = _build_base(df_raw, predicate_map)
    base_pairs = set(zip(base["buy_date"].astype(str), base["ts_code"].astype(str)))
    predicates = _candidate_predicates(df)

    rows = []
    best_trades = pd.DataFrame()
    best_score = -10**9

    combos = []
    for size in [1, 2]:
        combos.extend(combinations(predicates, size))

    # 只把三条件用于较少、可解释的路径型组合。
    focused_names = [
        name
        for name, _ in predicates
        if name.startswith(("market_style=", "factor_sector", "sector_ma10_ratio", "limit_up_count", "pre_T5_low_pct", "pre_T5_close_min_pct"))
    ][:22]
    focused_map = dict(predicates)
    combos.extend(combinations([(name, focused_map[name]) for name in focused_names if name in focused_map], 3))

    for combo in combos:
        names = [name for name, _ in combo]
        if set(names).issubset(set(BASE_RULE.split(" & "))):
            continue
        mask = _mask_for_names(df, names, predicate_map)
        if int(mask.sum()) < 20:
            continue
        for topn in [1, 2]:
            for score_profile in ["quality", "hybrid", "consensus"]:
                add = _select(df, mask, topn, score_profile)
                if add.empty:
                    continue
                add = add[
                    ~add.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in base_pairs, axis=1)
                ].copy()
                if not (4 <= len(add) <= 60):
                    continue
                add["candidate_layer"] = "readiness_addon"
                combined = pd.concat([base, add], ignore_index=True, sort=False).drop_duplicates(["buy_date", "ts_code"], keep="first")
                combined["ret"] = pd.to_numeric(combined["ret"], errors="coerce").fillna(0.0)
                combined["win"] = combined["ret"] > 0
                metrics = _metrics(combined)
                status, blockers = _readiness(metrics, combined)
                add_metrics = _metrics(add)
                score = (
                    (1000 if status == "ready" else 0)
                    + metrics["win_rate"] * 2.5
                    + min(metrics["trades"], 120) * 0.5
                    + min(metrics["total_ret"], 400) * 0.12
                    - metrics["loss_years"] * 20
                    - abs(min(metrics["worst_year"], 0.0)) * 3
                    - max(0, 80 - metrics["trades"]) * 12
                )
                if score > best_score:
                    best_score = score
                    best_trades = combined.copy()
                rows.append(
                    {
                        "status": status,
                        "blockers": ";".join(blockers),
                        "addon_rule": " & ".join(names),
                        "addon_topn": topn,
                        "addon_score": score_profile,
                        "trades": metrics["trades"],
                        "win_rate": metrics["win_rate"],
                        "total_ret": metrics["total_ret"],
                        "avg_ret": metrics["avg_ret"],
                        "positive_years": metrics["positive_years"],
                        "loss_years": metrics["loss_years"],
                        "worst_year": metrics["worst_year"],
                        "active_years": int(combined["year"].nunique()),
                        "recent_win_rate": _recent_win_rate(combined),
                        "addon_trades": add_metrics["trades"],
                        "addon_win_rate": add_metrics["win_rate"],
                        "addon_total_ret": add_metrics["total_ret"],
                        "score": score,
                    }
                )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            ["status", "score", "win_rate", "trades", "loss_years"],
            ascending=[True, False, False, False, True],
        ).reset_index(drop=True)
    return result, best_trades


def _write_doc(result: pd.DataFrame, best: pd.DataFrame) -> None:
    yearly = _group_metrics(best, "year").sort_values("year") if not best.empty else pd.DataFrame()
    layers = _group_metrics(best, "candidate_layer") if not best.empty else pd.DataFrame()
    lines = [
        "# 可上线候选优化搜索（2026-07-07）",
        "",
        "## 底座",
        "",
        f"- `strong_T1` + `{BASE_RULE}`，Top{BASE_TOPN}，`{BASE_SCORE}` 排序。",
        "- 底座候选 C 的主要缺口是交易数 76，距离上线标准差 4 笔。",
        "",
        "## 搜索结果 Top30",
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
    result, best = search_optimizer()
    result.to_csv(RESULT_OUT, index=False, encoding="utf-8-sig")
    best.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    _write_doc(result, best)
    print(result.head(40).to_string(index=False) if not result.empty else "no result")
    print()
    print(_group_metrics(best, "year").sort_values("year").to_string(index=False) if not best.empty else "no best")


if __name__ == "__main__":
    main()
