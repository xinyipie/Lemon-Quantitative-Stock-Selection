import pandas as pd

from research.clean_moneyflow_overlay import compute_moneyflow_features, moneyflow_ratio


def test_moneyflow_ratio_converts_wan_to_thousand_yuan():
    result = moneyflow_ratio(pd.Series([100.0]), pd.Series([10000.0]))
    assert result.iloc[0] == 0.1


def test_rolling_moneyflow_feature_never_uses_future_row():
    original = pd.DataFrame(
        {
            "trade_date": ["20200101", "20200101", "20200102", "20200102", "20200103", "20200103", "20200104", "20200104"],
            "ts_code": ["A", "B"] * 4,
            "amount": [1000.0] * 8,
            "net_mf_amount": [1.0, -1.0, 2.0, -2.0, 3.0, -3.0, 4.0, -4.0],
        }
    )
    changed = original.copy()
    changed.loc[(changed["trade_date"] == "20200104") & (changed["ts_code"] == "A"), "net_mf_amount"] = -99999.0

    first = compute_moneyflow_features(original)
    second = compute_moneyflow_features(changed)
    first_day3 = first[(first["trade_date"] == "20200103") & (first["ts_code"] == "A")].iloc[0]
    second_day3 = second[(second["trade_date"] == "20200103") & (second["ts_code"] == "A")].iloc[0]

    assert first_day3["mf_rank_3d"] == second_day3["mf_rank_3d"]
    assert first_day3["mf_positive_fraction_3d"] == second_day3["mf_positive_fraction_3d"]
    assert first_day3["mf_positive_fraction_3d"] == 1.0
