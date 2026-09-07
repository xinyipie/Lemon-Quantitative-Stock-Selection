import pandas as pd

from research.quality_momentum_rolling3y_v14_2019_2026 import select_margin_top1


def test_margin_selector_is_year_agnostic_and_requires_strict_margin() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20250102", "20250102", "20260102", "20260102"],
            "ts_code": ["A", "B", "C", "D"],
            "rank_prediction": [0.60, 0.57, 0.60, 0.581],
        }
    )
    result = select_margin_top1(frame)
    assert result["ts_code"].tolist() == ["A"]
