from research.clean_walkforward_technical_hgb_oos_calibrated import oos_calibration_splits


def test_train_calibration_prediction_years_are_strictly_ordered():
    assert all(
        max(train_years) < calibration_year < predict_year
        for train_years, calibration_year, predict_year in oos_calibration_splits()
    )
