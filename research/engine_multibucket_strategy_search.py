from __future__ import annotations

from itertools import combinations, product
from pathlib import Path
import sys

import pandas as pd

from research.research_integrity import lock_observable_topn


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from backtest_v2 import BacktestV2
from entry_timing_bucket_research import build_entry_outcomes, load_daily_subset, load_stage3_samples
from local_data_proxy import LocalDataProxy
from v45_engine_exit_backtest import _group_metrics, _metrics, _to_float
from v45_engine_exit_optimizer import _strong_engine_trades


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
ALL_EXITS = REPORTS / "engine_all_entry_bucket_candidate_exits_20260706.csv"


def _year_bucket(date: str) -> str:
    date = str(date)
    if date.startswith("2026"):
        return "2026H1"
    return date[:4]


def _load_all_entry_candidates() -> pd.DataFrame:
    samples = load_stage3_samples()
    daily = load_daily_subset(samples[["sample", "select_date", "buy_date", "ts_code"]])
    outcomes, _ = build_entry_outcomes(samples, daily)
    outcomes["entry_date"] = outcomes["entry_date"].astype(str)
    outcomes["ts_code"] = outcomes["ts_code"].astype(str)
    return outcomes.reset_index(drop=True)


def build_all_engine_exits(force: bool = False) -> pd.DataFrame:
    if ALL_EXITS.exists() and not force:
        return pd.read_csv(ALL_EXITS, encoding="utf-8-sig")

    candidates = _load_all_entry_candidates()
    pro = LocalDataProxy(cache_dir=str(ROOT / "data" / "cache"))
    engine = BacktestV2(
        pro=pro,
        start_date=str(candidates["entry_date"].min()),
        end_date=str(candidates["entry_date"].max()),
        hold_days=5,
        top_n=1,
        use_market_timing=False,
        min_open_ratio=0.0,
    )
    price_cache = {}
    for date in engine.all_trade_dates:
        df = pro.daily(trade_date=date)
        if df is not None and not df.empty:
            price_cache[date] = df

    rows = []
    copy_cols = [
        "sample",
        "select_date",
        "ts_code",
        "name",
        "industry",
        "entry_bucket",
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
        "market_style",
        "macro_mode",
        "regime",
        "operation_mode",
        "hybrid_score",
        "consensus_score",
        "pre_T3_low_pct",
        "pre_T3_close_min_pct",
        "pre_T5_low_pct",
        "pre_T5_close_min_pct",
        "pre_T7_low_pct",
        "pre_T7_close_min_pct",
    ]
    for _, event in candidates.iterrows():
        buy_date = str(event["entry_date"])
        future_dates = [date for date in engine.all_trade_dates if date >= buy_date]
        result = engine._simulate_trade(
            ts_code=str(event["ts_code"]),
            buy_date=buy_date,
            future_dates=future_dates,
            price_cache=price_cache,
            tech_stop_price=0.0,
            tech_target_price=0.0,
            volatility=3.0,
            tech_low20=0.0,
            select_close=0.0,
            regime_max_hold=5,
            track_type=f"candidate_{event.get('entry_bucket', '')}",
            signal_row=event,
        )
        if result is None:
            continue
        for column in copy_cols:
            if column in event:
                result[column] = event.get(column)
        result["entry_date"] = buy_date
        result["entry_rule"] = f"candidate_{event.get('entry_bucket', '')}"
        result["ret"] = _to_float(pd.Series(result), "profit_after_fee", _to_float(pd.Series(result), "profit_pct", 0.0))
        result["win"] = result["ret"] > 0
        result["year"] = _year_bucket(str(result.get("buy_date", buy_date)))
        rows.append(result)

    out = pd.DataFrame(rows)
    out.to_csv(ALL_EXITS, index=False, encoding="utf-8-sig")
    return out


def _pre_cols(bucket: str) -> tuple[str | None, str | None]:
    if bucket == "T3":
        return "pre_T3_low_pct", "pre_T3_close_min_pct"
    if bucket == "T5":
        return "pre_T5_low_pct", "pre_T5_close_min_pct"
    if bucket == "T7":
        return "pre_T7_low_pct", "pre_T7_close_min_pct"
    return None, None


def _rule_name(rule: dict) -> str:
    parts = [rule["bucket"], f"br<={rule['best_rank']}", f"ar<={rule['avg_rank']}", f"pat>={rule['pattern']}", f"ld<={rule['limit_down']}"]
    if rule.get("pre_low") is not None:
        parts.append(f"low>{rule['pre_low']}")
    if rule.get("pre_close") is not None:
        parts.append(f"close>{rule['pre_close']}")
    if rule.get("market_style") is not None:
        parts.append(f"style={rule['market_style']}")
    if rule.get("macro_mode") is not None:
        parts.append(f"macro={rule['macro_mode']}")
    return "|".join(str(x) for x in parts)


