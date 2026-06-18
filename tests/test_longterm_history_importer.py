import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from history_store import HistoryStore
from longterm_history_importer import import_longterm_audit_csv
from web_app.services.signal_service import (
    get_longterm_audit_samples,
    get_longterm_audit_summary,
    summarize_longterm_audit_sample_filter,
)


class LongtermHistoryImporterTest(unittest.TestCase):
    def test_imports_audit_csv_and_exposes_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            csv_path = tmp / "longterm_pool_quality_2025H2_v18_market_sync_full.csv"
            db_path = tmp / "signals.db"
            pd.DataFrame(
                [
                    {
                        "select_date": "20250725",
                        "ts_code": "002170.SZ",
                        "code": "2170",
                        "name": "芭田股份",
                        "industry": "农药化肥",
                        "longterm_profile": "longterm_quality_lifecycle_v18_market_sync",
                        "pool_type": "elastic_quality_lifecycle",
                        "regime": "BULL_TREND",
                        "longterm_score": 90.9,
                        "pool_rank_score": 90.9,
                        "industry_rs": 5.3,
                        "drawdown_from_high": 5.3,
                        "ret_10d": -2.0,
                        "ret_40d": -0.7,
                        "ret_80d": 11.5,
                        "mfe_80d": 30.0,
                        "mae_80d": -4.6,
                        "benchmark_ret_80d": 7.8,
                        "excess_ret_80d": 3.7,
                        "outperform_80d": True,
                        "v16_lifecycle_reasons": "elastic_midcap_quality_industry_pullback",
                    },
                    {
                        "select_date": "20250728",
                        "ts_code": "000902.SZ",
                        "code": "902",
                        "name": "新洋丰",
                        "industry": "农药化肥",
                        "longterm_profile": "longterm_quality_lifecycle_v18_market_sync",
                        "pool_type": "elastic_quality_lifecycle",
                        "regime": "BULL_TREND",
                        "longterm_score": 88.0,
                        "pool_rank_score": 88.0,
                        "industry_rs": 3.8,
                        "drawdown_from_high": 6.1,
                        "ret_10d": 1.0,
                        "ret_40d": 9.5,
                        "ret_80d": -3.0,
                        "mfe_80d": 14.6,
                        "mae_80d": -10.6,
                        "benchmark_ret_80d": 7.3,
                        "excess_ret_80d": -10.3,
                        "outperform_80d": False,
                    },
                ]
            ).to_csv(csv_path, index=False, encoding="utf-8-sig")

            result = import_longterm_audit_csv(csv_path, db_path)
            summary = get_longterm_audit_summary(db_path)
            samples = get_longterm_audit_samples(db_path, limit=5)
            filtered_samples = get_longterm_audit_samples(db_path, limit=5, start="20250726", end="20250729")
            filter_summary = summarize_longterm_audit_sample_filter(
                filtered_samples,
                {"start": "20250726", "end": "20250729"},
            )

            conn = sqlite3.connect(db_path)
            try:
                run_count = conn.execute("select count(*) from longterm_audit_runs").fetchone()[0]
                sample_count = conn.execute("select count(*) from longterm_audit_samples").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(result["import_rows"], 2)
        self.assertEqual(run_count, 1)
        self.assertEqual(sample_count, 2)
        self.assertEqual(summary["total_samples"], 2)
        self.assertEqual(summary["runs"][0]["period"], "2025H2")
        self.assertAlmostEqual(summary["runs"][0]["avg_ret_80d"], 4.25)
        self.assertAlmostEqual(summary["runs"][0]["win_rate_80d"], 0.5)
        sample_by_code = {item["display_code"]: item for item in samples}
        self.assertEqual(sample_by_code["002170.SZ"]["display_name"], "芭田股份")
        self.assertEqual(sample_by_code["002170.SZ"]["ret_80d_text"], "+11.50%")
        self.assertEqual(sample_by_code["002170.SZ"]["reason_text"], "中市值质量趋势 + 行业同步 + 健康回调")
        self.assertEqual([item["display_code"] for item in filtered_samples], ["000902.SZ"])
        self.assertTrue(filter_summary["is_filtered"])
        self.assertEqual(filter_summary["sample_count"], 1)
        self.assertEqual(filter_summary["actual_start"], "20250728")
        self.assertEqual(filter_summary["actual_end"], "20250728")

    def test_unmatured_longterm_sample_shows_current_path_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            csv_path = tmp / "longterm_pool_quality_2026H1_v18_market_sync_full.csv"
            db_path = tmp / "signals.db"
            history_db = tmp / "history.db"
            pd.DataFrame(
                [
                    {
                        "select_date": "20260601",
                        "ts_code": "603444.SH",
                        "name": "吉比特",
                        "industry": "游戏",
                        "longterm_profile": "longterm_quality_lifecycle_v18_market_sync",
                        "pool_type": "elastic_quality_lifecycle",
                        "regime": "BULL_TREND",
                        "longterm_score": 91.0,
                        "ret_10d": 3.0,
                        "ret_40d": None,
                        "ret_80d": None,
                        "mfe_80d": 12.0,
                        "mae_80d": -6.5,
                        "excess_ret_80d": None,
                        "outperform_80d": False,
                    }
                ]
            ).to_csv(csv_path, index=False, encoding="utf-8-sig")
            history = HistoryStore(history_db)
            try:
                history.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {"trade_date": "20260601", "ts_code": "603444.SH", "close": 100.0},
                            {"trade_date": "20260602", "ts_code": "603444.SH", "close": 104.0},
                            {"trade_date": "20260603", "ts_code": "603444.SH", "close": 110.0},
                        ]
                    ),
                )
            finally:
                history.close()

            import_longterm_audit_csv(csv_path, db_path)
            sample = get_longterm_audit_samples(db_path, history_db=history_db, limit=1)[0]

        self.assertEqual(sample["stage_return_text"], "当前+10.00%(t+2)")
        self.assertEqual(sample["ret_40d_text"], "未满")
        self.assertEqual(sample["ret_80d_text"], "未满")
        self.assertEqual(sample["mae_80d_text"], "-6.50%")
        self.assertEqual(sample["excess_80d_text"], "未满 vs 沪深300")
        self.assertEqual(sample["lifecycle_label"], "观察中 t+2")

    def test_longterm_web_audit_defaults_to_half_year_periods(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "signals.db"
            for period in ["2026Q1", "2026H1"]:
                csv_path = Path(tmpdir) / f"longterm_pool_quality_{period}_v18_market_sync_full.csv"
                pd.DataFrame(
                    [
                        {
                            "select_date": "20260113",
                            "ts_code": "605016.SH",
                            "name": "百龙创园",
                            "industry": "食品",
                            "longterm_profile": "longterm_quality_lifecycle_v18_market_sync",
                            "pool_type": "elastic_quality_lifecycle",
                            "regime": "BULL_TREND",
                            "longterm_score": 88.0,
                            "ret_80d": 5.0,
                            "outperform_80d": True,
                        }
                    ]
                ).to_csv(csv_path, index=False, encoding="utf-8-sig")
                import_longterm_audit_csv(csv_path, db_path)

            summary = get_longterm_audit_summary(db_path)
            samples = get_longterm_audit_samples(db_path, history_db=None, limit=10)

        self.assertEqual([item["period"] for item in summary["runs"]], ["2026H1"])
        self.assertEqual({item["period"] for item in samples}, {"2026H1"})


if __name__ == "__main__":
    unittest.main()
