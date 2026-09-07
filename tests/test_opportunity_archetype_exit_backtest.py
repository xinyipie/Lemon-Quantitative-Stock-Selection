import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.opportunity_archetype_exit_backtest import (
    FROZEN_PROFILES,
    select_profile_candidates,
    simulate_five_day_exit,
)


def _bars(rows):
    return pd.DataFrame(rows, columns=["trade_date", "open", "high", "low", "close"])


def test_fixed_stop_uses_stop_price_and_cost():
    result = simulate_five_day_exit(
        100.0,
        _bars([["20250103", 100.0, 103.0, 92.0, 95.0]]),
    )
    assert result["exit_reason"] == "fixed_stop"
    assert result["exit_price"] == 93.0
    assert result["gross_ret_pct"] == -7.0
    assert result["net_ret_pct"] == -7.3


def test_take_profit_precedes_close_exit():
    result = simulate_five_day_exit(
        100.0,
        _bars([["20250103", 100.0, 116.0, 99.0, 114.0]]),
    )
    assert result["exit_reason"] == "take_profit"
    assert result["exit_price"] == 115.0
    assert result["net_ret_pct"] == 14.7


def test_trailing_stop_activates_from_previous_peak():
    result = simulate_five_day_exit(
        100.0,
        _bars(
            [
                ["20250103", 100.0, 105.0, 100.0, 104.0],
                ["20250106", 104.0, 104.0, 96.0, 97.0],
            ]
        ),
    )
    assert result["exit_reason"] == "trailing_stop"
    assert result["hold_days"] == 2
    assert result["exit_price"] == 97.65
    assert result["net_ret_pct"] == -2.65


def test_max_hold_exits_on_fifth_close():
    bars = _bars(
        [[f"2025010{day}", 100.0, 102.0, 99.0, 101.0] for day in range(3, 8)]
    )
    result = simulate_five_day_exit(100.0, bars)
    assert result["exit_reason"] == "max_hold"
    assert result["hold_days"] == 5
    assert result["net_ret_pct"] == 0.7


def test_candidate_selection_uses_liquidity_not_future_returns():
    panel = pd.DataFrame(
        {
            "trade_date": ["20250102"] * 4,
            "ts_code": ["A", "B", "C", "D"],
            "name": ["甲", "乙", "丙", "丁"],
            "amount": [10, 40, 30, 20],
            "history_count": [100] * 4,
            "turnover_rate": [5.0] * 4,
            "ret_5d": [100, -100, 50, -50],
            "volatility_20_bin": ["6.5~9"] * 4,
            "pct_chg_bin": ["0~2%"] * 4,
            "ret_20_bin": ["0~10%"] * 4,
        }
    )
    profile = [item for item in FROZEN_PROFILES if item["profile_id"] == "volatility_6_5_9"]
    first = select_profile_candidates(panel, profile, top_n=2)
    changed = panel.copy()
    changed["ret_5d"] *= -999
    second = select_profile_candidates(changed, profile, top_n=2)
    assert first["ts_code"].tolist() == ["B", "C"]
    assert second["ts_code"].tolist() == ["B", "C"]

