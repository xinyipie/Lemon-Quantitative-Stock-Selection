"""八日截面超额模型的标签口径测试。"""

import pandas as pd

from research.clean_walkforward_technical_hgb_excess_8d import (
    adapt_to_shared_evaluation,
    add_excess_target_8d,
)


def test_excess_target_is_cross_sectional() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20200102", "20200102", "20200103"],
            "ret_8d": [2.0, 4.0, -1.0],
        }
    )
    result = add_excess_target_8d(frame)
    assert result["ret_8d_excess"].tolist() == [-1.0, 1.0, 0.0]


def test_shared_evaluation_uses_eight_day_return() -> None:
    frame = pd.DataFrame({"ret_5d": [99.0], "ret_8d": [3.5]})
    result = adapt_to_shared_evaluation(frame)
    assert result["ret_5d"].iloc[0] == 3.5
