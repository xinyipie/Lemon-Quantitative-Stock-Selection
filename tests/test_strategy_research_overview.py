import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.strategy_research_overview import build_research_overview, write_research_overview


class StrategyResearchOverviewTest(unittest.TestCase):
    def test_build_research_overview_summarizes_short_and_long_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = root / "reports"
            backtests = root / "backtest_results"
            reports.mkdir()
            backtests.mkdir()

            pd.DataFrame(
                [
                    {
                        "select_date": "20260601",
                        "ts_code": "000001.SZ",
                        "score": 60,
                        "rank": 1,
                        "ret_5d": 5.2,
                        "mfe": 8.0,
                        "mae": -3.0,
                    },
                    {
                        "select_date": "20260602",
                        "ts_code": "000002.SZ",
                        "score": 48,
                        "rank": 2,
                        "ret_5d": -2.0,
                        "mfe": 1.0,
                        "mae": -6.0,
                    },
                ]
            ).to_csv(backtests / "ic_short_20260618_120000.csv", index=False)
            pd.DataFrame(
                [
                    {"select_date": "20260501", "ts_code": f"00000{i}.SZ", "score": 50 + i, "ret_5d": i - 2}
                    for i in range(5)
                ]
            ).to_csv(backtests / "ic_short_20260601_120000.csv", index=False)

            pd.DataFrame(
                [
                    {
                        "period": "2025H2",
                        "ts_code": "000001.SZ",
                        "name": "Alpha",
                        "ret_80d": 10.0,
                        "win_80d": 1,
                        "beat_index_80d": 1,
                        "score": 66.0,
                    },
                    {
                        "period": "2025H2",
                        "ts_code": "000002.SZ",
                        "name": "Beta",
                        "ret_80d": -4.0,
                        "win_80d": 0,
                        "beat_index_80d": 0,
                        "score": 42.0,
                    },
                ]
            ).to_csv(reports / "longterm_pool_quality_2025H2_v18_market_sync_full.csv", index=False)

            overview = build_research_overview(root=root)

        self.assertEqual(overview["short"]["latest_ic_file"], "ic_short_20260618_120000.csv")
        self.assertEqual(overview["short"]["sample_count"], 2)
        self.assertEqual(overview["short"]["largest_ic_file"], "ic_short_20260601_120000.csv")
        self.assertEqual(overview["short"]["largest_sample_count"], 5)
        self.assertAlmostEqual(overview["short"]["avg_ret_5d"], 1.6)
        self.assertEqual(overview["longterm"]["period_count"], 1)
        self.assertAlmostEqual(overview["longterm"]["avg_ret_80d"], 3.0)

    def test_write_research_overview_creates_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "reports").mkdir()
            (root / "backtest_results").mkdir()
            output = root / "reports" / "research" / "overview.md"

            write_research_overview(root=root, output=output)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            text = output.read_text(encoding="utf-8")
            self.assertIn("端午策略研究总览", text)
            payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertIn("short", payload)
            self.assertIn("longterm", payload)


if __name__ == "__main__":
    unittest.main()
