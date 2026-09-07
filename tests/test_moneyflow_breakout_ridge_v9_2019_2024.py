import pandas as pd

from research.moneyflow_breakout_ridge_v9_2019_2024 import select_top1_confident


def test_select_top1_confident_abstains_when_cross_section_is_not_distinct() -> None:
    test = pd.DataFrame(
        {
            "trade_date": ["20240102"] * 4,
            "ts_code": ["A.SH", "B.SH", "C.SH", "D.SH"],
            "rank_prediction": [0.51, 0.50, 0.49, 0.48],
            "ret_5d": [2.0, 1.0, 0.0, -1.0],
        }
    )

    assert select_top1_confident(test, minimum_zscore=2.0, cost=0.25).empty


def test_select_top1_confident_keeps_only_daily_best() -> None:
    test = pd.DataFrame(
        {
            "trade_date": ["20240102"] * 4,
            "ts_code": ["A.SH", "B.SH", "C.SH", "D.SH"],
            "rank_prediction": [2.0, 0.1, 0.0, -0.1],
            "ret_5d": [2.0, 1.0, 0.0, -1.0],
        }
    )

    result = select_top1_confident(test, minimum_zscore=1.5, cost=0.25)

    assert result["ts_code"].tolist() == ["A.SH"]
    assert result["net_ret"].tolist() == [1.75]
