import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.flow_breadth_factor_research import (
    add_industry_breadth,
    compute_stock_flow_features,
)


def test_flow_features_use_only_current_and_past_rows():
    frame = pd.DataFrame(
        {
            "ts_code": ["A"] * 6,
            "trade_date": [f"2025010{day}" for day in range(1, 7)],
            "amount": [100.0] * 6,
            "net_mf_amount": [1.0, 2.0, -1.0, 3.0, 4.0, 1000.0],
        }
    )
    first = compute_stock_flow_features(frame.iloc[:5]).iloc[-1]
    with_future = compute_stock_flow_features(frame).iloc[4]
    assert first["mf_5_ratio"] == with_future["mf_5_ratio"]
    assert first["mf_positive_days_5"] == 4.0
    assert first["mf_1_ratio"] == 0.4


def test_amount_acceleration_compares_five_and_twenty_day_means():
    frame = pd.DataFrame(
        {
            "ts_code": ["A"] * 20,
            "trade_date": [f"202501{day:02d}" for day in range(1, 21)],
            "amount": [100.0] * 15 + [200.0] * 5,
            "net_mf_amount": [0.0] * 20,
        }
    )
    result = compute_stock_flow_features(frame).iloc[-1]
    assert round(result["amount_accel_5_20"], 4) == 1.6


def test_industry_breadth_is_computed_within_date_and_industry():
    frame = pd.DataFrame(
        {
            "trade_date": ["20250102"] * 4,
            "industry": ["电子", "电子", "银行", "银行"],
            "pct_chg": [2.0, -1.0, 1.0, 2.0],
            "synthetic_close": [2.0, 1.0, 2.0, 1.0],
            "ma_20": [1.0, 2.0, 1.0, 2.0],
            "mf_1_ratio": [0.1, -0.2, 0.3, 0.4],
            "amount_accel_5_20": [2.0, 1.0, 1.5, 0.5],
        }
    )
    result = add_industry_breadth(frame)
    electronic = result[result["industry"].eq("电子")].iloc[0]
    bank = result[result["industry"].eq("银行")].iloc[0]
    assert electronic["industry_up_ratio"] == 0.5
    assert electronic["industry_above_ma20_ratio"] == 0.5
    assert electronic["industry_flow_positive_ratio"] == 0.5
    assert bank["industry_up_ratio"] == 1.0
    assert bank["industry_flow_positive_ratio"] == 1.0

