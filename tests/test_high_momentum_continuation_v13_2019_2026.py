import pandas as pd

from research.high_momentum_continuation_v13_2019_2026 import (
    RuleConfig,
    candidate_mask,
    select_with_cooldown,
)


def test_guangxun_like_row_passes_fixed_candidate_mask() -> None:
    frame = pd.DataFrame(
        {
            "name": ["示例通信"], "ts_code": ["000001.SZ"], "history_count": [201],
            "pct_chg": [1.79], "turnover_rate": [10.18], "volume_ratio": [1.31],
            "entry_gap_pct": [0.71], "ret_20": [55.2], "ret_60": [70.1],
            "drawdown_20": [-1.79], "rsi_14": [81.5], "industry_rs_20": [43.3],
            "flow_ratio_5d": [0.002], "ma_20": [2.14], "ma_60": [1.79],
            "synthetic_close": [2.63], "regime": ["BULL_TREND"],
        }
    )
    assert bool(candidate_mask(frame, RuleConfig()).iloc[0])


def test_selector_enforces_industry_and_stock_cooldown() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20260101", "20260101", "20260102", "20260102"],
            "ts_code": ["A", "B", "A", "C"],
            "industry": ["通信", "通信", "通信", "电子"],
            "momentum_score": [1.0, 0.9, 1.0, 0.8],
        }
    )
    result = select_with_cooldown(frame, topn=2, cooldown_days=10)
    assert result["ts_code"].tolist() == ["A", "C"]
