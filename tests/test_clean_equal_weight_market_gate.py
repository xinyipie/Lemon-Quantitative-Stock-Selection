import pandas as pd

from research.clean_equal_weight_market_gate import add_equal_weight_market_features, market_gate


def _sample() -> pd.DataFrame:
    rows = []
    for day in range(1, 82):
        for code, move in (("A", 1.0), ("B", 0.5)):
            rows.append(
                {
                    "trade_date": f"2020{(day // 28) + 1:02d}{(day % 28) + 1:02d}",
                    "ts_code": code,
                    "pct_chg": move,
                    "close": 100.0 + day,
                    "ma_20": 90.0,
                }
            )
    return pd.DataFrame(rows)


def test_future_return_change_does_not_change_prior_market_state():
    original = _sample()
    changed = original.copy()
    last_date = changed["trade_date"].max()
    changed.loc[changed["trade_date"] == last_date, "pct_chg"] = -99.0
    first = add_equal_weight_market_features(original)
    second = add_equal_weight_market_features(changed)
    prior_date = sorted(first["trade_date"].unique())[-2]
    columns = ["ew_index", "ew_ma20", "ew_ma60", "ew_ma60_change_20d", "breadth_change_5d"]
    assert first.loc[first["trade_date"] == prior_date, columns].reset_index(drop=True).equals(
        second.loc[second["trade_date"] == prior_date, columns].reset_index(drop=True)
    )


def test_adaptive_gate_is_union_of_strict_and_recovery():
    frame = add_equal_weight_market_features(_sample())
    assert market_gate(frame, "adaptive_trend").equals(
        market_gate(frame, "strict_trend") | market_gate(frame, "early_recovery")
    )
