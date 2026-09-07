from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.volatility_contraction_breakout import (  # noqa: E402
    FORBIDDEN_COLUMNS,
    SCORE_COLUMNS,
    build_candidates,
)


def test_score_does_not_use_future_columns():
    assert SCORE_COLUMNS.isdisjoint(FORBIDDEN_COLUMNS)


def test_candidate_cap_and_contraction_filter():
    rows = []
    for day_index in range(70):
        for stock_index in range(70):
            rows.append(
                {
                    "trade_date": f"2020{day_index + 101:04d}",
                    "ts_code": f"{stock_index:06d}.SZ",
                    "tradeable": True,
                    "history_count": 200,
                    "pct_chg": 2.0,
                    "turnover_rate": 3.0,
                    "volume_ratio": 1.4,
                    "entry_gap_pct": 0.0,
                    "ret_60": 20.0 + stock_index / 10,
                    "ret_20": 8.0,
                    "drawdown_20": 1.0,
                    "rsi_14": 60.0,
                    "industry_rs_20": 5.0,
                    "ma_20": 12.0,
                    "ma_60": 10.0,
                    "close": 13.0,
                    "volatility_20": 2.0 if day_index < 50 else 1.0,
                }
            )
    result = build_candidates(pd.DataFrame(rows), topn=60)
    assert not result.empty
    assert result.groupby("trade_date").size().max() <= 60
    assert result["volatility_contraction_60"].max() <= 0.85

