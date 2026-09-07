import pandas as pd

from research.clean_three_day_reversal_basket import eligible_universe


def test_three_day_universe_excludes_extreme_microcap_and_hot_stock():
    frame = pd.DataFrame(
        {
            "rank_log_amount": [0.10, 0.50, 0.50],
            "rank_turnover_rate": [0.50, 0.50, 0.90],
            "rank_volatility_20": [0.50, 0.50, 0.50],
            "ts_code": ["MICRO", "KEEP", "HOT"],
        }
    )
    assert eligible_universe(frame)["ts_code"].tolist() == ["KEEP"]
