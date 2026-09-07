import pandas as pd

from research.moneyflow_breakout_factor_audit import breakout_candidate_mask


def test_breakout_candidate_mask_uses_adjusted_price_scale() -> None:
    frame = pd.DataFrame(
        {
            "ts_code": ["A.SH", "B.SH"],
            "name": ["样本A", "样本B"],
            "history_count": [200, 200],
            "synthetic_close": [99.0, 80.0],
            "prior_high_20": [100.0, 100.0],
            "ma_20": [95.0, 95.0],
            "ma_60": [90.0, 90.0],
            "ret_20": [10.0, 10.0],
            "ret_60": [20.0, 20.0],
            "pct_chg": [2.0, 2.0],
            "turnover_rate": [3.0, 3.0],
            "volume_ratio": [1.2, 1.2],
            "entry_gap_pct": [0.0, 0.0],
        }
    )

    assert breakout_candidate_mask(frame).tolist() == [True, False]
