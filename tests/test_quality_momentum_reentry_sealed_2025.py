from research.quality_momentum_reentry_sealed_2025 import (
    INTERNAL_PANEL_YEARS,
    RESEARCH_VALIDATION_YEARS,
    SEALED_HOLDOUT_YEAR,
    internal_gate,
)
import inspect

from research import two_stage_walkforward_research


def test_sealed_protocol_does_not_build_holdout_year() -> None:
    assert max(INTERNAL_PANEL_YEARS + RESEARCH_VALIDATION_YEARS) == 2024
    assert SEALED_HOLDOUT_YEAR == 2025


def test_internal_gate_requires_all_three_positive_years() -> None:
    metrics = {
        "trades": 101,
        "avg_net": 0.1,
        "profit_factor": 1.11,
        "positive_years": 2,
        "years": 3,
    }

    assert not internal_gate(metrics)


def test_gate_training_filters_missing_end_of_sample_targets() -> None:
    """年末未完成持有期的标签不得进入下一年度门控模型。"""

    source = inspect.getsource(two_stage_walkforward_research.walk_forward)
    assert "valid_gate_target = gate_target.notna() & np.isfinite(gate_target)" in source
    assert "gate_train = gate_train.loc[valid_gate_target].copy()" in source


def test_rank_training_supports_rolling_year_window() -> None:
    source = inspect.getsource(two_stage_walkforward_research.walk_forward)
    assert "rank_window_years: int = 0" in source
    assert 'rank_train["year"] >= test_year - rank_window_years' in source
