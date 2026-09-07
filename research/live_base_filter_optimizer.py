from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from broad_engine_factor_miner import _load_candidates, _predicates, _select
from live_readiness_optimizer import _mask_for_names
from live_readiness_postmortem import _readiness, _recent_win_rate
from v45_engine_exit_backtest import _group_metrics, _metrics
from v45_engine_exit_optimizer import _strong_engine_trades


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
RESULT_OUT = REPORTS / "live_base_filter_optimizer_20260707.csv"
TRADES_OUT = REPORTS / "live_base_filter_best_trades_20260707.csv"
DOC_OUT = DOCS / "LIVE_BASE_FILTER_OPTIMIZER_20260707.md"


BASE_CORE = ["market_style=weak_momentum", "sector_ma10_ratio>=90", "factor_sector>=30"]
BASE_SCORE = "quality"
BASE_TOPN = 1


BASE_EXTRA_CANDIDATES = [
    "factor_pattern>=30",
    "factor_pattern>=40",
    "factor_pattern>=50",
    "factor_wyckoff>=55",
    "factor_wyckoff>=65",
    "factor_volume_ratio>=45",
    "factor_volume_ratio>=55",
    "limit_down_count<=12",
    "limit_down_count<=8",
    "pre_T5_low_pct>-3",
    "pre_T5_low_pct>-2",
    "pre_T5_close_min_pct>-2",
    "pre_T5_close_min_pct>-1",
]

ADDON_RULES = [
    ("market_style=sideways & sector_ma10_ratio>=90", 2, "quality"),
    ("market_style=bear & factor_sector>=70 & limit_up_count>=80", 1, "quality"),
    ("market_style=sideways & limit_up_count>=50 & pre_T5_low_pct>-1", 1, "quality"),
    ("market_style=bear & factor_sector>=50 & pre_T5_close_min_pct>0", 2, "quality"),
    ("market_style=sideways & factor_sector>=30 & pre_T5_low_pct>-1", 1, "quality"),
]


def _strong() -> pd.DataFrame:
    strong = _strong_engine_trades().copy()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    strong["candidate_layer"] = "strong_T1"
    return strong


def _select_rule(df: pd.DataFrame, predicate_map: dict[str, pd.Series], rule: str, topn: int, score: str) -> pd.DataFrame:
    names = [part.strip() for part in rule.split(" & ") if part.strip()]
    mask = _mask_for_names(df, names, predicate_map)
    return _select(df, mask, topn, score)


def search() -> tuple[pd.DataFrame, pd.DataFrame]:
    df_raw = _load_candidates()
    predicate_map = {name: pred for name, pred in _predicates(df_raw)}
    strong = _strong()
    strong_pairs = set(zip(strong["buy_date"].astype(str), strong["ts_code"].astype(str)))
    df = df_raw[~df_raw.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in strong_pairs, axis=1)]

    base_variants = [BASE_CORE]
    for size in [1, 2]:
        for extra in combinations(BASE_EXTRA_CANDIDATES, size):
            base_variants.append(BASE_CORE + list(extra))

    rows = []
    best = pd.DataFrame()
    best_score = -10**9

    for base_names in base_variants:
        base_rule = " & ".join(base_names)
        base = _select_rule(df, predicate_map, base_rule, BASE_TOPN, BASE_SCORE)
        if base.empty:
            continue
        base["candidate_layer"] = "base_expansion"
        base_pairs = set(zip(base["buy_date"].astype(str), base["ts_code"].astype(str))) | strong_pairs
        for addon_rule, addon_topn, addon_score in ADDON_RULES:
            addon = _select_rule(df, predicate_map, addon_rule, addon_topn, addon_score)
            addon = addon[
                ~addon.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in base_pairs, axis=1)
            ].copy()
            addon["candidate_layer"] = "readiness_addon"
            trades = pd.concat([strong, base, addon], ignore_index=True, sort=False).drop_duplicates(["buy_date", "ts_code"], keep="first")
            trades["ret"] = pd.to_numeric(trades["ret"], errors="coerce").fillna(0.0)
            trades["win"] = trades["ret"] > 0
            metrics = _metrics(trades)
            status, blockers = _readiness(metrics, trades)
            yearly = _group_metrics(trades, "year")
            y2020 = yearly[yearly["year"].astype(str).eq("2020")]
            y2024 = yearly[yearly["year"].astype(str).eq("2024")]
            y2020_ret = float(y2020["total_ret"].iloc[0]) if not y2020.empty else 0.0
            y2024_wr = float(y2024["win_rate"].iloc[0]) if not y2024.empty else 0.0
            score = (
                (1000 if status == "ready" else 0)
                + metrics["win_rate"] * 3.0
                + min(metrics["total_ret"], 420) * 0.15
                + min(metrics["trades"], 110) * 0.6
                - metrics["loss_years"] * 25
                - abs(min(metrics["worst_year"], 0.0)) * 4
                + max(y2020_ret, -10) * 5
                + y2024_wr * 0.2
            )
            if score > best_score:
                best_score = score
                best = trades.copy()
            rows.append(
                {
                    "status": status,
                    "blockers": ";".join(blockers),
                    "base_rule": base_rule,
                    "base_trades": len(base),
                    "addon_rule": addon_rule,
                    "addon_trades": len(addon),
                    "trades": metrics["trades"],
                    "win_rate": metrics["win_rate"],
                    "total_ret": metrics["total_ret"],
                    "avg_ret": metrics["avg_ret"],
                    "positive_years": metrics["positive_years"],
                    "loss_years": metrics["loss_years"],
                    "worst_year": metrics["worst_year"],
                    "recent_win_rate": _recent_win_rate(trades),
                    "y2020_ret": y2020_ret,
                    "y2024_win_rate": y2024_wr,
                    "score": score,
                }
            )

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
        "# Base过滤优化搜索（2026-07-07）",
        "",
        "## 目标",
        "",
        "- 在可上线候选基础上，尝试修复 2020/2024 弱年度。",
        "- 方法：给 base_expansion 加质量过滤，再用少量 addon 补足交易数。",
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
