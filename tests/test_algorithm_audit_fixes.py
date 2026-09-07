from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import backtest_v2
import batch_backtest
import ic_analysis
import longterm_backtest_audit
import longterm_market_winner_profile_audit
import longterm_pool_compression_audit
import longterm_pool_watchlist_audit
import longterm_winner_profile_audit
import main
import market_analyzer
import strategy_profiles
import analyze_trades
import concept_heat_provider
import event_study_catchup
import news_analyzer
import rule_hit_diagnostics
import sector_heat_diagnostics


def _bare_backtest(*, hold_days: int = 1) -> backtest_v2.BacktestV2:
    engine = backtest_v2.BacktestV2.__new__(backtest_v2.BacktestV2)
    engine.hold_days = hold_days
    engine.fallback_stop_pct = -10.0
    engine.fallback_profit_pct = 50.0
    engine.trailing_stop_pct = 20.0
    engine.trailing_activate_pct = 50.0
    engine.min_open_ratio = 0.0
    engine.short_time_stop = False
    engine.conditional_lock_enabled = False
    return engine


def _daily(date: str, open_: float, high: float, low: float, close: float, pct_chg: float) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "ts_code": "000001.SZ",
            "trade_date": date,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "pct_chg": pct_chg,
            "pre_close": 100.0,
        }]
    )


def test_market_regime_fails_closed_when_benchmark_is_missing(monkeypatch):
    monkeypatch.setattr(main, "pro", SimpleNamespace(index_daily=lambda **_: pd.DataFrame()))

    regime, details = main.get_market_regime("20250102")

    assert regime == "DATA_UNAVAILABLE"
    assert details["position_multiplier"] == 0.0
    assert details["data_quality"] == "unavailable"


def test_short_term_market_risk_fails_closed_when_an_index_is_missing(monkeypatch):
    monkeypatch.setattr(main, "pro", SimpleNamespace(index_daily=lambda **_: pd.DataFrame()))
    state, _ = main.check_market_risk("20250102")
    assert state == "data_unavailable"


def test_intraday_take_profit_precedes_close_based_time_stop():
    engine = _bare_backtest(hold_days=1)
    engine.time_stop_days = 1
    engine.time_stop_threshold = 0.0
    rows = {
        "20250102": _daily("20250102", 100, 100, 100, 100, 0),
        "20250103": _daily("20250103", 100, 111, 95, 96, -4),
    }

    result = engine._simulate_trade(
        "000001.SZ", "20250102", list(rows), rows,
        tech_stop_price=90.0, tech_target_price=110.0, select_close=100.0,
    )

    assert result["exit_reason"] == "take_profit"
    assert result["sell_price"] == 110.0


def test_limit_up_does_not_delay_a_shareholder_sell():
    engine = _bare_backtest(hold_days=1)
    rows = {
        "20250102": _daily("20250102", 100, 100, 100, 100, 0),
        "20250103": _daily("20250103", 105, 110, 105, 110, 10),
    }

    result = engine._simulate_trade(
        "000001.SZ", "20250102", list(rows), rows,
        tech_stop_price=90.0, tech_target_price=108.0, select_close=100.0,
    )

    assert result["sell_date"] == "20250103"
    assert result["sell_price"] == 108.0
    assert result["exit_reason"] == "take_profit"


def test_batch_ic_uses_mode_specific_nonconstant_score():
    df = pd.DataFrame({"short_score": [1, 2], "longterm_score": [0, 0]})
    assert batch_backtest.pick_ic_score_column(df, mode="short") == "short_score"
    with pytest.raises(ValueError, match="常数"):
        batch_backtest.pick_ic_score_column(df, mode="longterm")


def test_batch_records_constant_score_as_ic_unavailable(tmp_path):
    path = tmp_path / "trades_short.csv"
    pd.DataFrame({
        "buy_date": ["20250102"] * 5,
        "ts_code": [f"00000{i}.SZ" for i in range(5)],
        "short_score": [0] * 5,
    }).to_csv(path, index=False)
    result = batch_backtest.safe_compute_ic_summary(str(path), horizons=[10], mode="short")
    assert result["has_score"] is False
    assert "常数" in result["ic_unavailable_reason"]


def test_batch_official_mode_uses_live_profiles_and_execution_gates():
    short = batch_backtest.build_engine_kwargs("short", validation_kind="official")
    official = __import__("config").get_official_short_profile()
    assert short["factor_profile"] == official["factor_profile"]
    assert short["style_gate"] == official["style_gate"]
    assert short["consensus_profile"] == official["consensus_profile"]
    assert short["use_market_timing"] is True
    assert short["min_open_ratio"] == 0.995
    assert short["hold_days"] == 8


