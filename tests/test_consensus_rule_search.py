import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.consensus_rule_search import SearchRule, _apply_rule, run_consensus_rule_search, write_consensus_rule_search


class ConsensusRuleSearchTest(unittest.TestCase):
    def _row(self, day: int, code: str, ret: float, **overrides):
        row = {
            "period": "2025",
            "select_date": day,
            "ts_code": f"{code}.SZ",
            "consensus_votes": 2,
            "consensus_score": 300.0,
            "limit_up_count": 80,
            "sector_ma10_ratio": 82.0,
            "change": 3.0,
            "volume_ratio": 2.0,
            "drawdown_from_high": 5.0,
            "factor_sector": 40.0,
            "factor_pattern": 30.0,
            "factor_wyckoff": 68.0,
            "ret_5d": ret,
            "mfe_pct": max(ret, 0) + 4.0,
            "mae_pct": -2.0 if ret >= 0 else -6.0,
        }
        row.update(overrides)
        return row

    def test_run_consensus_rule_search_ranks_defensive_rules(self):
        df = pd.DataFrame(
            [
                self._row(20250102, "000001", 5.0),
                self._row(20250102, "000002", -4.0, limit_up_count=35),
                self._row(20250103, "000003", 4.0),
                self._row(20250103, "000004", -5.0, sector_ma10_ratio=60),
                self._row(20230102, "000005", -6.0, period="2023", limit_up_count=35),
                self._row(20230103, "000006", 3.0, period="2023", limit_up_count=85),
            ]
        )

        result = run_consensus_rule_search(df, min_trades=2)

        self.assertGreater(len(result), 0)
        best = result.iloc[0]
        self.assertGreaterEqual(best["recent_win_rate"], 70.0)
        self.assertGreaterEqual(best["total_trades"], 2)
        self.assertLessEqual(best["bad_year_return"], 3.0)
        self.assertIn("rule_name", result.columns)
        self.assertIn("score", result.columns)

    def test_apply_rule_supports_high_pattern_cautious_friction_gate(self):
        df = pd.DataFrame(
            [
                self._row(20250102, "000001", 5.0, macro_mode="active", factor_pattern=45, limit_down_count=10),
                self._row(20250102, "000002", 4.0, macro_mode="cautious", factor_pattern=55, limit_down_count=10),
                self._row(20250102, "000003", 6.0, macro_mode="cautious", factor_pattern=65, limit_down_count=10),
            ]
        )
        rule = SearchRule(
            name="high_pattern_exception",
            topn=3,
            min_votes=2,
            min_cautious_friction_pattern=60,
            filter_cautious_down_friction=True,
        )

        result = _apply_rule(df, rule)

        self.assertEqual(["000001.SZ", "000003.SZ"], result["ts_code"].tolist())

    def test_write_consensus_rule_search_outputs_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "snapshot.csv"
            output = root / "search.csv"
            pd.DataFrame(
                [
                    self._row(20250102, "000001", 5.0),
                    self._row(20250103, "000002", 4.0),
                    self._row(20230102, "000003", -2.0, period="2023", limit_up_count=30),
                ]
            ).to_csv(snapshot, index=False)

            summary = write_consensus_rule_search(snapshot, output, min_trades=1)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".md").exists())
            self.assertTrue(output.with_suffix(".json").exists())
            self.assertGreaterEqual(summary["rules_evaluated"], 1)
            self.assertIn("top_rule", summary)


if __name__ == "__main__":
    unittest.main()
