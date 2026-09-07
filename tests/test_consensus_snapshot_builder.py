import tempfile
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.consensus_snapshot_builder import build_consensus_snapshot, write_consensus_snapshot


class ConsensusSnapshotBuilderTest(unittest.TestCase):
    def _row(self, code: str, **overrides):
        row = {
            "select_date": 20250102,
            "buy_date": 20250103,
            "ts_code": f"{code}.SZ",
            "code": code,
            "score": 70.0,
            "original_score": 70.0,
            "factor_inflow": 100.0,
            "factor_wyckoff": 68.0,
            "factor_sector": 40.0,
            "factor_pattern": 30.0,
            "factor_drawdown": 70.0,
            "drawdown_from_high": 5.0,
            "volume_ratio": 2.1,
            "change": 3.0,
            "market_style": "weak_momentum",
            "macro_mode": "active",
            "regime": "BULL_TREND",
            "sector_ma10_ratio": 82.0,
            "market_index_change": 0.1,
            "limit_up_count": 90,
            "limit_down_count": 5,
            "ret_5d": 4.0,
            "mfe_pct": 8.0,
            "mae_pct": -1.5,
        }
        row.update(overrides)
        return row

    def test_build_consensus_snapshot_replays_virtual_gates_and_votes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest_dir = root / "backtest_results"
            reports_dir = root / "reports"
            backtest_dir.mkdir()
            reports_dir.mkdir()

            pd.DataFrame(
                [
                    self._row("000001", factor_sector=40.0),
                    self._row("000002", factor_sector=72.0),
                    self._row("000003", factor_inflow=50.0),
                ]
            ).to_csv(backtest_dir / "ic_v19.csv", index=False)
            pd.DataFrame(
                [
                    self._row("000001", factor_sector=40.0),
                    self._row("000002", factor_sector=72.0),
                ]
            ).to_csv(backtest_dir / "ic_v25.csv", index=False)
            pd.DataFrame(
                [
                    self._row("000001", factor_sector=40.0),
                    self._row("000002", factor_sector=72.0),
                    self._row("000004", factor_sector=40.0, factor_inflow=50.0),
                ]
            ).to_csv(backtest_dir / "ic_v27.csv", index=False)

            mapping = pd.DataFrame(
                [
                    {
                        "strategy": "v19_top1_hold3",
                        "period": "2025",
                        "ic_file": str(backtest_dir / "ic_v19.csv"),
                    },
                    {
                        "strategy": "v25_top1_hold3",
                        "period": "2025",
                        "ic_file": str(backtest_dir / "ic_v25.csv"),
                    },
                    {
                        "strategy": "v27_top1_hold3",
                        "period": "2025",
                        "ic_file": str(backtest_dir / "ic_v27.csv"),
                    },
                ]
            )
            map_path = reports_dir / "map.csv"
            mapping.to_csv(map_path, index=False)

            snapshot = build_consensus_snapshot(map_path)

            self.assertEqual(["000001.SZ", "000002.SZ"], snapshot["ts_code"].tolist())
            votes = snapshot.set_index("ts_code")["consensus_votes"].to_dict()
            self.assertEqual(3, votes["000001.SZ"])
            self.assertEqual(3, votes["000002.SZ"])
            self.assertIn("v19", snapshot.loc[0, "consensus_profiles"])
            self.assertIn("virtual_rank", snapshot.columns)

    def test_write_consensus_snapshot_outputs_csv_and_summary_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest_dir = root / "backtest_results"
            reports_dir = root / "reports"
            backtest_dir.mkdir()
            reports_dir.mkdir()
            ic_path = backtest_dir / "ic_v19.csv"
            pd.DataFrame([self._row("000001")]).to_csv(ic_path, index=False)
            map_path = reports_dir / "map.csv"
            pd.DataFrame(
                [
                    {
                        "strategy": "v19_top1_hold3",
                        "period": "2025",
                        "ic_file": str(ic_path),
                    }
                ]
            ).to_csv(map_path, index=False)

            output = reports_dir / "snapshot.csv"
            summary = write_consensus_snapshot(map_path, output)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            self.assertEqual(1, summary["rows"])
            self.assertEqual(1, summary["dates"])


if __name__ == "__main__":
    unittest.main()
