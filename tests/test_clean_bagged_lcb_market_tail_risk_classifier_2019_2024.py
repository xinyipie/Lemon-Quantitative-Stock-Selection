import pandas as pd

from research.clean_bagged_lcb_market_tail_risk_classifier_2019_2024 import (
    TAIL_RISK_RETURN_PCT,
    apply_market_tail_risk_veto,
)


def test_tail_risk_boundary_is_frozen_at_two_percent_loss() -> None:
    assert TAIL_RISK_RETURN_PCT == -2.0


def test_tail_risk_veto_keeps_only_non_vetoed_days() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103"],
            "ts_code": ["A", "B"],
        }
    )
    market = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103"],
            "market_tail_risk_probability": [0.49, 0.51],
            "market_tail_risk_veto": [False, True],
        }
    )

    result = apply_market_tail_risk_veto(trades, market)

    assert result["ts_code"].tolist() == ["A"]
