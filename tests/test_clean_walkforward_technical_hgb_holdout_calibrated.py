import pandas as pd

from research.clean_walkforward_technical_hgb import FEATURES, TARGET
from research.clean_walkforward_technical_hgb_holdout_calibrated import split_fit_and_calibration


def test_fit_and_calibration_indices_are_disjoint():
    rows = []
    for index in range(20):
        row = {feature: float(index + 1) for feature in FEATURES}
        row.update({"year": 2018, TARGET: float(index), "row_id": index})
        rows.append(row)
    fit, calibration = split_fit_and_calibration(pd.DataFrame(rows), (2018,))
    assert set(fit["row_id"]).isdisjoint(set(calibration["row_id"]))
    assert len(fit) == 16
    assert len(calibration) == 4
