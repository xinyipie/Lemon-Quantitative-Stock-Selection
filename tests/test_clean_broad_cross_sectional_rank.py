import unittest

import pandas as pd

from research.clean_broad_cross_sectional_rank import FEATURE_COLUMNS, prepare_year


class CleanBroadCrossSectionalRankTest(unittest.TestCase):
    def test_future_target_is_not_a_feature(self):
        self.assertNotIn("target_rank_5d", FEATURE_COLUMNS)
        self.assertNotIn("ret_5d", FEATURE_COLUMNS)
        self.assertNotIn("entry_gap_pct", FEATURE_COLUMNS)

    def test_target_rank_is_cross_sectional(self):
        base = {
            "name": "x", "industry": "i", "trade_date": "20200102", "close": 10.0,
            "amount": 1000.0, "history_count": 200, "pct_chg": 1.0, "ret_5": 1.0,
            "ret_10": 1.0, "ret_20": 1.0, "ret_60": 1.0, "ma_20": 9.0, "ma_60": 8.0,
            "drawdown_20": 1.0, "rsi_14": 50.0, "volatility_20": 2.0,
            "turnover_rate": 2.0, "volume_ratio": 1.0, "industry_rs_20": 1.0,
            "regime": "BULL_TREND", "entry_open": 10.0, "entry_gap_pct": 0.0,
        }
        frame = pd.DataFrame([{**base, "ts_code": "A", "ret_5d": -1.0}, {**base, "ts_code": "B", "ret_5d": 2.0}])
        prepared = prepare_year(frame).set_index("ts_code")
        self.assertLess(prepared.loc["A", "target_rank_5d"], prepared.loc["B", "target_rank_5d"])


if __name__ == "__main__":
    unittest.main()
