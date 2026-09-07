import pandas as pd

from research.clean_walkforward_technical_hgb import RAW_COLUMNS
from research.clean_walkforward_excess_bagged_lcb_3d_2019_2024 import (
    EXCESS_TARGET_3D,
    add_3d_excess_target,
    execute_daily_top3_3d,
)


def test_shared_research_loader_exposes_existing_three_day_label() -> None:
    assert "ret_3d" in RAW_COLUMNS


def test_add_3d_excess_target_is_cross_sectionally_centered() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20240103"],
            "ret_3d": [1.0, 3.0, 4.0],
        }
    )

    result = add_3d_excess_target(frame)

    assert result[EXCESS_TARGET_3D].tolist() == [-1.0, 1.0, 0.0]


def test_execute_daily_top3_3d_uses_three_day_return_and_no_replacement() -> None:
    predictions = pd.DataFrame(
        [
            {"trade_date": "20240102", "ts_code": "A", "prediction": 4.0, "entry_open": 10.0, "entry_gap_pct": 0.0, "ret_3d": 2.0, "ret_3d_excess": 1.0},
            {"trade_date": "20240102", "ts_code": "B", "prediction": 3.0, "entry_open": None, "entry_gap_pct": 0.0, "ret_3d": 3.0, "ret_3d_excess": 2.0},
            {"trade_date": "20240102", "ts_code": "C", "prediction": 2.0, "entry_open": 10.0, "entry_gap_pct": 0.0, "ret_3d": 4.0, "ret_3d_excess": 3.0},
            {"trade_date": "20240102", "ts_code": "D", "prediction": 1.0, "entry_open": 10.0, "entry_gap_pct": 0.0, "ret_3d": 5.0, "ret_3d_excess": 4.0},
        ]
    )

    result = execute_daily_top3_3d(predictions)

    assert result["ts_code"].tolist() == ["A", "C"]
    assert "D" not in result["ts_code"].tolist()
    assert result.iloc[0]["net_return"] < result.iloc[0]["ret_3d"]
