"""绝对收益模型年度样本口径测试。"""

import pandas as pd

from research.clean_walkforward_absolute_bagged_lcb_2019_2024 import sample_member_year
from research.clean_walkforward_technical_hgb_excess_target import FEATURES, TARGET


def test_absolute_training_sample_uses_only_features_and_absolute_target() -> None:
    rows = []
    for index in range(10):
        row = {column: float(index) for column in FEATURES}
        row[TARGET] = float(index)
        row["ret_5d_excess"] = -999.0
        rows.append(row)
    result = sample_member_year(pd.DataFrame(rows), 2020, 20260808)
    assert result.columns.tolist() == FEATURES + [TARGET]
    assert "ret_5d_excess" not in result.columns
