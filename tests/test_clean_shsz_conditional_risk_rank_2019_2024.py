import pandas as pd

from research.clean_shsz_conditional_risk_rank_2019_2024 import (
    RISK_REGIME_THRESHOLD,
    apply_conditional_ranking,
    eligible_shsz,
)


def test_risk_regime_threshold_is_frozen_at_half() -> None:
    assert RISK_REGIME_THRESHOLD == 0.50


def test_conditional_ranking_only_scales_high_risk_rows() -> None:
    frame = pd.DataFrame(
        {
            "prediction_lower_bound": [2.0, 2.0],
            "volatility_20": [4.0, 4.0],
            "market_tail_risk_probability": [0.40, 0.60],
        }
    )

    result = apply_conditional_ranking(frame)

    assert result.tolist() == [2.0, 0.5]


def test_shsz_contract_applies_to_training_and_prediction_frames() -> None:
    frame = pd.DataFrame({"ts_code": ["A.SH", "B.SZ", "C.BJ"]})

    assert eligible_shsz(frame)["ts_code"].tolist() == ["A.SH", "B.SZ"]
