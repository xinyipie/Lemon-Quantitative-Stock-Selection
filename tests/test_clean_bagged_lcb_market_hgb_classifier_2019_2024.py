import pandas as pd

from research.clean_bagged_lcb_market_hgb_classifier_2019_2024 import (
    apply_market_classifier_gate,
    new_market_classifier,
)


def test_market_classifier_is_frozen_low_complexity_model() -> None:
    model = new_market_classifier()

    assert model.max_leaf_nodes == 7
    assert model.min_samples_leaf == 50
    assert model.l2_regularization == 1.0


def test_market_classifier_gate_uses_only_positive_probability_days() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103"],
            "ts_code": ["A", "B"],
        }
    )
    market = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103"],
            "market_prediction": [0.51, 0.49],
            "market_positive_prediction": [True, False],
        }
    )

    result = apply_market_classifier_gate(trades, market)

    assert result["ts_code"].tolist() == ["A"]
