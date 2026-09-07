import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.opportunity_exit_attribution import (
    adaptive_exit_parameters,
    choose_training_exit,
    simulate_fixed_holding,
)


def _bars():
    return pd.DataFrame(
        {
            "trade_date": [f"202501{day:02d}" for day in range(3, 11)],
            "open": [100.0] * 8,
            "high": [102.0] * 8,
            "low": [98.0] * 8,
            "close": [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0],
        }
    )


def test_fixed_holding_uses_requested_close_and_cost():
    result = simulate_fixed_holding(100.0, _bars(), hold_days=5, total_cost_pct=0.30)
    assert result["exit_price"] == 105.0
    assert result["hold_days"] == 5
    assert result["gross_ret_pct"] == 5.0
    assert result["net_ret_pct"] == 4.7
    assert result["exit_reason"] == "fixed_5d"


def test_adaptive_parameters_scale_without_grid_search():
    params = adaptive_exit_parameters(8.0)
    assert params == {
        "stop_loss_pct": 12.0,
        "take_profit_pct": 24.0,
        "trailing_activate_pct": 6.0,
        "trailing_drawdown_pct": 12.0,
        "max_hold_days": 8,
    }


def test_exit_choice_uses_training_rows_only():
    metrics = pd.DataFrame(
        [
            {"profile_id": "p", "exit_id": "fixed_5d", "split": "train", "avg_net_ret_pct": 1.0, "profit_factor": 1.2},
            {"profile_id": "p", "exit_id": "adaptive", "split": "train", "avg_net_ret_pct": 0.5, "profit_factor": 1.5},
            {"profile_id": "p", "exit_id": "fixed_5d", "split": "observed", "avg_net_ret_pct": -9.0, "profit_factor": 0.1},
            {"profile_id": "p", "exit_id": "adaptive", "split": "observed", "avg_net_ret_pct": 20.0, "profit_factor": 4.0},
        ]
    )
    chosen = choose_training_exit(metrics)
    assert set(chosen["exit_id"]) == {"fixed_5d"}

