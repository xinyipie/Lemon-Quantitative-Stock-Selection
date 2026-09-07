"""每日Top1锁定和不递补测试。"""

import pandas as pd

from research.clean_walkforward_excess_corrected_top1 import execute_daily_top1


def test_top1_is_locked_before_execution_and_not_replaced() -> None:
    predictions = pd.DataFrame(
        {
            "trade_date": ["20200102", "20200102"],
            "ts_code": ["A", "B"],
            "prediction": [2.0, 1.0],
            "entry_open": [None, 10.0],
            "entry_gap_pct": [0.0, 0.0],
            "ret_5d": [3.0, 4.0],
        }
    )
    result = execute_daily_top1(predictions)
    assert result.empty
