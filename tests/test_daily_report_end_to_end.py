import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from daily_report.facts import FactSources, build_daily_report_facts
from daily_report.selection_snapshot import build_selection_snapshot, get_selection_snapshot, save_selection_snapshot
from daily_report.service import generate_daily_report
from daily_report.store import get_report, search_reports
from daily_report.writer import generate_report_document


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}


class DailyReportEndToEndTest(unittest.TestCase):
    def test_empty_formal_pool_keeps_radar_stock_independent_and_retry_skips(self):
        with TemporaryDirectory() as tmp:
            signal_db = Path(tmp) / "signals.db"
            history_db = Path(tmp) / "history.db"
            snapshot = build_selection_snapshot(
                {
                    "trade_date": "20260722",
                    "market_state": "normal",
                    "market_style": "sideways",
                    "macro_mode": "cautious",
                    "regime": "BEAR_TREND",
                    "operation_mode": "stop",
                    "sentiment_data": {"sentiment": "分化"},
                    "stock_pool": [],
                    "short_observe_pool": [],
                    "longterm_pool": [],
                },
                include_longterm=True,
                longterm_watch_count=0,
                longterm_elite_count=0,
            )
            save_selection_snapshot(signal_db, snapshot)

            def recent_signals(*args, **kwargs):
                return []

            sources = FactSources(
                selection_snapshot=get_selection_snapshot,
                recent_signals=recent_signals,
                active_longterm=lambda *a, **k: [],
                signal_runs=lambda *a, **k: [],
                longterm_runs=lambda *a, **k: [],
                longterm_events=lambda *a, **k: [],
                longterm_audit_summary=lambda *a, **k: {"total_samples": 0, "runs": []},
                sector_radar=lambda *a, **k: {
                    "end_date": "20260722",
                    "summary": {"breadth": "分化"},
                    "healthy": [{"industry": "半导体", "stage": "趋势延续", "heat_score": 72}],
                    "risky": [],
                    "candidates": [{"ts_code": "688981.SH", "name": "中芯国际", "industry": "半导体", "stage": "趋势延续"}],
                },
                concept_news=lambda *a, **k: {"events": [], "reading_events": [], "news": {}},
                radar_decision=lambda radar, news: {"alignment": "趋势主线", "confidence": "中", "focus_industries": ["半导体"]},
                dragon_observation=lambda *a, **k: {
                    "trade_date": "20260722",
                    "display_groups": {
                        "priority": [],
                        "caution": [{"ts_code": "688981.SH", "name": "中芯国际", "industry": "半导体", "late_or_fragile": True, "stage": "高位分歧"}],
                    },
                },
                short_performance=lambda signals, limit: {"count": 0, "closed_count": 0},
            )

            def facts_builder(*args):
                return build_daily_report_facts(*args, sources=sources)

            calls = []
            analyst = {
                "judgements": [{"text": "行业趋势存在，但个股承接仍需确认", "confidence": "中", "evidence_ids": ["sector:半导体:healthy"]}],
                "focus_entities": ["stock:688981.SH"],
                "conflicts": [{"text": "高活跃阶段出现分歧", "evidence_ids": ["stock:688981.SH:caution_view"]}],
                "watch_questions": [{"text": "成交承接能否延续", "evidence_ids": ["stock:688981.SH:activity_view"]}],
            }
            paragraphs = {
                "core_judgement": {"text": "市场仍处在结构分化阶段，行业持续性需要后续确认。", "evidence_ids": ["market:state"], "entity_refs": []},
                "market_context": {"text": "半导体方向保持趋势延续，但扩散强度仍需观察。", "evidence_ids": ["sector:半导体:healthy"], "entity_refs": ["industry:半导体"]},
                "focus": {"text": "中芯国际出现在市场活跃度观察中，同时存在高位分歧和波动风险。", "evidence_ids": ["stock:688981.SH:activity_view", "stock:688981.SH:caution_view"], "entity_refs": ["stock:688981.SH"], "risk_refs": ["stock:688981.SH:risk:0"]},
                "performance_risk": {"text": "本期重点保留可核验的市场事实，不对尚未成熟的表现作外推。", "evidence_ids": ["market:state"], "entity_refs": []},
                "watch_points": {"text": "后续观察中芯国际所在方向的成交承接能否延续。", "evidence_ids": ["stock:688981.SH:activity_view"], "entity_refs": ["stock:688981.SH"], "validation_refs": ["stock:688981.SH:validation:0"]},
            }
            editor = {
                "title": "结构分化延续更需确认行业承接",
                "sections": [
                    {"key": key, "heading": heading, "paragraphs": [paragraphs[key]]}
                    for key, heading in zip(
                        ("core_judgement", "market_context", "focus", "performance_risk", "watch_points"),
                        ("核心判断", "市场脉络", "重点观察", "历史表现与风险", "后续观察"),
                    )
                ],
                "keywords": ["中芯国际", "半导体", "波动风险"],
            }

            def post(url, **kwargs):
                calls.append(kwargs)
                return _Response(analyst if len(calls) == 1 else editor)

            writer = lambda public: generate_report_document(
                public,
                ai_config={
                    "api_key": "test",
                    "base_url": "https://example.test",
                    "model": "deepseek-v4-flash",
                    "fast_model": "deepseek-v4-flash",
                    "reasoning_model": "deepseek-v4-pro",
                    "timeout": 1,
                },
                post=post,
            )
            facts = facts_builder("20260723", "20260722", signal_db, history_db)
            self.assertEqual(facts["source_status"]["short_formal"]["count"], 0)
            self.assertEqual(facts["source_status"]["longterm_active"]["count"], 0)
            observation = facts["observations"][0]
            self.assertEqual(set(observation["sources"]), {"market_radar", "dragon_caution"})

            result = generate_daily_report(
                "20260723", "20260722", signal_db, history_db,
                slot="night", facts_builder=facts_builder, writer=writer,
            )
            self.assertEqual(result["status"], "published")
            report = get_report(signal_db, "20260723")
            self.assertIn("中芯国际", report["body_text"])
            self.assertIn("波动风险", report["body_text"])
            for banned in ("AI", "Agent", "profile", "BEAR_TREND", "评分", "数据库", "模型"):
                self.assertNotIn(banned, report["body_text"])
            self.assertEqual(search_reports(signal_db, query="中芯国际")[0]["report_date"], "20260723")
            self.assertEqual(search_reports(signal_db, start="20260723", end="20260723")[0]["report_date"], "20260723")

            conn = sqlite3.connect(signal_db)
            try:
                self.assertEqual(conn.execute("select count(*) from daily_reports").fetchone()[0], 1)
                self.assertEqual(conn.execute("select count(*) from daily_report_versions").fetchone()[0], 1)
            finally:
                conn.close()

            call_count = len(calls)
            retry = generate_daily_report(
                "20260723", "20260722", signal_db, history_db,
                slot="morning", retry_if_missing=True, facts_builder=facts_builder, writer=writer,
            )
            self.assertEqual(retry["status"], "skipped")
            self.assertEqual(len(calls), call_count)


if __name__ == "__main__":
    unittest.main()
