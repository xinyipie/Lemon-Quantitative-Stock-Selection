import os
import sqlite3
import hashlib
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web_app.app import app
from web_app.services.dragon_service import _empty_observation


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STOCK_WEB_ALLOW_LOCAL_WRITE", "1")
    monkeypatch.delenv("STOCK_WEB_TOKEN", raising=False)
    return TestClient(app, client=("127.0.0.1", 41000))


def _history_db(
    path: Path,
    asset_type: str,
    include_daily: bool = True,
    include_basic: bool = True,
) -> None:
    basic_table = "index_basic" if asset_type == "index" else "fund_basic"
    daily_table = "index_daily" if asset_type == "index" else "fund_daily"
    ts_code = "000300.SH" if asset_type == "index" else "510300.SH"
    name = "沪深300" if asset_type == "index" else "测试ETF"
    extra_column = "category" if asset_type == "index" else "fund_type"
    extra_value = "规模指数" if asset_type == "index" else "股票型"
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"create table {basic_table} (ts_code text, name text, {extra_column} text)"
        )
        if include_basic:
            conn.execute(
                f"insert into {basic_table} values (?, ?, ?)",
                (ts_code, name, extra_value),
            )
        conn.execute(
            f"create table {daily_table} (ts_code text, trade_date text, close real, pct_chg real)"
        )
        if include_daily:
            conn.execute(
                f"insert into {daily_table} values (?, ?, ?, ?)",
                (ts_code, "20260630", 4010.25, 0.8),
            )


@pytest.mark.parametrize(
    ("asset_type", "query", "expected_label", "include_daily", "include_basic"),
    [
        ("index", "沪深300", "指数行情", True, False),
        ("index", "000300.SH", "指数行情", True, False),
        ("fund", "测试ETF", "ETF/场内基金行情", False, True),
    ],
)
def test_non_stock_detail_renders_without_stock_only_fields(
    client, tmp_path, asset_type, query, expected_label, include_daily, include_basic
):
    history_db = tmp_path / f"{asset_type}.db"
    _history_db(
        history_db,
        asset_type,
        include_daily=include_daily,
        include_basic=include_basic,
    )

    with patch("web_app.app.DEFAULT_HISTORY_DB_PATH", history_db), patch(
        "web_app.app.get_stock_signals", return_value=[]
    ) as get_signals:
        response = client.get(f"/stock/{query}")

    assert response.status_code == 200
    assert expected_label in response.text
    assert "估值质量" not in response.text
    assert "主力净流入" not in response.text
    assert "历史信号记录" not in response.text
    get_signals.assert_not_called()
    if asset_type == "index":
        assert "<h2>沪深300</h2>" in response.text
        assert "4010.25" in response.text
        assert "点" in response.text


def test_mounted_explicit_index_code_uses_index_daily_without_index_basic(tmp_path):
    history_db = tmp_path / "index.db"
    _history_db(history_db, "index", include_daily=True, include_basic=False)
    gateway = FastAPI()
    gateway.mount("/stock", app)

    with patch("web_app.app.DEFAULT_HISTORY_DB_PATH", history_db), patch(
        "web_app.app.get_stock_signals", return_value=[]
    ) as get_signals:
        response = TestClient(gateway).get("/stock/stock/000300.SH")

    assert response.status_code == 200
    assert "沪深300" in response.text
    assert "指数行情" in response.text
    get_signals.assert_not_called()


@pytest.mark.parametrize("query", ["000001", "abcdef"])
def test_empty_history_database_returns_a_readable_empty_state(client, tmp_path, query):
    history_db = tmp_path / "empty.db"
    sqlite3.connect(history_db).close()
    signal_db = tmp_path / "empty-signals.db"
    sqlite3.connect(signal_db).close()

    with patch("web_app.app.DEFAULT_HISTORY_DB_PATH", history_db), patch(
        "web_app.app.DEFAULT_SIGNAL_DB_PATH", signal_db
    ):
        response = client.get(f"/stock/{query}")

    assert response.status_code == 200
    assert "未找到该品种" in response.text
    assert query in response.text


def test_served_stylesheet_exposes_close_line_and_readable_content_navigation(client):
    css = client.get("/static/app.css").text
    close_rule = css.split(".chart-close", 1)[1].split("}", 1)[0]
    content_nav_rule = css.split(".page-section-nav a", 1)[1].split("}", 1)[0]

    assert "var(--blue)" in close_rule
    assert "color: var(--ink)" in content_nav_rule


