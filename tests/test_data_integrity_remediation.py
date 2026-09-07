import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")

import data_downloader
from local_data_proxy import LocalDataProxy
import main as stock_main


class FinancialHistoryPro:
    def __init__(self):
        self.fina_calls = []
        self.income_calls = []

    def fina_indicator(self, **kwargs):
        self.fina_calls.append(kwargs)
        return pd.DataFrame([
            {
                "ts_code": "000001.SZ",
                "ann_date": "20260430",
                "end_date": "20260331",
                "roe": 12.0,
                "debt_to_assets": 40.0,
                "netprofit_yoy": 20.0,
            }
        ])

    def income(self, **kwargs):
        self.income_calls.append(kwargs)
        return pd.DataFrame([
            {
                "ts_code": "000001.SZ",
                "ann_date": "20260430",
                "end_date": "20260331",
                "revenue": 120.0,
            }
        ])


class StockBasicPro:
    def __init__(self):
        self.statuses = []

    def stock_basic(self, **kwargs):
        status = kwargs["list_status"]
        self.statuses.append(status)
        return pd.DataFrame([
            {
                "ts_code": f"00000{len(self.statuses)}.SZ",
                "symbol": f"00000{len(self.statuses)}",
                "name": f"样本{status}",
                "industry": "测试行业",
                "list_date": "20200101",
                "delist_date": "20250101" if status == "D" else None,
                "list_status": status,
            }
        ])


