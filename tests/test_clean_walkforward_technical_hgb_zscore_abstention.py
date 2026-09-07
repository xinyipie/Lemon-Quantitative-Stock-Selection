import pandas as pd

from research.clean_walkforward_technical_hgb_zscore_abstention import add_daily_prediction_zscore


def test_daily_prediction_zscore_is_scale_and_shift_invariant():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101"] * 4,
            "prediction": [-1.0, 0.0, 1.0, 3.0],
        }
    )
    transformed = frame.copy()
    transformed["prediction"] = transformed["prediction"] * 9.0 + 77.0
    first = add_daily_prediction_zscore(frame)["prediction_zscore"].round(12)
    second = add_daily_prediction_zscore(transformed)["prediction_zscore"].round(12)
    assert first.equals(second)
