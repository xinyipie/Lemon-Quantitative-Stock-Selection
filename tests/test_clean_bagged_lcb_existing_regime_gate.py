"""既有BEAR_TREND门控语义测试。"""

import pandas as pd

from research.clean_bagged_lcb_existing_regime_gate import apply_existing_regime_gate


def test_only_existing_bear_trend_state_is_removed() -> None:
    trades = pd.DataFrame(
        {
            "regime": ["BULL_TREND", "BULL_PULLBACK", "BEAR_BOUNCE", "BEAR_TREND"],
            "ts_code": ["A", "B", "C", "D"],
        }
    )
    result = apply_existing_regime_gate(trades)
    assert result["ts_code"].tolist() == ["A", "B", "C"]