def test_backtest_passes_market_gate_choice_into_shared_selector(monkeypatch):
    engine = _bare_backtest()
    engine._is_offline = True
    engine.use_market_timing = False
    engine.short_filter_profile = "baseline"
    engine.factor_profile = "original"
    engine.longterm_profile = "baseline"
    seen = {}

    def fake_selection(**kwargs):
        seen.update(kwargs)
        return {
            "trade_date": "20250102", "operation_mode": "full", "sentiment_data": {},
            "stock_pool": pd.DataFrame(), "position_multiplier": 1.0,
            "score_threshold": 45, "regime": "BULL_TREND", "regime_data": {},
        }

    monkeypatch.setattr(backtest_v2.stock_main, "run_daily_selection", fake_selection)
    engine._select_stocks_for_date("20250102", retries=0)

    assert seen["apply_market_gates"] is False


def test_short_no_timing_keeps_candidates_when_regime_multiplier_is_zero(monkeypatch):
    engine = _bare_backtest()
    engine._is_offline = True
    engine.use_market_timing = False
    engine.short_filter_profile = "baseline"
    engine.factor_profile = "original"
    engine.longterm_profile = "baseline"
    engine.style_gate = "none"
    engine.consensus_profile = "none"
    engine.score_order = "desc"
    engine.top_n = 1
    engine._apply_style_gate = lambda frame: frame
    monkeypatch.setattr(backtest_v2.stock_main, "run_daily_selection", lambda **_: {
        "trade_date": "20250102", "operation_mode": "stop", "sentiment_data": {},
        "stock_pool": pd.DataFrame([{"code": "000001", "score": 80, "close": 10}]),
        "position_multiplier": 0.0, "score_threshold": 45,
        "regime": "BEAR_TREND", "regime_data": {}, "max_hold_days": 8,
    })
    selected, _ = engine._select_stocks_for_date("20250102", retries=0)
    assert len(selected) == 1


def test_longterm_no_timing_does_not_reject_candidates_after_selection(monkeypatch):
    engine = backtest_v2.BacktestLongterm.__new__(backtest_v2.BacktestLongterm)
    engine._is_offline = True
    engine.use_market_timing = False
    engine.longterm_profile = "test"
    engine.top_n = 1
    engine.max_hold_days = 60
    seen = {}

    def fake_selection(**kwargs):
        seen.update(kwargs)
        pool = pd.DataFrame([{
            "code": "000001", "close": 10, "longterm_score": 80,
            "stop_loss_price": 9, "target_price": 12,
        }])
        return {"trade_date": "20250102", "regime": "BEAR_TREND", "longterm_pool": pool}

    monkeypatch.setattr(backtest_v2.stock_main, "run_daily_selection", fake_selection)
    selected, _ = engine._select_stocks_for_date("20250102", retries=0)
    assert seen["apply_market_gates"] is False
    assert len(selected) == 1


def test_performance_classification_uses_net_returns():
    engine = _bare_backtest()
    engine.benchmark_df = pd.DataFrame()
    engine.start_date = "20250101"
    engine.end_date = "20250131"
    engine.top_n = 1
    engine.score_order = "desc"
    engine.factor_profile = "original"
    engine.style_gate = "none"
    engine.short_filter_profile = "baseline"
    trades = pd.DataFrame([
        {"profit_pct": 0.20, "profit_after_fee": -0.16, "sell_date": "20250103", "exit_reason": "hold_complete"},
        {"profit_pct": 1.00, "profit_after_fee": 0.64, "sell_date": "20250104", "exit_reason": "take_profit"},
    ])

    metrics = engine._calculate_metrics(trades, pd.DataFrame())

    assert metrics["win_trades"] == 1
    assert metrics["loss_trades"] == 1
    assert metrics["win_rate"] == 50.0
    assert metrics["gross_win_trades"] == 2


def test_live_compression_lookback_is_calendar_days_not_scan_count():
    df = pd.DataFrame([
        {"select_date": "20260101", "ts_code": "000001.SZ", "pool_rank_score": 60},
        {"select_date": "20260701", "ts_code": "000001.SZ", "pool_rank_score": 60},
    ])
    result = longterm_pool_compression_audit.add_compression_features(df, lookback_days=20)
    assert result["recent_appearances"].tolist() == [1, 1]


def test_stop_risk_uses_entry_price_as_denominator():
    assert strategy_profiles.stop_risk_pct(100.0, 80.0) == 20.0


def test_financial_versions_keep_latest_announcement_per_period():
    df = pd.DataFrame([
        {"ts_code": "000001.SZ", "end_date": "20240930", "ann_date": "20241020", "roe": 8},
        {"ts_code": "000001.SZ", "end_date": "20240930", "ann_date": "20241101", "roe": 9},
        {"ts_code": "000001.SZ", "end_date": "20240630", "ann_date": "20240801", "roe": 7},
    ])
    result = main._latest_announced_financial_versions(df)
    assert result[["end_date", "roe"]].to_dict("records") == [
        {"end_date": "20240930", "roe": 9},
        {"end_date": "20240630", "roe": 7},
    ]


