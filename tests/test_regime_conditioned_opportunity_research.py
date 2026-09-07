import sys
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.regime_conditioned_opportunity_research import (
    apply_validation_gate,
    choose_training_directions,
    normalize_regime,
    regime_holding_days,
    summarize_regime_rankings,
)


def test_script_can_be_started_directly_from_project_root():
    script = ROOT / "research" / "regime_conditioned_opportunity_research.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_regime_policy_is_fixed_and_bear_trend_is_disabled():
    regimes = normalize_regime(pd.Series(["BULL_TREND", "BULL_PULLBACK", "BEAR_BOUNCE", "OTHER", None]))
    assert regimes.tolist() == ["BULL_TREND", "BULL_PULLBACK", "BEAR_BOUNCE", "UNKNOWN", "UNKNOWN"]
    assert regime_holding_days("BULL_TREND") == 8
    assert regime_holding_days("BULL_PULLBACK") == 5
    assert regime_holding_days("BEAR_BOUNCE") == 3
    assert regime_holding_days("BEAR_TREND") is None


def test_summary_uses_only_the_horizon_fixed_for_each_regime():
    selected = pd.DataFrame(
        {
            "profile_id": ["p", "p"],
            "profile_description": ["画像", "画像"],
            "rank_factor": ["f", "f"],
            "rank_label": ["因子", "因子"],
            "rank_direction": ["high", "high"],
            "rank_id": ["f_high", "f_high"],
            "top_n": [3, 3],
            "split": ["train", "train"],
            "year": [2020, 2020],
            "regime": ["BULL_TREND", "BEAR_BOUNCE"],
            "trade_date": ["20200102", "20200103"],
            "ret_3d": [9.0, 3.0],
            "ret_5d": [8.0, 2.0],
            "ret_8d": [7.0, 1.0],
        }
    )
    metrics = summarize_regime_rankings(selected, cost_pct=0.30)
    bull = metrics[metrics["regime"].eq("BULL_TREND")].iloc[0]
    bounce = metrics[metrics["regime"].eq("BEAR_BOUNCE")].iloc[0]
    assert bull["holding_days"] == 8
    assert bull["avg_net_pct"] == 6.7
    assert bounce["holding_days"] == 3
    assert bounce["avg_net_pct"] == 2.7


def test_training_choice_cannot_be_changed_by_validation_performance():
    rows = []
    for split, high_avg, low_avg in [("train", 0.8, 0.2), ("validation", -2.0, 3.0)]:
        for direction, average in [("high", high_avg), ("low", low_avg)]:
            rows.append(
                {
                    "profile_id": "p",
                    "profile_description": "画像",
                    "regime": "BULL_TREND",
                    "rank_factor": "f",
                    "rank_label": "因子",
                    "rank_direction": direction,
                    "rank_id": f"f_{direction}",
                    "top_n": 3,
                    "split": split,
                    "holding_days": 8,
                    "trades": 200,
                    "active_days": 100,
                    "avg_net_pct": average,
                    "profit_factor": 1.2,
                    "positive_year_ratio": 1.0,
                    "worst_year_avg_pct": average,
                }
            )
    chosen = choose_training_directions(pd.DataFrame(rows))
    assert set(chosen["rank_direction"]) == {"high"}
    validation = chosen[chosen["split"].eq("validation")].iloc[0]
    assert validation["avg_net_pct"] == -2.0


def test_validation_gate_requires_absolute_and_baseline_improvement_thresholds():
    chosen = pd.DataFrame(
        {
            "split": ["validation", "validation"],
            "trades": [200, 200],
            "active_days": [100, 100],
            "avg_net_pct": [0.55, 0.55],
            "profit_factor": [1.20, 1.20],
            "positive_year_ratio": [0.67, 0.67],
            "worst_year_avg_pct": [-0.20, -0.20],
            "baseline_avg_net_pct": [0.30, 0.45],
            "train_avg_net_pct": [0.20, 0.20],
            "train_profit_factor": [1.08, 1.08],
            "train_positive_year_ratio": [0.67, 0.67],
            "train_worst_year_avg_pct": [-0.30, -0.30],
        }
    )
    gated = apply_validation_gate(chosen)
    assert gated["research_pass"].tolist() == [True, False]


def test_validation_cannot_pass_when_training_edge_is_negative():
    chosen = pd.DataFrame(
        {
            "split": ["validation"],
            "trades": [300],
            "active_days": [120],
            "avg_net_pct": [1.50],
            "profit_factor": [1.40],
            "positive_year_ratio": [1.0],
            "worst_year_avg_pct": [0.20],
            "baseline_avg_net_pct": [0.0],
            "train_avg_net_pct": [-0.10],
            "train_profit_factor": [0.95],
            "train_positive_year_ratio": [0.33],
            "train_worst_year_avg_pct": [-0.80],
        }
    )
    gated = apply_validation_gate(chosen)
    assert gated.loc[0, "research_pass"] == False
