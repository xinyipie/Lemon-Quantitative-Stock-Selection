from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.walkforward_linear_ranker import (
    FEATURE_COLUMNS,
    FUTURE_COLUMNS,
    add_cross_sectional_features,
    fit_weighted_ridge,
    metric_summary,
    phase_for_date,
    select_predictions,
)


def test_feature_columns_exclude_future_outcomes() -> None:
    assert not set(FEATURE_COLUMNS) & set(FUTURE_COLUMNS)
    assert all(not name.startswith(("ret_3d", "ret_5d", "ret_8d", "mfe_", "mae_")) for name in FEATURE_COLUMNS)


def test_phase_boundaries_are_fixed() -> None:
    assert phase_for_date("20211231") == "train"
    assert phase_for_date("20220104") == "validation"
    assert phase_for_date("20250102") == "recent"


def test_cross_sectional_features_use_same_day_ranks() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20200102", "20200102", "20200103"],
            "pct_chg": [1.0, 3.0, 100.0],
        }
    )
    result, columns = add_cross_sectional_features(frame, numeric_columns=["pct_chg"])
    assert columns == ["rank_pct_chg"]
    assert result.loc[0, "rank_pct_chg"] == 0.5
    assert result.loc[1, "rank_pct_chg"] == 1.0
    assert result.loc[2, "rank_pct_chg"] == 1.0


def test_weighted_ridge_learns_positive_direction() -> None:
    x = np.array([[0.0], [1.0], [2.0], [3.0]])
    y = np.array([0.0, 1.0, 2.0, 3.0])
    dates = pd.Series(["a", "a", "b", "b"])
    beta = fit_weighted_ridge(x, y, dates, ridge_lambda=0.01)
    assert beta[1] > 0.9


def test_selection_applies_threshold_and_topn() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20200102"] * 3 + ["20200103"] * 2,
            "ts_code": ["a", "b", "c", "d", "e"],
            "prediction": [0.9, 0.8, 0.1, 0.4, 0.3],
        }
    )
    selected = select_predictions(frame, topn=2, threshold=0.35)
    assert selected["ts_code"].tolist() == ["a", "b", "d"]


def test_metrics_deduct_round_trip_cost() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20220104", "20220105"],
            "ret_5d": [1.0, -0.5],
        }
    )
    metrics = metric_summary(frame, cost_pct=0.25)
    assert metrics["trades"] == 2
    assert metrics["avg_net_pct"] == 0.0
    assert metrics["win_rate_pct"] == 50.0
