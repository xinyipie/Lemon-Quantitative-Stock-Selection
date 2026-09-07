import pandas as pd

from research.clean_factor_discovery_confirmation import (
    benjamini_hochberg,
    choose_low_correlation_factors,
    prepare_factor_ranks,
)


def test_benjamini_hochberg_is_monotonic_in_sorted_p_values():
    adjusted = benjamini_hochberg({"a": 0.001, "b": 0.02, "c": 0.40})
    assert adjusted["a"] <= adjusted["b"] <= adjusted["c"]


def test_future_target_change_does_not_change_factor_rank():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101", "20200101", "20200102", "20200102"],
            "ts_code": ["A", "B", "A", "B"],
            "close": [10.0, 20.0, 11.0, 19.0],
            "amount": [100.0, 200.0, 110.0, 190.0],
            "ret_5": [1.0, 2.0, 1.5, 1.0],
            "ret_20": [2.0, 3.0, 2.5, 2.0],
            "ret_60": [3.0, 4.0, 3.5, 3.0],
            "ma_20": [9.0, 18.0, 9.5, 18.5],
            "ma_60": [8.0, 17.0, 8.5, 17.5],
            "drawdown_20": [-1.0, -2.0, -1.5, -1.0],
            "rsi_14": [55.0, 60.0, 58.0, 57.0],
            "volatility_20": [2.0, 3.0, 2.5, 2.2],
            "turnover_rate": [1.0, 2.0, 1.5, 1.2],
            "volume_ratio": [1.0, 1.2, 1.1, 0.9],
            "industry_rs_20": [1.0, 2.0, 1.5, 1.0],
            "ret_5d": [3.0, -2.0, 1.0, -1.0],
        }
    )
    changed = frame.copy()
    changed.loc[changed["trade_date"] == "20200102", "ret_5d"] = [999.0, -999.0]
    first = prepare_factor_ranks(frame)
    second = prepare_factor_ranks(changed)
    factor_rank_columns = [column for column in first.columns if column.startswith("rank_")]
    assert first[factor_rank_columns].equals(second[factor_rank_columns])


def test_factor_selector_uses_only_supplied_discovery_diagnostics():
    discovery = pd.DataFrame({"rank_ret_5": [0.1, 0.9], "rank_ret_20": [0.2, 0.8]})
    diagnostics = {
        "ret_5": {"qualified": True, "mean_daily_ic": 0.05, "direction": 1},
        "ret_20": {"qualified": False, "mean_daily_ic": 0.50, "direction": 1},
    }
    selected = choose_low_correlation_factors(discovery, diagnostics)
    assert [item["factor"] for item in selected] == ["ret_5"]
