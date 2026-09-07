from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from research.research_evidence_registry import qualification_for_script


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from broad_engine_factor_miner import _load_candidates, _predicates, _required_entry_bucket, _select
from v45_engine_exit_backtest import _group_metrics, _metrics
from v45_engine_exit_optimizer import _strong_engine_trades


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
RULES_IN = REPORTS / "broad_engine_rule_union_search_20260706.csv"
SUMMARY_OUT = REPORTS / "live_readiness_postmortem_summary_20260707.csv"
YEARLY_OUT = REPORTS / "live_readiness_postmortem_yearly_20260707.csv"
LAYER_OUT = REPORTS / "live_readiness_postmortem_layers_20260707.csv"
FAILURES_OUT = REPORTS / "live_readiness_postmortem_failures_20260707.csv"
DOC_OUT = DOCS / "LIVE_READINESS_POSTMORTEM_20260707.md"


LIVE_CRITERIA = {
    "trades_min": 80,
    "win_rate_min": 65.0,
    "total_ret_min": 250.0,
    "loss_years_max": 1,
    "worst_year_min": -5.0,
    "active_years_min": 9,
    "max_year_trade_share": 0.45,
    "recent_years": ["2023", "2024", "2025", "2026H1"],
    "recent_win_rate_min": 60.0,
}


MANUAL_CANDIDATES = [
    {
        "name": "candidate_a_weak_breadth_dual_score",
        "label": "候选A：弱动量强板块双排序并集",
        "rule_a": "market_style=weak_momentum & sector_ma10_ratio>=90 & factor_sector>=30",
        "topn_a": 1,
        "score_a": "quality",
        "rule_b": "market_style=weak_momentum & sector_ma10_ratio>=90 & factor_sector>=30",
        "topn_b": 1,
        "score_b": "hybrid",
    },
    {
        "name": "candidate_b_bear_heat_plus_weak_t5",
        "label": "候选B：熊市涨停热度 + 弱动量T5承接",
        "rule_a": "market_style=bear & limit_up_count>=80",
        "topn_a": 2,
        "score_a": "hybrid",
        "rule_b": "market_style=weak_momentum & factor_sector>=50 & pre_T5_low_pct>-1",
        "topn_b": 1,
        "score_b": "hybrid",
    },
    {
        "name": "candidate_c_single_weak_breadth",
        "label": "候选C：弱动量强板块单层",
        "rule_a": "market_style=weak_momentum & sector_ma10_ratio>=90 & factor_sector>=30",
        "topn_a": 1,
        "score_a": "quality",
        "rule_b": "",
        "topn_b": 0,
        "score_b": "",
    },
]


def _mask_for_rule(df: pd.DataFrame, rule: str, predicate_map: dict[str, pd.Series]) -> pd.Series:
    names = [part.strip() for part in str(rule).split(" & ") if part.strip()]
    if not names:
        return pd.Series(False, index=df.index)
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


def _build_expansion(df: pd.DataFrame, predicate_map: dict[str, pd.Series], spec: dict) -> pd.DataFrame:
    frames = []
    for suffix in ["a", "b"]:
        rule = spec.get(f"rule_{suffix}", "")
        topn = int(spec.get(f"topn_{suffix}", 0) or 0)
        score = str(spec.get(f"score_{suffix}", "") or "")
        if not rule or topn <= 0:
            continue
        mask = _mask_for_rule(df, rule, predicate_map)
        selected = _select(df, mask, topn, score)
        if not selected.empty:
            selected = selected.copy()
            selected["postmortem_layer"] = suffix
            selected["postmortem_rule"] = rule
            frames.append(selected)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False).drop_duplicates(["buy_date", "ts_code"], keep="first")


def _recent_win_rate(trades: pd.DataFrame) -> float:
    recent = trades[trades["year"].astype(str).isin(LIVE_CRITERIA["recent_years"])]
    if recent.empty:
        return 0.0
    return float(recent["win"].mean() * 100)


