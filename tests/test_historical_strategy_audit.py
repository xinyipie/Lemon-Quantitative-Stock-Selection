import tempfile
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.historical_strategy_audit import (
    build_strategy_audit,
    load_matrix_files,
    write_strategy_audit,
)


class HistoricalStrategyAuditTest(unittest.TestCase):
    def _matrix_row(self, strategy: str, period: str, trades: int, win: float, ret: float, **overrides):
        row = {
            "strategy": strategy,
            "period": period,
            "start": "20250101",
            "end": "20251231",
            "returncode": 0,
            "metrics_file": "",
            "total_trades": trades,
            "win_rate": win,
            "total_return_pct": ret,
            "max_drawdown_pct": 2.0,
            "avg_profit_after_fee": ret / trades if trades else 0.0,
            "max_consecutive_loss": 1,
            "avg_mfe_pct": 6.0,
            "avg_mae_pct": -1.5,
            "hit_3pct_rate": 80.0,
            "hit_5pct_rate": 55.0,
        }
        row.update(overrides)
        return row

    def test_build_strategy_audit_prefers_robust_return_over_tiny_perfect_sample(self):
        df = pd.DataFrame(
            [
                self._matrix_row("tiny_perfect", "2024", 1, 100.0, 5.0, hit_5pct_rate=100.0),
                self._matrix_row("tiny_perfect", "2025", 2, 100.0, 10.0, hit_5pct_rate=100.0),
                self._matrix_row("tiny_perfect", "2026H1", 1, 100.0, 3.0, hit_5pct_rate=100.0),
                self._matrix_row("steady", "2023", 4, 75.0, 12.0),
                self._matrix_row("steady", "2024", 4, 75.0, 14.0),
                self._matrix_row("steady", "2025", 8, 87.5, 60.0),
                self._matrix_row("steady", "2026H1", 4, 100.0, 18.0),
            ]
        )

        audit = build_strategy_audit(df, min_main_trades=10, min_confidence_trades=4)

        self.assertEqual("steady", audit.iloc[0]["strategy"])
        self.assertEqual("main_candidate", audit.iloc[0]["tier"])
        tiny = audit[audit["strategy"] == "tiny_perfect"].iloc[0]
        self.assertEqual("watch_only", tiny["tier"])
        self.assertLess(tiny["robust_score"], audit.iloc[0]["robust_score"])

    def test_load_matrix_files_deduplicates_strategy_period_with_latest_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            older = root / "ten_year_strategy_matrix_20260101_010101.csv"
            newer = root / "ten_year_strategy_matrix_20260102_010101.csv"
            pd.DataFrame([self._matrix_row("demo", "2025", 1, 0.0, -5.0)]).to_csv(older, index=False)
            pd.DataFrame([self._matrix_row("demo", "2025", 3, 100.0, 9.0)]).to_csv(newer, index=False)

            loaded = load_matrix_files(root)

        self.assertEqual(1, len(loaded))
        self.assertEqual(3, int(loaded.iloc[0]["total_trades"]))
        self.assertEqual("ten_year_strategy_matrix_20260102_010101.csv", loaded.iloc[0]["source_file"])

    def test_write_strategy_audit_outputs_csv_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            matrix = root / "ten_year_strategy_matrix_20260102_010101.csv"
            output = root / "audit.csv"
            pd.DataFrame(
                [
                    self._matrix_row("steady", "2024", 4, 75.0, 14.0),
                    self._matrix_row("steady", "2025", 8, 87.5, 60.0),
                    self._matrix_row("steady", "2026H1", 4, 100.0, 18.0),
                ]
            ).to_csv(matrix, index=False)

            summary = write_strategy_audit(root, output, min_main_trades=10, min_confidence_trades=4)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            self.assertTrue(output.with_suffix(".md").exists())
            self.assertEqual("steady", summary["top_strategy"])


if __name__ == "__main__":
    unittest.main()
