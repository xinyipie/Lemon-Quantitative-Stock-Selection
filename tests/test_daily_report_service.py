import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from daily_report.service import generate_daily_report
from daily_report.store import get_generation_job, get_report
from daily_report.writer import build_deterministic_report_document


def _facts(can_publish=True):
    return {
        "report_date": "20260723",
        "market_date": "20260722",
        "cutoffs": {"data": "2026-07-22 15:00:00", "news": "2026-07-23 08:30:00"},
        "market": {"regime": "BULL_TREND", "market_style": "sideways", "sentiment": {"limit_up_count": 45}},
        "market_radar_decision": {},
        "source_status": {},
        "sectors": {"healthy": [], "risky": []},
        "events": [],
        "observations": [],
        "performance": {},
        "evidence_index": {"market:state": {"label": "市场状态", "values": [45], "payload": {}}},
        "completeness": {"can_publish": can_publish, "confidence_cap": "中", "warnings": []},
        "input_hash": "facts-hash",
    }


def _document(title="缩量分化下更需观察承接持续性"):
    keys = ("core_judgement", "market_context", "focus", "performance_risk", "watch_points")
    return {
        "title": title,
        "sections": [
            {"key": key, "heading": key, "paragraphs": [{"text": "市场活跃度为45，后续仍需观察。", "evidence_ids": ["market:state"], "entity_refs": []}]}
            for key in keys
        ],
        "keywords": [],
        "ai_model": "deepseek-v4-pro",
        "ai_thinking": "high",
        "ai_pipeline": "two_pass_reasoning",
    }


class DailyReportServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.signal_db = Path(self.tmp.name) / "signals.db"
        self.history_db = Path(self.tmp.name) / "history.db"

    def tearDown(self):
        self.tmp.cleanup()

    def generate(self, **kwargs):
        return generate_daily_report(
            "20260723", "20260722", self.signal_db, self.history_db,
            facts_builder=kwargs.pop("facts_builder", lambda *args: _facts()),
            writer=kwargs.pop("writer", lambda public: _document()),
            reviser=kwargs.pop("reviser", lambda public, document, errors: None),
            fallback_builder=kwargs.pop("fallback_builder", lambda public: None),
            **kwargs,
        )

    def test_valid_document_is_published(self):
        result = self.generate(slot="night")
        self.assertEqual(result["status"], "published")
        self.assertEqual(get_report(self.signal_db, "20260723")["title"], _document()["title"])

    def test_incomplete_facts_record_failure_without_public_report(self):
        result = self.generate(facts_builder=lambda *args: _facts(False))
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(get_report(self.signal_db, "20260723"))
        self.assertEqual(get_generation_job(self.signal_db, "20260723")["status"], "failed")

    def test_writer_failure_keeps_last_valid_version(self):
        self.assertEqual(self.generate()["status"], "published")
        result = self.generate(force=True, writer=lambda public: None)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(get_report(self.signal_db, "20260723")["title"], _document()["title"])

    def test_generated_ai_document_is_published_without_content_validation(self):
        calls = []
        result = self.generate(
            writer=lambda public: _document("bad"),
            reviser=lambda public, document, errors: calls.append("reviser"),
            fallback_builder=lambda public: calls.append("fallback"),
        )
        self.assertEqual(result["status"], "published")
        self.assertEqual(calls, [])
        report = get_report(self.signal_db, "20260723")
        self.assertEqual(report["title"], "bad")
        self.assertEqual(report["document"]["generation_mode"], "pro_reasoning")

    def test_missing_ai_document_uses_deterministic_fallback(self):
        result = self.generate(
            writer=lambda public: None,
            fallback_builder=build_deterministic_report_document,
        )
        self.assertEqual(result["status"], "published")
        report = get_report(self.signal_db, "20260723")
        self.assertEqual(report["document"]["generation_mode"], "data_fallback")

    def test_generated_document_is_not_blocked_by_model_metadata(self):
        document = _document()
        document["ai_model"] = "deepseek-v4-flash"
        result = self.generate(writer=lambda public: document)
        self.assertEqual(result["status"], "published")

    def test_missing_ai_and_missing_fallback_save_no_report(self):
        result = self.generate(writer=lambda public: None, fallback_builder=lambda public: None)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(get_report(self.signal_db, "20260723"))

    def test_deterministic_fallback_uses_concrete_sectors_and_observations(self):
        public_facts = {
            "market": {"trend_environment": "弱势环境中的强修复", "style": "结构分化", "sentiment": "高涨", "evidence_id": "market:state"},
            "sectors": [
                {"entity_ref": "industry:黄金", "industry": "黄金", "stage": "趋势延续", "view": "趋势观察", "evidence_id": "sector:黄金:healthy"},
                {"entity_ref": "industry:乳制品", "industry": "乳制品", "stage": "退潮中", "view": "风险观察", "evidence_id": "sector:乳制品:risk"},
            ],
            "events": [],
            "observations": [{
                "entity_ref": "stock:600988.SH", "name": "赤峰黄金", "industry": "黄金",
                "evidence_ids": ["stock:600988.SH:activity_view"],
                "validation": [{"ref": "stock:600988.SH:validation:0", "text": "观察承接"}],
            }],
            "performance": {"short_cycle": {"average_return": -0.4, "evidence_id": "performance:short:recent"}},
            "evidence": {
                "market:state": {"values": ["弱势环境中的强修复", "结构分化", "高涨"]},
                "sector:黄金:healthy": {"values": ["黄金", "趋势延续"]},
                "sector:乳制品:risk": {"values": ["乳制品", "退潮中"]},
                "stock:600988.SH:activity_view": {"values": ["观察承接"]},
                "performance:short:recent": {"values": [-0.4]},
            },
        }
        document = build_deterministic_report_document(public_facts)
        body = " ".join(paragraph["text"] for section in document["sections"] for paragraph in section["paragraphs"])
        self.assertIn("黄金", body)
        self.assertIn("赤峰黄金", body)
        self.assertIn("乳制品", body)
        self.assertGreater(sum(len(section["paragraphs"]) for section in document["sections"]), 5)
        self.assertEqual(document["generation_mode"], "data_fallback")
    def test_morning_retry_skips_existing_report_without_calling_dependencies(self):
        self.assertEqual(self.generate()["status"], "published")
        calls = []
        result = self.generate(
            retry_if_missing=True,
            slot="morning",
            facts_builder=lambda *args: calls.append("facts"),
            writer=lambda public: calls.append("writer"),
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(calls, [])

    def test_force_creates_new_version(self):
        self.generate()
        self.generate(force=True)
        conn = sqlite3.connect(self.signal_db)
        try:
            count = conn.execute("select count(*) from daily_report_versions where report_date='20260723'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
