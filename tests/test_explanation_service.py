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
    build_fallback_daily_brief,
    get_or_create_daily_brief,
    get_or_create_signal_explanation,
)


class ExplanationServiceTest(unittest.TestCase):
    def test_fallback_daily_brief_summarizes_current_dashboard_facts(self):
        facts = {
            "trade_date": "20260618",
            "latest_live_short_run": {"trade_date": "20260618", "status_label": "有入池标的", "signal_count": 2},
            "live_short_signals": [
                {"display_name": "海康威视", "display_code": "002415.SZ", "industry": "IT设备", "score": 76.0},
                {"display_name": "中国稀土", "display_code": "000831.SZ", "industry": "小金属", "score": 63.4},
            ],
            "longterm_pool": [],
            "longterm_runs": [{"trade_date": "20260618", "status_label": "无入池标的"}],
            "freshness": {"warnings": ["历史复盘样本落后实盘 2 天"]},
        }

        doc = build_fallback_daily_brief(facts)

        self.assertEqual(doc["title"], "20260618 今日AI摘要")
        self.assertIn("短线", doc["summary"])
        self.assertTrue(any("海康威视" in item for item in doc["positives"]))
        self.assertTrue(any("长线" in item for item in doc["risks"]))
        self.assertIn("不构成收益承诺", doc["confidence_note"])

    def test_get_or_create_daily_brief_calls_ai_once_and_caches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            history_db = Path(tmpdir) / "history.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260618", mode="short", profile="profile_v9_sector_quality_guard", source="live")
                store.update_pool(
                    run_id,
                    "20260618",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[SignalRecord(ts_code="002415.SZ", name="海康威视", industry="IT设备", rank=1, score=76.0)],
                )
                store.record_run("20260618", mode="longterm", profile="longterm_quality_lifecycle_v18_market_sync", source="live")
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
                                "title": "20260618 今日AI摘要",
                                "summary": "今日短线有可关注信号，长线池保持空仓，适合先观察主线承接。",
                                "positives": ["短线出现海康威视等信号，说明局部机会存在。"],
                                "risks": ["长线规则未放行，说明中期胜率条件仍不足。"],
                                "watch_plan": "先看短线信号次日承接和板块扩散。",
                                "invalidation": "若短线信号低开走弱且板块退潮，应降低参与欲望。",
                                "style": "今日观察",
                                "confidence_note": "基于本地信号和市场数据，不构成收益承诺。",
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
            first = get_or_create_daily_brief(
                "20260618",
                signal_db=signal_db,
                history_db=history_db,
                ai_config=cfg,
                post=fake_post,
            )
            second = get_or_create_daily_brief(
                "20260618",
                signal_db=signal_db,
                history_db=history_db,
                ai_config=cfg,
                post=fake_post,
            )

            conn = sqlite3.connect(signal_db)
            try:
                row = conn.execute(
                    """
                    select doc_type, cache_key, trade_date, mode, profile, source,
                           model, prompt_version, summary
                    from ai_analysis_documents
                    where cache_key = 'daily_brief:20260618'
                    """
                ).fetchone()
            finally:
                conn.close()

        self.assertEqual(calls["count"], 1)
        self.assertEqual(row[0], "daily_brief")
        self.assertEqual(row[1], "daily_brief:20260618")
        self.assertEqual(row[2], "20260618")
        self.assertEqual(row[3], "dashboard")
        self.assertEqual(row[4], "daily_brief")
        self.assertEqual(row[5], "ai")
        self.assertEqual(row[6], "deepseek-chat")
        self.assertTrue(row[7].startswith("daily_brief_v"))
        self.assertIn("今日短线", row[8])
        self.assertEqual(first["doc"]["style"], "今日观察")
        self.assertEqual(second["source"], "cache")

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

    def test_fallback_explanation_uses_structured_rule_reasons(self):
        signal = {
            "trade_date": "20260525",
            "ts_code": "000012.SZ",
            "display_name": "南玻A",
            "display_code": "000012.SZ",
            "quality_label": "有效信号",
            "outcome_label": "窗口未满",
            "process_label": "待观察",
            "recommend_reason": "资金分较强；板块热度较好",
            "risk_reason_text": "形态38分偏弱；量比3.20偏热",
            "score_explain": {
                "rule_reasons": ["资金分较强", "板块热度较好"],
                "risk_reasons": ["形态38分偏弱", "量比3.20偏热"],
                "action_hint": "轻仓观察，次日不能站稳关键位就放弃",
            },
        }

        doc = build_fallback_explanation(signal)

        self.assertIn("资金分较强", doc["positives"][0])
        self.assertTrue(any("量比3.20偏热" in item for item in doc["risks"]))
        self.assertIn("轻仓观察", doc["watch_plan"])

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
