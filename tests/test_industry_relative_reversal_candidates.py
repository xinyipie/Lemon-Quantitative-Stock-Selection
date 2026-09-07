import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.industry_relative_reversal_candidates import (  # noqa: E402
    FORBIDDEN_COLUMNS,
    SCORE_COLUMNS,
    build_candidates,
)


def _row(index: int, industry: str) -> dict:
    return {
        "trade_date": "20200102",
        "ts_code": f"{index:06d}.SZ",
        "industry": industry,
        "tradeable": True,
        "history_count": 200,
        "pct_chg": 0.0,
        "turnover_rate": 2.0 + index / 100,
        "volume_ratio": 0.8,
        "entry_gap_pct": 0.0,
        "drawdown_20": 5.0 + index / 10,
        "ret_5": -float(index) / 10,
        "ret_10": -float(index) / 8,
        "ret_20": -float(index) / 6,
        "ret_60": 5.0,
        "rsi_14": 40.0,
        "volatility_20": 2.0,
        "industry_rs_20": 3.0 if industry == "电子" else 1.0,
    }


def test_score_has_no_future_inputs() -> None:
    assert FORBIDDEN_COLUMNS.isdisjoint(SCORE_COLUMNS)


def test_candidates_are_capped_by_industry_and_day() -> None:
    frame = pd.DataFrame([_row(i, "电子" if i < 10 else "银行") for i in range(20)])
    result = build_candidates(frame, topn=60, per_industry=2)
    assert result.groupby(["trade_date", "industry_bucket"]).size().max() == 2
    assert len(result) == 4

