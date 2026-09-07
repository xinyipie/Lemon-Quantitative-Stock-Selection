import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from daily_report.store import publish_report


app_module = importlib.import_module("web_app.app")


def _document(title, marker=""):
    keys = ("core_judgement", "market_context", "focus", "performance_risk", "watch_points")
    headings = ("核心判断", "市场脉络", "重点观察", "历史表现与风险", "后续观察")
    return {
        "title": title,
        "sections": [
            {"key": key, "heading": heading, "paragraphs": [{"text": f"{heading}内容{marker}", "evidence_ids": ["hidden:id"], "entity_refs": []}]}
            for key, heading in zip(keys, headings)
        ],
        "keywords": ["半导体"],
    }


class DailyReportWebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Path(self.tmp.name) / "signals.db"
        for date, title, body, marker in (
            ("20260721", "市场缩量整理等待方向进一步明确", "消费行业观察", ""),
            ("20260722", "半导体分化加大更看重成交承接", "半导体行业分化，风险仍需确认", "<script>alert(1)</script>"),
            ("20260723", "行业轮动加快持续性仍有待确认", "银行行业观察", ""),
        ):
            publish_report(
                self.db,
                report_date=date,
                market_date="20260722",
                title=title,
                document=_document(title, marker),
                body_text=body,
                keywords=["半导体"] if date == "20260722" else ["银行"],
                input_hash=date,
                data_cutoff="2026-07-22 15:00:00",
                news_cutoff="2026-07-23 08:30:00",
            )
        self.patch = patch.object(app_module, "DEFAULT_SIGNAL_DB_PATH", self.db)
        self.patch.start()
        self.client = TestClient(app_module.app)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_archive_searches_by_keyword_and_date(self):
        response = self.client.get("/reports?q=半导体&start=20260701&end=20260731")
        self.assertEqual(response.status_code, 200)
        self.assertIn("半导体分化加大更看重成交承接", response.text)
        self.assertIn("2026-07-22", response.text)
        self.assertNotIn("市场缩量整理等待方向进一步明确", response.text)

    def test_detail_is_one_escaped_article_with_dates_and_navigation(self):
        response = self.client.get("/reports/20260722")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count('<article class="research-report">'), 1)
        for heading in ("核心判断", "市场脉络", "重点观察", "历史表现与风险", "后续观察"):
            self.assertIn(heading, response.text)
        self.assertIn("报告日期：2026-07-22", response.text)
        self.assertIn("行情截至：2026-07-22", response.text)
        self.assertIn("数据截至：2026-07-22 15:00:00", response.text)
        self.assertIn("消息截至：2026-07-23 08:30:00", response.text)
        self.assertIn("/reports/20260721", response.text)
        self.assertIn("/reports/20260723", response.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", response.text)
        self.assertNotIn("<script>alert(1)</script>", response.text)
        self.assertNotIn("hidden:id", response.text)
        for banned in ("AI", "Agent", "profile", "BEAR_TREND", "评分", "数据库", "模型"):
            self.assertNotIn(banned, response.text)

    def test_unknown_report_returns_404(self):
        self.assertEqual(self.client.get("/reports/19990101").status_code, 404)


if __name__ == "__main__":
    unittest.main()
