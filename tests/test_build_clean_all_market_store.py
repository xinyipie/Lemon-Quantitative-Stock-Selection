from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.build_clean_all_market_store import clean_panel  # noqa: E402


def test_clean_store_eligibility_is_independent_of_future_open():
    base = {
        "ts_code": "000001.SZ", "name": "样本", "industry": "银行", "trade_date": "20260105",
        "open": 10, "high": 11, "low": 9, "close": 10, "pct_chg": 0, "amount": 100,
        "history_count": 200, "turnover_rate": 2.0, "volume_ratio": 1.0,
        "entry_open": 0.0, "entry_gap_pct": 20.0,
    }
    first = clean_panel(pd.DataFrame([base]))
    base["entry_open"] = 10.0
    base["entry_gap_pct"] = 1.0
    second = clean_panel(pd.DataFrame([base]))
    assert first["ts_code"].tolist() == second["ts_code"].tolist() == ["000001.SZ"]


def test_clean_store_preserves_adjusted_price_scale():
    row = {
        "ts_code": "000001.SZ", "name": "样本", "industry": "银行", "trade_date": "20260105",
        "open": 10, "high": 11, "low": 9, "close": 10, "synthetic_close": 1.25,
        "pct_chg": 0, "amount": 100, "history_count": 200,
        "turnover_rate": 2.0, "volume_ratio": 1.0,
    }
    result = clean_panel(pd.DataFrame([row]))
    assert result["synthetic_close"].iloc[0] == 1.25
