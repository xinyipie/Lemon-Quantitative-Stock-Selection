import pandas as pd

from research.quality_momentum_moneyflow_v12_observation_2026 import select_observation_v3


def test_observation_selector_keeps_only_top1_with_frozen_margin() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20260422", "20260422", "20260423", "20260423"],
            "ts_code": ["A", "B", "C", "D"],
            "rank_prediction": [0.60, 0.57, 0.60, 0.59],
        }
    )
    result = select_observation_v3(frame)
    assert result["ts_code"].tolist() == ["A"]
    assert round(float(result.iloc[0]["prediction_margin"]), 2) == 0.03
