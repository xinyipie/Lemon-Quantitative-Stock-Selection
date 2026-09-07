from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.high_confidence_abstention_audit import (  # noqa: E402
    concentration_metrics,
    non_overlapping_sleeves,
)


def test_non_overlapping_sleeves_partition_dates() -> None:
    days = pd.DataFrame(
        {
            "trade_date": [f"202001{day:02d}" for day in range(1, 11)],
            "net_ret": range(10),
        }
    )
    sleeves = non_overlapping_sleeves(days, spacing=5)
    assert len(sleeves) == 5
    assert sum(len(frame) for frame in sleeves.values()) == len(days)
    assert all(len(frame) == 2 for frame in sleeves.values())


def test_concentration_metrics_detect_single_name() -> None:
    trades = pd.DataFrame(
        {
            "ts_code": ["A", "A", "B"],
            "industry": ["X", "X", "Y"],
            "net_ret": [3.0, 2.0, -1.0],
        }
    )
    result = concentration_metrics(trades)
    assert result["largest_stock_positive_share"] == 1.0
    assert result["largest_industry_positive_share"] == 1.0