def test_stylesheet_url_version_matches_served_content(client):
    deps = _dashboard_dependencies()
    with ExitStack() as stack:
        for name, value in deps.items():
            stack.enter_context(patch(f"web_app.app.{name}", return_value=value))
        page = client.get("/")

    css_href = page.text.split('rel="stylesheet" href="', 1)[1].split('"', 1)[0]
    parsed = urlsplit(css_href)
    css = client.get(parsed.path)
    expected = hashlib.sha256(css.content).hexdigest()[:12]

    assert parse_qs(parsed.query)["v"] == [expected]


def _dashboard_dependencies():
    status = {
        "latest_trade_date": "20260630",
        "latest_daily_stock_count": 1,
        "stock_count": 1,
    }
    live_run = {"trade_date": "20260630", "signal_count": 0, "status_label": "无入池标的"}
    return {
        "get_db_status": status,
        "read_update_status": {},
        "get_recent_signals": [],
        "get_signal_runs": [live_run],
        "get_active_longterm_pool": [],
        "get_longterm_runs": [],
        "get_daily_brief": None,
    }


def test_mounted_dashboard_prefixes_dynamic_actions_and_marks_stale_decision_historical(monkeypatch):
    monkeypatch.setenv("STOCK_WEB_ALLOW_LOCAL_WRITE", "1")
    deps = _dashboard_dependencies()
    decision = {
        "level": "今日不宜开新仓",
        "tone": "caution",
        "stance": "今日只观察",
        "reasons": [],
        "next_actions": [
            {"label": "单股体检", "href": "/stock/000001", "hint": "查看"}
        ],
    }
    with ExitStack() as stack:
        for name, value in deps.items():
            stack.enter_context(patch(f"web_app.app.{name}", return_value=value))
        stack.enter_context(patch("web_app.app.build_dashboard_decision", return_value=decision))
        response = TestClient(
            app,
            root_path="/stock",
            client=("127.0.0.1", 41000),
        ).get("/")

    assert response.status_code == 200
    assert 'href="/stock/stock/000001"' in response.text
    assert "截至 2026-06-30 的历史判断" in response.text
    assert "今日决策" not in response.text
    assert "今日只观察" not in response.text


def test_stale_dashboard_labels_cached_ai_brief_as_historical(client):
    deps = _dashboard_dependencies()
    deps["get_daily_brief"] = {
        "source": "cache",
        "facts": {"trade_date": "20260630"},
        "doc": {
            "summary": "今日更适合防守和观察",
            "positives": [],
            "risks": [],
            "confidence_note": "旧缓存正文",
        },
    }
    with ExitStack() as stack:
        for name, value in deps.items():
            stack.enter_context(patch(f"web_app.app.{name}", return_value=value))
        response = client.get("/")

    assert response.status_code == 200
    assert "历史摘要 · 来源日期 2026-06-30" in response.text
    assert "不能作为当前建议" in response.text
    assert "今日更适合防守和观察" in response.text


def test_db_status_uses_shared_status_panel_and_freshness_message(client):
    status = {
        "latest_trade_date": "20260630",
        "latest_daily_stock_count": 1,
        "stock_count": 1,
        "tables": {},
    }
    update = {
        "state": "finished",
        "running": False,
        "message": "同步完成",
        "display_message": "行情有效日停在 20260630",
        "alignment_state": "warn",
        "finished_at": "2026-07-01 10:00:00",
    }
    with patch("web_app.app.get_db_status", return_value=status), patch(
        "web_app.app._read_decorated_update_status", return_value=update
    ), patch("web_app.app.read_update_status", return_value=update):
        response = client.get("/db")

    assert response.status_code == 200
    assert 'data-update-status-url="/update/status"' in response.text
    assert "行情有效日停在 20260630" in response.text
    assert 'data-update-finished' in response.text


