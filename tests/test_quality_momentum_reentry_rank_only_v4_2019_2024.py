import pandas as pd

from research.quality_momentum_reentry_rank_only_v4_2019_2024 import (
    BASE_MARGIN,
    select_by_prediction_margin,
)


def test_rank_only_selection_keeps_top1_when_lead_exceeds_frozen_margin() -> None:
    ranked = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20240103", "20240103"],
            "ts_code": ["A.SH", "B.SZ", "C.SH", "D.SZ"],
            "rank_prediction": [0.80, 0.77, 0.70, 0.69],
            "ret_5d": [2.0, 5.0, 9.0, 1.0],
        }
    )

    selected = select_by_prediction_margin(ranked, BASE_MARGIN, cost=0.25)

    assert BASE_MARGIN == 0.02
    assert selected["ts_code"].tolist() == ["A.SH"]
    assert selected["net_ret"].tolist() == [1.75]


def test_rank_only_selection_rejects_day_without_two_candidates() -> None:
    ranked = pd.DataFrame(
        {
            "trade_date": ["20240102"],
            "ts_code": ["A.SH"],
            "rank_prediction": [0.80],
            "ret_5d": [2.0],
        }
    )

    assert select_by_prediction_margin(ranked, BASE_MARGIN, cost=0.25).empty