class DataIntegrityRemediationTest(unittest.TestCase):
    def setUp(self):
        self.old_cache_dir = data_downloader.CACHE_DIR
        self.old_sleep = data_downloader.time.sleep
        data_downloader.time.sleep = lambda _seconds: None

    def tearDown(self):
        data_downloader.CACHE_DIR = self.old_cache_dir
        data_downloader.time.sleep = self.old_sleep

    def test_financial_refresh_merges_complete_history_without_truncation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_downloader.CACHE_DIR = tmpdir
            basic = pd.DataFrame([{"ts_code": "000001.SZ"}])
            basic.to_parquet(Path(tmpdir) / "stock_basic.parquet", index=False)
            old_fina = pd.DataFrame([
                {
                    "ts_code": "000001.SZ",
                    "ann_date": f"{2023 + index // 4}{(index % 4 + 1) * 3:02d}30",
                    "end_date": f"{2023 + index // 4}{(index % 4 + 1) * 3:02d}28",
                    "roe": float(index),
                    "debt_to_assets": 40.0,
                    "netprofit_yoy": float(index),
                }
                for index in range(9)
            ])
            old_fina.to_parquet(Path(tmpdir) / "fina_indicator.parquet", index=False)
            old_income = old_fina.iloc[:5][["ts_code", "ann_date", "end_date"]].copy()
            old_income["revenue"] = range(5)
            old_income.to_parquet(Path(tmpdir) / "income.parquet", index=False)

            pro = FinancialHistoryPro()
            data_downloader.download_fina_indicator(pro, force=True)
            data_downloader.download_income(pro, force=True)

            saved_fina = pd.read_parquet(Path(tmpdir) / "fina_indicator.parquet")
            saved_income = pd.read_parquet(Path(tmpdir) / "income.parquet")
            self.assertEqual(len(saved_fina), 10)
            self.assertEqual(len(saved_income), 6)
            self.assertIn("20230328", set(saved_fina["end_date"].astype(str)))
            self.assertIn("20260331", set(saved_fina["end_date"].astype(str)))

    def test_financial_merge_keeps_cached_values_when_increment_is_partial(self):
        existing = pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20250430", "end_date": "20250331", "roe": 10.0, "netprofit_yoy": 8.0}
        ])
        incoming = pd.DataFrame([
            {"ts_code": "000001.SZ", "ann_date": "20250430", "end_date": "20250331", "roe": 11.0}
        ])

        merged = data_downloader._merge_financial_history(existing, incoming)

        self.assertEqual(merged.iloc[0]["roe"], 11.0)
        self.assertEqual(merged.iloc[0]["netprofit_yoy"], 8.0)

    def test_financial_increment_uses_latest_announcement_as_overlap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_downloader.CACHE_DIR = tmpdir
            pd.DataFrame([{"ts_code": "000001.SZ"}]).to_parquet(
                Path(tmpdir) / "stock_basic.parquet", index=False
            )
            pd.DataFrame([
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20250430",
                    "end_date": "20250331",
                    "roe": 10.0,
                    "debt_to_assets": 40.0,
                    "netprofit_yoy": 5.0,
                }
            ]).to_parquet(Path(tmpdir) / "fina_indicator.parquet", index=False)

            pro = FinancialHistoryPro()
            data_downloader.download_fina_indicator(pro)

            self.assertEqual(pro.fina_calls[0]["start_date"], "20250430")

    def test_financial_increment_backfills_codes_missing_from_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_downloader.CACHE_DIR = tmpdir
            pd.DataFrame([
                {"ts_code": "000001.SZ"},
                {"ts_code": "000002.SZ"},
            ]).to_parquet(Path(tmpdir) / "stock_basic.parquet", index=False)
            pd.DataFrame([
                {
                    "ts_code": "000001.SZ",
                    "ann_date": "20250430",
                    "end_date": "20250331",
                    "roe": 10.0,
                    "debt_to_assets": 40.0,
                    "netprofit_yoy": 5.0,
                }
            ]).to_parquet(Path(tmpdir) / "fina_indicator.parquet", index=False)

            pro = FinancialHistoryPro()
            data_downloader.download_fina_indicator(pro)

            calls = {call["ts_code"]: call for call in pro.fina_calls}
            self.assertEqual(calls["000001.SZ"]["start_date"], "20250430")
            self.assertNotIn("start_date", calls["000002.SZ"])

    def test_financial_increment_uses_oldest_per_code_watermark(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_downloader.CACHE_DIR = tmpdir
            pd.DataFrame([
                {"ts_code": "000001.SZ"},
                {"ts_code": "000002.SZ"},
            ]).to_parquet(Path(tmpdir) / "stock_basic.parquet", index=False)
            pd.DataFrame([
                {"ts_code": "000001.SZ", "ann_date": "20250430", "end_date": "20250331", "roe": 10.0},
                {"ts_code": "000002.SZ", "ann_date": "20250331", "end_date": "20241231", "roe": 9.0},
            ]).to_parquet(Path(tmpdir) / "fina_indicator.parquet", index=False)

            pro = FinancialHistoryPro()
            data_downloader.download_fina_indicator(pro)

            self.assertEqual(pro.fina_calls[0]["start_date"], "20250331")

    def test_stock_basic_download_includes_all_statuses_and_lifecycle_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_downloader.CACHE_DIR = tmpdir
            pro = StockBasicPro()

            data_downloader.download_stock_basic(pro, force=True)

            saved = pd.read_parquet(Path(tmpdir) / "stock_basic.parquet")
            self.assertEqual(pro.statuses, ["L", "D", "P"])
            self.assertEqual(set(saved["list_status"]), {"L", "D", "P"})
            self.assertIn("delist_date", saved.columns)
            self.assertIn("basic_snapshot_date", saved.columns)
            snapshot_path = Path(tmpdir) / "stock_basic_history" / f"{saved['basic_snapshot_date'].iloc[0]}.parquet"
            self.assertTrue(snapshot_path.exists())
            self.assertEqual(len(pd.read_parquet(snapshot_path)), 3)

    def test_stock_basic_snapshot_date_uses_china_timezone_across_utc_midnight(self):
        utc_time = datetime(2026, 9, 6, 16, 30, tzinfo=timezone.utc)

        self.assertEqual(data_downloader._china_date(utc_time), "20260907")

    def test_local_stock_basic_prefers_exact_historical_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            master = pd.DataFrame([
                {"ts_code": "A.SZ", "list_status": "L", "list_date": "20200101", "delist_date": None, "name": "现名", "industry": "现行业", "basic_snapshot_date": "20260907", "basic_status_scope": "L,D,P"}
            ])
            master.to_parquet(Path(tmpdir) / "stock_basic.parquet", index=False)
            history_dir = Path(tmpdir) / "stock_basic_history"
            history_dir.mkdir()
            historical = master.copy()
            historical["name"] = "旧名"
            historical["industry"] = "旧行业"
            historical["basic_snapshot_date"] = "20240101"
            historical.to_parquet(history_dir / "20240101.parquet", index=False)
            proxy = LocalDataProxy(tmpdir)

            result = proxy.stock_basic(
                list_status="L",
                as_of_date="20240101",
                fields="ts_code,name,industry",
            )

            self.assertEqual(result.iloc[0]["name"], "旧名")
            self.assertEqual(result.iloc[0]["industry"], "旧行业")
            self.assertTrue(result.iloc[0]["membership_point_in_time_reliable"])
            self.assertTrue(result.iloc[0]["name_industry_point_in_time_reliable"])
            self.assertEqual(result.iloc[0]["point_in_time_source"], "exact_snapshot")

    def test_local_stock_basic_filters_lifecycle_at_historical_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"ts_code": "A.SZ", "list_status": "D", "list_date": "20200101", "delist_date": "20250101", "name": "A", "industry": "甲", "basic_snapshot_date": "20260907"},
                {"ts_code": "B.SZ", "list_status": "L", "list_date": "20260101", "delist_date": None, "name": "B", "industry": "乙", "basic_snapshot_date": "20260907"},
                {"ts_code": "C.SZ", "list_status": "D", "list_date": "20100101", "delist_date": "20210101", "name": "C", "industry": "丙", "basic_snapshot_date": "20260907"},
            ]
            pd.DataFrame(rows).to_parquet(Path(tmpdir) / "stock_basic.parquet", index=False)
            proxy = LocalDataProxy(tmpdir, strict_point_in_time=False)

            result = proxy.stock_basic(
                list_status="L",
                as_of_date="20240101",
                fields="ts_code,name,industry,list_date,delist_date,list_status",
            )

            self.assertEqual(result["ts_code"].tolist(), ["A.SZ"])
            self.assertFalse(result["name_industry_point_in_time_reliable"].iloc[0])
            self.assertEqual(result["point_in_time_as_of_date"].iloc[0], "20240101")

    def test_local_stock_basic_lifecycle_supports_arrow_string_missing_dates(self):
        with pd.option_context("mode.string_storage", "pyarrow"):
            self.test_local_stock_basic_filters_lifecycle_at_historical_date()

    def test_local_stock_basic_strict_mode_requires_exact_historical_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pd.DataFrame([
                {"ts_code": "A.SZ", "list_status": "L", "list_date": "20200101", "delist_date": None, "name": "现名", "industry": "现行业", "basic_snapshot_date": "20260907", "basic_status_scope": "L,D,P"}
            ]).to_parquet(Path(tmpdir) / "stock_basic.parquet", index=False)
            proxy = LocalDataProxy(tmpdir)

            with self.assertRaisesRegex(ValueError, "精确历史快照"):
                proxy.stock_basic(as_of_date="20240101", fields="ts_code,name,industry")

    def test_local_stock_basic_strict_mode_rejects_missing_master_and_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proxy = LocalDataProxy(tmpdir)

            with self.assertRaisesRegex(ValueError, "没有可用数据"):
                proxy.stock_basic(as_of_date="20240101", fields="ts_code,name,industry")

    def test_profit_growth_uses_injected_proxy_cache_not_cwd_default(self):
        old_pro = stock_main.pro
        old_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                injected = root / "injected"
                default = root / "data" / "cache"
                injected.mkdir()
                default.mkdir(parents=True)
                rows = [
                    {"ts_code": "000001.SZ", "ann_date": "20260430", "end_date": "20260331", "netprofit_yoy": 24.0},
                    {"ts_code": "000001.SZ", "ann_date": "20251030", "end_date": "20250930", "netprofit_yoy": 18.0},
                ]
                pd.DataFrame(rows).to_parquet(injected / "fina_indicator.parquet", index=False)
                wrong = [dict(row, netprofit_yoy=999.0) for row in rows]
                pd.DataFrame(wrong).to_parquet(default / "fina_indicator.parquet", index=False)
                os.chdir(root)
                stock_main.set_pro(LocalDataProxy(str(injected)))

                result = stock_main.get_net_profit_growth_batch(["000001"], trade_date="20260623")

                self.assertEqual(result["000001"]["netprofit_yoy"], 24.0)
                os.chdir(old_cwd)
        finally:
            os.chdir(old_cwd)
            stock_main.set_pro(old_pro)


