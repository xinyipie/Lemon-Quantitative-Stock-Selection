from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.full_market_event_research import (  # noqa: E402
    FORBIDDEN_SCORE_COLUMNS,
    SCORE_INPUT_COLUMNS,
    build_event_candidates,
    select_topn,
)


def _fixture() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": ["20200102"] * 4,
            "ts_code": ["A", "B", "C", "D"],
            "close": [11.0, 9.0, 12.0, 15.0],
            "ma_20": [10.5, 10.0, 11.0, 12.0],
            "ma_60": [10.0, 10.5, 10.0, 10.0],
            "prior_high_20": [12.0, 12.0, 12.1, 15.2],
            "ret_5": [-2.0, -10.0, 4.0, 12.0],
            "ret_10": [5.0, -12.0, 8.0, 18.0],
            "ret_20": [18.0, -15.0, 15.0, 45.0],
            "ret_60": [25.0, -10.0, 22.0, 70.0],
            "drawdown_20": [8.0, 18.0, 1.0, 2.0],
            "rsi_14": [55.0, 32.0, 62.0, 78.0],
            "volatility_20": [2.0, 3.0, 1.8, 2.5],
            "pct_chg": [-1.0, 2.0, 3.0, 2.0],
            "volume_ratio": [0.9, 1.4, 1.6, 1.4],
            "turnover_rate": [4.0, 5.0, 4.0, 6.0],
            "industry_rs_20": [8.0, -2.0, 12.0, 30.0],
            "entry_gap_pct": [0.0] * 4,
            "regime": ["BULL_TREND"] * 4,
            "tradeable": [True] * 4,
            "ret_3d": [99.0] * 4,
            "ret_5d": [99.0] * 4,
            "ret_8d": [99.0] * 4,
            "mfe_8d": [99.0] * 4,
            "mae_8d": [-99.0] * 4,
        }
    )


def test_score_inputs_exclude_future_columns() -> None:
    assert FORBIDDEN_SCORE_COLUMNS.isdisjoint(SCORE_INPUT_COLUMNS)


def test_four_fixed_events_can_be_identified() -> None:
    result = build_event_candidates(_fixture())
    assert set(result["event"]) == {
        "trend_pullback",
        "oversold_repair",
        "quiet_breakout",
        "leader_continuation",
    }


def test_topn_is_unique_per_day_and_event() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20200102"] * 4,
            "event": ["x"] * 4,
            "ts_code": ["A", "B", "C", "D"],
            "event_score": [4.0, 3.0, 2.0, 1.0],
        }
    )
    selected = select_topn(frame, 3)
    assert selected["ts_code"].tolist() == ["A", "B", "C"]
    assert not selected.duplicated(["trade_date", "event", "ts_code"]).any()
