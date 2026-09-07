from pathlib import Path
import sys

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.clean_momentum_exit_family import ExitRule, simulate_exit  # noqa: E402


def test_stop_is_causal_and_checked_before_same_day_target():
    path = pd.DataFrame(
        [
            {"open": 100.0, "high": 111.0, "low": 94.0, "close": 105.0},
            {"open": 105.0, "high": 108.0, "low": 103.0, "close": 107.0},
        ]
    )
    result = simulate_exit(path, ExitRule("test", max_days=2, stop_pct=5.0, take_pct=10.0))
    assert result["exit_reason"] == "stop"
    assert result["gross_ret"] == pytest.approx(-5.0)


def test_trailing_uses_prior_peak_not_same_day_high():
    path = pd.DataFrame(
        [
            {"open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0},
            {"open": 104.0, "high": 110.0, "low": 100.0, "close": 109.0},
        ]
    )
    result = simulate_exit(path, ExitRule("test", max_days=2, stop_pct=10.0, trail_activate_pct=4.0, trail_pct=4.0))
    assert result["exit_reason"] == "trailing"
    assert round(result["gross_ret"], 2) == 0.80
