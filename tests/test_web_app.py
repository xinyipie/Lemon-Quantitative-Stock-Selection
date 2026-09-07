import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_app.app import app


class WebAppTest(unittest.TestCase):
    def setUp(self):
        self.local_write = patch.dict(os.environ, {"STOCK_WEB_ALLOW_LOCAL_WRITE": "1"})
        self.local_write.start()
        self.addCleanup(self.local_write.stop)
        self.client = TestClient(app, client=("127.0.0.1", 41000))

    @staticmethod
    def stock_detail_fixture(query="000001", found=True):
        """提供旧页面结构测试所需的固定服务结果，不读取生产数据库。"""
        return {
            "query": query,
            "found": found,
            "stock": {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行"},
            "asset_type": "stock",
            "asset_type_label": "股票",
            "latest_daily": {"trade_date": "20260630", "close": 12.5, "pct_chg": 0.8},
            "latest_basic": {},
            "latest_moneyflow": {},
            "latest_finance": {},
            "returns": {"10d": None, "40d": None, "80d": None},
            "signal_state": {},
            "latest_trade_date": "20260630" if found else None,
            "verdict": {"level": "数据不足", "score": 0, "reasons": [], "risks": []},
            "price_chart": {"point_count": 0, "close_path": "", "ma20_path": "", "ma60_path": ""},
        }

    def test_dashboard_page_renders(self):
        status = {"latest_trade_date": "20260630", "latest_daily_stock_count": 1, "stock_count": 1}
        brief = {
            "source": "cache",
            "facts": {"trade_date": "20260630"},
            "doc": {"summary": "固定测试摘要", "positives": [], "risks": [], "confidence_note": "测试"},
        }
        with patch("web_app.app.get_db_status", return_value=status), patch(
            "web_app.app.read_update_status", return_value={}
        ), patch("web_app.app.get_recent_signals", return_value=[]), patch(
            "web_app.app.get_signal_runs", return_value=[]
        ), patch("web_app.app.get_active_longterm_pool", return_value=[]), patch(
            "web_app.app.get_longterm_runs", return_value=[]
        ), patch("web_app.app.get_daily_brief", return_value=brief):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("策略工作台", response.text)
        self.assertTrue("最近运行决策" in response.text or "历史判断" in response.text)
        self.assertIn("行情有效日", response.text)
        self.assertIn("数据状态", response.text)
        self.assertIn("已复盘至", response.text)
        self.assertIn("最近一次有股票入选", response.text)
        self.assertIn("最近AI摘要", response.text)
        self.assertIn("最近实盘短线", response.text)
        self.assertIn("快速检测", response.text)

        self.assertIn("更新到最新交易日", response.text)
        self.assertIn("完整重算", response.text)
        self.assertIn("单股体检", response.text)
        self.assertNotIn("批量体检自选股", response.text)
        self.assertIn("/update/run?mode=daily", response.text)
        self.assertIn("/update/run?mode=full", response.text)
        self.assertNotIn("/update/run?mode=dragon", response.text)
        self.assertNotIn("/update/run?mode=radar", response.text)
        self.assertLess(response.text.find("/update/run?mode=daily"), response.text.find("/update/run?mode=full"))
        self.assertIn("Strong Shortlist", response.text)
        self.assertIn('data-update-status-url="/update/status"', response.text)
        self.assertIn("data-background-update-form", response.text)
        self.assertIn("stock:updatePending", response.text)
        self.assertIn("window.location.reload()", response.text)

    def test_dashboard_has_accessible_responsive_shell(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="主导航"', response.text)
        self.assertIn('aria-controls="primary-navigation"', response.text)
        self.assertIn('class="mobile-nav-toggle"', response.text)
        self.assertIn('data-confirm-message=', response.text)

    def test_global_content_uses_all_available_width(self):
        response = self.client.get("/static/app.css")

        self.assertEqual(response.status_code, 200)
        self.assertIn(".content {", response.text)
        self.assertIn("max-width: none;", response.text.split(".content {", 1)[1].split("}", 1)[0])

    def test_global_usability_redesign_covers_every_page(self):
        css_response = self.client.get("/static/app.css")
        page_response = self.client.get("/")

        self.assertEqual(css_response.status_code, 200)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("ALL-PAGE USABILITY REDESIGN", css_response.text)
        for page_class in (
            "page-dashboard",
            "page-signals",
            "page-dragon",
            "page-longterm",
            "page-sectors",
            "page-stock",
            "page-db",
            "page-explanation",
        ):
            self.assertIn(f".{page_class}", css_response.text)
        css_href = page_response.text.split('rel="stylesheet" href="', 1)[1].split('"', 1)[0]
        self.assertEqual(self.client.get(css_href).status_code, 200)

    def test_dashboard_update_button_starts_background_update(self):
        with patch("web_app.app.start_web_update") as start_update:
            start_update.return_value = {"state": "running", "started": True}
            response = self.client.post("/update/run?mode=full", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        start_update.assert_called_once_with(mode="full")

    def test_dashboard_update_button_can_start_without_page_redirect_for_ajax(self):
        with patch("web_app.app.start_web_update") as start_update:
            start_update.return_value = {"state": "running", "started": True, "mode": "daily"}
            response = self.client.post("/update/run?mode=daily", headers={"Accept": "application/json"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "running")
        start_update.assert_called_once_with(mode="daily")

    def test_dashboard_update_button_labels_match_actions_after_polling(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/update/run?mode=daily"', response.text)
        self.assertIn('action="/update/run?mode=full"', response.text)
        self.assertNotIn('action="/update/run?mode=dragon"', response.text)
        self.assertNotIn('action="/update/run?mode=radar"', response.text)
        self.assertIn("button.dataset.updateLabel", response.text)
        self.assertIn("button.dataset.updateMode === status.mode", response.text)

    def test_update_status_endpoint_returns_json(self):
        with patch("web_app.app.read_update_status") as read_status:
            read_status.return_value = {
                "state": "running",
                "running": True,
                "message": "正在更新",
                "started_at": "2026-06-18 09:25:21",
            }
            response = self.client.get("/update/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "running")
        self.assertTrue(response.json()["running"])

    def test_db_status_page_renders(self):
        response = self.client.get("/db")
        self.assertEqual(response.status_code, 200)
        self.assertIn("数据库状态", response.text)
        self.assertIn("python daily_web_update.py --mode full --end 最新交易日", response.text)

    def test_db_page_offers_web_sync_and_advanced_cli_details(self):
        response = self.client.get("/db")

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/update/run?mode=daily"', response.text)
        self.assertIn("高级操作", response.text)
        self.assertNotIn("页面只读，不会自动拉取数据", response.text)

    def test_stock_page_renders_for_code(self):
        with patch("web_app.app.get_stock_detail", return_value=self.stock_detail_fixture()), patch(
            "web_app.app.get_stock_signals", return_value=[]
        ):
            response = self.client.get("/stock/000001")
        self.assertEqual(response.status_code, 200)
        self.assertIn("单股查询", response.text)
        self.assertIn("系统结论", response.text)
        self.assertIn("价格表现", response.text)
        self.assertIn("历史信号记录", response.text)

    def test_stock_page_accepts_chinese_name(self):
        with patch("web_app.app.get_stock_detail", return_value=self.stock_detail_fixture("平安银行")), patch(
            "web_app.app.get_stock_signals", return_value=[]
        ):
            response = self.client.get("/stock/平安银行")
        self.assertEqual(response.status_code, 200)
        self.assertIn("平安银行", response.text)

    def test_stock_page_shows_not_found_for_invalid_input(self):
        detail = self.stock_detail_fixture("abcdef", found=False)
        detail["stock"] = {"ts_code": "ABCDEF.SZ", "name": "", "industry": ""}
        with patch("web_app.app.get_stock_detail", return_value=detail):
            response = self.client.get("/stock/abcdef")
        self.assertEqual(response.status_code, 200)
        self.assertIn("未找到该品种", response.text)
        self.assertIn("abcdef", response.text)
        self.assertNotIn("ABCDEF.SZ", response.text)

    def test_signals_page_renders(self):
        response = self.client.get("/signals")
        self.assertEqual(response.status_code, 200)
        self.assertIn("短线复盘", response.text)
        self.assertIn("5日最终收益", response.text)
        self.assertIn("机会", response.text)
        self.assertIn("风险", response.text)
        self.assertIn("已满5日", response.text)
        self.assertIn("Strong Shortlist", response.text)
        self.assertIn('data-update-status-url="/update/status"', response.text)
        self.assertIn("stock:updatePending", response.text)

    def test_signals_page_paginates_and_preserves_filters(self):
        fake_signals = [
            {
                "trade_date": "20260709",
                "ts_code": f"{index:06d}.SZ",
                "display_name": f"样本{index}",
                "display_code": f"{index:06d}",
                "industry": "银行",
                "score": 60,
                "factors": {},
                "ai_view": {},
                "performance": {"ret_3d": 1.0, "ret_5d": 2.0, "ret_8d": 3.0, "mfe_pct": 4.0, "mae_pct": -1.0},
            }
            for index in range(120)
        ]
        with patch("web_app.app.get_signal_runs", return_value=[]), patch(
            "web_app.app.get_recent_signals", side_effect=lambda *args, **kwargs: fake_signals if kwargs.get("limit") in {900, 3000} else []
        ), patch("web_app.app.get_short_live_push_history", return_value=[]):
            response = self.client.get("/signals?page=2&start=2026-01-01&industry=银行")

        self.assertEqual(response.status_code, 200)
        self.assertIn("第 2 / 4 页", response.text)
        self.assertIn("样本30", response.text)
        self.assertNotIn("样本60", response.text)
        self.assertIn('type="date"', response.text)
        self.assertIn('class="table-shell"', response.text)

    def test_signals_page_uses_latest_run_date_when_no_new_signals(self):
        with patch("web_app.app.get_signal_runs") as get_runs, patch("web_app.app.get_recent_signals") as get_signals:
            get_runs.return_value = [
                {
                    "trade_date": "20260630",
                    "status_label": "无入选标的",
                    "signal_count": 0,
                }
            ]
            get_signals.return_value = []
            response = self.client.get("/signals")

        self.assertEqual(response.status_code, 200)
        self.assertIn("2026-06-30", response.text)

    def test_signals_kpi_uses_the_selected_strategy_samples(self):
        from fastapi import Response

        steady = {"strategy_key": "steady", "performance": {"ret_5d": 5.0}, "factors": {}}
        repair = {"strategy_key": "repair", "performance": {"ret_5d": -5.0}, "factors": {}}

        def fake_signals(*args, **kwargs):
            return [steady, repair] if kwargs.get("limit") == 900 else []

        with patch("web_app.app.get_signal_runs", return_value=[]), patch(
            "web_app.app.get_recent_signals", side_effect=fake_signals
        ), patch("web_app.app.get_short_live_push_history", return_value=[]), patch(
            "web_app.app.summarize_short_signal_performance", return_value={}
        ) as summarize, patch(
            "web_app.app.templates.TemplateResponse", return_value=Response("ok")
        ):
            response = self.client.get("/signals?strategy=steady")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(summarize.call_args.args[0], [steady])
        self.assertEqual(summarize.call_args.kwargs["limit"], 1)

    def test_strategy_links_urlencode_existing_filters(self):
        with patch("web_app.app.get_signal_runs", return_value=[]), patch(
            "web_app.app.get_recent_signals", return_value=[]
        ), patch("web_app.app.get_short_live_push_history", return_value=[]):
            response = self.client.get("/signals?q=A%26B%2BC%23D&industry=%E9%93%B6%E8%A1%8C%26AI")

        self.assertEqual(response.status_code, 200)
        self.assertIn("q=A%26B%2BC%23D", response.text)
        self.assertIn("industry=%E9%93%B6%E8%A1%8C%26AI", response.text)

    def test_configured_token_protects_reads_and_accepts_bearer_and_basic(self):
        import base64

        basic = base64.b64encode(b"stock:secret").decode("ascii")
        with patch.dict(os.environ, {"STOCK_WEB_TOKEN": "secret"}):
            denied = self.client.get("/")
            bearer = self.client.get("/static/app.css", headers={"Authorization": "Bearer secret"})
            browser = self.client.get("/static/app.css", headers={"Authorization": f"Basic {basic}"})

        self.assertEqual(denied.status_code, 401)
        self.assertIn("Basic", denied.headers["www-authenticate"])
        self.assertEqual(bearer.status_code, 200)
        self.assertEqual(browser.status_code, 200)

    def test_non_ascii_basic_password_is_rejected_without_server_error(self):
        import base64

        basic = base64.b64encode("stock:错误".encode("utf-8")).decode("ascii")
        with patch.dict(os.environ, {"STOCK_WEB_TOKEN": "secret"}):
            response = self.client.get("/", headers={"Authorization": f"Basic {basic}"})

        self.assertEqual(response.status_code, 401)

    def test_remote_write_is_forbidden_without_configured_token(self):
        remote_client = TestClient(app, client=("203.0.113.9", 41000))
        with patch.dict(os.environ, {"STOCK_WEB_ALLOW_LOCAL_WRITE": "1"}, clear=True), patch(
            "web_app.app.start_web_update"
        ) as start_update:
            response = remote_client.post("/update/run?mode=daily")

        self.assertEqual(response.status_code, 403)
        start_update.assert_not_called()

    def test_local_write_requires_explicit_development_opt_in_without_token(self):
        with patch.dict(os.environ, {}, clear=True), patch("web_app.app.start_web_update") as start_update:
            response = self.client.post("/update/run?mode=daily")

        self.assertEqual(response.status_code, 403)
        start_update.assert_not_called()

    def test_cross_origin_write_is_forbidden(self):
        with patch.dict(os.environ, {"STOCK_WEB_ALLOW_LOCAL_WRITE": "1"}, clear=True), patch(
            "web_app.app.start_web_update"
        ) as start_update:
            response = self.client.post(
                "/update/run?mode=daily",
                headers={"Origin": "https://attacker.example"},
            )

        self.assertEqual(response.status_code, 403)
        start_update.assert_not_called()

    def test_signal_explanation_get_only_reads_cached_content(self):
        cached = {
            "source": "cache",
            "doc": {"title": "缓存解释", "summary": "只读", "positives": [], "risks": []},
            "signal": {},
        }
        with patch("web_app.app.get_signal_explanation", return_value=cached) as read_cached, patch(
            "web_app.app.get_or_create_signal_explanation"
        ) as generate:
            response = self.client.get("/explain/signal/20260525/000012.SZ")

        self.assertEqual(response.status_code, 200)
        read_cached.assert_called_once()
        generate.assert_not_called()

    def test_signal_explanation_cache_lock_returns_service_unavailable(self):
        from web_app.services.explanation_service import ExplanationCacheBusyError

        with patch("web_app.app.get_signal_explanation", side_effect=ExplanationCacheBusyError("busy")):
            response = self.client.get("/explain/signal/20260525/000012.SZ")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["retry-after"], "2")

    def test_dashboard_uses_single_retrying_update_poller(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count("async function fetchStatus()"), 1)
        self.assertIn("scheduleNext", response.text)
        self.assertIn("throw new Error", response.text)
        self.assertIn("window.sessionStorage.removeItem(pendingKey)", response.text)
        self.assertIn("if (!response.ok)", response.text)

    def test_signal_explanation_page_renders(self):
        cached = {
            "source": "cache",
            "signal": {
                "trade_date": "20260525", "ts_code": "000012.SZ", "name": "测试股票",
                "display_name": "测试股票", "display_code": "000012", "industry": "测试行业",
                "profile": "short_v9_final", "profile_label": "短线策略", "score": 70,
                "outcome_label": "待验证", "basis_text": "固定入选依据",
                "performance_text": "尚未形成结果", "process_label": "观察中",
            },
            "doc": {
                "title": "固定解释",
                "summary": "固定缓存内容",
                "positives": ["当时可见的量价因素"],
                "risks": ["样本风险"],
                "watch_plan": "等待量价确认",
                "invalidation": "跌破观察位",
                "confidence_note": "固定测试快照",
            },
        }
        with patch("web_app.app.get_signal_explanation", return_value=cached):
            response = self.client.get("/explain/signal/20260525/000012.SZ")
        self.assertEqual(response.status_code, 200)
        self.assertIn("AI解释文档", response.text)
        self.assertIn("当时已知的支持因素", response.text)
        self.assertIn("风险点", response.text)
        self.assertIn('method="post"', response.text)

    def test_signal_explanation_refresh_uses_post_and_redirects_to_canonical_url(self):
        with patch("web_app.app.get_or_create_signal_explanation") as get_explanation:
            get_explanation.return_value = {"source": "ai", "doc": {}, "signal": {}}
            response = self.client.post(
                "/explain/signal/20260525/000012.SZ/refresh",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/explain/signal/20260525/000012.SZ")
        self.assertTrue(get_explanation.call_args.kwargs["force"])

    def test_longterm_page_renders(self):
        response = self.client.get("/longterm")
        self.assertEqual(response.status_code, 200)
        self.assertIn("长线观察池", response.text)
        self.assertIn("Elite", response.text)
        self.assertIn("Watch", response.text)
        self.assertIn('data-update-status-url="/update/status"', response.text)
        self.assertIn("stock:updatePending", response.text)
        self.assertIn("最近运行", response.text)
        self.assertIn("生命周期事件", response.text)
        self.assertIn("历史长线池验证", response.text)

    def test_longterm_page_accepts_sample_date_filters(self):
        response = self.client.get("/longterm?start=20260201&end=20260228")
        self.assertEqual(response.status_code, 200)
        self.assertIn("当前明细筛选", response.text)
        self.assertIn("20260201", response.text)
        self.assertIn("20260228", response.text)

    def test_longterm_page_has_section_navigation_and_pagination(self):
        samples = [{"select_date": "20260709", "ts_code": f"{index:06d}.SZ", "ret_80d": 2.0} for index in range(120)]
        with patch("web_app.app.get_active_longterm_pool", return_value=[]), patch(
            "web_app.app.get_longterm_runs", return_value=[]
        ), patch("web_app.app.get_longterm_events", return_value=[]), patch(
            "web_app.app.get_longterm_audit_summary", return_value={"runs": []}
        ), patch("web_app.app.get_longterm_audit_samples", return_value=samples):
            response = self.client.get("/longterm?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="#current-pool"', response.text)
        self.assertIn('href="#lifecycle"', response.text)
        self.assertIn('href="#history-audit"', response.text)
        self.assertIn('class="pagination"', response.text)
        self.assertIn("第 2 / 4 页", response.text)
        self.assertIn("000030.SZ", response.text)
        self.assertNotIn("000060.SZ", response.text)


if __name__ == "__main__":
    unittest.main()
