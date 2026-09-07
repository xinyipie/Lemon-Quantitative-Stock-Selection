import pandas as pd

from research.clean_breadth_gate import add_breadth_features, state_mask


def _sample() -> pd.DataFrame:
    rows = []
    for day in range(1, 8):
        for code, offset in (("A", 1.0), ("B", -1.0)):
            rows.append(
                {
                    "trade_date": f"2020010{day}",
                    "ts_code": code,
                    "close": 10.0 + day + offset,
                    "ma_20": 10.0,
                    "ma_60": 9.0,
                    "ret_5": float(day),
                    "ret_20": float(day - 2),
                }
            )
    return pd.DataFrame(rows)


def test_future_market_row_does_not_change_prior_breadth():
    original = _sample()
    changed = original.copy()
    changed.loc[changed["trade_date"] == "20200107", "close"] = -999.0

    first = add_breadth_features(original)
    second = add_breadth_features(changed)
    first_day6 = first[first["trade_date"] == "20200106"].iloc[0]
    second_day6 = second[second["trade_date"] == "20200106"].iloc[0]

    assert first_day6["breadth_ma20"] == second_day6["breadth_ma20"]
    assert first_day6["breadth_ma20_change_5d"] == second_day6["breadth_ma20_change_5d"]


def test_adaptive_support_is_union_of_frozen_states():
    frame = add_breadth_features(_sample())
    adaptive = state_mask(frame, "adaptive_support")
    expected = state_mask(frame, "broad_support") | state_mask(frame, "improving_support")
    assert adaptive.equals(expected)
