import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.strategy_delta_audit import build_delta_audit, write_delta_audit


class StrategyDeltaAuditTest(unittest.TestCase):
    def _row(self, date: int, code: str, profit: float, **overrides):
        row = {
            "select_date": date,
            "ts_code": f"{code}.SZ",
            "name": code,
            "profit_after_fee": profit,
            "profit_pct": profit + 0.36,
            "mfe_pct": max(profit, 0) + 3.0,
            "mae_pct": -1.0 if profit > 0 else -4.0,
            "hit_3pct": profit > 0,
            "hit_5pct": profit >= 3.0,
            "market_style": "weak_momentum",
            "macro_mode": "active",
            "factor_sector": 40.0,
            "factor_pattern": 60.0,
            "consensus_avg_rank": 1.2,
            "consensus_score": 300.0,
        }
        row.update(overrides)
        return row

    def test_build_delta_audit_summarizes_common_and_unique_trades(self):
        base = pd.DataFrame(
            [
                self._row(20250102, "000001", 5.0),
                self._row(20250103, "000002", -3.0, consensus_avg_rank=2.0),
                self._row(20250104, "000003", 4.0, consensus_avg_rank=1.8),
            ]
        )
        compare = pd.DataFrame(
            [
                self._row(20250102, "000001", 5.0),
                self._row(20250105, "000004", 6.0, consensus_avg_rank=1.1),
            ]
        )

        result = build_delta_audit(base, compare, base_label="v35", compare_label="v39")

        by_bucket = {row["bucket"]: row for row in result["summary"]}
        self.assertEqual(1, by_bucket["common"]["trades"])
        self.assertEqual(100.0, by_bucket["common"]["hit_3pct_rate"])
        self.assertEqual(2, by_bucket["v35_only"]["trades"])
        self.assertEqual(50.0, by_bucket["v35_only"]["win_rate"])
        self.assertEqual(1.0, by_bucket["v35_only"]["total_profit_after_fee"])
        self.assertEqual(1, by_bucket["v39_only"]["trades"])
        self.assertEqual(["000002.SZ", "000003.SZ"], result["base_only"]["ts_code"].tolist())

    def test_write_delta_audit_outputs_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_path = root / "base.csv"
            compare_path = root / "compare.csv"
            output = root / "delta.csv"
            pd.DataFrame([self._row(20250102, "000001", 5.0)]).to_csv(base_path, index=False)
            pd.DataFrame([self._row(20250103, "000002", 6.0)]).to_csv(compare_path, index=False)

            summary = write_delta_audit(base_path, compare_path, output, base_label="base", compare_label="compare")

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            self.assertTrue(output.with_suffix(".md").exists())
            self.assertEqual("base", summary["base_label"])
            self.assertEqual("compare", summary["compare_label"])


if __name__ == "__main__":
    unittest.main()
