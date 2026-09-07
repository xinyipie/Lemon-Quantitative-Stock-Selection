import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.quality_momentum_reentry import FORBIDDEN_COLUMNS, SCORE_COLUMNS, build_candidates  # noqa: E402


def test_quality_momentum_score_has_no_future_inputs() -> None:
    assert FORBIDDEN_COLUMNS.isdisjoint(SCORE_COLUMNS)


def test_quality_momentum_candidates_are_capped() -> None:
    rows = []
    for index in range(80):
        rows.append(
            {
                "trade_date": "20200102",
                "ts_code": f"{index:06d}.SZ",
                "tradeable": True,
                "history_count": 200,
                "pct_chg": 1.0,
                "turnover_rate": 2.0,
                "volume_ratio": 1.0,
                "entry_gap_pct": 0.0,
                "ret_60": 20.0 + index / 10,
                "ret_20": 5.0 + index / 20,
                "drawdown_20": 5.0,
                "rsi_14": 60.0,
                "industry_rs_20": 5.0,
                "ma_20": 12.0,
                "ma_60": 10.0,
                "close": 12.0,
                "volatility_20": 2.0,
            }
        )
    result = build_candidates(pd.DataFrame(rows), topn=60)
    assert len(result) == 60

