"""持续恶化市场宽度门控的时序测试。"""

import pandas as pd

from research.clean_walkforward_excess_falling_breadth_gate import (
    BREADTH_DELTA,
    RISK_OFF,
    add_falling_breadth_gate,
)


def test_gate_uses_five_prior_market_dates_and_all_sign_conditions() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [f"2020010{i}" for i in range(1, 8)],
            "market_breadth_ma20": [0.6, 0.6, 0.6, 0.6, 0.6, 0.5, 0.7],
            "market_median_ret5": [-1.0] * 7,
            "market_median_ret20": [-2.0] * 7,
        }
    )
    result = add_falling_breadth_gate(frame)
    assert pd.isna(result.loc[0, BREADTH_DELTA])
    assert bool(result.loc[5, RISK_OFF]) is True
    assert bool(result.loc[6, RISK_OFF]) is False


def test_gate_requires_both_market_returns_to_be_negative() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [f"2020010{i}" for i in range(1, 7)],
            "market_breadth_ma20": [0.6, 0.6, 0.6, 0.6, 0.6, 0.5],
            "market_median_ret5": [-1.0] * 6,
            "market_median_ret20": [-2.0] * 5 + [1.0],
        }
    )
    result = add_falling_breadth_gate(frame)
    assert bool(result.loc[5, RISK_OFF]) is False
