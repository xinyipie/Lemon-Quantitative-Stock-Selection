from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from daily_report.facts import FactSources, build_daily_report_facts
from daily_report.publication import build_public_facts


class DailyReportNewsContractTest(unittest.TestCase):
    def test_report_uses_market_date_news_with_traceable_fields(self):
        calls = []

        def concept_news(*args, **kwargs):
            calls.append((kwargs.get("today"), kwargs.get("limit")))
            return {
                "news": {"source_date": "20260812"},
                "reading_events": [
                    {
                        "title": "产业政策发布",
                        "industry": "半导体",
                        "impact": "positive",
                        "effect_summary": "政策支持产业升级",
                        "source_name": "工业和信息化部",
                        "source_url": "https://example.test/policy",
                        "publish_time": "2026-08-12 18:30:00",
                        "mapped_industries": ["半导体"],
                        "verification_points": ["观察后续项目落地"],
                        "risk_note": "政策传导仍需时间",
                    }
                ],
            }

        sources = FactSources(
            selection_snapshot=lambda *a, **k: {
                "trade_date": "20260812",
                "created_at": "2026-08-12T16:00:00+08:00",
                "market": {"regime": "BULL_TREND", "market_style": "sideways", "sentiment": {}},
                "short_scan": {"status": "completed_empty"},
                "longterm_scan": {"status": "not_triggered"},
            },
            recent_signals=lambda *a, **k: [],
            active_longterm=lambda *a, **k: [],
            signal_runs=lambda *a, **k: [],
            longterm_runs=lambda *a, **k: [],
            longterm_events=lambda *a, **k: [],
            longterm_audit_summary=lambda *a, **k: {},
            sector_radar=lambda *a, **k: {"healthy": [], "risky": [], "candidates": []},
            concept_news=concept_news,
            radar_decision=lambda *a, **k: {},
            dragon_observation=lambda *a, **k: {},
            short_performance=lambda *a, **k: {},
        )

        with TemporaryDirectory() as tmpdir:
            facts = build_daily_report_facts(
                "20260813",
                "20260812",
                Path(tmpdir) / "signals.db",
                Path(tmpdir) / "history.db",
                sources=sources,
            )

        public = build_public_facts(facts)
        event = public["events"][0]
        self.assertEqual(calls, [("20260812", 50)])
        self.assertEqual(event["source_name"], "工业和信息化部")
        self.assertEqual(event["publish_time"], "2026-08-12 18:30:00")
        self.assertEqual(event["source_url"], "https://example.test/policy")
        self.assertEqual(event["effect_summary"], "政策支持产业升级")
        self.assertEqual(event["mapped_industries"], ["半导体"])
        self.assertEqual(event["verification_points"], ["观察后续项目落地"])
        self.assertEqual(event["risk_note"], "政策传导仍需时间")


if __name__ == "__main__":
    unittest.main()
