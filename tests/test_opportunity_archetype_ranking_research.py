import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.opportunity_archetype_ranking_research import (
    choose_train_directions,
    select_ranked_candidates,
    summarize_rankings,
)


PROFILE = [
    {
        "profile_id": "test_profile",
        "description": "测试画像",
        "conditions": [("volatility_20_bin", "6.5~9")],
    }
]


def _panel():
    return pd.DataFrame(
        {
            "trade_date": ["20250102"] * 4,
            "ts_code": ["A", "B", "C", "D"],
            "name": ["甲", "乙", "丙", "丁"],
            "history_count": [100] * 4,
            "turnover_rate": [5.0] * 4,
            "amount": [10.0, 40.0, 30.0, 20.0],
            "ret_20": [1.0, 2.0, 3.0, 4.0],
            "entry_open": [10.0] * 4,
            "entry_gap_pct": [0.0] * 4,
            "ret_3d": [1.0, 2.0, 3.0, 4.0],
            "ret_5d": [100.0, -100.0, 50.0, -50.0],
            "ret_8d": [1.0, 2.0, 3.0, 4.0],
            "mfe_8d": [2.0] * 4,
            "mae_8d": [-2.0] * 4,
            "volatility_20_bin": ["6.5~9"] * 4,
        }
    )


def test_rank_selection_uses_signal_factor_not_future_return():
    specs = [{"factor": "amount", "column": "amount", "directions": ["high"]}]
    first = select_ranked_candidates(_panel(), PROFILE, specs, top_n=2)
    changed = _panel()
    changed["ret_5d"] *= -1000
    second = select_ranked_candidates(changed, PROFILE, specs, top_n=2)
    assert first["ts_code"].tolist() == ["B", "C"]
    assert second["ts_code"].tolist() == ["B", "C"]


def test_low_direction_selects_smallest_signal_values():
    specs = [{"factor": "ret_20", "column": "ret_20", "directions": ["low"]}]
    result = select_ranked_candidates(_panel(), PROFILE, specs, top_n=2)
    assert result["ts_code"].tolist() == ["A", "B"]


def test_summary_deducts_cost_from_fixed_holding_return():
    selected = _panel().iloc[:2].copy()
    selected["profile_id"] = "test_profile"
    selected["profile_description"] = "测试画像"
    selected["rank_factor"] = "amount"
    selected["rank_direction"] = "high"
    selected["rank_id"] = "amount_high"
    selected["split"] = "sealed"
    selected["year"] = "2025"
    result = summarize_rankings(selected, total_cost_pct=0.30)
    assert result.iloc[0]["avg_net_5d_pct"] == -0.3
    assert result.iloc[0]["win_rate_5d"] == 0.5


def test_direction_choice_uses_train_rows_only():
    metrics = pd.DataFrame(
        [
            {"profile_id": "p", "rank_factor": "ret_20", "rank_direction": "high", "rank_id": "ret_20_high", "split": "train", "avg_net_5d_pct": 1.0, "profit_factor_5d": 1.2},
            {"profile_id": "p", "rank_factor": "ret_20", "rank_direction": "low", "rank_id": "ret_20_low", "split": "train", "avg_net_5d_pct": -1.0, "profit_factor_5d": 0.8},
            {"profile_id": "p", "rank_factor": "ret_20", "rank_direction": "high", "rank_id": "ret_20_high", "split": "sealed", "avg_net_5d_pct": -5.0, "profit_factor_5d": 0.2},
            {"profile_id": "p", "rank_factor": "ret_20", "rank_direction": "low", "rank_id": "ret_20_low", "split": "sealed", "avg_net_5d_pct": 9.0, "profit_factor_5d": 3.0},
        ]
    )
    chosen = choose_train_directions(metrics)
    assert set(chosen["rank_id"]) == {"ret_20_high"}

