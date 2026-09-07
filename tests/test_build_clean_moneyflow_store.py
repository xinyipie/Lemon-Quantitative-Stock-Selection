import pandas as pd

from research.build_clean_moneyflow_store import add_moneyflow_features


def test_moneyflow_rolling_features_use_current_and_prior_rows_only() -> None:
    panel = pd.DataFrame(
        {
            "ts_code": ["A.SH"] * 6,
            "trade_date": [f"2024010{i}" for i in range(1, 7)],
            "amount": [1000.0] * 6,
            "net_mf_amount": [10.0, -10.0, 20.0, 0.0, 30.0, -1000.0],
        }
    )

    result = add_moneyflow_features(panel)

    assert result.loc[0, "flow_ratio_1d"] == 0.1
    assert result.loc[2, "flow_ratio_3d"] == (100.0 - 100.0 + 200.0) / 3000.0
    assert pd.isna(result.loc[3, "flow_ratio_5d"])
    assert result.loc[4, "flow_positive_days_5d"] == 3.0
    # 第五日特征不能被第六日的大额流出污染。
    assert result.loc[4, "flow_ratio_5d"] == (100.0 - 100.0 + 200.0 + 0.0 + 300.0) / 5000.0