class TushareUrlValidationTest(unittest.TestCase):
    def test_init_tushare_validates_and_normalizes_custom_url_before_assignment(self):
        old_config = dict(stock_main.config.TUSHARE_CONFIG)
        old_pro_api = stock_main.ts.pro_api
        old_require_secure_url = stock_main.config.require_secure_tushare_url
        seen = []

        class FakePro:
            def query(self, *_args, **_kwargs):
                return pd.DataFrame()

        fake = FakePro()
        try:
            stock_main.config.TUSHARE_CONFIG.update({"token": "token", "timeout": 30, "http_url": "https://example.test/"})
            stock_main.config.require_secure_tushare_url = lambda value: seen.append(value) or value.rstrip("/")
            stock_main.ts.pro_api = lambda **_kwargs: fake

            result = stock_main.init_tushare()

            self.assertIs(result, fake)
            self.assertEqual(seen, ["https://example.test/"])
            self.assertEqual(fake._DataApi__http_url, "https://example.test")
        finally:
            stock_main.config.TUSHARE_CONFIG.clear()
            stock_main.config.TUSHARE_CONFIG.update(old_config)
            stock_main.config.require_secure_tushare_url = old_require_secure_url
            stock_main.ts.pro_api = old_pro_api


if __name__ == "__main__":
    unittest.main()
