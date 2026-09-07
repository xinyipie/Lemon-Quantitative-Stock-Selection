import pandas as pd

from research.clean_walkforward_technical_hgb_excess_risk_gate import risk_off_mask


def test_risk_off_detects_weakness_or_panic_but_not_normal_day():
    frame = pd.DataFrame(
        {
            "market_breadth_ma20": [0.20, 0.60, 0.60],
            "market_median_ret20": [-8.0, 2.0, 2.0],
            "market_median_pct_chg": [0.0, -2.0, 0.5],
            "market_dispersion_pct_chg": [1.0, 3.0, 1.0],
        }
    )
    assert risk_off_mask(frame).tolist() == [True, True, False]
