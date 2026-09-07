"""风险调整超额分数口径测试。"""

import pandas as pd

from research.clean_risk_adjusted_bagged_lcb_market_2019_2024 import risk_adjusted_score


def test_same_expected_excess_prefers_lower_volatility() -> None:
    result = risk_adjusted_score(pd.Series([1.0, 1.0]), pd.Series([2.0, 4.0]))
    assert result.tolist() == [0.5, 0.25]
