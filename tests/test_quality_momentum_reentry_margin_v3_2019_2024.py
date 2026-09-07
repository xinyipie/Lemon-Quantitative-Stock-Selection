import pandas as pd

from research.quality_momentum_reentry_margin_v3_2019_2024 import (
    MINIMUM_PREDICTION_MARGIN,
    select_high_confidence_top1,
)


def test_margin_threshold_is_frozen_at_two_points() -> None:
    assert MINIMUM_PREDICTION_MARGIN == 0.02


def test_select_high_confidence_top1_requires_two_ranked_rows_and_seals_2025() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20240103", "20240103", "20250102", "20250102"],
            "ts_code": ["A.SH", "B.SZ", "C.SH", "D.SZ", "E.SH", "F.SZ"],
            "rank_prediction": [0.80, 0.77, 0.80, 0.79, 1.0, 0.0],
            "net_ret": [1.0, 2.0, 3.0, 4.0, 100.0, 100.0],
        }
    )

    result = select_high_confidence_top1(trades)

    assert result["ts_code"].tolist() == ["A.SH"]
    assert result["prediction_margin"].iloc[0] > MINIMUM_PREDICTION_MARGIN
