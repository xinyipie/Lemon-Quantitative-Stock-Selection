import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from history_store import HistoryStore
from signal_store import SignalRecord, SignalStore
from web_app.services.history_service import get_db_status, get_stock_detail
from web_app.services.signal_service import (
    build_admission_diagnostics,
    build_dashboard_decision,
    build_data_freshness,
    build_default_signal_start,
    build_longterm_pool_status,
    build_longterm_run_funnel,
    build_strong_recommendation_card,
    get_active_longterm_pool,
    get_longterm_audit_samples,
    get_signal_runs,
    get_stock_signals,
    get_longterm_events,
    get_longterm_runs,
    get_recent_signals,
    summarize_short_signal_performance,
    summarize_stock_strategy_history,
)


class WebServicesTest(unittest.TestCase):
    def test_history_service_returns_db_status_and_stock_detail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_db = Path(tmpdir) / "history.db"
            store = HistoryStore(history_db)
            try:
                store.upsert_dataframe(
                    "stock_basic",
                    pd.DataFrame([{"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "industry": "银行"}]),
                )
                store.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {"trade_date": "20250101", "ts_code": "000001.SZ", "close": 10.0},
                            {"trade_date": "20250102", "ts_code": "000001.SZ", "close": 11.0},
                        ]
                    ),
                )
            finally:
                store.close()

            status = get_db_status(history_db)
            detail = get_stock_detail("000001", history_db=history_db, signal_db=None)

        self.assertEqual(status["latest_trade_date"], "20250102")
        self.assertEqual(status["tables"]["stock_daily"]["rows"], 2)
        self.assertEqual(status["tables"]["stock_daily"]["status_label"], "OK")
        self.assertEqual(detail["stock"]["name"], "平安银行")

    def test_history_status_marks_lagging_market_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_db = Path(tmpdir) / "history.db"
            store = HistoryStore(history_db)
            try:
                store.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {"trade_date": "20250102", "ts_code": "000001.SZ", "close": 10.0},
                        ]
                    ),
                )
                store.upsert_dataframe(
                    "stock_daily_basic",
                    pd.DataFrame(
                        [
                            {"trade_date": "20250101", "ts_code": "000001.SZ", "turnover_rate": 1.0},
                        ]
                    ),
                )
            finally:
                store.close()

            status = get_db_status(history_db)

        self.assertEqual(status["tables"]["stock_daily_basic"]["status_label"], "滞后")
        self.assertEqual(status["tables"]["stock_daily_basic"]["status_tone"], "warn")

    def test_history_status_warns_when_index_daily_has_only_broad_indices(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_db = Path(tmpdir) / "history.db"
            store = HistoryStore(history_db)
            try:
                store.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {"trade_date": "20260622", "ts_code": "000001.SZ", "close": 10.0},
                        ]
                    ),
                )
                store.upsert_dataframe(
                    "stock_daily_basic",
                    pd.DataFrame(
                        [
                            {"trade_date": "20260622", "ts_code": "000001.SZ", "turnover_rate": 1.0},
                        ]
                    ),
                )
                store.upsert_dataframe(
                    "stock_moneyflow",
                    pd.DataFrame(
                        [
                            {"trade_date": "20260622", "ts_code": "000001.SZ", "net_mf_amount": 10.0},
                        ]
                    ),
                )
                store.upsert_dataframe(
                    "index_daily",
                    pd.DataFrame(
                        [
                            {"trade_date": "20260622", "ts_code": "000001.SH", "close": 4163.0},
                            {"trade_date": "20260622", "ts_code": "000300.SH", "close": 5059.0},
                        ]
                    ),
                )
            finally:
                store.close()

            status = get_db_status(history_db)

        self.assertEqual(status["tables"]["index_daily"]["status_label"], "覆盖不足")
        self.assertEqual(status["tables"]["index_daily"]["status_tone"], "warn")
        self.assertEqual(status["tables"]["index_daily"]["latest_count"], 2)

    def test_signal_service_returns_recent_and_active_longterm_pool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_db = Path(tmpdir) / "history.db"
            history = HistoryStore(history_db)
            try:
                history.upsert_dataframe(
                    "stock_basic",
                    pd.DataFrame(
                        [
                            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "industry": "银行"},
                            {"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台", "industry": "白酒"},
                        ]
                    ),
                )
            finally:
                history.close()

            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20250102", mode="short", profile="profile_v9", source="test")
                store.update_pool(
                    run_id,
                    "20250102",
                    mode="short",
                    profile="profile_v9",
                    records=[SignalRecord(ts_code="000001.SZ", name="", industry="", score=66, factors={"ret_5d": 3.2, "mfe_pct": 8.5})],
                )
                long_run = store.record_run("20250102", mode="longterm", profile="longterm_elite", source="test")
                store.update_pool(
                    long_run,
                    "20250102",
                    mode="longterm",
                    profile="longterm_elite",
                    records=[SignalRecord(ts_code="600519.SH", name="贵州茅台", industry="白酒", score=91)],
                )
                empty_run = store.record_run("20250103", mode="longterm", profile="longterm_watch", source="live", label="daily")
                store.update_pool(empty_run, "20250103", mode="longterm", profile="longterm_watch", records=[])
                replacement_run = store.record_run("20250103", mode="longterm", profile="longterm_watch", source="live", label="daily_rerun")
                store.update_pool(
                    replacement_run,
                    "20250103",
                    mode="longterm",
                    profile="longterm_watch",
                    records=[SignalRecord(ts_code="600519.SH", name="贵州茅台", industry="白酒", score=93)],
                )
                live_report_run = store.record_run("20250103", mode="short", profile="profile_v9", source="live_report")
                store.update_pool(
                    live_report_run,
                    "20250103",
                    mode="short",
                    profile="profile_v9",
                    records=[SignalRecord(ts_code="600519.SH", name="", industry="", score=51)],
                )
                live_main_run = store.record_run("20250105", mode="short", profile="profile_v9_sector_quality_guard", source="live", label="daily")
                store.update_pool(
                    live_main_run,
                    "20250105",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[SignalRecord(ts_code="600519.SH", name="", industry="", score=58)],
                )
                backtest_run = store.record_run(
                    "20250104",
                    mode="short",
                    profile="short_v9_final",
                    source="backtest_ic_short",
                )
                store.update_pool(
                    backtest_run,
                    "20250104",
                    mode="short",
                    profile="short_v9_final",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            name="",
                            industry="",
                            score=72,
                            factors={"ret_5d": -6.0, "mfe_pct": 9.0},
                        )
                    ],
                )
            finally:
                store.close()

            recent = get_recent_signals(signal_db, history_db=history_db, limit=10)
            live_recent = get_recent_signals(signal_db, history_db=history_db, limit=5, source=["live", "live_report"], mode="short")
            backtest_recent = get_recent_signals(
                signal_db,
                history_db=history_db,
                limit=5,
                source="backtest_ic_short",
                profile="short_v9_final",
            )
            mixed_short_recent = get_recent_signals(
                signal_db,
                history_db=history_db,
                limit=5,
                source=["backtest_ic_short", "live"],
                profile=["short_v9_final", "profile_v9_sector_quality_guard"],
                mode="short",
            )
            named_recent = get_recent_signals(
                signal_db,
                history_db=history_db,
                limit=5,
                source="backtest_ic_short",
                profile="short_v9_final",
                query="平安",
            )
            longterm = get_active_longterm_pool(signal_db)
            longterm_runs = get_longterm_runs(signal_db, limit=5)
            longterm_events = get_longterm_events(signal_db, history_db=history_db, limit=5)
            short_runs = get_signal_runs(signal_db, mode="short", source=["live", "live_report"], limit=5)

        short = [item for item in recent if item["mode"] == "short" and item["source"] == "test"][0]
        self.assertEqual(short["trade_date"], "20250102")
        self.assertEqual(short["name"], "平安银行")
        self.assertEqual(short["display_name"], "平安银行")
        self.assertEqual(short["display_code"], "000001.SZ")
        self.assertEqual(short["performance"]["ret_5d"], 3.2)
        self.assertIn("5日", short["performance_text"])
        self.assertEqual(longterm[0]["ts_code"], "600519.SH")
        self.assertEqual(longterm[0]["state"], "active")
        self.assertEqual([item["source"] for item in live_recent], ["live", "live_report"])
        self.assertEqual(backtest_recent[0]["source_label"], "历史回测")
        self.assertEqual(backtest_recent[0]["display_name"], "平安银行")
        self.assertEqual(backtest_recent[0]["quality_label"], "初筛通过")
        self.assertEqual(backtest_recent[0]["outcome_label"], "短线亏损")
        self.assertEqual(backtest_recent[0]["process_label"], "曾冲高回落")
        self.assertEqual(named_recent[0]["ts_code"], "000001.SZ")
        self.assertEqual(longterm_runs[0]["trade_date"], "20250103")
        self.assertEqual(longterm_runs[0]["profile"], "longterm_watch")
        self.assertEqual(longterm_runs[0]["signal_count"], 1)
        self.assertEqual(longterm_runs[0]["label"], "daily_rerun")
        self.assertEqual(longterm_runs[1]["signal_count"], 1)
        self.assertEqual(longterm_events[0]["event_type_label"], "新入池")
        self.assertIn(longterm_events[0]["state_path_label"], {"未入池 → 入池", "移出 → 入池"})
        self.assertEqual(longterm_events[0]["display_name"], "贵州茅台")
        self.assertEqual(short_runs[0]["trade_date"], "20250105")
        self.assertEqual(short_runs[0]["signal_count"], 1)
        self.assertEqual(short_runs[0]["status_label"], "有入池标的")
        self.assertEqual([item["trade_date"] for item in mixed_short_recent[:2]], ["20250105", "20250104"])

    def test_recent_signals_tolerates_history_db_without_stock_basic_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20250102", mode="short", profile="profile_v9", source="test")
                store.update_pool(
                    run_id,
                    "20250102",
                    mode="short",
                    profile="profile_v9",
                    records=[SignalRecord(ts_code="000001.SZ", score=66)],
                )
            finally:
                store.close()

            empty_history_db = Path(tmpdir) / "empty_history.db"
            empty_history_db.touch()

            recent = get_recent_signals(signal_db, history_db=empty_history_db, limit=10)

        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["ts_code"], "000001.SZ")

    def test_strong_recommendation_card_only_promotes_v39_or_t1_live_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run(
                    "20260706",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    source="live",
                    label="daily",
                )
                store.update_pool(
                    run_id,
                    "20260706",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            name="A",
                            industry="Bank",
                            rank=1,
                            score=88,
                            factors={
                                "consensus_profile": "v39",
                                "recommendation_layer": "T1_BUY_CANDIDATE",
                                "entry_timing": "T1",
                                "consensus_votes": 3,
                                "consensus_avg_rank": 1.0,
                                "stop_loss_price": 9.5,
                                "target_price": 11.2,
                                "factor_inflow": 82,
                                "factor_sector": 75,
                                "factor_pattern": 70,
                                "factor_volume_ratio": 60,
                                "factor_drawdown": 55,
                                "factor_wyckoff": 58,
                            },
                        ),
                        SignalRecord(
                            ts_code="000002.SZ",
                            name="B",
                            industry="Tech",
                            rank=2,
                            score=91,
                            factors={
                                "factor_inflow": 80,
                                "factor_sector": 72,
                                "factor_pattern": 68,
                                "factor_volume_ratio": 60,
                                "factor_drawdown": 55,
                                "factor_wyckoff": 58,
                            },
                        ),
                    ],
                )
            finally:
                store.close()

            latest_run = get_signal_runs(signal_db, source="live", mode="short", limit=1)[0]
            live_rows = get_recent_signals(signal_db, history_db=None, limit=10, source="live", mode="short")
            card = build_strong_recommendation_card(latest_run, live_rows)

        self.assertEqual(card["title"], "\u5f3a\u63a8\u8350 1 \u53ea")
        self.assertEqual(card["candidate_count"], 2)
        self.assertEqual(card["strong_count"], 1)
        self.assertEqual(card["items"][0]["ts_code"], "000001.SZ")
        self.assertTrue(card["items"][0]["strong_recommendation"])
        self.assertIn("v39\u5f3a\u4fe1\u53f7", card["items"][0]["strong_badges"])
        self.assertIn("T1", card["items"][0]["strong_badges"])
        self.assertIn("9.50", card["items"][0]["strong_guard"])

    def test_recent_and_stock_signals_merge_live_with_backtest_review_for_same_stock_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                live_run = store.record_run("20260618", mode="short", profile="profile_v9_sector_quality_guard", source="live")
                store.update_pool(
                    live_run,
                    "20260618",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(
                            ts_code="002326.SZ",
                            name="永太科技",
                            industry="化工原料",
                            score=72.6,
                            rank=1,
                            factors={"factor_profile": "profile_v9_sector_quality_guard", "score": 72.6},
                        )
                    ],
                )
                review_run = store.record_run("20260618", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    review_run,
                    "20260618",
                    mode="short",
                    profile="short_v9_final",
                    records=[
                        SignalRecord(
                            ts_code="002326.SZ",
                            name="永太科技",
                            industry="化工原料",
                            score=71.2,
                            rank=1,
                            factors={"signal_window_days": 1, "window_end_pct": 5.56, "mfe_pct": 7.13, "mae_pct": -2.04},
                        )
                    ],
                )
            finally:
                store.close()

            recent = get_recent_signals(
                signal_db,
                history_db=None,
                source=["backtest_ic_short", "live"],
                profile=["short_v9_final", "profile_v9_sector_quality_guard"],
                mode="short",
                limit=10,
            )
            stock_rows = get_stock_signals("002326.SZ", signal_db=signal_db, history_db=None, limit=10)

        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["source"], "live")
        self.assertEqual(recent[0]["score"], 72.6)
        self.assertEqual(recent[0]["source_label"], "实盘记录 + 复盘表现")
        self.assertEqual(recent[0]["final_return_text"], "待满5日")
        self.assertEqual(recent[0]["mfe_text"], "+7.13%")
        self.assertEqual(recent[0]["mae_text"], "-2.04%")
        self.assertEqual(len(stock_rows), 1)
        self.assertEqual(stock_rows[0]["source_label"], "实盘记录 + 复盘表现")

    def test_data_freshness_treats_backtest_lag_as_review_lag_when_live_is_current(self):
        freshness = build_data_freshness(
            status={"latest_trade_date": "20260615"},
            latest_live_short_run={"trade_date": "20260615"},
            signal_summary={"latest_backtest_date": "20260529"},
            now=datetime(2026, 6, 15),
        )

        self.assertEqual(freshness["live_lag_days"], 0)
        self.assertEqual(freshness["backtest_lag_days"], 17)
        self.assertIn("今日实盘记录已更新", freshness["notes"][0])
        self.assertTrue(any("事后复盘" in item for item in freshness["notes"]))
        self.assertFalse(freshness["warnings"])

    def test_data_freshness_warns_when_live_signal_is_ahead_of_history_db(self):
        freshness = build_data_freshness(
            status={"latest_trade_date": "20260615"},
            latest_live_short_run={"trade_date": "20260617"},
            signal_summary={"latest_backtest_date": "20260612"},
            now=datetime(2026, 6, 17),
        )

        self.assertEqual(freshness["history_date"], "20260615")
        self.assertEqual(freshness["live_date"], "20260617")
        self.assertEqual(freshness["history_lag_days"], 2)
        self.assertTrue(any("历史行情库" in item and "20260615" in item and "20260617" in item for item in freshness["warnings"]))
        self.assertFalse(freshness["is_fresh"])
        self.assertEqual(freshness["tone"], "warn")
        self.assertEqual(freshness["status_label"], "行情滞后")
        self.assertIn("实盘信号已到 20260617", freshness["headline"])

    def test_dashboard_decision_explains_empty_signal_day(self):
        decision = build_dashboard_decision(
            latest_live_short_run={"trade_date": "20260615", "signal_count": 0},
            live_signals=[],
            longterm_pool=[],
            backtest_signals=[{"trade_date": "20260529"}],
        )

        self.assertEqual(decision["level"], "今日不宜开新仓")
        self.assertIn("短线 v9 未产生入池信号", decision["reasons"])
        self.assertGreaterEqual(len(decision["next_actions"]), 3)
        self.assertEqual(decision["next_actions"][0]["label"], "单股体检")

    def test_default_signal_start_uses_100_calendar_days(self):
        self.assertEqual(build_default_signal_start("20260615", days=100), "20260307")
        self.assertIsNone(build_default_signal_start("", days=100))

    def test_admission_diagnostics_explains_empty_live_and_backtest_state(self):
        diagnostics = build_admission_diagnostics(
            latest_live_short_run={"trade_date": "20260615", "signal_count": 0},
            live_signals=[],
            longterm_runs=[
                {"trade_date": "20260615", "profile": "longterm_elite", "signal_count": 0},
                {"trade_date": "20260615", "profile": "longterm_watch", "signal_count": 0},
            ],
            longterm_pool=[],
            backtest_signals=[{"trade_date": "20260612"}],
        )

        self.assertEqual(diagnostics["short_live_count"], 0)
        self.assertEqual(diagnostics["longterm_active_count"], 0)
        self.assertEqual(diagnostics["longterm_latest_count"], 0)
        self.assertTrue(diagnostics["is_empty_day"])
        self.assertGreaterEqual(len(diagnostics["items"]), 3)

    def test_longterm_run_funnel_groups_latest_trade_date_runs(self):
        funnel = build_longterm_run_funnel(
            runs=[
                {"trade_date": "20260615", "profile": "longterm_watch", "profile_label": "Watch观察", "signal_count": 2},
                {"trade_date": "20260615", "profile": "longterm_elite", "profile_label": "Elite强提醒", "signal_count": 1},
                {"trade_date": "20260614", "profile": "longterm_watch", "profile_label": "Watch观察", "signal_count": 5},
            ],
            pool=[{"ts_code": "000001.SZ"}, {"ts_code": "000002.SZ"}],
        )

        self.assertEqual(funnel["trade_date"], "20260615")
        self.assertEqual(funnel["run_count"], 2)
        self.assertEqual(funnel["entry_count"], 3)
        self.assertEqual(funnel["active_count"], 2)
        self.assertEqual(len(funnel["steps"]), 4)
        self.assertEqual(funnel["steps"][-1]["value"], "未采集")
        self.assertIn("运行摘要可用", funnel["steps"][-1]["hint"])
        self.assertEqual(funnel["telemetry_status"], "missing")

    def test_longterm_pool_status_explains_empty_but_recently_scanned_pool(self):
        status = build_longterm_pool_status(
            pool=[],
            runs=[{"trade_date": "20260616", "signal_count": 0, "status_label": "无入池标的"}],
        )

        self.assertEqual(status["title"], "当前长线池：空仓")
        self.assertEqual(status["tone"], "neutral")
        self.assertIn("20260616", status["subtitle"])
        self.assertIn("规则未放行", status["description"])

    def test_longterm_audit_sample_display_fields_reduce_unmatured_noise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            history_db = Path(tmpdir) / "history.db"
            history = HistoryStore(history_db)
            try:
                history.upsert_dataframe(
                    "stock_daily",
                    pd.DataFrame(
                        [
                            {"trade_date": "20260601", "ts_code": "000001.SZ", "close": 10.0},
                            {"trade_date": "20260602", "ts_code": "000001.SZ", "close": 9.0},
                            {"trade_date": "20260603", "ts_code": "000001.SZ", "close": 8.5},
                        ]
                    ),
                )
            finally:
                history.close()

            import sqlite3

            conn = sqlite3.connect(signal_db)
            try:
                conn.executescript(
                    """
                    create table longterm_audit_runs (
                        id integer primary key autoincrement,
                        period text not null,
                        profile text not null,
                        source_file text not null unique,
                        sample_count integer not null default 0,
                        date_start text,
                        date_end text,
                        avg_ret_10d real,
                        avg_ret_40d real,
                        avg_ret_80d real,
                        win_rate_80d real,
                        outperform_rate_80d real,
                        created_at text not null
                    );
                    create table longterm_audit_samples (
                        id integer primary key autoincrement,
                        run_id integer not null,
                        select_date text not null,
                        ts_code text not null,
                        name text,
                        industry text,
                        profile text,
                        pool_type text,
                        regime text,
                        score real,
                        pool_rank_score real,
                        industry_rs real,
                        drawdown_from_high real,
                        ret_10d real,
                        ret_40d real,
                        ret_80d real,
                        mfe_80d real,
                        mae_80d real,
                        benchmark_ret_80d real,
                        excess_ret_80d real,
                        outperform_80d integer,
                        factor_json text
                    );
                    """
                )
                conn.execute(
                    """
                    insert into longterm_audit_runs
                    (period, profile, source_file, sample_count, date_start, date_end, created_at)
                    values ('2026H1', 'longterm_quality_lifecycle_v18_market_sync', 'x.csv', 1, '20260601', '20260601', 'now')
                    """
                )
                conn.execute(
                    """
                    insert into longterm_audit_samples
                    (run_id, select_date, ts_code, name, industry, score, ret_10d, ret_40d, ret_80d, mae_80d, excess_ret_80d)
                    values (1, '20260601', '000001.SZ', '平安银行', '银行', 88, null, null, null, -16.0, null)
                    """
                )
                conn.commit()
            finally:
                conn.close()

            samples = get_longterm_audit_samples(signal_db, history_db=history_db, limit=5)

        self.assertEqual(samples[0]["stage_return_text"], "当前-15.00%(t+2)")
        self.assertEqual(samples[0]["stage_return_tone"], "market-down")
        self.assertEqual(samples[0]["ret_40d_text"], "t+2/40")
        self.assertEqual(samples[0]["ret_40d_tone"], "muted")
        self.assertEqual(samples[0]["excess_80d_text"], "未满")
        self.assertEqual(samples[0]["mae_pain_tone"], "risk-high")
        self.assertEqual(samples[0]["lifecycle_label"], "窗口未满 t+2")
        self.assertEqual(samples[0]["watch_risk_label"], "风险升级")
        self.assertEqual(samples[0]["watch_risk_tone"], "bad")
        self.assertIn("当前回撤已超过10%", samples[0]["watch_risk_reason"])

    def test_dashboard_decision_promotes_live_signals_when_present(self):
        decision = build_dashboard_decision(
            latest_live_short_run={"trade_date": "20260615", "signal_count": 1},
            live_signals=[{"ts_code": "000001.SZ"}],
            longterm_pool=[],
            backtest_signals=[],
        )

        self.assertEqual(decision["level"], "有可关注信号")
        self.assertIn("短线实盘出现 1 个入池信号", decision["reasons"])

    def test_data_freshness_notes_when_backtest_review_is_not_mature(self):
        freshness = build_data_freshness(
            status={"latest_trade_date": "20260615"},
            latest_live_short_run={"trade_date": "20260615"},
            signal_summary={"latest_backtest_date": "20260529"},
            now=datetime(2026, 6, 15),
        )

        self.assertEqual(freshness["history_date"], "20260615")
        self.assertEqual(freshness["live_date"], "20260615")
        self.assertEqual(freshness["backtest_lag_days"], 17)
        self.assertFalse(freshness["warnings"])
        self.assertTrue(any("事后复盘" in item for item in freshness["notes"]))

    def test_data_freshness_warns_when_history_date_is_far_behind_today(self):
        freshness = build_data_freshness(
            status={"latest_trade_date": "20260625"},
            latest_live_short_run={"trade_date": "20260625"},
            signal_summary={"latest_backtest_date": "20260618"},
            now=datetime(2026, 6, 30),
        )

        self.assertEqual(freshness["tone"], "warn")
        self.assertEqual(freshness["status_label"], "行情源滞后")
        self.assertEqual(freshness["current_lag_days"], 5)
        self.assertTrue(any("20260625" in item and "行情源" in item for item in freshness["warnings"]))

    def test_short_signal_performance_summary_uses_recent_signal_outcomes(self):
        summary = summarize_short_signal_performance(
            [
                {"performance": {"ret_5d": 5.0, "mfe_pct": 9.0, "mae_pct": -2.0}},
                {"performance": {"ret_5d": -6.0, "mfe_pct": 3.0, "mae_pct": -8.0}},
                {"performance": {"ret_5d": 1.0, "mfe_pct": 4.0, "mae_pct": -1.0}},
            ]
        )

        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["win_count"], 2)
        self.assertAlmostEqual(summary["win_rate"], 66.666, places=2)
        self.assertEqual(summary["avg_ret_5d"], 0.0)
        self.assertAlmostEqual(summary["avg_mfe"], 5.333, places=2)
        self.assertAlmostEqual(summary["avg_mae"], -3.666, places=2)
        self.assertAlmostEqual(summary["opportunity_risk_ratio"], 1.454, places=2)

    def test_stock_strategy_history_summarizes_prior_hits(self):
        summary = summarize_stock_strategy_history(
            [
                {
                    "trade_date": "20260601",
                    "mode": "short",
                    "profile": "short_v9_final",
                    "performance": {"ret_5d": -2.0, "mfe_pct": 4.0},
                },
                {
                    "trade_date": "20260520",
                    "mode": "short",
                    "profile": "short_v9_final",
                    "performance": {"ret_5d": 6.0, "mfe_pct": 12.0},
                },
            ]
        )

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["short_count"], 2)
        self.assertEqual(summary["profitable_count"], 1)
        self.assertEqual(summary["best_mfe"], 12.0)
        self.assertEqual(summary["latest_date"], "20260601")

    def test_short_signal_display_splits_final_return_from_intraday_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20250102", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20250102",
                    mode="short",
                    profile="short_v9_final",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            score=66,
                            factors={"ret_5d": -6.0, "mfe_pct": 9.0, "mae_pct": -8.0},
                        )
                    ],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertEqual(signal["final_return_text"], "5日-6.00%")
        self.assertEqual(signal["process_text"], "MFE+9.00% / MAE-8.00%")
        self.assertEqual(signal["basis_summary"], "v9分 66.0")
        self.assertEqual(signal["final_return_tone"], "market-down")
        self.assertEqual(signal["mfe_text"], "+9.00%")
        self.assertEqual(signal["mae_text"], "-8.00%")

    def test_short_signal_exposes_rule_reasons_and_score_tooltip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20250102", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20250102",
                    mode="short",
                    profile="short_v9_final",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            score=56,
                            factors={
                                "original_score": 66,
                                "factor_inflow": 82,
                                "factor_sector": 61,
                                "factor_pattern": 38,
                                "rule_reasons": ["资金分较强", "板块热度较好"],
                                "risk_reasons": ["形态38分偏弱"],
                                "action_hint": "轻仓观察，次日不能站稳关键位就放弃",
                            },
                        )
                    ],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertIn("资金分较强", signal["recommend_reason"])
        self.assertIn("形态38分偏弱", signal["risk_reason_text"])
        self.assertIn("总分：56.0", signal["score_tooltip"])
        self.assertIn("原始分 66.0", signal["score_tooltip"])
        self.assertIn("处理：轻仓观察", signal["score_tooltip"])

    def test_short_signal_reason_fallback_does_not_show_pool_enum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20250102", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20250102",
                    mode="short",
                    profile="short_v9_final",
                    records=[SignalRecord(ts_code="000001.SZ", score=75, reason="short_top", factors={})],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertNotEqual(signal["recommend_reason"], "short_top")
        self.assertIn("v9分 75.0", signal["recommend_reason"])
        self.assertIn("因子拆解不完整", signal["recommend_reason"])

    def test_incomplete_short_factor_breakdown_lowers_confidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260617", mode="short", profile="profile_v9_sector_quality_guard", source="live")
                store.update_pool(
                    run_id,
                    "20260617",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            score=76,
                            factors={
                                "score": 76,
                                "factor_profile": "profile_v9_sector_quality_guard",
                                "style_gate": "swing",
                            },
                        )
                    ],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertEqual(signal["factor_payload_status"], "incomplete")
        self.assertEqual(signal["confidence_label"], "\u53ea\u89c2\u5bdf")
        self.assertIn("\u56e0\u5b50\u62c6\u89e3\u4e0d\u5b8c\u6574", signal["confidence_summary"])
        self.assertIn("\u56e0\u5b50\u62c6\u89e3\u4e0d\u5b8c\u6574", signal["recommend_reason"])
        self.assertIn("factor_inflow", signal["score_tooltip"])

    def test_very_weak_pattern_turns_high_score_short_signal_into_weak_signal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260618", mode="short", profile="profile_v9_sector_quality_guard", source="live")
                store.update_pool(
                    run_id,
                    "20260618",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            score=76,
                            factors={
                                "score": 76,
                                "original_score": 88,
                                "factor_profile": "profile_v9_sector_quality_guard",
                                "factor_inflow": 95,
                                "factor_sector": 70,
                                "factor_pattern": 25,
                                "factor_volume_ratio": 60,
                                "factor_drawdown": 55,
                                "factor_wyckoff": 50,
                            },
                        )
                    ],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertEqual(signal["factor_payload_status"], "complete")
        self.assertEqual(signal["confidence_label"], "暂不跟")
        self.assertEqual(signal["confidence_tone"], "bad")
        self.assertIn("形态分低于30", signal["confidence_summary"])
        self.assertIn("形态分低于30", signal["risk_reason_text"])
        self.assertIn("形态分低于30", signal["recommend_reason"])

    def test_short_signal_marks_cached_ai_explanation_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20250102", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20250102",
                    mode="short",
                    profile="short_v9_final",
                    records=[SignalRecord(ts_code="000001.SZ", score=75, reason="short_top", factors={})],
                )
            finally:
                store.close()

            import sqlite3

            conn = sqlite3.connect(signal_db)
            try:
                conn.execute(
                    """
                    create table ai_analysis_documents (
                        id integer primary key autoincrement,
                        doc_type text not null,
                        cache_key text not null unique,
                        trade_date text,
                        ts_code text,
                        mode text,
                        profile text,
                        source_ref text,
                        source text,
                        model text,
                        prompt_version text,
                        input_hash text,
                        doc_json text not null,
                        summary text,
                        created_at text not null,
                        updated_at text not null
                    )
                    """
                )
                conn.execute(
                    """
                    insert into ai_analysis_documents(
                        doc_type, cache_key, trade_date, ts_code, mode, profile, source,
                        doc_json, summary, created_at, updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "signal_explanation",
                        "signal:20250102:000001.SZ",
                        "20250102",
                        "000001.SZ",
                        "short",
                        "short_v9_final",
                        "ai",
                        "{}",
                        "cached",
                        "2026-06-18 00:00:00",
                        "2026-06-18 00:00:00",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertEqual(signal["explanation_label"], "AI已缓存")
        self.assertEqual(signal["explanation_tone"], "ok")

    def test_short_signal_display_uses_plain_process_labels_and_risk_levels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20250102", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20250102",
                    mode="short",
                    profile="short_v9_final",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            score=66,
                            factors={"ret_5d": 2.0, "mfe_pct": 10.0, "mae_pct": -11.0},
                        )
                    ],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertEqual(signal["process_label"], "盘中给过机会")
        self.assertEqual(signal["process_tone"], "ok")
        self.assertEqual(signal["mae_risk_label"], "风险偏高")
        self.assertEqual(signal["mae_risk_tone"], "risk-high")

    def test_short_signal_labels_are_actionable_for_review_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                pending_run = store.record_run("20260618", mode="short", profile="profile_v9_sector_quality_guard", source="live")
                store.update_pool(
                    pending_run,
                    "20260618",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[
                        SignalRecord(
                            ts_code="000001.SZ",
                            score=52,
                            factors={
                                "factor_inflow": 55,
                                "factor_sector": 52,
                                "factor_pattern": 50,
                                "factor_volume_ratio": 50,
                                "factor_drawdown": 50,
                                "factor_wyckoff": 50,
                            },
                        )
                    ],
                )
                weak_run = store.record_run("20260610", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    weak_run,
                    "20260610",
                    mode="short",
                    profile="short_v9_final",
                    records=[SignalRecord(ts_code="000002.SZ", score=24, factors={"ret_5d": 1.0, "mfe_pct": 2.0, "mae_pct": -2.0})],
                )
            finally:
                store.close()

            rows = get_recent_signals(signal_db, history_db=None, limit=5)

        pending = rows[0]
        weak = rows[1]
        self.assertEqual(pending["confidence_label"], "只观察")
        self.assertEqual(pending["quality_label"], "线索不足")
        self.assertEqual(pending["outcome_label"], "未满5日")
        self.assertEqual(pending["process_label"], "等走势确认")
        self.assertEqual(weak["confidence_label"], "暂不跟")
        self.assertEqual(weak["quality_label"], "质量偏弱")
        self.assertEqual(weak["outcome_label"], "未走出方向")
        self.assertEqual(weak["process_label"], "回撤可控")

    def test_unmatured_short_signal_uses_soft_pending_display(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260616", mode="short", profile="profile_v9_sector_quality_guard", source="live", label="daily")
                store.update_pool(
                    run_id,
                    "20260616",
                    mode="short",
                    profile="profile_v9_sector_quality_guard",
                    records=[SignalRecord(ts_code="000001.SZ", score=76)],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertEqual(signal["final_return_text"], "待满5日")
        self.assertEqual(signal["final_return_tone"], "muted")
        self.assertEqual(signal["mfe_text"], "待观察")
        self.assertEqual(signal["mae_text"], "待观察")
        self.assertEqual(signal["quality_label"], "初筛通过")
        self.assertEqual(signal["result_tag"], "初筛通过/未满5日")
        self.assertEqual(signal["confidence_label"], "只观察")
        self.assertEqual(signal["confidence_tone"], "warn")
        self.assertIn("未满5日", signal["confidence_summary"])
        self.assertIn("因子拆解不完整", signal["confidence_summary"])

    def test_partial_backtest_short_window_stays_pending_until_five_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260618", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20260618",
                    mode="short",
                    profile="short_v9_final",
                    records=[
                        SignalRecord(
                            ts_code="002326.SZ",
                            score=72.56,
                            factors={
                                "signal_window_days": 1,
                                "window_end_pct": 5.56,
                                "mfe_pct": 7.13,
                                "mae_pct": -2.04,
                            },
                        )
                    ],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertEqual(signal["final_return_text"], "待满5日")
        self.assertEqual(signal["final_return_tone"], "muted")
        self.assertEqual(signal["outcome_label"], "未满5日")
        self.assertEqual(signal["quality_label"], "初筛通过")
        self.assertIn("MFE+7.13%", signal["process_text"])
        self.assertIn("未满5日", signal["confidence_summary"])
        self.assertNotIn("已满期样本短线盈利", signal["confidence_summary"])

    def test_short_signal_confidence_downgrades_weak_matured_signal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260610", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20260610",
                    mode="short",
                    profile="short_v9_final",
                    records=[
                        SignalRecord(
                            ts_code="000002.SZ",
                            score=24,
                            factors={"ret_5d": -6.2, "mfe_pct": 1.1, "mae_pct": -9.5},
                        )
                    ],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=None, limit=1)[0]

        self.assertEqual(signal["confidence_label"], "暂不跟")
        self.assertEqual(signal["confidence_tone"], "bad")
        self.assertIn("分数偏低", signal["confidence_summary"])
        self.assertIn("短线亏损", signal["confidence_summary"])

    def test_short_signal_marks_current_risk_guard_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            signal_db = Path(tmpdir) / "signals.db"
            history_db = Path(tmpdir) / "history.db"
            conn = __import__("sqlite3").connect(history_db)
            try:
                conn.executescript(
                    """
                    create table stock_basic (
                        ts_code text primary key,
                        symbol text,
                        name text,
                        industry text
                    );
                    create table fina_indicator (
                        ts_code text,
                        ann_date text,
                        end_date text,
                        roe real,
                        debt_to_assets real,
                        netprofit_yoy real,
                        netprofit_margin real
                    );
                    """
                )
                conn.execute(
                    "insert into stock_basic values (?, ?, ?, ?)",
                    ("002217.SZ", "002217", "合力泰", "元器件"),
                )
                conn.execute(
                    "insert into fina_indicator values (?, ?, ?, ?, ?, ?, ?)",
                    ("002217.SZ", "20260423", "20260331", 0.04, 26.3, -79.7, 0.48),
                )
                conn.commit()
            finally:
                conn.close()

            store = SignalStore(signal_db)
            try:
                run_id = store.record_run("20260617", mode="short", profile="short_v9_final", source="backtest_ic_short")
                store.update_pool(
                    run_id,
                    "20260617",
                    mode="short",
                    profile="short_v9_final",
                    records=[SignalRecord(ts_code="002217.SZ", name="合力泰", industry="元器件", score=53)],
                )
            finally:
                store.close()

            signal = get_recent_signals(signal_db, history_db=history_db, limit=1)[0]

        self.assertTrue(signal["current_risk_blocked"])
        self.assertEqual(signal["current_risk_label"], "现行风险规则已排除")
        self.assertIn("净利润同比断崖", signal["current_risk_reason"])
        self.assertEqual(signal["confidence_label"], "风险排除")
        self.assertEqual(signal["confidence_tone"], "bad")
        self.assertIn("现行风险规则", signal["confidence_summary"])


if __name__ == "__main__":
    unittest.main()
