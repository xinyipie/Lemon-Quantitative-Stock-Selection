"""市场头独立硬门控测试。"""

import pandas as pd

from research.clean_bagged_lcb_market_head_hard_gate_2019_2024 import apply_market_hard_gate


def test_stock_excess_cannot_override_negative_market_prediction() -> None:
    trades = pd.DataFrame(
        {"trade_date": ["20200102", "20200103"], "prediction": [99.0, -99.0], "ts_code": ["A", "B"]}
    )
    market = pd.DataFrame(
        {"trade_date": ["20200102", "20200103"], "market_prediction": [-0.1, 0.1]}
    )
    result = apply_market_hard_gate(trades, market)
    assert result["ts_code"].tolist() == ["B"]
