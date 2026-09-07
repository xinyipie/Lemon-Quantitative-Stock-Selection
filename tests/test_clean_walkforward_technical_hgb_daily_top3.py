import pandas as pd

from research.clean_walkforward_technical_hgb_daily_top3 import lock_daily_top3


def test_daily_top3_is_scale_and_shift_invariant():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101"] * 5,
            "ts_code": list("ABCDE"),
            "prediction": [0.1, 0.7, -0.2, 0.3, 1.0],
        }
    )
    transformed = frame.copy()
    transformed["prediction"] = transformed["prediction"] * 5.0 + 9.0
    assert lock_daily_top3(frame)["ts_code"].tolist() == lock_daily_top3(transformed)["ts_code"].tolist()
