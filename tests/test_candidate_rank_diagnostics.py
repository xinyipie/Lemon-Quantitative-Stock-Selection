import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from candidate_rank_diagnostics import (
    FACTOR_COLUMNS,
    build_markdown_report,
    compare_top3_vs_missed,
    find_missed_good_candidates,
    rank_candidates,
)


class CandidateRankDiagnosticsTest(unittest.TestCase):
    def make_frame(self):
        rows = []
        for rank, score in enumerate([90, 80, 70, 60, 50, 40], start=1):
            rows.append(
                {
                    "select_date": "20250102",
                    "ts_code": f"00000{rank}.SZ",
                    "score": score,
                    "mfe_pct": [3, 4, 5, 9, 8, 1][rank - 1],
                    "window_end_pct": [0, 1, 2, 6, 5, -2][rank - 1],
                    "factor_pattern": [40, 45, 50, 75, 72, 30][rank - 1],
                    "factor_inflow": [60, 62, 64, 90, 88, 20][rank - 1],
                    "factor_sector": [80, 82, 84, 30, 35, 20][rank - 1],
                    "factor_drawdown": [70, 72, 74, 55, 58, 30][rank - 1],
                    "factor_wyckoff": [45, 46, 47, 80, 78, 20][rank - 1],
                    "volume_ratio": [1.5, 1.6, 1.7, 2.5, 2.4, 1.0][rank - 1],
                    "market_style": "sideways",
                    "macro_mode": "active",
                }
            )
        for rank, score in enumerate([95, 85, 75, 65], start=1):
            rows.append(
                {
                    "select_date": "20250103",
                    "ts_code": f"30000{rank}.SZ",
                    "score": score,
                    "mfe_pct": [7, 6, 5, 1][rank - 1],
                    "window_end_pct": [4, 3, 2, -1][rank - 1],
                    "factor_pattern": [60, 58, 56, 20][rank - 1],
                    "factor_inflow": [70, 68, 66, 10][rank - 1],
                    "factor_sector": [50, 52, 54, 90][rank - 1],
                    "factor_drawdown": [65, 63, 61, 30][rank - 1],
                    "factor_wyckoff": [55, 53, 51, 10][rank - 1],
                    "volume_ratio": [2.0, 1.9, 1.8, 4.0][rank - 1],
                    "market_style": "weak_momentum",
                    "macro_mode": "cautious",
                }
            )
        return pd.DataFrame(rows)

    def test_rank_candidates_adds_daily_rank_and_bucket(self):
        ranked = rank_candidates(self.make_frame(), top_n=3, compare_max_rank=10)

        first_day = ranked[ranked["select_date"] == "20250102"]
        self.assertEqual(first_day.iloc[0]["candidate_rank"], 1)
        self.assertEqual(first_day.iloc[3]["rank_bucket"], "rank_4_10")
        self.assertTrue(first_day.iloc[0]["is_top_n"])

    def test_find_missed_good_candidates_flags_rank_4_10_that_beats_daily_top3(self):
        missed = find_missed_good_candidates(self.make_frame(), top_n=3, compare_max_rank=10)

        self.assertEqual(set(missed["ts_code"]), {"000004.SZ", "000005.SZ"})
        self.assertTrue((missed["miss_reason"].str.contains("MFE")).all())

    def test_compare_top3_vs_missed_reports_factor_differences(self):
        ranked = rank_candidates(self.make_frame())
        missed = find_missed_good_candidates(ranked)

        result = compare_top3_vs_missed(ranked, missed, factors=FACTOR_COLUMNS)
        pattern = result[result["factor"] == "factor_pattern"].iloc[0]

        self.assertEqual(pattern["top3_count"], 6)
        self.assertEqual(pattern["missed_count"], 2)
        self.assertGreater(pattern["missed_avg"], pattern["top3_avg"])

    def test_build_markdown_report_contains_plain_chinese_sections(self):
        report = build_markdown_report(self.make_frame(), source="sample.csv")

        self.assertIn("# Candidate Rank Diagnostics", report)
        self.assertIn("## 先看结论", report)
        self.assertIn("## Top3 vs 错过好票因子差异", report)
        self.assertIn("形态质量", report)


if __name__ == "__main__":
    unittest.main()
