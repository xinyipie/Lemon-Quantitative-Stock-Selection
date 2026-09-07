import pandas as pd

from research.quality_momentum_dual_window_consensus_v15_2019_2026 import build_consensus


def test_consensus_requires_same_stock_and_an_open_market_gate() -> None:
    expanding = pd.DataFrame(
        {"trade_date": ["20260101", "20260102"], "ts_code": ["A", "B"], "ret_5d": [1, 2]}
    )
    rolling = pd.DataFrame(
        {"trade_date": ["20260101", "20260102"], "ts_code": ["A", "C"]}
    )
    result = build_consensus(expanding, rolling, {"20260101"})
    assert result["ts_code"].tolist() == ["A"]
