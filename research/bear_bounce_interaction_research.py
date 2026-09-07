"""研究熊市反弹中弱行业修复与个股确认信号的交互。"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import all_market_multi_engine_research as market_research
from research.all_market_opportunity_archetypes import assign_feature_bins
from research.opportunity_archetype_ranking_research import select_ranked_candidates
from research.regime_conditioned_opportunity_research import (
    SPLITS,
    _split_label,
    apply_validation_gate,
    normalize_regime,
    summarize_regime_rankings,
)


INTERACTION_SPECS = [
    {"factor": "amount_confirm", "label": "成交额确认", "column": "amount", "direction": "high"},
    {"factor": "price_reversal_confirm", "label": "当日反转确认", "column": "pct_chg", "direction": "high"},
    {"factor": "deep_drawdown_confirm", "label": "深回撤确认", "column": "drawdown_20", "direction": "high"},
    {"factor": "oversold_20d_confirm", "label": "20日超跌确认", "column": "ret_20", "direction": "low"},
    {"factor": "volume_ratio_confirm", "label": "量比确认", "column": "volume_ratio", "direction": "high"},
]

BASELINE_PROFILE = {
    "profile_id": "all_market",
    "description": "全市场可交易股票",
    "conditions": [],
}
BASELINE_RANK_SPEC = [
    {
        "factor": "industry_rs_20",
        "label": "行业相对强度",
        "column": "industry_rs_20",
        "directions": ["low"],
    }
]


def select_two_stage_candidates(
    panel: pd.DataFrame,
    specs: list[dict] = INTERACTION_SPECS,
    top_n: int = 3,
    industry_fraction: float = 0.30,
) -> pd.DataFrame:
    """先选同日弱行业，再按预先指定的个股确认因子排序。"""
    if panel.empty:
        return pd.DataFrame()
    work = panel.copy()
    work["regime"] = normalize_regime(work["regime"])
    names = work.get("name", pd.Series("", index=work.index)).fillna("").astype(str)
    eligible = (
        work["regime"].eq("BEAR_BOUNCE")
        & ~names.str.upper().str.contains("ST|退", regex=True)
        & pd.to_numeric(work.get("history_count"), errors="coerce").ge(60)
        & pd.to_numeric(work.get("amount"), errors="coerce").ge(100000)
        & pd.to_numeric(work.get("ret_3d"), errors="coerce").notna()
    )
    if "tradeable" in work.columns:
        eligible &= work["tradeable"].fillna(False).astype(bool)
    work = work[eligible].copy()
    if work.empty:
        return pd.DataFrame()

    # 行业排名先去重，避免成分股数量多的行业在分位计算中获得额外权重。
    sectors = (
        work[["trade_date", "industry", "industry_rs_20"]]
        .dropna(subset=["industry", "industry_rs_20"])
        .groupby(["trade_date", "industry"], as_index=False)["industry_rs_20"]
        .median()
    )
    sectors["industry_rank"] = sectors.groupby("trade_date")["industry_rs_20"].rank(method="first", ascending=True)
    sectors["industry_count"] = sectors.groupby("trade_date")["industry"].transform("count")
    sectors["industry_cutoff"] = sectors["industry_count"].map(
        lambda count: max(1, int(math.ceil(float(count) * float(industry_fraction))))
    )
    weak_sectors = sectors[sectors["industry_rank"].le(sectors["industry_cutoff"])][["trade_date", "industry"]]
    work = work.merge(weak_sectors.assign(_weak_industry=True), on=["trade_date", "industry"], how="inner")
    if work.empty:
        return pd.DataFrame()

    selected_frames = []
    for spec in specs:
        column = spec["column"]
        if column not in work.columns:
            continue
        valid = work[pd.to_numeric(work[column], errors="coerce").notna()].copy()
        ascending = spec["direction"] == "low"
        selected = (
            valid.sort_values(
                ["trade_date", column, "amount", "ts_code"],
                ascending=[True, ascending, False, True],
                kind="mergesort",
            )
            .groupby("trade_date", group_keys=False)
            .head(int(top_n))
            .copy()
        )
        # 排名发生在T日；T+1不可成交时跳过，不拿下一名递补。
        selected = selected[
            pd.to_numeric(selected.get("entry_open"), errors="coerce").gt(0)
            & pd.to_numeric(selected.get("entry_gap_pct"), errors="coerce").lt(9.5)
        ]
        if selected.empty:
            continue
        selected["profile_id"] = "bear_bounce_weak_industry"
        selected["profile_description"] = "熊市反弹中的弱行业修复"
        selected["rank_factor"] = spec["factor"]
        selected["rank_label"] = spec["label"]
        selected["rank_direction"] = spec["direction"]
        selected["rank_id"] = f"{spec['factor']}_{spec['direction']}"
        selected["top_n"] = int(top_n)
        selected_frames.append(selected)
    return pd.concat(selected_frames, ignore_index=True, sort=False) if selected_frames else pd.DataFrame()


def _write_report(chosen: pd.DataFrame, coverage: pd.DataFrame, start: str, end: str) -> str:
    validation = chosen[chosen["split"].eq("validation")].sort_values(
        ["research_pass", "avg_net_pct", "profit_factor"], ascending=[False, False, False]
    )
    passed = validation[validation["research_pass"]]
    lines = [
        "# 熊市反弹弱行业修复交互研究",
        "",
        f"- 数据范围：{start} 至 {end}",
        "- 仅研究 BEAR_BOUNCE；行业RS最低30%后进行个股二次确认。",
        "- T+1开盘买入、固定持有3日、往返成本0.30%、每日Top3。",
        f"- 预先指定交互：{len(INTERACTION_SPECS)} 组；独立验证通过：{len(passed)} 组。",
        "",
        "## 结论",
        "",
    ]
    if passed.empty:
        lines.append("弱行业修复加入个股确认后，仍没有组合同时通过训练稳定性、独立验证和相对基线提升门槛。")
    else:
        lines.append("存在通过独立验证的预设交互，下一步必须检查极端赢家依赖、成本、TopN与行业阈值扰动。")
    columns = [
        "rank_label",
        "train_avg_net_pct",
        "train_profit_factor",
        "trades",
        "active_days",
        "avg_net_pct",
        "median_net_pct",
        "win_rate",
        "profit_factor",
        "positive_year_ratio",
        "worst_year_avg_pct",
        "baseline_avg_net_pct",
        "baseline_improvement_pct",
        "research_pass",
    ]
    lines.extend(["", "## 独立验证", "", validation[columns].to_markdown(index=False) if not validation.empty else "无结果。"])
    lines.extend(["", "## 样本覆盖", "", coverage.to_markdown(index=False) if not coverage.empty else "无结果。"])
    return "\n".join(lines) + "\n"


def run_research(root: Path, start: str, end: str) -> dict[str, pd.DataFrame | Path]:
    cache_dir = root / "data" / "cache"
    history_start = f"{int(start[:4]) - 1}0101"
    all_dates = market_research._available_dates(cache_dir, history_start, end)
    stock_info = market_research._load_stock_info(cache_dir)
    regimes = market_research._build_regimes(cache_dir, all_dates)
    interaction_frames = []
    baseline_frames = []
    coverage_rows = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        print(f"processing {year}", flush=True)
        panel = market_research.build_year_panel(cache_dir, stock_info, regimes, all_dates, year, start, end)
        if panel.empty:
            continue
        panel = assign_feature_bins(panel)
        panel["regime"] = normalize_regime(panel["regime"])
        panel["split"] = _split_label(panel["trade_date"])
        panel["year"] = panel["trade_date"].astype(str).str[:4].astype(int)
        bounce = panel[panel["regime"].eq("BEAR_BOUNCE")]
        coverage_rows.append(
            {
                "year": year,
                "bounce_days": int(bounce["trade_date"].astype(str).nunique()),
                "bounce_rows": int(len(bounce)),
            }
        )
        interactions = select_two_stage_candidates(panel)
        if not interactions.empty:
            interaction_frames.append(interactions)
        investable = panel[pd.to_numeric(panel["amount"], errors="coerce").ge(100000)].copy()
        baseline = select_ranked_candidates(
            investable,
            profiles=[BASELINE_PROFILE],
            rank_specs=BASELINE_RANK_SPEC,
            top_n=3,
        )
        if not baseline.empty:
            baseline_frames.append(baseline)

    interactions_all = pd.concat(interaction_frames, ignore_index=True, sort=False) if interaction_frames else pd.DataFrame()
    baseline_all = pd.concat(baseline_frames, ignore_index=True, sort=False) if baseline_frames else pd.DataFrame()
    metrics = summarize_regime_rankings(interactions_all)
    baseline_metrics = summarize_regime_rankings(baseline_all)
    baseline_lookup = baseline_metrics[
        baseline_metrics["regime"].eq("BEAR_BOUNCE") & baseline_metrics["rank_direction"].eq("low")
    ][["split", "avg_net_pct"]].rename(columns={"avg_net_pct": "baseline_avg_net_pct"})
    chosen = metrics.merge(baseline_lookup, on="split", how="left", validate="many_to_one") if not metrics.empty else metrics.copy()
    if chosen.empty:
        chosen["baseline_avg_net_pct"] = pd.Series(dtype=float)
    chosen = apply_validation_gate(chosen)
    coverage = pd.DataFrame(coverage_rows)

    output_dir = root / "reports" / "research"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = "20260807"
    report_path = output_dir / f"bear_bounce_interaction_{stamp}.md"
    metrics_path = output_dir / f"bear_bounce_interaction_metrics_{stamp}.csv"
    chosen_path = output_dir / f"bear_bounce_interaction_chosen_{stamp}.csv"
    trades_path = output_dir / f"bear_bounce_interaction_trades_{stamp}.csv"
    coverage_path = output_dir / f"bear_bounce_interaction_coverage_{stamp}.csv"
    report_path.write_text(_write_report(chosen, coverage, start, end), encoding="utf-8")
    metrics.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    chosen.to_csv(chosen_path, index=False, encoding="utf-8-sig")
    compact_columns = [
        "trade_date", "year", "split", "ts_code", "name", "industry", "industry_rs_20",
        "rank_factor", "rank_label", "rank_direction", "top_n", "entry_open", "entry_gap_pct",
        "ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d",
    ]
    existing_columns = [column for column in compact_columns if column in interactions_all.columns]
    interactions_all[existing_columns].to_csv(trades_path, index=False, encoding="utf-8-sig")
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig")
    return {
        "metrics": metrics,
        "chosen": chosen,
        "trades": interactions_all,
        "coverage": coverage,
        "report_path": report_path,
        "chosen_path": chosen_path,
        "trades_path": trades_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="熊市反弹弱行业修复交互研究")
    parser.add_argument("--start", default=SPLITS["train"][0])
    parser.add_argument("--end", default=SPLITS["observed"][1])
    args = parser.parse_args()
    result = run_research(ROOT, args.start, args.end)
    validation = result["chosen"][result["chosen"]["split"].eq("validation")].sort_values(
        ["research_pass", "avg_net_pct"], ascending=[False, False]
    )
    print("\nVALIDATION")
    print(validation.to_string(index=False))
    print(f"passed={int(validation['research_pass'].sum())} report={result['report_path']}")


if __name__ == "__main__":
    main()
