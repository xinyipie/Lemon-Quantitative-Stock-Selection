import pandas as pd

from research.clean_walkforward_technical_hgb_relative_top1 import lock_relative_top1


def test_relative_top1_is_invariant_to_positive_scale_and_shift():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101", "20200101", "20200102", "20200102"],
            "ts_code": ["A", "B", "A", "B"],
            "prediction": [0.1, 0.2, -0.5, -0.2],
        }
    )
    transformed = frame.copy()
    transformed["prediction"] = transformed["prediction"] * 7.0 + 123.0
    assert lock_relative_top1(frame)["ts_code"].tolist() == lock_relative_top1(transformed)["ts_code"].tolist()
