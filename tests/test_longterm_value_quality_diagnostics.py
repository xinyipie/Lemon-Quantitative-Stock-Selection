import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_value_quality_diagnostics import (
    build_factor_snapshot,
    build_report,
    latest_financial_snapshot,
    summarize_factor_quantiles,
)


class LongtermValueQualityDiagnosticsTest(unittest.TestCase):
    def make_daily(self):
        rows = []
        for i in range(1, 9):
            date = f"2025010{i}"
            rows.extend(
                [
                    {"ts_code": "good.SZ", "trade_date": date, "close": 10 + i, "high": 10 + i},
                    {"ts_code": "bad.SZ", "trade_date": date, "close": 20 - i, "high": 20 - i},
                    {"ts_code": "unknown.SZ", "trade_date": date, "close": 30 + i, "high": 30 + i},
                ]
            )
        return pd.DataFrame(rows)

    def test_latest_financial_snapshot_respects_announcement_date(self):
        fina = pd.DataFrame(
            [
                {"ts_code": "good.SZ", "ann_date": "20241231", "end_date": "20240930", "roe": 15, "debt_to_assets": 35, "netprofit_yoy": 40},
                {"ts_code": "good.SZ", "ann_date": "20250105", "end_date": "20241231", "roe": 5, "debt_to_assets": 80, "netprofit_yoy": -20},
            ]
        )

        snap = latest_financial_snapshot(fina, asof_date="20250104")

        self.assertEqual(float(snap.loc["good.SZ", "roe"]), 15.0)

    def test_build_factor_snapshot_includes_forward_return_and_quality_fields(self):
        daily = self.make_daily()
        fina = pd.DataFrame(
            [
                {"ts_code": "good.SZ", "ann_date": "20241231", "end_date": "20240930", "roe": 15, "debt_to_assets": 35, "netprofit_yoy": 40},
                {"ts_code": "bad.SZ", "ann_date": "20241231", "end_date": "20240930", "roe": 2, "debt_to_assets": 85, "netprofit_yoy": -30},
            ]
        )
        stock_basic = pd.DataFrame(
            [
                {"ts_code": "good.SZ", "name": "好公司", "industry": "消费"},
                {"ts_code": "bad.SZ", "name": "差公司", "industry": "地产"},
                {"ts_code": "unknown.SZ", "name": "未知财务", "industry": "制造"},
            ]
        )

        snap = build_factor_snapshot(
            daily=daily,
            fina=fina,
            income=pd.DataFrame(),
            stock_basic=stock_basic,
            asof_date="20250104",
            forward_days=[2],
            trend_window=3,
        )

        good = snap[snap["ts_code"] == "good.SZ"].iloc[0]
        bad = snap[snap["ts_code"] == "bad.SZ"].iloc[0]
        unknown = snap[snap["ts_code"] == "unknown.SZ"].iloc[0]
        self.assertGreater(good["ret_2d"], 0)
        self.assertLess(bad["ret_2d"], 0)
        self.assertGreater(good["quality_score"], bad["quality_score"])
        self.assertTrue(good["financial_known"])
        self.assertFalse(unknown["financial_known"])
        self.assertTrue(pd.isna(unknown["quality_score_known"]))

    def test_report_contains_quantile_factor_and_coverage_sections(self):
        snap = pd.DataFrame(
            [
                {"ts_code": "a", "ret_2d": 10, "quality_score_known": 80, "quality_score": 80, "financial_known": True, "financial_complete": True, "roe": 15, "debt_to_assets": 30, "netprofit_yoy": 40},
                {"ts_code": "b", "ret_2d": -5, "quality_score_known": 20, "quality_score": 20, "financial_known": True, "financial_complete": True, "roe": 2, "debt_to_assets": 80, "netprofit_yoy": -10},
                {"ts_code": "c", "ret_2d": 3, "quality_score_known": 60, "quality_score": 60, "financial_known": True, "financial_complete": True, "roe": 8, "debt_to_assets": 50, "netprofit_yoy": 15},
                {"ts_code": "d", "ret_2d": -2, "quality_score_known": None, "quality_score": 50, "financial_known": False, "financial_complete": False},
            ]
        )
        summary = summarize_factor_quantiles(snap, target_col="ret_2d", factors=["quality_score_known"], buckets=2)
        report = build_report(snap, summary, title="value quality test")

        self.assertIn("# value quality test", report)
        self.assertIn("先看结论", report)
        self.assertIn("财务质量字段覆盖", report)
        self.assertIn("因子分桶", report)
        self.assertIn("quality_score_known", report)


if __name__ == "__main__":
    unittest.main()
