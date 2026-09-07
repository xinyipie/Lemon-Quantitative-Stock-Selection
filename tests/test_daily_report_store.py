import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from daily_report.store import (
    begin_generation,
    finish_generation,
    get_adjacent_report_dates,
    get_latest_report,
    get_report,
    publish_report,
    search_reports,
)


class DailyReportStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Path(self.tmp.name) / "signals.db"

    def tearDown(self):
        self.tmp.cleanup()

    def version_count(self, report_date):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "select count(*) from daily_report_versions where report_date = ?",
                (report_date,),
            ).fetchone()[0]
        finally:
            conn.close()

    def publish(self, report_date, title, body, input_hash):
        return publish_report(
            self.db,
            report_date=report_date,
            market_date="20260722",
            title=title,
            document={"title": title, "sections": []},
            body_text=body,
            keywords=["半导体", "贵州茅台", "600519.SH"],
            input_hash=input_hash,
            data_cutoff="2026-07-22 15:00:00",
            news_cutoff="2026-07-23 08:30:00",
        )

    def test_publish_keeps_versions_and_searches_current_text(self):
        self.assertTrue(begin_generation(self.db, "20260723", "night"))
        first_id = self.publish("20260723", "缩量分化延续仍需等待确认", "半导体扩散不足，贵州茅台仅作风险样本。", "hash-1")
        finish_generation(self.db, "20260723", "published", "")
        second_id = self.publish("20260723", "缩量分化之下更看重持续性", "半导体方向尚未形成行业扩散。", "hash-2")

        self.assertGreater(second_id, first_id)
        self.assertEqual(get_report(self.db, "20260723")["title"], "缩量分化之下更看重持续性")
        self.assertEqual(search_reports(self.db, query="半导体")[0]["report_date"], "20260723")
        self.assertEqual(self.version_count("20260723"), 2)

    def test_retry_gate_skips_published_date_and_reopens_failed_date(self):
        self.assertTrue(begin_generation(self.db, "20260723", "night"))
        finish_generation(self.db, "20260723", "failed", "writer timeout")
        self.assertTrue(begin_generation(self.db, "20260723", "morning", retry_if_missing=True))
        finish_generation(self.db, "20260723", "published", "")
        self.assertFalse(begin_generation(self.db, "20260723", "morning", retry_if_missing=True))

    def test_failed_new_date_keeps_last_published_report(self):
        self.publish("20260722", "前一交易日市场保持结构分化", "医药板块活跃。", "old")
        self.assertTrue(begin_generation(self.db, "20260723", "night"))
        finish_generation(self.db, "20260723", "failed", "bad output")
        self.assertEqual(get_latest_report(self.db)["report_date"], "20260722")

    def test_date_filters_and_adjacent_dates(self):
        for date in ("20260721", "20260722", "20260723"):
            self.publish(date, f"{date}市场结构观察记录", "风险与行业事件。", date)
        self.assertEqual(
            get_adjacent_report_dates(self.db, "20260722"),
            ("20260721", "20260723"),
        )
        rows = search_reports(self.db, start="2026-07-22", end="2026-07-22")
        self.assertEqual([row["report_date"] for row in rows], ["20260722"])


if __name__ == "__main__":
    unittest.main()