def test_longterm_exposure_requires_real_slot_count():
    trades = pd.DataFrame([
        {"buy_date": "20250102", "sell_date": "20250104", "ts_code": "000001.SZ", "portfolio_slot": 7, "max_positions": 15},
    ])
    result = longterm_backtest_audit.audit_trades(trades)
    assert result["max_positions"] == 15
    assert result["slot_weight_pct"] == pytest.approx(6.67, abs=0.01)


def test_longterm_exposure_refuses_to_infer_capacity_from_used_slots():
    trades = pd.DataFrame([
        {"buy_date": "20250102", "sell_date": "20250104", "ts_code": "000001.SZ", "portfolio_slot": 0},
    ])
    with pytest.raises(ValueError, match="max_positions"):
        longterm_backtest_audit.audit_trades(trades)


def test_watchlist_age_uses_real_date_arithmetic():
    df = pd.DataFrame([
        {"source_label": "x", "stage": "s", "select_date": "20260131", "ts_code": "000001.SZ"},
        {"source_label": "x", "stage": "s", "select_date": "20260201", "ts_code": "000001.SZ"},
    ])
    result = longterm_pool_watchlist_audit.promote_watchlist(df, lookback_scans=3, min_appearances=2)
    assert result.iloc[0]["days_since_first_seen"] == 1


def test_ic_refuses_realized_profit_as_a_score():
    df = pd.DataFrame({"profit_after_fee": [1.0, 2.0]})
    with pytest.raises(ValueError, match="预测评分"):
        ic_analysis.pick_score_col(df)
    with pytest.raises(ValueError, match="预测评分"):
        ic_analysis.pick_score_col(df, use_profit=True)


@pytest.mark.parametrize(
    "classifier",
    [longterm_winner_profile_audit.classify_samples, longterm_market_winner_profile_audit.classify_market_samples],
)
def test_excess_winner_labels_are_unavailable_without_benchmark(classifier):
    result = classifier(pd.DataFrame([{"ret_80d": 30.0}]), horizon=80)
    assert result.iloc[0]["sample_group"] == "基准缺失"
    assert pd.isna(result.iloc[0]["excess_ret_80d"])


def test_event_study_uses_board_specific_limit_thresholds():
    assert event_study_catchup.is_limit_up("688001.SH", "样本", 10.0) is False
    assert event_study_catchup.is_limit_up("688001.SH", "样本", 20.0) is True
    assert event_study_catchup.is_limit_up("000001.SZ", "*ST样本", 5.0) is True


