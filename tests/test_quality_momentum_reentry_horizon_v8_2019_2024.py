from research.quality_momentum_reentry_horizon_v8_2019_2024 import choose_horizon


def test_choose_horizon_uses_worst_internal_year_before_average() -> None:
    summaries = [
        {
            "horizon": 3,
            "eligible": True,
            "worst_year_avg_net": 0.40,
            "avg_net": 5.0,
            "profit_factor": 3.0,
        },
        {
            "horizon": 5,
            "eligible": True,
            "worst_year_avg_net": 0.50,
            "avg_net": 1.0,
            "profit_factor": 1.5,
        },
    ]

    assert choose_horizon(summaries) == 5


def test_choose_horizon_prefers_shorter_period_on_full_tie() -> None:
    summaries = [
        {
            "horizon": horizon,
            "eligible": True,
            "worst_year_avg_net": 0.50,
            "avg_net": 1.0,
            "profit_factor": 1.5,
        }
        for horizon in (8, 3, 5)
    ]

    assert choose_horizon(summaries) == 3
