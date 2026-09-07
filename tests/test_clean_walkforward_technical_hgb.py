import pandas as pd

from research.clean_walkforward_technical_hgb import build_features, walkforward_splits


def test_walkforward_training_years_are_strictly_before_prediction_year():
    assert all(max(train_years) < predict_year for train_years, predict_year in walkforward_splits())


def test_future_target_change_does_not_change_model_features():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101", "20200101", "20200102", "20200102"],
            "ts_code": ["A", "B", "A", "B"],
            "close": [10.0, 20.0, 11.0, 19.0],
            "synthetic_close": [10.0, 20.0, 11.0, 19.0],
            "pct_chg": [1.0, -1.0, 2.0, -2.0],
            "amount": [100.0, 200.0, 110.0, 190.0],
            "ret_5": [1.0, 2.0, 1.5, 1.0],
            "ret_10": [1.5, 2.5, 2.0, 1.5],
            "ret_20": [2.0, 3.0, 2.5, 2.0],
            "ret_60": [3.0, 4.0, 3.5, 3.0],
            "ma_5": [9.5, 19.0, 10.0, 18.5],
            "ma_20": [9.0, 18.0, 9.5, 18.0],
            "ma_60": [8.0, 17.0, 8.5, 17.5],
            "prior_high_20": [10.5, 21.0, 11.5, 20.0],
            "drawdown_20": [-1.0, -2.0, -1.5, -1.0],
            "rsi_14": [55.0, 60.0, 58.0, 57.0],
            "volatility_20": [2.0, 3.0, 2.5, 2.2],
            "turnover_rate": [1.0, 2.0, 1.5, 1.2],
            "volume_ratio": [1.0, 1.2, 1.1, 0.9],
            "industry_rs_20": [1.0, 2.0, 1.5, 1.0],
            "ret_5d": [3.0, -2.0, 1.0, -1.0],
        }
    )
    changed = frame.copy()
    changed["ret_5d"] = [999.0, -999.0, 888.0, -888.0]
    feature_columns = [column for column in build_features(frame).columns if column not in ("ret_5d",)]
    assert build_features(frame)[feature_columns].equals(build_features(changed)[feature_columns])
