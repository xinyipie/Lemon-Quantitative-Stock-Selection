"""研究脚本证据资格登记表；供报告和上线门读取。"""

from __future__ import annotations

import json
from pathlib import Path

from research.research_integrity import evidence_qualification


SAME_SAMPLE_SEARCH = {
    "broad_engine_factor_miner.py",
    "broad_engine_rule_union_search.py",
    "consensus_rule_search.py",
    "delayed_confirmation_gate_search.py",
    "engine_multibucket_strategy_search.py",
    "entry_timing_bucket_research.py",
    "expansion_layer_rule_search.py",
    "live_base_filter_optimizer.py",
    "live_readiness_optimizer.py",
    "live_readiness_postmortem.py",
    "pattern_breadth_rule_search.py",
    "short_signal_factor_miner.py",
    "sparse_year_addon_search.py",
    "strong_adjacent_engine_search.py",
    "t3_confirmation_quality_search.py",
    "v41_v42_snapshot_experiment.py",
    "v45_engine_exit_optimizer.py",
}

GROSS_RETURN_ONLY = {
    "consensus_rule_search.py",
    "dragon_fast_money_experiment.py",
    "dragon_page_backtest.py",
    "dragon_reliability_backtest.py",
    "expansion_layer_rule_search.py",
    "pattern_breadth_rule_search.py",
    "strategy_candidate_simulator.py",
    "v41_v42_snapshot_experiment.py",
}

CONSUMED_HOLDOUT = {
    "all_market_opportunity_archetypes.py",
    "defensive_quality_reentry_v16_2019_2026.py",
    "defensive_quality_reentry_v17_stress_2019_2026.py",
    "opportunity_archetype_ranking_research.py",
    "quality_momentum_dual_window_consensus_v15_2019_2026.py",
    "quality_momentum_moneyflow_v12_observation_2026.py",
    "quality_momentum_reentry_margin_v3_holdout_2025.py",
    "high_momentum_continuation_v13_2019_2026.py",
    "quality_momentum_rolling3y_v14_2019_2026.py",
}

OVERLAPPING_HORIZON_METRICS = {
    "full_market_event_research.py",
    "two_stage_walkforward_research.py",
    "walkforward_linear_ranker.py",
}


def qualification_for_script(script: str | Path) -> dict[str, object]:
    """返回脚本当前可声明的证据等级，阻断项不能被 ready 字段覆盖。"""
    path = Path(script)
    name = path.name
    blockers: list[str] = []
    if name in SAME_SAMPLE_SEARCH:
        blockers.append("same_sample_optimization")
    if name in GROSS_RETURN_ONLY:
        blockers.append("gross_return_or_incomplete_execution")
    if name in CONSUMED_HOLDOUT or "sealed" in name.lower():
        blockers.append("consumed_holdout")
    if name in OVERLAPPING_HORIZON_METRICS:
        blockers.append("overlapping_horizon_not_account_curve")
    if name == "strategy_candidate_simulator.py":
        blockers.append("retrospective_period_not_forward_holdout")
    if name == "clean_walkforward_technical_hgb_holdout_calibrated.py":
        blockers.append("calibration_holdout_not_final_oos")
    if "2019_2024" in name or name == "validate_walkforward_excess_bagged_lcb.py":
        blockers.append("historical_validation_period_reused_for_development")
    if "strategy_archive" in path.parts:
        blockers.extend(["archived_snapshot", "not_current_strategy_evidence"])
    return evidence_qualification(name.removesuffix(".py"), blockers=blockers)


def registry_manifest() -> dict[str, dict[str, object]]:
    names = sorted(
        SAME_SAMPLE_SEARCH
        | GROSS_RETURN_ONLY
        | CONSUMED_HOLDOUT
        | OVERLAPPING_HORIZON_METRICS
        | {path.name for path in Path(__file__).parent.glob("*2019_2024*.py")}
        | {path.name for path in Path(__file__).parent.glob("*sealed*.py")}
        | {
            "clean_walkforward_technical_hgb_holdout_calibrated.py",
            "validate_walkforward_excess_bagged_lcb.py",
        }
    )
    return {name: qualification_for_script(name) for name in names}


if __name__ == "__main__":
    print(json.dumps(registry_manifest(), ensure_ascii=False, indent=2))
