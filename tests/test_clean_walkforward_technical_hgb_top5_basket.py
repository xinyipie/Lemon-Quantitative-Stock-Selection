import pandas as pd

from research.clean_walkforward_technical_hgb_top5_basket import lock_top5_baskets


def test_top5_basket_is_invariant_to_positive_scale_and_shift():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101"] * 7,
            "ts_code": list("ABCDEFG"),
            "prediction": [0.1, 0.7, -0.2, 0.3, 1.0, 0.6, 0.4],
        }
    )
    transformed = frame.copy()
    transformed["prediction"] = transformed["prediction"] * 11.0 + 50.0
    assert lock_top5_baskets(frame, 0)["ts_code"].tolist() == lock_top5_baskets(transformed, 0)["ts_code"].tolist()
