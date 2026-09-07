import pandas as pd

from research.quality_momentum_direct_top2_2019_2024 import select_daily_top2


def test_select_daily_top2_is_deterministic_and_seals_2025() -> None:
    candidates = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20240102", "20250102"],
            "ts_code": ["B.SZ", "A.SH", "C.SH", "D.SH"],
            "quality_momentum_score": [9.0, 9.0, 8.0, 100.0],
            "ret_5d": [1.0, 2.0, 3.0, 100.0],
        }
    )

    result = select_daily_top2(candidates, cost=0.25)

    assert result["ts_code"].tolist() == ["A.SH", "B.SZ"]
    assert result["test_year"].max() == 2024
