from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from daily_report.selection_snapshot import (
    build_selection_snapshot,
    get_selection_snapshot,
    save_selection_snapshot,
)


class DailySelectionSnapshotTest(unittest.TestCase):
    def test_round_trip_preserves_empty_and_not_triggered_states(self):
        selection = {
            "trade_date": "20260722",
            "market_state": "caution",
            "market_style": "sideways",
            "macro_mode": "cautious",
            "regime": "BEAR_TREND",
            "regime_data": {"price_vs_ma60_pct": -3.2, "ma60_slope_pct": -0.04},
            "operation_mode": "stop",
            "sentiment_data": {"limit_up_count": 31, "limit_down_count": 9, "sentiment": "偏弱"},
            "stock_pool": pd.DataFrame(),
            "short_observe_pool": pd.DataFrame(),
            "longterm_pool": pd.DataFrame(),
        }
        snapshot = build_selection_snapshot(selection, True, 0, 0)
        self.assertEqual(snapshot["short_scan"]["status"], "completed_empty")
        self.assertEqual(snapshot["longterm_scan"]["status"], "not_triggered")
        self.assertEqual(snapshot["market"]["regime"], "BEAR_TREND")

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "signals.db"
            save_selection_snapshot(db, snapshot)
            self.assertEqual(get_selection_snapshot(db, "20260722"), snapshot)

    def test_disabled_and_completed_longterm_states_are_distinct(self):
        selection = {
            "trade_date": "20260722",
            "regime": "BULL_TREND",
            "stock_pool": pd.DataFrame([{"code": "000001"}]),
            "short_observe_pool": pd.DataFrame(),
            "longterm_pool": pd.DataFrame([{"code": "600519"}]),
        }
        disabled = build_selection_snapshot(selection, False, 0, 0)
        completed = build_selection_snapshot(selection, True, 1, 1)
        self.assertEqual(disabled["longterm_scan"]["status"], "disabled")
        self.assertEqual(completed["longterm_scan"]["status"], "completed_with_results")


if __name__ == "__main__":
    unittest.main()
