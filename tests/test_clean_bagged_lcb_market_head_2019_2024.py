"""分层市场头零阈值合并口径测试。"""

import pandas as pd

from research.clean_bagged_lcb_market_head_2019_2024 import apply_predicted_absolute_gate


def test_absolute_gate_adds_market_and_stock_predictions_in_same_units() -> None:
    trades = pd.DataFrame(
        {"trade_date": ["20200102", "20200103"], "prediction": [0.4, 0.4], "ts_code": ["A", "B"]}
    )
    market = pd.DataFrame(
        {"trade_date": ["20200102", "20200103"], "market_prediction": [-0.5, -0.3]}
    )
    result = apply_predicted_absolute_gate(trades, market)
    assert result["ts_code"].tolist() == ["B"]
    assert round(result["predicted_absolute_return"].iloc[0], 6) == 0.1
