import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.archived_momentum_reconstruction import (
    archive_momentum_eligibility,
    select_archive_momentum_candidates,
)


def _guangxun_like(volume_ratio: float = 1.31) -> dict:
    return {
        "trade_date": "20260422",
        "year": 2026,
        "split": "observed",
        "regime": "BULL_TREND",
        "ts_code": "002281.SZ",
        "name": "光迅科技",
        "industry": "通信设备",
        "synthetic_close": 124.0,
        "ma_20": 110.0,
        "ma_60": 95.0,
        "pct_chg": 1.79,
        "ret_5": 16.19,
        "ret_20": 55.21,
        "drawdown_20": 1.30,
        "volume_ratio": volume_ratio,
        "turnover_rate": 10.18,
        "amount": 9791456.8,
        "industry_rs_20": 43.37,
        "mf_3_ratio": 0.09,
        "industry_amount_accel": 1.5,
        "history_count": 100,
        "tradeable": True,
        "entry_open": 124.85,
        "entry_gap_pct": 0.71,
        "ret_3d": 7.75,
        "ret_5d": 6.42,
        "ret_8d": 10.0,
    }


def test_report_reconciled_variant_captures_original_case_but_strict_does_not():
    panel = pd.DataFrame([_guangxun_like()])
    assert archive_momentum_eligibility(panel, min_volume_ratio=1.2).iloc[0]
    assert not archive_momentum_eligibility(panel, min_volume_ratio=1.5).iloc[0]


def test_bear_trend_and_broken_trend_are_rejected():
    bear = _guangxun_like(1.8)
    bear["regime"] = "BEAR_TREND"
    broken = _guangxun_like(1.8)
    broken["ts_code"] = "BROKEN"
    broken["synthetic_close"] = 90.0
    panel = pd.DataFrame([bear, broken])
    assert archive_momentum_eligibility(panel, 1.5).tolist() == [False, False]


def test_future_date_cannot_change_prior_day_selection():
    first = _guangxun_like(1.8)
    second = _guangxun_like(2.5)
    second["trade_date"] = "20260423"
    second["ts_code"] = "FUTURE"
    panel = pd.DataFrame([first, second])
    first_only = select_archive_momentum_candidates(panel.iloc[:1], top_n=1)
    with_future = select_archive_momentum_candidates(panel, top_n=1)
    earlier = with_future[with_future["trade_date"].eq("20260422")]
    assert first_only[["variant", "ts_code"]].to_dict("records") == earlier[["variant", "ts_code"]].to_dict("records")


def test_script_can_be_started_directly_from_project_root():
    script = ROOT / "research" / "archived_momentum_reconstruction.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
