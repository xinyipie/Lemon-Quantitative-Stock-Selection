import pandas as pd

from research.clean_walkforward_technical_hgb_train_calibrated import select_calibrated_trades


def test_calibrated_selection_is_invariant_when_predictions_and_thresholds_share_transform():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101", "20200101"],
            "ts_code": ["A", "B"],
            "prediction": [0.8, 0.5],
            "calibrated_threshold": [0.7, 0.7],
            "entry_open": [10.0, 10.0],
            "entry_gap_pct": [0.0, 0.0],
            "ret_5d": [1.0, 2.0],
        }
    )
    transformed = frame.copy()
    transformed["prediction"] = transformed["prediction"] * 4.0 + 9.0
    transformed["calibrated_threshold"] = transformed["calibrated_threshold"] * 4.0 + 9.0
    first = select_calibrated_trades(frame, ["20200101"])["ts_code"].tolist()
    second = select_calibrated_trades(transformed, ["20200101"])["ts_code"].tolist()
    assert first == second == ["A"]