def test_stale_signal_and_dragon_pages_use_historical_time_language(client):
    live_run = {"trade_date": "20260630", "signal_count": 0, "status_label": "无入池标的"}
    with patch("web_app.app.get_signal_runs", return_value=[live_run]), patch(
        "web_app.app.get_recent_signals", return_value=[]
    ), patch("web_app.app.get_short_live_push_history", return_value=[]), patch(
        "web_app.app.read_update_status", return_value={}
    ):
        signals = client.get("/signals")

    dragon_payload = _empty_observation(end_date="20260630")
    dragon_payload["emotion_snapshot"]["summary_text"] = "情绪回落，明日偏向：降低短线出手。"
    with patch("web_app.app.build_dragon_observation", return_value=dragon_payload), patch(
        "web_app.app.read_update_status", return_value={}
    ):
        dragon = client.get("/dragon")

    assert "截至 2026-06-30 的历史扫描" in signals.text
    assert "今日无强推荐" not in signals.text
    assert "下一交易日倾向（历史）" in dragon.text
    assert "明日偏向" not in dragon.text


def test_write_denial_uses_chinese_message(client, monkeypatch):
    monkeypatch.delenv("STOCK_WEB_ALLOW_LOCAL_WRITE", raising=False)

    response = client.post(
        "/explain/signal/20260525/000012.SZ/refresh",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "当前服务为只读模式，未启用写操作"


def test_reversed_signal_dates_show_error_and_skip_history_query(client):
    live_run = {"trade_date": "20260630", "signal_count": 0, "status_label": "无入池标的"}
    with patch("web_app.app.get_signal_runs", return_value=[live_run]), patch(
        "web_app.app.get_recent_signals", return_value=[]
    ) as get_signals, patch("web_app.app.get_short_live_push_history", return_value=[]), patch(
        "web_app.app.read_update_status", return_value={}
    ):
        response = client.get("/signals?start=2026-06-30&end=2026-01-01")

    history_calls = [
        call for call in get_signals.call_args_list if call.kwargs.get("limit") == 900
    ]
    assert response.status_code == 200
    assert "开始日期不能晚于结束日期" in response.text
    assert history_calls == []


def test_reversed_report_dates_show_error_without_querying_archive(client):
    with patch("web_app.app.build_report_archive_context") as build_archive:
        response = client.get("/reports?start=2026-06-30&end=2026-01-01")

    assert response.status_code == 200
    assert "开始日期不能晚于结束日期" in response.text
    build_archive.assert_not_called()


def test_reversed_longterm_dates_show_error_without_querying_samples(client):
    with patch("web_app.app.get_active_longterm_pool", return_value=[]), patch(
        "web_app.app.get_longterm_runs", return_value=[]
    ), patch("web_app.app.get_longterm_events", return_value=[]), patch(
        "web_app.app.get_longterm_audit_summary", return_value={"runs": []}
    ), patch("web_app.app.get_longterm_audit_samples") as get_samples, patch(
        "web_app.app.read_update_status", return_value={}
    ):
        response = client.get("/longterm?start=2026-06-30&end=2026-01-01")

    assert response.status_code == 200
    assert "开始日期不能晚于结束日期" in response.text
    get_samples.assert_not_called()


def test_stale_longterm_run_uses_historical_conclusion_heading(client):
    run = {"trade_date": "20260723", "status_label": "无入池标的"}
    with patch("web_app.app.get_active_longterm_pool", return_value=[]), patch(
        "web_app.app.get_longterm_runs", return_value=[run]
    ), patch("web_app.app.get_longterm_events", return_value=[]), patch(
        "web_app.app.get_longterm_audit_summary", return_value={"runs": []}
    ), patch("web_app.app.get_longterm_audit_samples", return_value=[]), patch(
        "web_app.app.build_longterm_run_funnel", return_value={}
    ), patch(
        "web_app.app.build_longterm_pool_status",
        return_value={"tone": "neutral", "title": "当前长线池为空", "description": "历史扫描无入池标的", "subtitle": "0只"},
    ), patch("web_app.app.read_update_status", return_value={}):
        response = client.get("/longterm")

    assert response.status_code == 200
    assert "截至 2026-07-23 的历史长线结论" in response.text
    assert "今日长线结论" not in response.text


def test_strategy_history_panels_disclose_that_statistics_are_not_recomputed():
    notice = "历史统计尚未按本次修复重算，仅供复盘参考"
    template_dir = Path("web_app/templates")

    for filename in ("signals.html", "dragon_leaders.html", "longterm_pool.html"):
        assert notice in (template_dir / filename).read_text(encoding="utf-8")
