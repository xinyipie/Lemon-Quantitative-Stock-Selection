import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from signal_store import SignalRecord, SignalStore
from web_app.services.signal_service import get_recent_signals, summarize_short_strategy_cards


class ShortStrategyShowcaseTest(unittest.TestCase):
    def _record(self, score, ret_5d):
        return SignalRecord(
            ts_code="600000.SH",
            name="浦发银行",
            industry="银行",
            rank=1,
            score=score,
            pool_type="short_top",
            reason="测试",
            factors={"ret_5d": ret_5d, "entry_open": 10.0},
        )

    def test_same_stock_same_day_is_preserved_across_strategies(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "signals.sqlite"
            store = SignalStore(db)
            official = store.record_run("20260812", "short", "profile_v9_sector_quality_guard", "live", "daily")
            observe = store.record_run("20260812", "short", "short_live_observe_best_balance", "live_observe", "daily")
            shadow = store.record_run("20260812", "short", "short_defensive_quality_reentry_v16", "research_shadow", "frozen_v16")
            store.update_pool(official, "20260812", "short", "profile_v9_sector_quality_guard", [self._record(68.3, 2.0)])
            store.update_pool(observe, "20260812", "short", "short_live_observe_best_balance", [self._record(62.4, -1.0)])
            store.update_pool(shadow, "20260812", "short", "short_defensive_quality_reentry_v16", [self._record(0.08, 3.0)])
            store.close()

            signals = get_recent_signals(
                db,
                history_db=None,
                limit=20,
                source=["live", "live_observe", "research_shadow"],
                mode="short",
            )

            self.assertEqual(len(signals), 3)
            self.assertEqual({item["strategy_key"] for item in signals}, {"steady", "balance", "repair"})

    def test_strategy_cards_use_only_each_strategys_completed_returns(self):
        signals = [
            {"strategy_key": "steady", "source": "live", "profile": "profile_v9_sector_quality_guard", "performance": {"ret_5d": 2.0}},
            {"strategy_key": "steady", "source": "live", "profile": "profile_v9_sector_quality_guard", "performance": {"ret_5d": -1.0}},
            {"strategy_key": "balance", "source": "live_observe", "profile": "short_live_observe_best_balance", "performance": {"ret_5d": 4.0}},
            {"strategy_key": "repair", "source": "research_shadow", "profile": "short_defensive_quality_reentry_v16", "performance": {"ret_5d": None}},
        ]

        cards = {item["key"]: item for item in summarize_short_strategy_cards(signals)}

        self.assertEqual(cards["all"]["count"], 4)
        self.assertEqual(cards["steady"]["win_rate_text"], "50.0%")
        self.assertEqual(cards["balance"]["avg_return_text"], "+4.00%")
        self.assertEqual(cards["repair"]["win_rate_text"], "待积累")

    def test_template_has_compact_light_strategy_controls(self):
        root = Path(__file__).resolve().parents[1]
        partial = (root / "web_app/templates/partials/short_strategy_selector.html").read_text(encoding="utf-8")
        template = (root / "web_app/templates/signals.html").read_text(encoding="utf-8")

        self.assertIn("grid-template-columns:repeat(4", partial)
        self.assertIn("width:17px;height:17px", partial)
        self.assertNotIn("strategy-compact-tabs", partial)
        self.assertIn('name="strategy"', template)
        self.assertGreater(
            template.index('{% include "partials/short_strategy_selector.html" %}'),
            template.index("历史信号结果"),
        )
        self.assertIn("shadow-strategy", template)


if __name__ == "__main__":
    unittest.main()
