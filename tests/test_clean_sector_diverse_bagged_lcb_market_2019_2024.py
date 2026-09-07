import pandas as pd

from research.clean_sector_diverse_bagged_lcb_market_2019_2024 import (
    execute_daily_sector_diverse_top3,
    lock_daily_sector_diverse_top3,
)


def _predictions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"trade_date": "20240102", "ts_code": "A", "industry": "电子", "prediction": 9.0, "entry_open": 10.0, "entry_gap_pct": 0.0, "ret_5d": 3.0},
            {"trade_date": "20240102", "ts_code": "B", "industry": "电子", "prediction": 8.0, "entry_open": 10.0, "entry_gap_pct": 0.0, "ret_5d": 4.0},
            {"trade_date": "20240102", "ts_code": "C", "industry": "通信", "prediction": 7.0, "entry_open": 10.0, "entry_gap_pct": 0.0, "ret_5d": 5.0},
            {"trade_date": "20240102", "ts_code": "D", "industry": "机械", "prediction": 6.0, "entry_open": None, "entry_gap_pct": 0.0, "ret_5d": 6.0},
            {"trade_date": "20240102", "ts_code": "E", "industry": "汽车", "prediction": 5.0, "entry_open": 10.0, "entry_gap_pct": 0.0, "ret_5d": 7.0},
        ]
    )


def test_lock_daily_sector_diverse_top3_uses_distinct_industries() -> None:
    locked = lock_daily_sector_diverse_top3(_predictions())

    assert locked["ts_code"].tolist() == ["A", "C", "D"]
    assert locked["industry"].nunique() == 3


def test_execution_does_not_replace_failed_locked_stock() -> None:
    executed = execute_daily_sector_diverse_top3(_predictions())

    assert executed["ts_code"].tolist() == ["A", "C"]
    assert "E" not in executed["ts_code"].tolist()