def _select_rule(candidates: pd.DataFrame, rule: dict) -> pd.DataFrame:
    work = candidates[candidates["entry_bucket"].astype(str).eq(rule["bucket"])].copy()
    for col in [
        "best_rank",
        "avg_rank",
        "factor_pattern",
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
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work[
        (work["best_rank"] <= rule["best_rank"])
        & (work["avg_rank"] <= rule["avg_rank"])
        & (work["factor_pattern"] >= rule["pattern"])
        & (work["limit_down_count"] <= rule["limit_down"])
    ].copy()
    low_col, close_col = _pre_cols(rule["bucket"])
    if rule.get("pre_low") is not None and low_col is not None:
        work = work[work[low_col] > rule["pre_low"]]
    if rule.get("pre_close") is not None and close_col is not None:
        work = work[work[close_col] > rule["pre_close"]]
    if rule.get("market_style") is not None:
        work = work[work["market_style"].astype(str).eq(rule["market_style"])]
    if rule.get("macro_mode") is not None:
        work = work[work["macro_mode"].astype(str).eq(rule["macro_mode"])]
    if work.empty:
        return work
    score_col = "hybrid_score" if "hybrid_score" in work.columns else "consensus_score"
    work["candidate_rule"] = _rule_name(rule)
    return work.sort_values(["select_date", score_col, "ts_code"], ascending=[True, False, True])


def generate_single_rules() -> list[dict]:
    rules = []
    for bucket in ["T1", "T3", "T5", "T7"]:
        pre_lows = [None] if bucket == "T1" else [-0.5, -1.0, -1.5, -2.0]
        pre_closes = [None] if bucket == "T1" else [-0.5, -1.0, -1.5, -2.0]
        for best_rank, avg_rank, pattern, limit_down, pre_low, pre_close, market_style, macro_mode in product(
            [1.0, 1.5, 2.0],
            [1.5, 2.0, 2.5],
            [50.0, 55.0, 60.0],
            [4.0, 8.0, 12.0],
            pre_lows,
            pre_closes,
            [None, "momentum", "sideways", "weak_momentum"],
            [None, "active", "cautious"],
        ):
            rules.append(
                {
                    "bucket": bucket,
                    "best_rank": best_rank,
                    "avg_rank": avg_rank,
                    "pattern": pattern,
                    "limit_down": limit_down,
                    "pre_low": pre_low,
                    "pre_close": pre_close,
                    "market_style": market_style,
                    "macro_mode": macro_mode,
                }
            )
    return rules


def score_single_rules(candidates: pd.DataFrame, strong_dates: set[str]) -> pd.DataFrame:
    rows = []
    for rule in generate_single_rules():
        selected = _select_rule(candidates, rule)
        selected = selected[~selected["select_date"].astype(str).isin(strong_dates)]
        if not (8 <= len(selected) <= 90):
            continue
        selected = selected.groupby("select_date", group_keys=False).head(1)
        metrics = _metrics(selected)
        if metrics["trades"] < 8:
            continue
        rows.append(
            {
                "rule_name": _rule_name(rule),
                **rule,
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "total_ret": metrics["total_ret"],
                "avg_ret": metrics["avg_ret"],
                "positive_years": metrics["positive_years"],
                "loss_years": metrics["loss_years"],
                "worst_year": metrics["worst_year"],
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["win_rate", "total_ret", "trades"], ascending=[False, False, False]).reset_index(drop=True)


def _materialize_rule(candidates: pd.DataFrame, row: pd.Series, strong_dates: set[str]) -> pd.DataFrame:
    rule = {
        "bucket": row["bucket"],
        "best_rank": row["best_rank"],
        "avg_rank": row["avg_rank"],
        "pattern": row["pattern"],
        "limit_down": row["limit_down"],
        "pre_low": None if pd.isna(row.get("pre_low")) else row.get("pre_low"),
        "pre_close": None if pd.isna(row.get("pre_close")) else row.get("pre_close"),
        "market_style": None if pd.isna(row.get("market_style")) else row.get("market_style"),
        "macro_mode": None if pd.isna(row.get("macro_mode")) else row.get("macro_mode"),
    }
    selected = _select_rule(candidates, rule)
    selected = selected[~selected["select_date"].astype(str).isin(strong_dates)]
    return selected.groupby("select_date", group_keys=False).head(1).copy()


def search_combinations(candidates: pd.DataFrame, strong: pd.DataFrame, top_single: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    strong_dates = set(strong["select_date"].astype(str))
    materialized = []
    for _, row in top_single.head(160).iterrows():
        selected = _materialize_rule(candidates, row, strong_dates)
        if selected.empty:
            continue
        materialized.append((row["rule_name"], selected))

    rows = []
    best_events = pd.DataFrame()
    for size in [1, 2, 3]:
        for combo in combinations(range(len(materialized)), size):
            frames = []
            names = []
            for idx in combo:
                names.append(materialized[idx][0])
                frames.append(materialized[idx][1])
            expansion = pd.concat(frames, ignore_index=True, sort=False)
            if expansion.empty:
                continue
            score_col = "hybrid_score" if "hybrid_score" in expansion.columns else "consensus_score"
            expansion = lock_observable_topn(expansion, "select_date", score_col, topn=1)
            combined = pd.concat([strong, expansion], ignore_index=True, sort=False)
            combined["ret"] = pd.to_numeric(combined["ret"], errors="coerce").fillna(0.0)
            combined["win"] = combined["ret"] > 0
            metrics = _metrics(combined)
            expansion_metrics = _metrics(expansion)
            if metrics["trades"] <= 80 and not (metrics["win_rate"] >= 65 and metrics["trades"] > 75):
                continue
            row = {
                "combo_size": size,
                "rules": " || ".join(names),
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "total_ret": metrics["total_ret"],
                "avg_ret": metrics["avg_ret"],
                "positive_years": metrics["positive_years"],
                "loss_years": metrics["loss_years"],
                "worst_year": metrics["worst_year"],
                "expansion_trades": expansion_metrics["trades"],
                "expansion_win_rate": expansion_metrics["win_rate"],
                "expansion_total_ret": expansion_metrics["total_ret"],
            }
            rows.append(row)
            if metrics["trades"] > 80 and metrics["win_rate"] >= 65:
                best_events = combined.copy()
                # Do not stop immediately; keep searching for better score in this run.
    result = pd.DataFrame(rows)
    if result.empty:
        return result, best_events
    result = result.sort_values(["win_rate", "trades", "total_ret"], ascending=[False, False, False]).reset_index(drop=True)
    if not best_events.empty:
        best_rule = result[(result["trades"] > 80) & (result["win_rate"] >= 65)].iloc[0]
        # Re-materialize the best by matching combo rules.
        rule_names = str(best_rule["rules"]).split(" || ")
        frames = [selected for name, selected in materialized if name in rule_names]
        expansion = pd.concat(frames, ignore_index=True, sort=False)
        score_col = "hybrid_score" if "hybrid_score" in expansion.columns else "consensus_score"
        expansion = lock_observable_topn(expansion, "select_date", score_col, topn=1)
        best_events = pd.concat([strong, expansion], ignore_index=True, sort=False)
    return result, best_events


def _write_doc(single: pd.DataFrame, combos: pd.DataFrame, output: Path) -> None:
    lines = [
        "# 多入场桶真实退出策略搜索（2026-07-06）",
        "",
        "## 口径",
        "",
        "- 保留 `strong_T1`。",
        "- T1/T3/T5/T7 候选全部用 `BacktestV2._simulate_trade` 真实退出规则重算。",
        "- 搜索只使用选股日已知因子和对应入场前已发生路径。",
        "- 强信号日期不补扩容票；其他日期每天最多补 1 只。",
        "",
        "## 单规则 Top30",
        "",
        single.head(30).to_markdown(index=False, floatfmt=".2f") if not single.empty else "无",
        "",
        "## 组合 Top30",
        "",
        combos.head(30).to_markdown(index=False, floatfmt=".2f") if not combos.empty else "无",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    candidates = build_all_engine_exits()
    strong = _strong_engine_trades()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    strong_dates = set(strong["select_date"].astype(str))
    single = score_single_rules(candidates, strong_dates)
    combos, best_events = search_combinations(candidates, strong, single)

    single.to_csv(REPORTS / "engine_multibucket_single_rules_20260706.csv", index=False, encoding="utf-8-sig")
    combos.to_csv(REPORTS / "engine_multibucket_combo_rules_20260706.csv", index=False, encoding="utf-8-sig")
    if not best_events.empty:
        best_events.to_csv(REPORTS / "engine_multibucket_best_events_20260706.csv", index=False, encoding="utf-8-sig")
        _group_metrics(best_events, "year").to_csv(REPORTS / "engine_multibucket_best_yearly_20260706.csv", index=False, encoding="utf-8-sig")
        _group_metrics(best_events, "entry_rule").to_csv(REPORTS / "engine_multibucket_best_layers_20260706.csv", index=False, encoding="utf-8-sig")
    _write_doc(single, combos, DOCS / "ENGINE_MULTIBUCKET_STRATEGY_SEARCH_20260706.md")

    print("single")
    print(single.head(30).to_string(index=False) if not single.empty else "none")
    print()
    print("combos")
    print(combos.head(40).to_string(index=False) if not combos.empty else "none")
    if not best_events.empty:
        print()
        print("best yearly")
        print(_group_metrics(best_events, "year").to_string(index=False))
        print()
        print("best layers")
        print(_group_metrics(best_events, "entry_rule").to_string(index=False))


if __name__ == "__main__":
    main()
