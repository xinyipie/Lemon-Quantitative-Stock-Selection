import pandas as pd

from research.moneyflow_breakout_online_opportunity_v10_2019_2024 import (
    apply_online_opportunity_gate,
)


def test_online_gate_never_uses_current_prediction_in_threshold():
    frame = pd.DataFrame(
        {
            "trade_date": ["20240101", "20240102", "20240103", "20240104"],
            "rank_prediction": [1.0, 2.0, 3.0, 100.0],
        }
    )
    result = apply_online_opportunity_gate(frame, 0.5, lookback_days=3, min_history_days=3)
    assert result["trade_date"].tolist() == ["20240104"]
    assert result.iloc[0]["opportunity_threshold"] == 2.0


def test_online_gate_rejects_low_current_prediction():
    frame = pd.DataFrame(
        {
            "trade_date": ["20240101", "20240102", "20240103", "20240104"],
            "rank_prediction": [3.0, 4.0, 5.0, 1.0],
        }
    )
    result = apply_online_opportunity_gate(frame, 0.5, lookback_days=3, min_history_days=3)
    assert result.empty