def test_event_study_requires_exact_historical_industry_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(event_study_catchup, "CACHE_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="精确快照"):
        event_study_catchup.load_stock_basic("20250102")


def test_analyze_trades_selects_latest_matching_result(tmp_path):
    old = tmp_path / "metrics_old.json"
    new = tmp_path / "metrics_new.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    old.touch()
    import os
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    rows = [
        {"label": "2025旧", "metrics_file": str(old)},
        {"label": "2025新", "metrics_file": str(new)},
    ]
    assert analyze_trades.select_latest_result(rows, label_contains="2025")["label"] == "2025新"


def test_analyze_trades_maps_metrics_json_to_trades_csv():
    path = analyze_trades.trades_path_for_result({"metrics_file": "metrics_short_2025.json"})
    assert path.replace("\\", "/").endswith("backtest_results/trades_short_2025.csv")


def test_rule_with_missing_required_fields_is_not_a_hit():
    df = pd.DataFrame([{"select_date": "20250102", "ts_code": "x", "score": 75}])
    result = rule_hit_diagnostics.evaluate_rule(df, "rerank_low_base_weak_pattern")
    assert result["_rule_hit"].tolist() == [False]


def test_rule_summary_rejects_duplicate_candidate_keys_and_missing_net_returns():
    candidates = pd.DataFrame([
        {"select_date": "20250102", "ts_code": "x", "score": 75, "original_score": 55, "factor_pattern": 40},
        {"select_date": "20250102", "ts_code": "x", "score": 74, "original_score": 55, "factor_pattern": 40},
    ])
    candidates = rule_hit_diagnostics.add_candidate_rank(candidates)
    candidates = rule_hit_diagnostics.evaluate_rule(candidates, "rerank_low_base_weak_pattern")
    with pytest.raises(ValueError, match="候选键重复"):
        rule_hit_diagnostics.summarize_rule_hits(
            candidates, pd.DataFrame([{"select_date": "20250102", "ts_code": "x", "profit_after_fee": 2}])
        )
    with pytest.raises(ValueError, match="profit_after_fee"):
        rule_hit_diagnostics.summarize_rule_hits(
            candidates.iloc[:1], pd.DataFrame([{"select_date": "20250102", "ts_code": "x"}])
        )


def test_sector_heat_rejects_stale_stock_rows_and_marks_missing_inputs():
    daily = pd.DataFrame([
        {"trade_date": "20250101", "ts_code": "x", "close": 10, "pct_chg": 1, "amount": 100},
        {"trade_date": "20250102", "ts_code": "y", "close": 10, "pct_chg": 1, "amount": 100},
    ])
    basics = pd.DataFrame([
        {"ts_code": "x", "name": "x", "industry": "甲", "list_status": "L"},
        {"ts_code": "y", "name": "y", "industry": "甲", "list_status": "L"},
    ])
    stocks = sector_heat_diagnostics._stock_metrics(daily, basics, "20250102")
    assert stocks.empty


def test_sector_heat_marks_missing_benchmark_and_market_inputs_as_degraded():
    daily = pd.DataFrame([
        {"trade_date": "20250101", "ts_code": "x", "close": 9, "pct_chg": 0, "amount": 100},
        {"trade_date": "20250102", "ts_code": "x", "close": 10, "pct_chg": 1, "amount": 120},
    ])
    basics = pd.DataFrame([{"ts_code": "x", "name": "x", "industry": "甲", "list_status": "L"}])
    heat, stocks = sector_heat_diagnostics.calculate_sector_heat(
        daily, basics, end_date="20250102", min_stocks=1,
    )
    assert heat.iloc[0]["data_quality"] == "degraded"
    assert "benchmark_missing" in heat.iloc[0]["data_quality_reasons"]
    assert "moneyflow_missing" in stocks.iloc[0]["data_quality_reasons"]


def test_sector_history_uses_exact_basic_snapshot(tmp_path):
    history = tmp_path / "stock_basic_history"
    history.mkdir()
    expected = pd.DataFrame([{"ts_code": "x", "name": "旧名", "industry": "旧行业", "list_status": "L"}])
    expected.to_parquet(history / "20250102.parquet")
    result = sector_heat_diagnostics.load_stock_basic_snapshot(tmp_path, "20250102")
    assert result.iloc[0]["industry"] == "旧行业"
    with pytest.raises(FileNotFoundError, match="精确快照"):
        sector_heat_diagnostics.load_stock_basic_snapshot(tmp_path, "20250103")


def test_old_news_fallback_filters_outside_requested_window(monkeypatch):
    stale = pd.DataFrame([{"新闻标题": "旧闻", "发布时间": "2010-01-01"}])
    fake_ak = SimpleNamespace(stock_news_em=lambda **_: stale)
    monkeypatch.setitem(__import__("sys").modules, "akshare", fake_ak)
    result = news_analyzer.get_policy_news(days=1, prefer_rich=False, as_of="20260907")
    assert result.empty


def test_news_sentiment_deduplicates_titles_and_reports_bad_dates():
    news = pd.DataFrame([
        {"title": "重大利好政策支持", "date": "2026-09-07"},
        {"title": "重大利好政策支持", "date": "2026-09-07"},
        {"title": "未来新闻利好", "date": "2099-01-01"},
        {"title": "无时间新闻利好", "date": "bad"},
    ])
    result = news_analyzer.analyze_news_sentiment(news, [], as_of="20260907", max_age_days=3)
    assert result["news_count_used"] == 1
    assert result["data_quality"] == "degraded"
    assert result["dropped_duplicate_count"] == 1
    assert result["dropped_bad_date_count"] == 2


def test_sector_boosts_drop_unknown_ai_industries():
    result = news_analyzer.build_sector_boosts([
        {"sectors": ["火星产业", "电子"], "impact": "positive", "strength": 10},
    ])
    assert result == {"电子": 30.0}


def test_market_decision_cannot_be_overridden_by_unknown_industry():
    mode, _, _ = market_analyzer.get_market_decision(
        "downtrend",
        {"sentiment": "正常", "ratio": 0, "limit_up_count": 0, "limit_down_count": 0},
        {"sentiment": "neutral", "score": 0, "ai_boost_total": 0},
        {"火星产业": 30},
    )
    assert mode == "stop"


def test_ths_concept_fallback_drops_stale_events():
    summary = pd.DataFrame([{"概念名称": "旧概念", "驱动事件": "旧闻", "日期": "2010-01-01"}])
    info = pd.DataFrame([{"项目": "板块涨幅", "值": "3%"}, {"项目": "涨跌家数", "值": "8/2"}])
    fake_ak = SimpleNamespace(
        stock_board_concept_summary_ths=lambda: summary,
        stock_board_concept_info_ths=lambda **_: info,
    )
    result = concept_heat_provider.fetch_real_concept_heat(
        top_n=5, ak_module=fake_ak, as_of_date="20260907", max_age_days=3,
    )
    assert result == []