def _max_year_trade_share(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    return float(trades.groupby("year")["ts_code"].count().max() / len(trades))


def _readiness(metrics: dict, trades: pd.DataFrame) -> tuple[str, list[str]]:
    reasons = []
    active_years = int(trades["year"].nunique()) if "year" in trades.columns else 0
    max_share = _max_year_trade_share(trades)
    recent_wr = _recent_win_rate(trades)
    checks = [
        (metrics["trades"] >= LIVE_CRITERIA["trades_min"], f"trades<{LIVE_CRITERIA['trades_min']}"),
        (metrics["win_rate"] >= LIVE_CRITERIA["win_rate_min"], f"win_rate<{LIVE_CRITERIA['win_rate_min']}"),
        (metrics["total_ret"] >= LIVE_CRITERIA["total_ret_min"], f"total_ret<{LIVE_CRITERIA['total_ret_min']}"),
        (metrics["loss_years"] <= LIVE_CRITERIA["loss_years_max"], f"loss_years>{LIVE_CRITERIA['loss_years_max']}"),
        (metrics["worst_year"] >= LIVE_CRITERIA["worst_year_min"], f"worst_year<{LIVE_CRITERIA['worst_year_min']}"),
        (active_years >= LIVE_CRITERIA["active_years_min"], f"active_years<{LIVE_CRITERIA['active_years_min']}"),
        (max_share <= LIVE_CRITERIA["max_year_trade_share"], f"max_year_trade_share>{LIVE_CRITERIA['max_year_trade_share']:.0%}"),
        (recent_wr >= LIVE_CRITERIA["recent_win_rate_min"], f"recent_win_rate<{LIVE_CRITERIA['recent_win_rate_min']}"),
    ]
    for ok, reason in checks:
        if not ok:
            reasons.append(reason)
    evidence = qualification_for_script("live_readiness_postmortem.py")
    reasons.extend(f"evidence:{item}" for item in evidence["evidence_blockers"])
    return ("ready" if not reasons else "research_only"), reasons


def _candidate_specs() -> list[dict]:
    specs = MANUAL_CANDIDATES.copy()
    if RULES_IN.exists():
        rules = pd.read_csv(RULES_IN, encoding="utf-8-sig")
        rules = rules[rules["target_pass"].astype(bool)].head(10)
        for i, row in rules.iterrows():
            specs.append(
                {
                    "name": f"union_top_{i + 1}",
                    "label": f"并集搜索Top{i + 1}",
                    "rule_a": row["rule_a"],
                    "topn_a": int(row["topn_a"]),
                    "score_a": row["score_a"],
                    "rule_b": row["rule_b"],
                    "topn_b": int(row["topn_b"]),
                    "score_b": row["score_b"],
                }
            )
    deduped = []
    seen = set()
    for spec in specs:
        key = (spec["rule_a"], spec["topn_a"], spec["score_a"], spec["rule_b"], spec["topn_b"], spec["score_b"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


def build_postmortem() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = _load_candidates()
    strong = _strong_engine_trades().copy()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    strong_pairs = set(zip(strong["buy_date"].astype(str), strong["ts_code"].astype(str)))
    df = df[~df.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in strong_pairs, axis=1)]
    predicate_map = {name: pred for name, pred in _predicates(df)}

    summaries = []
    yearly_frames = []
    layer_frames = []
    failure_frames = []

    for spec in _candidate_specs():
        expansion = _build_expansion(df, predicate_map, spec)
        expansion["candidate_layer"] = "expansion"
        strong_copy = strong.copy()
        strong_copy["candidate_layer"] = "strong_T1"
        trades = pd.concat([strong_copy, expansion], ignore_index=True, sort=False)
        trades = trades.drop_duplicates(["buy_date", "ts_code"], keep="first").copy()
        trades["ret"] = pd.to_numeric(trades["ret"], errors="coerce").fillna(0.0)
        trades["win"] = trades["ret"] > 0
        metrics = _metrics(trades)
        status, reasons = _readiness(metrics, trades)
        active_years = int(trades["year"].nunique()) if not trades.empty else 0
        summary = {
            "candidate": spec["name"],
            "label": spec["label"],
            "status": status,
            "blockers": ";".join(reasons),
            "active_years": active_years,
            "recent_win_rate": _recent_win_rate(trades),
            "max_year_trade_share": _max_year_trade_share(trades) * 100,
            **metrics,
            "rule_a": spec["rule_a"],
            "topn_a": spec["topn_a"],
            "score_a": spec["score_a"],
            "rule_b": spec["rule_b"],
            "topn_b": spec["topn_b"],
            "score_b": spec["score_b"],
        }
        summaries.append(summary)

        yearly = _group_metrics(trades, "year")
        yearly.insert(0, "candidate", spec["name"])
        yearly_frames.append(yearly)

        layers = _group_metrics(trades, "candidate_layer")
        layers.insert(0, "candidate", spec["name"])
        layer_frames.append(layers)

        failures = trades[~trades["win"]].copy()
        if not failures.empty:
            failures["candidate"] = spec["name"]
            failure_frames.append(failures)

    summary_df = pd.DataFrame(summaries).sort_values(
        ["status", "win_rate", "trades", "loss_years", "max_year_trade_share"],
        ascending=[True, False, False, True, True],
    )
    yearly_df = pd.concat(yearly_frames, ignore_index=True, sort=False) if yearly_frames else pd.DataFrame()
    layer_df = pd.concat(layer_frames, ignore_index=True, sort=False) if layer_frames else pd.DataFrame()
    failures_df = pd.concat(failure_frames, ignore_index=True, sort=False) if failure_frames else pd.DataFrame()
    return summary_df, yearly_df, layer_df, failures_df


def _write_doc(summary: pd.DataFrame, yearly: pd.DataFrame, layers: pd.DataFrame, failures: pd.DataFrame) -> None:
    top = summary.head(8)
    best_name = str(top.iloc[0]["candidate"]) if not top.empty else ""
    best_yearly = yearly[yearly["candidate"].eq(best_name)].sort_values("year") if best_name else pd.DataFrame()
    best_layers = layers[layers["candidate"].eq(best_name)] if best_name else pd.DataFrame()
    failure_by_year = (
        failures[failures["candidate"].eq(best_name)]
        .groupby(["year", "exit_reason"], dropna=False)
        .agg(losses=("ts_code", "count"), total_ret=("ret", "sum"), avg_ret=("ret", "mean"))
        .reset_index()
        .sort_values(["year", "losses"], ascending=[True, False])
        if best_name and not failures.empty
        else pd.DataFrame()
    )

    lines = [
        "# 历史版本复盘与上线准备审计（2026-07-07）",
        "",
        "## 上线标准",
        "",
        f"- 真实退出交易数 >= {LIVE_CRITERIA['trades_min']}。",
        f"- 总胜率 >= {LIVE_CRITERIA['win_rate_min']:.0f}%，总收益 >= {LIVE_CRITERIA['total_ret_min']:.0f}%。",
        f"- 亏损年份 <= {LIVE_CRITERIA['loss_years_max']}，最差年份收益 >= {LIVE_CRITERIA['worst_year_min']:.0f}%。",
        f"- 活跃年份 >= {LIVE_CRITERIA['active_years_min']}，单一年份交易占比 <= {LIVE_CRITERIA['max_year_trade_share']:.0%}。",
        f"- 近年（{', '.join(LIVE_CRITERIA['recent_years'])}）胜率 >= {LIVE_CRITERIA['recent_win_rate_min']:.0f}%。",
        "",
        "## 候选审计 Top8",
        "",
        top[
            [
                "candidate",
                "status",
                "trades",
                "win_rate",
                "total_ret",
                "positive_years",
                "loss_years",
                "worst_year",
                "active_years",
                "recent_win_rate",
                "max_year_trade_share",
                "blockers",
            ]
        ].to_markdown(index=False, floatfmt=".2f")
        if not top.empty
        else "无",
        "",
        "## 现阶段结论",
        "",
        "- 小样本强版本（v35/v39/v39 类）优点是命中率极高，缺点是十年总笔数太少，不能直接解决稳定推荐问题。",
        "- v45 的 T5 扩展在样本级好看，但真实退出后扩展层胜率只有约 35%，说明延迟买入不能只看5日后路径，必须有买入前确认和市场层过滤。",
        "- 今晚的并集候选已经越过 `65% + 80笔` 的研究门槛，但按更严格上线标准仍是 `research_only`，主要问题是年度覆盖、亏损年份和 2025 集中度。",
        "- 更值得继续打磨的方向是 `weak_momentum + 板块广度/强度 + T5不破位`，而不是泛候选池或单纯推迟到 T7。",
        "",
        f"## 当前最优候选：{best_name}",
        "",
        "### 分层",
        "",
        best_layers.to_markdown(index=False, floatfmt=".2f") if not best_layers.empty else "无",
        "",
        "### 年度",
        "",
        best_yearly.to_markdown(index=False, floatfmt=".2f") if not best_yearly.empty else "无",
        "",
        "### 亏损退出分布",
        "",
        failure_by_year.to_markdown(index=False, floatfmt=".2f") if not failure_by_year.empty else "无",
        "",
        "## 下一步优化方向",
        "",
        "1. 对 2020、2024、2016 的失败票做负样本共性过滤，优先减少弱年度损失。",
        "2. 给扩展层增加年度稳健惩罚，不再只按总收益和总胜率排序。",
        "3. 把候选策略做 walk-forward：用早期年份选规则，后续年份验证，压低过拟合风险。",
        "4. 只有当候选从 `research_only` 变成 `ready`，才考虑写入线上正式版本。",
        "",
    ]
    DOC_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    summary, yearly, layers, failures = build_postmortem()
    summary.to_csv(SUMMARY_OUT, index=False, encoding="utf-8-sig")
    yearly.to_csv(YEARLY_OUT, index=False, encoding="utf-8-sig")
    layers.to_csv(LAYER_OUT, index=False, encoding="utf-8-sig")
    failures.to_csv(FAILURES_OUT, index=False, encoding="utf-8-sig")
    _write_doc(summary, yearly, layers, failures)
    print(summary.head(12).to_string(index=False))


if __name__ == "__main__":
    main()
