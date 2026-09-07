"""既有退出压力成本口径测试。"""

import pandas as pd

from research.clean_walkforward_excess_existing_exit import (
    add_position_counts,
    add_stress_exit_cost,
    normalize_nav_base,
)


def test_stress_cost_is_added_only_to_copied_exit_results() -> None:
    original = [{"profit_after_fee": 2.0, "ts_code": "000001.SZ"}]
    stressed = add_stress_exit_cost(original, extra_cost_pct=0.25)
    assert original[0]["profit_after_fee"] == 2.0
    assert stressed[0]["profit_after_fee"] == 1.75


def test_position_count_excludes_sell_date_after_intraday_exit() -> None:
    curve = pd.DataFrame({"trade_date": ["20200102", "20200103"], "nav": [100.0, 101.0]})
    trades = [{"buy_date": "20200102", "sell_date": "20200103"}]
    result = add_position_counts(curve, trades)
    assert result["positions"].tolist() == [1, 0]


def test_backtest_nav_is_normalized_to_one_base() -> None:
    result = normalize_nav_base(pd.DataFrame({"nav": [100.0, 125.0]}))
    assert result["nav"].tolist() == [1.0, 1.25]
