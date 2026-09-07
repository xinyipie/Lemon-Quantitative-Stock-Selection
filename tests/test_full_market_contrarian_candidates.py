from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.full_market_contrarian_candidates import (  # noqa: E402
    FORBIDDEN_COLUMNS,
    SCORE_COLUMNS,
    build_candidates,
)


def test_contrarian_score_has_no_future_inputs() -> None:
    assert FORBIDDEN_COLUMNS.isdisjoint(SCORE_COLUMNS)


def test_candidates_are_capped_per_day() -> None:
    rows = []
    for index in range(80):
        rows.append(
            {
                "trade_date": "20200102",
                "ts_code": f"{index:06d}.SZ",
                "tradeable": True,
                "history_count": 100,
                "pct_chg": 1.0,
                "turnover_rate": 2.0 + index / 100,
                "volume_ratio": 1.0,
                "entry_gap_pct": 0.0,
                "drawdown_20": float(index),
                "ret_5": -float(index),
                "ret_10": -float(index),
                "ret_20": -float(index),
                "ret_60": -float(index),
                "rsi_14": 50.0,
                "volatility_20": 2.0,
                "industry_rs_20": 0.0,
            }
        )
    result = build_candidates(pd.DataFrame(rows), topn=50)
    assert len(result) == 50
    assert result["ts_code"].is_unique
