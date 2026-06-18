import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_pool_quality_audit import (
    build_report,
    calculate_forward_quality,
    score_layer_summary,
    summarize_forward_quality,
)


class LongtermPoolQualityAuditTest(unittest.TestCase):
    def make_pool(self):
        return pd.DataFrame(
            [
                {"select_date": "20250102", "ts_code": "good.SZ", "longterm_score": 90, "industry": "AI"},
                {"select_date": "20250102", "ts_code": "weak.SZ", "longterm_score": 70, "industry": "医药"},
            ]
        )

    def make_daily(self):
        rows = []
        for i, date in enumerate(["20250102", "20250103", "20250106", "20250107"]):
            rows.append({"trade_date": date, "ts_code": "good.SZ", "close": 10 + i, "high": 10.5 + i, "low": 9.5 + i})
            rows.append({"trade_date": date, "ts_code": "weak.SZ", "close": 10 - i, "high": 10.2 - i, "low": 9.0 - i})
            rows.append({"trade_date": date, "ts_code": "000300.SH", "close": 100 + i, "high": 101 + i, "low": 99 + i})
        return pd.DataFrame(rows)

    def test_calculate_forward_quality_uses_pool_without_position_limit(self):
        result = calculate_forward_quality(self.make_pool(), self.make_daily(), [2])

        by_code = result.set_index("ts_code")

        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(by_code.loc["good.SZ", "ret_2d"], 20.0)
        self.assertAlmostEqual(by_code.loc["weak.SZ", "ret_2d"], -20.0)
        self.assertTrue(bool(by_code.loc["good.SZ", "outperform_2d"]))
        self.assertFalse(bool(by_code.loc["weak.SZ", "outperform_2d"]))

    def test_summarize_forward_quality_reports_win_and_outperform_rates(self):
        quality = calculate_forward_quality(self.make_pool(), self.make_daily(), [2])
        summary = summarize_forward_quality(quality, [2])

        row = summary.iloc[0]

        self.assertEqual(row["horizon"], "2d")
        self.assertEqual(row["count"], 2)
        self.assertAlmostEqual(row["avg_ret"], 0.0)
        self.assertAlmostEqual(row["win_rate"], 50.0)
        self.assertAlmostEqual(row["outperform_rate"], 50.0)

    def test_score_layer_summary_splits_by_daily_score_rank(self):
        quality = calculate_forward_quality(self.make_pool(), self.make_daily(), [2])
        layers = score_layer_summary(quality, [2])

        top = layers[layers["score_layer"] == "Top10%"].iloc[0]
        bottom = layers[layers["score_layer"] == "Bottom20%"].iloc[0]

        self.assertEqual(top["count"], 1)
        self.assertAlmostEqual(top["avg_ret_2d"], 20.0)
        self.assertAlmostEqual(bottom["avg_ret_2d"], -20.0)

    def test_score_layer_summary_prefers_quality_rank_score_when_present(self):
        quality = calculate_forward_quality(self.make_pool(), self.make_daily(), [2])
        quality["quality_rank_score"] = quality["ts_code"].map({"good.SZ": 60, "weak.SZ": 90})
        layers = score_layer_summary(quality, [2])

        top = layers[layers["score_layer"] == "Top10%"].iloc[0]
        bottom = layers[layers["score_layer"] == "Bottom20%"].iloc[0]

        self.assertAlmostEqual(top["avg_score"], 90.0)
        self.assertAlmostEqual(top["avg_ret_2d"], -20.0)
        self.assertAlmostEqual(bottom["avg_ret_2d"], 20.0)

    def test_build_report_handles_empty_pool(self):
        report = build_report(pd.DataFrame(), [10, 40, 80])

        self.assertIn("0", report)
        self.assertIn("高分样本", report)


if __name__ == "__main__":
    unittest.main()
