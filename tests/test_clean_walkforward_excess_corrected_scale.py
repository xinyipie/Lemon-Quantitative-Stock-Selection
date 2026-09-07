"""复权价格尺度修复后的特征口径测试。"""

import pandas as pd

from research.clean_walkforward_technical_hgb_excess_target import build_features


def test_adjusted_price_is_compared_with_adjusted_moving_average() -> None:
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "trade_date": ["20210104", "20210104"],
            "close": [100.0, 5.0],
            "synthetic_close": [1.2, 0.8],
            "ma_5": [1.0, 1.0],
            "ma_20": [1.0, 1.0],
            "ma_60": [0.9, 0.9],
            "prior_high_20": [1.3, 1.0],
            "amount": [100.0, 200.0],
            "ret_5": [1.0, -1.0],
            "ret_20": [2.0, -2.0],
            "ret_60": [3.0, -3.0],
            "pct_chg": [1.0, -1.0],
        }
    )
    result = build_features(frame)
    assert result["above_ma20"].tolist() == [1.0, 0.0]
    assert result["market_breadth_ma20"].tolist() == [0.5, 0.5]
    assert result["close_to_ma20"].round(4).tolist() == [0.2, -0.2]
