import pandas as pd

from research.quality_momentum_reentry_online_gate_v5_2019_2024 import (
    online_gate_decisions,
)


def test_online_gate_uses_only_predictions_strictly_before_current_day() -> None:
    daily = pd.DataFrame(
        {
            "trade_date": ["20240101", "20240102", "20240103", "20240104"],
            "gate_prediction": [1.0, 2.0, 100.0, 3.0],
        }
    )

    result = online_gate_decisions(daily, quantile=0.50, warmup_days=2)

    assert result["online_gate_pass"].tolist() == [False, False, True, True]
    assert result.loc[2, "online_gate_threshold"] == 1.5
    assert result.loc[3, "online_gate_threshold"] == 2.0


def test_online_gate_sorts_dates_before_building_history() -> None:
    daily = pd.DataFrame(
        {
            "trade_date": ["20240103", "20240101", "20240102"],
            "gate_prediction": [3.0, 1.0, 2.0],
        }
    )

    result = online_gate_decisions(daily, quantile=0.50, warmup_days=2)

    assert result["trade_date"].tolist() == ["20240101", "20240102", "20240103"]
    assert result["online_gate_pass"].tolist() == [False, False, True]
