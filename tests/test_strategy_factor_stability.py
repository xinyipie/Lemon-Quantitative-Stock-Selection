import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.strategy_factor_stability import build_factor_stability, write_factor_stability_report


class StrategyFactorStabilityTest(unittest.TestCase):
    def test_build_factor_stability_classifies_stable_and_unstable_factors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backtests = root / "backtest_results"
            reports = root / "reports"
            backtests.mkdir()
            reports.mkdir()

            pd.DataFrame(
                {
                    "select_date": ["20240101"] * 5,
                    "factor_good": [1, 2, 3, 4, 5],
                    "factor_flip": [1, 2, 3, 4, 5],
                    "ret_5d": [1, 2, 3, 4, 5],
                    "mfe_pct": [2, 3, 4, 5, 6],
                }
            ).to_csv(backtests / "ic_short_20240101.csv", index=False)
            pd.DataFrame(
                {
                    "select_date": ["20240701"] * 5,
                    "factor_good": [1, 2, 3, 4, 5],
                    "factor_flip": [1, 2, 3, 4, 5],
                    "ret_5d": [1, 2, 3, 4, 5],
                    "mfe_pct": [2, 3, 4, 5, 6],
                }
            ).to_csv(backtests / "ic_short_20240701.csv", index=False)
            pd.DataFrame(
                {
                    "select_date": ["20240801"] * 5,
                    "factor_profile": ["profile_v8_sector_rank"] * 5,
                    "factor_good": [1, 2, 3, 4, 5],
                    "ret_5d": [5, 4, 3, 2, 1],
                }
            ).to_csv(backtests / "ic_short_20240801.csv", index=False)
            pd.DataFrame(
                {
                    "period": ["2024H2"] * 5,
                    "score_rs": [1, 2, 3, 4, 5],
                    "score_fin": [1, 2, 3, 4, 5],
                    "ret_80d": [1, 2, 3, 4, 5],
                }
            ).to_csv(reports / "longterm_pool_quality_2024H2_v18_market_sync_full.csv", index=False)
            pd.DataFrame(
                {
                    "period": ["2025H2"] * 5,
                    "score_rs": [1, 2, 3, 4, 5],
                    "score_fin": [1, 2, 3, 4, 5],
                    "ret_80d": [1, 2, 3, 4, 5],
                }
            ).to_csv(reports / "longterm_pool_quality_2025H2_v18_market_sync_full.csv", index=False)
            pd.DataFrame(
                {
                    "select_date": ["20250101"] * 5,
                    "factor_good": [5, 4, 3, 2, 1],
                    "factor_flip": [1, 2, 3, 4, 5],
                    "ret_5d": [5, 4, 3, 2, 1],
                    "mfe_pct": [6, 5, 4, 3, 2],
                }
            ).to_csv(backtests / "ic_short_20250101.csv", index=False)

            result = build_factor_stability(root=root, min_periods=2, min_abs_corr=0.2)

        short_by_factor = {item["factor"]: item for item in result["short"]["factors"]}
        long_by_factor = {item["factor"]: item for item in result["longterm"]["factors"]}
        self.assertEqual(short_by_factor["factor_good"]["classification"], "stable_positive")
        self.assertEqual(short_by_factor["factor_flip"]["classification"], "unstable")
        self.assertEqual(long_by_factor["score_rs"]["classification"], "stable_positive")
        self.assertEqual(result["short"]["target"], "ret_5d")
        self.assertNotIn("ic_short_20240801.csv", result["short"]["files"])
        self.assertEqual(result["longterm"]["target"], "ret_80d")

    def test_write_factor_stability_report_outputs_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backtest_results").mkdir()
            (root / "reports").mkdir()
            output = root / "reports" / "research" / "factor_stability.md"

            write_factor_stability_report(root=root, output=output)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            self.assertIn("因子稳定性研究", output.read_text(encoding="utf-8"))
            payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertIn("short", payload)
            self.assertIn("longterm", payload)


if __name__ == "__main__":
    unittest.main()
