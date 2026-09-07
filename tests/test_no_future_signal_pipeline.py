from pathlib import Path
import sys

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.no_future_signal_pipeline import (  # noqa: E402
    apply_next_open_execution,
    assert_no_future_features,
    lock_daily_topn,
    signal_eligible_mask,
)


def test_future_fields_are_rejected_as_features():
    with pytest.raises(ValueError):
        assert_no_future_features(["ret_20", "entry_gap_pct"])
    assert_no_future_features(["ret_5", "ret_20", "roe"])


def test_signal_eligibility_does_not_change_with_next_open():
    panel = pd.DataFrame(
        [{"name": "样本", "history_count": 200, "turnover_rate": 2.0, "close": 10.0, "entry_open": 11.0, "entry_gap_pct": 10.0}]
    )
    first = signal_eligible_mask(panel)
    panel.loc[0, "entry_open"] = 0.0
    panel.loc[0, "entry_gap_pct"] = -20.0
    second = signal_eligible_mask(panel)
    assert first.tolist() == second.tolist() == [True]


def test_unfilled_top_candidate_does_not_promote_third_place():
    frame = pd.DataFrame(
        [
            {"trade_date": "20260105", "ts_code": "000001.SZ", "score": 3.0, "entry_open": 11.0, "entry_gap_pct": 10.0, "ret_5d": 5.0},
            {"trade_date": "20260105", "ts_code": "000002.SZ", "score": 2.0, "entry_open": 10.0, "entry_gap_pct": 1.0, "ret_5d": 2.0},
            {"trade_date": "20260105", "ts_code": "000003.SZ", "score": 1.0, "entry_open": 10.0, "entry_gap_pct": 1.0, "ret_5d": 9.0},
        ]
    )
    locked = lock_daily_topn(frame, "score", topn=2)
    executed = apply_next_open_execution(locked)
    assert locked["ts_code"].tolist() == ["000001.SZ", "000002.SZ"]
    assert executed[executed["executed"]]["ts_code"].tolist() == ["000002.SZ"]
    assert "000003.SZ" not in executed["ts_code"].tolist()


def test_execution_can_use_frozen_horizon_without_changing_ranks():
    frame = pd.DataFrame(
        [{"trade_date": "20260105", "ts_code": "000001.SZ", "score": 1.0, "entry_open": 10.0, "entry_gap_pct": 1.0, "ret_3d": 3.0}]
    )
    locked = lock_daily_topn(frame, "score", topn=1)
    executed = apply_next_open_execution(locked, outcome_column="ret_3d")
    assert float(executed.iloc[0]["net_ret"]) == 2.75
