import pandas as pd

from research.quality_momentum_reentry_top1_v2_2019_2024 import select_daily_top1


def test_select_daily_top1_uses_prediction_and_seals_2025() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20250102"],
            "ts_code": ["B.SZ", "A.SH", "C.SH"],
            "rank_prediction": [0.8, 0.9, 1.0],
            "net_ret": [1.0, 2.0, 100.0],
        }
    )

    result = select_daily_top1(trades)

    assert result["ts_code"].tolist() == ["A.SH"]
    assert result["trade_date"].str[:4].max() == "2024"
