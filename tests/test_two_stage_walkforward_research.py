from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.two_stage_walkforward_research import (  # noqa: E402
    FEATURE_COLUMNS,
    add_cross_sectional_features,
    fit_ridge,
    finalize_broad_market_features,
    make_market_features,
    predict_ridge,
    select_by_gate,
)


def test_future_columns_are_not_features() -> None:
    forbidden = {"ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d"}
    assert forbidden.isdisjoint(FEATURE_COLUMNS)


def test_cross_sectional_features_are_bounded() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101"] * 3,
            "ret_20": [1.0, 2.0, 3.0],
            "turnover_rate": [3.0, 2.0, 1.0],
        }
    )
    result = add_cross_sectional_features(frame, ["ret_20", "turnover_rate"])
    assert result[["rank_ret_20", "rank_turnover_rate"]].min().min() >= 0
    assert result[["rank_ret_20", "rank_turnover_rate"]].max().max() <= 1


def test_ridge_round_trip() -> None:
    x = np.array([[0.0], [1.0], [2.0], [3.0]])
    y = np.array([1.0, 3.0, 5.0, 7.0])
    model = fit_ridge(x, y, ridge=0.01)
    predicted = predict_ridge(x, model)
    assert np.corrcoef(predicted, y)[0, 1] > 0.99


def test_market_features_use_signal_day_columns() -> None:
    rows = pd.DataFrame(
        {
            "trade_date": ["20200101", "20200101", "20200102"],
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "regime": ["BULL_TREND", "BULL_TREND", "BEAR_TREND"],
            "engine": ["reversal", "pullback", "breakout"],
            "ret_5": [0.5, 1.5, -1.0],
            "ret_20": [1.0, 3.0, -2.0],
            "rsi_14": [40.0, 60.0, 30.0],
            "pct_chg": [1.0, -1.0, 2.0],
            "volume_ratio": [1.0, 2.0, 1.5],
        }
    )
    result = make_market_features(rows)
    first = result.loc[result["trade_date"].eq("20200101")].iloc[0]
    assert first["candidate_count"] == 2
    assert first["reversal_share"] == 0.5
    assert first["median_ret_20"] == 2.0


def test_gate_selection_only_keeps_dates_above_threshold() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20200101", "20200102"],
            "gate_prediction": [-0.1, 0.2],
        }
    )
    result = select_by_gate(trades, threshold=0.0)
    assert result["trade_date"].tolist() == ["20200102"]


def test_broad_market_rolling_features_only_use_past_rows() -> None:
    rows = pd.DataFrame(
        {
            "trade_date": [f"2020010{day}" for day in range(1, 7)],
            "csi_close": [100.0, 101.0, 102.0, 103.0, 104.0, 200.0],
            "csi_pct_chg": [0.0, 1.0, 1.0, 1.0, 1.0, 92.0],
            "total_amount": [10.0, 10.0, 10.0, 10.0, 10.0, 1000.0],
        }
    )
    first = finalize_broad_market_features(rows.iloc[:5])
    with_future = finalize_broad_market_features(rows)
    assert first.iloc[-1]["csi_ma20_gap"] == with_future.iloc[4]["csi_ma20_gap"]
    assert first.iloc[-1]["amount_ratio_5"] == with_future.iloc[4]["amount_ratio_5"]
