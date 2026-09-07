from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.download_historical_financial_snapshots import normalize, periods  # noqa: E402


def test_periods_are_quarterly_and_bounded():
    values = periods(2024, 2025, "20250630")
    assert values == ["20240331", "20240630", "20240930", "20241231", "20250331", "20250630"]


def test_normalize_rejects_invalid_announcement_dates():
    frame = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "ann_date": "20240420", "end_date": "20240331", "roe": 9, "debt_to_assets": 60, "netprofit_yoy": 20},
            {"ts_code": "000002.SZ", "ann_date": None, "end_date": "20240331", "roe": 9, "debt_to_assets": 60, "netprofit_yoy": 20},
        ]
    )
    result = normalize(frame)
    assert result["ts_code"].tolist() == ["000001.SZ"]

