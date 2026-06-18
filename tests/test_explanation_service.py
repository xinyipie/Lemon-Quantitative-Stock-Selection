import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from history_store import HistoryStore
from signal_store import SignalRecord, SignalStore
from web_app.services.explanation_service import (
    build_fallback_explanation,
    get_or_create_signal_explanation,
)


class ExplanationServiceTest(unittest.TestCase):
    def test_fallback_explanation_is_structured_and_plain(self):
        signal = {
            "trade_date": "20260525",
            "ts_code": "000012.SZ",
            "display_name": "南玻A",
            "score": 66.57,
            "basis_text": "v9分 66.6 / 资金70 / 板块52 / 形态10",
            "performance_text": "5日-10.87% / MFE+8.24% / MAE-8.24%",
            "quality_label": "有效信号",
            "outcome_label": "短线亏损",
            "process_label": "曾冲高回落",
        }

        doc = build_fallback_explanation(signal)

        self.assertEqual(doc["title"], "南玻A 000012.SZ 信号解释")
        self.assertIn("曾冲高回落", doc["summary"])
        self.assertTrue(doc["positives"])
        self.assertTrue(doc["risks"])
        self.assertIn("不构成收益承诺", doc["confidence_note"])

    def test_get_or_create_signal_explanation_calls_ai_once_and_caches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history_db = tmp / "history.db"
            signal_db = tmp / "signals.db"
            history = HistoryStore(history_db)
            try:
                history.upsert_dataframe(
                    "stock_basic",
                    pd.DataFrame([{"ts_code": "000012.SZ", "symbol": "000012", "name": "南玻A", "industry": "玻璃"}]),
                )
            finally:
                history.close()

            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260525", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20260525",
                    mode="short",
                    profile="short_v9_final",
                    records=[
                        SignalRecord(
                            ts_code="000012.SZ",
                            name="",
                            industry="",
                            rank=1,
                            score=66.57,
                            reason="短线v9 Top1",
                            factors={
                                "ret_5d": -10.87,
                                "mfe_pct": 8.24,
                                "mae_pct": -8.24,
                                "factor_inflow": 70,
                                "factor_sector": 52,
                                "factor_pattern": 10,
                            },
                        )
                    ],
                )
            finally:
                store.close()

            calls = {"count": 0}

            def fake_post(*args, **kwargs):
                calls["count"] += 1

                class Response:
                    def raise_for_status(self):
                        return None

                    def json(self):
                        content = json.dumps(
                            {
                                "title": "南玻A 短线信号解释",
                                "summary": "资金与板块有一定支持，但形态确认不足，后续冲高回落说明承接不稳。",
                                "positives": ["资金分较高，说明当时有资金线索。"],
                                "risks": ["5日收益转负，且过程出现冲高回落。"],
                                "watch_plan": "只适合等待重新站稳关键位后观察。",
                                "invalidation": "若继续放量下跌或跌破关键支撑，应放弃。",
                                "style": "短线观察",
                                "confidence_note": "仅解释已有数据，不构成收益承诺。",
                            },
                            ensure_ascii=False,
                        )
                        return {"choices": [{"message": {"content": content}}]}

                return Response()

            cfg = {
                "api_key": "fake-key",
                "base_url": "https://example.test/chat",
                "model": "deepseek-chat",
                "temperature": 0.1,
                "max_tokens": 1000,
                "timeout": 5,
            }
            first = get_or_create_signal_explanation(
                "20260525",
                "000012.SZ",
                signal_db=signal_db,
                history_db=history_db,
                ai_config=cfg,
                post=fake_post,
            )
            second = get_or_create_signal_explanation(
                "20260525",
                "000012.SZ",
                signal_db=signal_db,
                history_db=history_db,
                ai_config=cfg,
                post=fake_post,
            )

            conn = sqlite3.connect(signal_db)
            try:
                rows = conn.execute("select count(*) from ai_analysis_documents").fetchone()[0]
                stored = conn.execute(
                    """
                    select doc_type, trade_date, ts_code, mode, profile, model,
                           prompt_version, input_hash, summary
                    from ai_analysis_documents
                    """
                ).fetchone()
            finally:
                conn.close()

        self.assertEqual(calls["count"], 1)
        self.assertEqual(rows, 1)
        self.assertEqual(stored[0], "signal_explanation")
        self.assertEqual(stored[1], "20260525")
        self.assertEqual(stored[2], "000012.SZ")
        self.assertEqual(stored[3], "short")
        self.assertEqual(stored[4], "short_v9_final")
        self.assertEqual(stored[5], "deepseek-chat")
        self.assertTrue(stored[6].startswith("signal_explanation_v"))
        self.assertTrue(stored[7])
        self.assertIn("资金与板块", stored[8])
        self.assertEqual(first["doc"]["style"], "短线观察")
        self.assertEqual(second["source"], "cache")

    def test_reads_legacy_ai_explanations_when_document_table_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history_db = tmp / "history.db"
            signal_db = tmp / "signals.db"
            history = HistoryStore(history_db)
            try:
                history.upsert_dataframe(
                    "stock_basic",
                    pd.DataFrame([{"ts_code": "000012.SZ", "symbol": "000012", "name": "南玻A", "industry": "玻璃"}]),
                )
            finally:
                history.close()

            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260525", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20260525",
                    mode="short",
                    profile="short_v9_final",
                    records=[SignalRecord(ts_code="000012.SZ", score=66.57)],
                )
            finally:
                store.close()

            legacy_doc = build_fallback_explanation(
                {
                    "trade_date": "20260525",
                    "ts_code": "000012.SZ",
                    "display_name": "南玻A",
                    "display_code": "000012.SZ",
                    "quality_label": "有效信号",
                    "outcome_label": "震荡",
                    "process_label": "波动正常",
                }
            )
            conn = sqlite3.connect(signal_db)
            try:
                conn.execute(
                    """
                    create table ai_explanations (
                        cache_key text primary key,
                        trade_date text,
                        ts_code text,
                        mode text,
                        profile text,
                        source text,
                        doc_json text not null,
                        created_at text not null,
                        updated_at text not null
                    )
                    """
                )
                conn.execute(
                    "insert into ai_explanations values(?,?,?,?,?,?,?,?,?)",
                    (
                        "signal:20260525:000012.SZ",
                        "20260525",
                        "000012.SZ",
                        "short",
                        "short_v9_final",
                        "fallback",
                        json.dumps(legacy_doc, ensure_ascii=False),
                        "2026-06-16 00:00:00",
                        "2026-06-16 00:00:00",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            result = get_or_create_signal_explanation(
                "20260525",
                "000012.SZ",
                signal_db=signal_db,
                history_db=history_db,
                ai_config={"api_key": ""},
            )
            conn = sqlite3.connect(signal_db)
            try:
                migrated = conn.execute("select count(*) from ai_analysis_documents").fetchone()[0]
            finally:
                conn.close()

        self.assertEqual(result["source"], "cache")
        self.assertEqual(migrated, 1)
        self.assertEqual(result["doc"]["title"], legacy_doc["title"])


if __name__ == "__main__":
    unittest.main()
