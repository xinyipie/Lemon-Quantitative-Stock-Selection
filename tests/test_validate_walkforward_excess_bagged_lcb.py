"""独立验证年度训练边界和抽样口径测试。"""

import pandas as pd

from research.validate_walkforward_excess_bagged_lcb import sample_member_year


def test_member_sampling_never_adds_unregistered_columns_or_future_rows() -> None:
    from research.clean_walkforward_technical_hgb_excess_target import EXCESS_TARGET, FEATURES

    rows = []
    for index in range(10):
        row = {column: float(index) for column in FEATURES}
        row[EXCESS_TARGET] = float(index)
        row["trade_date"] = f"202201{index + 1:02d}"
        row["label_exit_date_5d"] = f"202202{index + 1:02d}"
        row["future_only"] = 999.0
        rows.append(row)
    result = sample_member_year(pd.DataFrame(rows), 2022, 20260808)
    assert result.columns.tolist() == FEATURES + [EXCESS_TARGET]
    assert "future_only" not in result.columns
