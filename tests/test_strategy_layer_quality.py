import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.strategy_layer_quality import build_layer_quality, write_layer_quality_report


class StrategyLayerQualityTest(unittest.TestCase):
    def test_build_layer_quality_detects_top_layer_edge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backtests = root / "backtest_results"
            reports = root / "reports"
            backtests.mkdir()
            reports.mkdir()

            short_rows = []
            for date, rets in [("20240101", [8, 6, -1, -2]), ("20240102", [4, 2, -3, -4])]:
                for idx, ret in enumerate(rets):
                    short_rows.append(
                        {
                            "select_date": date,
                            "ts_code": f"00000{idx}.SZ",
                            "factor_profile": "profile_v9_sector_quality_guard",
                            "score": 4 - idx,
                            "ret_5d": ret,
                            "mfe_pct": ret + 2,
                            "mae_pct": -idx - 1,
                        }
                    )
            pd.DataFrame(short_rows).to_csv(backtests / "ic_short_20240101.csv", index=False)

            long_rows = []
            for date, rets in [("20240701", [20, 12, 1, -3]), ("20250701", [10, 8, -2, -5])]:
                for idx, ret in enumerate(rets):
                    long_rows.append(
                        {
                            "select_date": date,
                            "ts_code": f"60000{idx}.SH",
                            "longterm_score": 80 - idx * 10,
                            "ret_80d": ret,
                            "mfe_80d": ret + 5,
                            "mae_80d": -idx - 2,
                        }
                    )
            pd.DataFrame(long_rows).to_csv(
                reports / "longterm_pool_quality_2025H2_v18_market_sync_full.csv",
                index=False,
            )

            result = build_layer_quality(root=root, short_layers=(1, 3, "all"), long_layers=(1, 3, "all"))

        short_top1 = result["short"]["layers"]["top1"]
        short_all = result["short"]["layers"]["all"]
        long_top1 = result["longterm"]["layers"]["top1"]
        self.assertGreater(short_top1["avg_ret"], short_all["avg_ret"])
        self.assertEqual(short_top1["classification"], "quality_edge")
        self.assertEqual(long_top1["classification"], "quality_edge")
        self.assertEqual(result["short"]["target"], "ret_5d")
        self.assertEqual(result["longterm"]["target"], "ret_80d")

    def test_write_layer_quality_report_outputs_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backtest_results").mkdir()
            (root / "reports").mkdir()
            output = root / "reports" / "research" / "layer_quality.md"

            write_layer_quality_report(root=root, output=output)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            self.assertIn("分层质量诊断", output.read_text(encoding="utf-8"))
            payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertIn("short", payload)
            self.assertIn("longterm", payload)


if __name__ == "__main__":
    unittest.main()
