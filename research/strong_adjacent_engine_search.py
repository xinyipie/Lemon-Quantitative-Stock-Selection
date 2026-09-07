from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from backtest_v2 import BacktestV2
from local_data_proxy import LocalDataProxy
from v45_engine_exit_backtest import _group_metrics, _metrics, _to_float
from v45_engine_exit_optimizer import _strong_engine_trades


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
SAMPLES = REPORTS / "historical_winner_commonality_h1_v30_20260706.samples.csv"
ALL_EXITS = REPORTS / "strong_adjacent_engine_candidate_exits_20260706.csv"
RULES_OUT = REPORTS / "strong_adjacent_engine_rule_search_20260706.csv"
TRADES_OUT = REPORTS / "strong_adjacent_engine_best_trades_20260706.csv"
DOC_OUT = DOCS / "STRONG_ADJACENT_ENGINE_SEARCH_20260706.md"


def _clean_date(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _year_bucket(date: str) -> str:
    date = str(date)
    if date.startswith("2026"):
        return "2026H1"
    return date[:4]


def _load_samples() -> pd.DataFrame:
    df = pd.read_csv(SAMPLES, encoding="utf-8-sig")
    df["select_date"] = df["select_date"].map(_clean_date)
    df["buy_date"] = df["buy_date"].map(_clean_date)
    df["ts_code"] = df["ts_code"].astype(str)
    df = df[df["select_date"].str.len().eq(8) & df["buy_date"].str.len().eq(8)].copy()
    df = df[~df["version_tag"].astype(str).eq("stage3_consensus_candidates")].copy()
    for col in [
        "score",
        "original_score",
        "factor_volume_ratio",
        "factor_drawdown",
        "factor_inflow",
        "factor_turnover",
        "factor_sector",
        "factor_pattern",
        "factor_wyckoff",
        "factor_accel",
        "change",
        "volume_ratio",
        "drawdown_from_high",
        "turnover",
        "market_index_change",
        "sector_ma10_ratio",
        "limit_up_count",
        "limit_down_count",
        "consensus_votes",
        "consensus_avg_rank",
        "consensus_avg_score",
        "n_versions",
        "best_rank",
        "avg_rank",
        "avg_score",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def _build_price_cache(pro: LocalDataProxy, dates: list[str]) -> dict[str, pd.DataFrame]:
    cache = {}
    for date in dates:
        daily = pro.daily(trade_date=date)
        if daily is not None and not daily.empty:
            cache[date] = daily
    return cache


def build_engine_exits(force: bool = False) -> pd.DataFrame:
    if ALL_EXITS.exists() and not force:
        return pd.read_csv(ALL_EXITS, encoding="utf-8-sig")

    samples = _load_samples()
    samples = samples.drop_duplicates(
        subset=["version_tag", "select_date", "buy_date", "ts_code"],
        keep="first",
    ).copy()
    pro = LocalDataProxy(cache_dir=str(ROOT / "data" / "cache"))
    engine = BacktestV2(
        pro=pro,
        start_date=str(samples["buy_date"].min()),
        end_date=str(samples["buy_date"].max()),
        hold_days=5,
        top_n=1,
        use_market_timing=False,
        min_open_ratio=0.0,
    )
    price_cache = _build_price_cache(pro, engine.all_trade_dates)

    copy_cols = [
        "source_family",
        "source_file",
        "version_tag",
        "period",
        "select_date",
        "name",
        "industry",
        "score",
        "original_score",
        "factor_volume_ratio",
        "factor_drawdown",
        "factor_inflow",
        "factor_turnover",
        "factor_sector",
        "factor_pattern",
        "factor_wyckoff",
        "factor_accel",
        "change",
        "volume_ratio",
        "drawdown_from_high",
        "turnover",
        "market_index_change",
        "sector_ma10_ratio",
        "limit_up_count",
        "limit_down_count",
        "consensus_votes",
        "consensus_avg_rank",
        "consensus_avg_score",
        "market_style",
        "macro_mode",
        "market_state",
        "operation_mode",
        "regime",
        "n_versions",
        "best_rank",
        "avg_rank",
        "avg_score",
    ]
    rows = []
    for _, event in samples.iterrows():
        buy_date = str(event["buy_date"])
        future_dates = [date for date in engine.all_trade_dates if date >= buy_date]
        result = engine._simulate_trade(
            ts_code=str(event["ts_code"]),
            buy_date=buy_date,
            future_dates=future_dates,
            price_cache=price_cache,
            tech_stop_price=_to_float(event, "stop_loss_price", 0.0),
            tech_target_price=_to_float(event, "target_price", 0.0),
            volatility=_to_float(event, "volatility", 3.0),
            tech_low20=_to_float(event, "low20", 0.0),
            select_close=_to_float(event, "select_close", 0.0),
            regime_max_hold=5,
            track_type=f"strong_adjacent_{event.get('version_tag', '')}",
            signal_row=event,
        )
        if result is None:
            continue
        for column in copy_cols:
            if column in event:
                result[column] = event.get(column)
        result["entry_date"] = buy_date
        result["entry_rule"] = "strong_adjacent"
        result["ret"] = _to_float(pd.Series(result), "profit_after_fee", _to_float(pd.Series(result), "profit_pct", 0.0))
        result["win"] = result["ret"] > 0
        result["year"] = _year_bucket(str(result.get("buy_date", buy_date)))
        rows.append(result)

    out = pd.DataFrame(rows)
    out.to_csv(ALL_EXITS, index=False, encoding="utf-8-sig")
    return out


def _version_groups(candidates: pd.DataFrame) -> dict[str, list[str]]:
    tags = sorted(candidates["version_tag"].dropna().astype(str).unique())
    groups = {tag: [tag] for tag in tags}
    groups.update(
        {
            "v35_v39": ["v35", "v39"],
            "top4_sample": ["v35", "v39", "v37", "v38"],
            "top8_sample": ["v35", "v39", "v37", "v38", "v34", "v36", "v33", "v32"],
            "strong_family": ["v35", "v39", "v37", "v38", "v34", "v36", "v33", "v32", "v30", "v40"],
            "all_non_stage3": tags,
        }
    )
    return {name: [tag for tag in members if tag in tags] for name, members in groups.items()}


def _score_candidates(work: pd.DataFrame, score_profile: str) -> pd.Series:
    score = pd.Series(0.0, index=work.index)
    base = pd.to_numeric(work.get("score", 0), errors="coerce").fillna(0)
    original = pd.to_numeric(work.get("original_score", 0), errors="coerce").fillna(0)
    if score_profile == "base":
        return base.where(base != 0, original)
    score = score + base.where(base != 0, original)
    if score_profile == "quality":
        for col, weight in [
            ("factor_pattern", 0.8),
            ("factor_wyckoff", 0.5),
            ("factor_sector", 0.35),
            ("factor_inflow", 0.25),
            ("factor_volume_ratio", 0.2),
        ]:
            if col in work.columns:
                score = score + pd.to_numeric(work[col], errors="coerce").fillna(0) * weight
    elif score_profile == "defensive":
        for col, weight in [
            ("factor_pattern", 1.0),
            ("factor_wyckoff", 0.7),
            ("sector_ma10_ratio", 0.35),
            ("factor_inflow", 0.2),
        ]:
            if col in work.columns:
                score = score + pd.to_numeric(work[col], errors="coerce").fillna(0) * weight
        if "limit_down_count" in work.columns:
            score = score - pd.to_numeric(work["limit_down_count"], errors="coerce").fillna(0) * 3.0
    return score


def _select_expansion(candidates: pd.DataFrame, rule: dict, strong: pd.DataFrame) -> pd.DataFrame:
    work = candidates[candidates["version_tag"].astype(str).isin(rule["versions"])].copy()
    if {"buy_date", "ts_code"}.issubset(strong.columns):
        strong_pairs = set(zip(strong["buy_date"].astype(str), strong["ts_code"].astype(str)))
        work = work[
            ~work.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in strong_pairs, axis=1)
        ].copy()
    if work.empty:
        return work

    filters = [
        ("macro_mode", rule["macro_mode"], "eq"),
        ("market_style", rule["market_style"], "eq"),
        ("factor_pattern", rule["pattern_min"], "ge"),
        ("factor_wyckoff", rule["wyckoff_min"], "ge"),
        ("factor_sector", rule["sector_min"], "ge"),
        ("factor_inflow", rule["inflow_min"], "ge"),
        ("factor_volume_ratio", rule["volume_min"], "ge"),
        ("limit_down_count", rule["limit_down_max"], "le"),
        ("best_rank", rule["best_rank_max"], "le"),
        ("avg_rank", rule["avg_rank_max"], "le"),
        ("sector_ma10_ratio", rule["sector_ma10_min"], "ge"),
        ("market_index_change", rule["market_index_min"], "ge"),
    ]
    for col, value, op in filters:
        if value is None or col not in work.columns:
            continue
        if op == "eq":
            work = work[work[col].astype(str).eq(str(value))]
        else:
            values = pd.to_numeric(work[col], errors="coerce")
            if op == "ge":
                work = work[values >= float(value)]
            elif op == "le":
                work = work[values <= float(value)]
        if work.empty:
            return work

    work["research_score"] = _score_candidates(work, rule["score_profile"])
    work = work.sort_values(
        ["select_date", "research_score", "version_tag", "ts_code"],
        ascending=[True, False, True, True],
    )
    work = work.drop_duplicates(subset=["select_date", "ts_code"], keep="first")
    return work.groupby("select_date", group_keys=False).head(int(rule["daily_topn"])).reset_index(drop=True)


def _target_pass(metrics: dict) -> bool:
    return metrics["trades"] > 80 and metrics["win_rate"] >= 65.0


def search_rules(candidates: pd.DataFrame, strong: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    best_trades = pd.DataFrame()
    best_score = -10**9
    groups = _version_groups(candidates)
    rules = []
    core_groups = [
        "v39",
        "v35",
        "v36",
        "v37",
        "v38",
        "v34",
        "v33",
        "v35_v39",
        "top4_sample",
        "top8_sample",
        "strong_family",
    ]
    broad_filters = [
        {},
        {"macro_mode": "cautious"},
        {"macro_mode": "active"},
        {"factor_pattern": 50.0},
        {"factor_pattern": 60.0},
        {"factor_wyckoff": 55.0},
        {"factor_wyckoff": 65.0},
        {"factor_sector": 40.0},
        {"factor_inflow": 80.0},
        {"factor_volume_ratio": 55.0},
        {"limit_down_count": 8.0},
        {"sector_ma10_ratio": 70.0},
        {"market_index_change": -1.0},
        {"macro_mode": "cautious", "factor_pattern": 50.0},
        {"macro_mode": "cautious", "sector_ma10_ratio": 70.0},
        {"factor_pattern": 50.0, "factor_wyckoff": 55.0},
        {"factor_sector": 40.0, "factor_inflow": 80.0},
        {"factor_pattern": 50.0, "limit_down_count": 8.0},
        {"factor_wyckoff": 55.0, "sector_ma10_ratio": 70.0},
    ]
    market_styles = [None, "weak_momentum"]
    score_profiles = ["base", "quality", "defensive"]
    for group_name in core_groups:
        if group_name not in groups:
            continue
        for filter_set in broad_filters:
            for style in market_styles:
                for score_profile in score_profiles:
                    for daily_topn in [1, 2]:
                        rules.append(
                            {
                                "version_group": group_name,
                                "macro_mode": filter_set.get("macro_mode"),
                                "market_style": style,
                                "pattern_min": filter_set.get("factor_pattern"),
                                "wyckoff_min": filter_set.get("factor_wyckoff"),
                                "sector_min": filter_set.get("factor_sector"),
                                "inflow_min": filter_set.get("factor_inflow"),
                                "volume_min": filter_set.get("factor_volume_ratio"),
                                "limit_down_max": filter_set.get("limit_down_count"),
                                "best_rank_max": None,
                                "avg_rank_max": None,
                                "sector_ma10_min": filter_set.get("sector_ma10_ratio"),
                                "market_index_min": filter_set.get("market_index_change"),
                                "score_profile": score_profile,
                                "daily_topn": daily_topn,
                                "versions": groups[group_name],
                            }
                        )

    for rule in rules:
        if not rule["versions"]:
            continue
        expansion = _select_expansion(candidates, rule, strong)
        if not (20 <= len(expansion) <= 160):
            continue
        combined = pd.concat([strong, expansion], ignore_index=True, sort=False)
        combined = combined.drop_duplicates(subset=["buy_date", "ts_code"], keep="first").copy()
        combined["ret"] = pd.to_numeric(combined["ret"], errors="coerce").fillna(0.0)
        combined["win"] = combined["ret"] > 0
        metrics = _metrics(combined)
        expansion_metrics = _metrics(expansion)
        score = (
            metrics["win_rate"] * 2.0
            + min(metrics["trades"], 140) * 0.35
            + min(metrics["total_ret"], 360) * 0.14
            - metrics["loss_years"] * 7.0
            - abs(min(metrics["worst_year"], 0.0)) * 1.2
        )
        if _target_pass(metrics):
            score += 200.0
        if score > best_score:
            best_score = score
            best_trades = combined.copy()
        rows.append(
            {
                **{k: v for k, v in rule.items() if k != "versions"},
                "versions": ",".join(rule["versions"]),
                "trades": metrics["trades"],
                "win_rate": metrics["win_rate"],
                "total_ret": metrics["total_ret"],
                "avg_ret": metrics["avg_ret"],
                "positive_years": metrics["positive_years"],
                "loss_years": metrics["loss_years"],
                "worst_year": metrics["worst_year"],
                "target_pass": _target_pass(metrics),
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
    return result, best_trades


def _version_summary(candidates: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tag, frame in candidates.groupby("version_tag", dropna=False):
        rows.append({"version_tag": tag, **_metrics(frame)})
    return pd.DataFrame(rows).sort_values(["win_rate", "trades"], ascending=[False, False])


def _write_doc(candidates: pd.DataFrame, rules: pd.DataFrame, best: pd.DataFrame) -> None:
    lines = [
        "# strong_T1 + 历史强版本邻近样本真实退出搜索（2026-07-06）",
        "",
        "## 口径",
        "",
        "- 保留 `strong_T1`，扩展层来自 `historical_winner_commonality_h1_v30` 中的历史强版本样本。",
        "- 所有扩展样本复用 `BacktestV2._simulate_trade`，不使用未来收益排序。",
        "- 每个选股日扩展层最多取 Top1 或 Top2，跳过已有 `strong_T1` 日期。",
        "- 目标：十年真实退出胜率 >= 65%，总笔数 > 80。",
        "",
        "## 历史版本真实退出复核 Top20",
        "",
        _version_summary(candidates).head(20).to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 规则搜索 Top30",
        "",
        rules.head(30).to_markdown(index=False, floatfmt=".2f") if not rules.empty else "无候选规则",
        "",
        "## 当前最佳年度分布",
        "",
        _group_metrics(best, "year").sort_values("year").to_markdown(index=False, floatfmt=".2f") if not best.empty else "无",
        "",
    ]
    DOC_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    candidates = build_engine_exits()
    strong = _strong_engine_trades().copy()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    rules, best = search_rules(candidates, strong)
    rules.to_csv(RULES_OUT, index=False, encoding="utf-8-sig")
    best.to_csv(TRADES_OUT, index=False, encoding="utf-8-sig")
    _write_doc(candidates, rules, best)
    print("version summary")
    print(_version_summary(candidates).head(20).to_string(index=False))
    print()
    print("rule search")
    print(rules.head(40).to_string(index=False) if not rules.empty else "no candidates")
    print()
    print("best yearly")
    print(_group_metrics(best, "year").sort_values("year").to_string(index=False) if not best.empty else "no best")


if __name__ == "__main__":
    main()
