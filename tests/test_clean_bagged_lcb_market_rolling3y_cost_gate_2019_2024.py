"""市场方向与基础成本联合门控测试。"""

import pandas as pd

from research.clean_bagged_lcb_market_rolling3y_cost_gate_2019_2024 import (
    apply_market_and_cost_gate,
)


def test_both_market_and_cost_conditions_are_required() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20200102", "20200103", "20200104"],
            "prediction": [0.30, 0.20, 0.30],
            "ts_code": ["A", "B", "C"],
        }
    )
    market = pd.DataFrame(
        {
            "trade_date": ["20200102", "20200103", "20200104"],
            "market_prediction": [0.1, 0.1, -0.1],
        }
    )
    result = apply_market_and_cost_gate(trades, market)
    assert result["ts_code"].tolist() == ["A"]
