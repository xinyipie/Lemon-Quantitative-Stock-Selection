import pandas as pd

from research.clean_low_risk_reversal_basket import eligible_universe, rebalance_dates


def test_rebalance_offsets_cover_distinct_five_day_sequences():
    dates = [f"202001{day:02d}" for day in range(1, 16)]
    sequences = [set(rebalance_dates(dates, offset)) for offset in range(5)]
    assert set.union(*sequences) == set(dates)
    assert all(sequences[left].isdisjoint(sequences[right]) for left in range(5) for right in range(left + 1, 5))


def test_extreme_low_liquidity_and_extreme_high_risk_are_excluded():
    frame = pd.DataFrame(
        {
            "rank_log_amount": [0.10, 0.50, 0.50],
            "rank_turnover_rate": [0.50, 0.50, 0.90],
            "rank_volatility_20": [0.50, 0.50, 0.50],
            "ts_code": ["MICRO", "KEEP", "HOT"],
        }
    )
    result = eligible_universe(frame)
    assert result["ts_code"].tolist() == ["KEEP"]
