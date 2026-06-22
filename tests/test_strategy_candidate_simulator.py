import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.strategy_candidate_simulator import (
    build_candidate_simulation,
    write_candidate_simulation_report,
)


class StrategyCandidateSimulatorTest(unittest.TestCase):
    def test_build_candidate_simulation_compares_research_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest_dir = root / "backtest_results"
            reports_dir = root / "reports"
            backtest_dir.mkdir()
            reports_dir.mkdir()

            short_rows = []
            for day in [20240701, 20240702, 20250701]:
                for rank, score in enumerate([80, 70, 60, 50], start=1):
                    short_rows.append(
                        {
                            "select_date": day,
                            "ts_code": f"00000{rank}.SZ",
                            "score": score,
                            "factor_profile": "profile_v9_sector_quality_guard",
                            "factor_inflow": 80 if rank <= 2 else 5,
                            "factor_sector": 70 if rank <= 2 else 10,
                            "factor_volume_ratio": 60,
                            "factor_pattern": 40,
                            "factor_turnover": 30,
                            "ret_5d": 8 - rank,
                            "mfe_pct": 10 - rank,
                            "mae_pct": -rank,
                        }
                    )
            pd.DataFrame(short_rows).to_csv(backtest_dir / "ic_short_mock.csv", index=False)

            long_rows = []
            for day in [20240701, 20250701]:
                for rank, score in enumerate([90, 80, 70, 60], start=1):
                    long_rows.append(
                        {
                            "select_date": day,
                            "ts_code": f"60000{rank}.SH",
                            "longterm_score": score,
                            "quality_rank_score": score,
                            "industry_rs": 8 if rank <= 2 else -6,
                            "roe": 12 if rank <= 2 else 2,
                            "debt_ratio": 40 if rank <= 2 else 85,
                            "netprofit_yoy": 15 if rank <= 2 else -20,
                            "ret_80d": 12 - rank,
                            "mfe_80d": 18 - rank,
                            "mae_80d": -rank,
                        }
                    )
            pd.DataFrame(long_rows).to_csv(
                reports_dir / "longterm_pool_quality_2025H2_v18_market_sync_full.csv",
                index=False,
            )

            result = build_candidate_simulation(root=root, max_short_files=0)

            self.assertIn("short_v9_baseline_top3", result["short"]["candidates"])
            self.assertIn("long_v18_quality_floor_top10", result["longterm"]["candidates"])
            self.assertGreater(
                result["short"]["candidates"]["short_v9_top1_concentration"]["overall"]["avg_ret"],
                result["short"]["candidates"]["short_v9_baseline_top3"]["overall"]["avg_ret"],
            )
            self.assertGreater(
                result["longterm"]["candidates"]["long_v18_quality_floor_top10"]["overall"]["avg_ret"],
                result["longterm"]["candidates"]["long_v18_baseline_top3"]["overall"]["avg_ret"],
            )

    def test_write_candidate_simulation_report_outputs_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest_dir = root / "backtest_results"
            reports_dir = root / "reports"
            backtest_dir.mkdir()
            reports_dir.mkdir()
            pd.DataFrame(
                [
                    {
                        "select_date": 20240701,
                        "ts_code": "000001.SZ",
                        "score": 70,
                        "factor_profile": "profile_v9_sector_quality_guard",
                        "ret_5d": 3,
                    }
                ]
            ).to_csv(backtest_dir / "ic_short_mock.csv", index=False)

            output = root / "reports" / "research" / "candidate.md"
            write_candidate_simulation_report(root=root, output=output, max_short_files=0)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            self.assertIn("候选策略离线模拟", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
