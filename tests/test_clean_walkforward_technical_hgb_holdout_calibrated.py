import pandas as pd

from research.clean_walkforward_technical_hgb import FEATURES, TARGET
from research.clean_walkforward_technical_hgb_holdout_calibrated import split_fit_and_calibration


def test_fit_and_calibration_indices_are_disjoint():
    rows = []
    for index in range(20):
        row = {feature: float(index + 1) for feature in FEATURES}
        row.update(
            {
                "year": 2018,
                "trade_date": f"201801{index + 1:02d}",
                "label_exit_date_5d": f"201801{index + 6:02d}",
                TARGET: float(index),
                "row_id": index,
            }
        )
        rows.append(row)
    fit, calibration = split_fit_and_calibration(
        pd.DataFrame(rows),
        (2018,),
        prediction_start_date="20190101",
    )
    assert set(fit["row_id"]).isdisjoint(set(calibration["row_id"]))
    assert len(fit) == 11
    assert len(calibration) == 4
