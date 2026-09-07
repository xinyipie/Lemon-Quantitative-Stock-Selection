import pandas as pd

from research.quality_momentum_reentry_margin_v3_holdout_2025 import (
    HOLDOUT_YEAR,
    MINIMUM_PREDICTION_MARGIN,
    select_holdout_v3,
    verify_frozen_hashes,
)


def test_frozen_hashes_match_before_holdout() -> None:
    verify_frozen_hashes()


def test_holdout_selection_uses_only_2025_and_frozen_margin() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20250102", "20250102"],
            "ts_code": ["A.SH", "B.SZ", "C.SH", "D.SZ"],
            "rank_prediction": [1.0, 0.0, 0.80, 0.77],
            "net_ret": [100.0, 100.0, 1.0, 2.0],
        }
    )

    result = select_holdout_v3(trades)

    assert HOLDOUT_YEAR == 2025
    assert MINIMUM_PREDICTION_MARGIN == 0.02
    assert result["ts_code"].tolist() == ["C.SH"]


def test_holdout_selection_returns_empty_when_gate_emits_no_2025_trade() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102"],
            "ts_code": ["A.SH", "B.SZ"],
            "rank_prediction": [1.0, 0.0],
            "net_ret": [1.0, 2.0],
        }
    )

    result = select_holdout_v3(trades)

    assert result.empty
    assert "prediction_margin" in result.columns


def test_holdout_selection_skips_day_without_second_candidate() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20250102"],
            "ts_code": ["A.SH"],
            "rank_prediction": [1.0],
            "net_ret": [1.0],
        }
    )

    assert select_holdout_v3(trades).empty
