import pandas as pd

from research.clean_shsz_bagged_lcb_high_conf_tail_veto_2019_2024 import (
    HIGH_CONFIDENCE_RISK_THRESHOLD,
    apply_shsz_high_confidence_tail_veto,
)


def test_high_confidence_threshold_is_frozen_at_two_thirds() -> None:
    assert HIGH_CONFIDENCE_RISK_THRESHOLD == 2.0 / 3.0


def test_gate_excludes_bj_and_only_vetoes_high_confidence_risk() -> None:
    trades = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20240103"],
            "ts_code": ["A.SH", "B.BJ", "C.SZ"],
        }
    )
    market = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240103"],
            "market_tail_risk_probability": [0.60, 0.70],
        }
    )

    result = apply_shsz_high_confidence_tail_veto(trades, market)

    assert result["ts_code"].tolist() == ["A.SH"]
