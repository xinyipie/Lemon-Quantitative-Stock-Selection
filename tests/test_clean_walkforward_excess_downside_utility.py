"""连续下行效用研究的关键口径测试。"""

import pandas as pd

from research.clean_walkforward_excess_downside_utility import (
    add_downside_target,
    calculate_utility,
)


def test_downside_target_only_penalizes_negative_return() -> None:
    frame = pd.DataFrame({"ret_5d": [3.0, 0.0, -4.0, -20.0]})
    result = add_downside_target(frame)
    assert result["downside_5d"].tolist() == [0.0, 0.0, 4.0, 15.0]


def test_utility_decreases_when_predicted_downside_rises() -> None:
    excess = pd.Series([1.0, 1.0])
    downside = pd.Series([0.2, 0.8])
    utility = calculate_utility(excess, downside)
    assert utility.iloc[0] > utility.iloc[1]
    assert utility.tolist() == [0.8, 0.19999999999999996]
