import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from web_app.app import app


class WebAppTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_dashboard_page_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("策略工作台", response.text)
        self.assertIn("最近运行决策", response.text)
        self.assertIn("行情有效日", response.text)
        self.assertIn("数据状态", response.text)
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
        response = self.client.get("/stock/000001")
        self.assertEqual(response.status_code, 200)
        self.assertIn("单股查询", response.text)
        self.assertIn("系统结论", response.text)
        self.assertIn("价格表现", response.text)
        self.assertIn("历史信号记录", response.text)

    def test_stock_page_accepts_chinese_name(self):
        response = self.client.get("/stock/平安银行")
        self.assertEqual(response.status_code, 200)
        self.assertIn("平安银行", response.text)

    def test_stock_page_shows_not_found_for_invalid_input(self):
        response = self.client.get("/stock/abcdef")
        self.assertEqual(response.status_code, 200)
        self.assertIn("未找到股票", response.text)
        self.assertNotIn("ABCDEF.SZ", response.text)

    def test_signals_page_renders(self):
        response = self.client.get("/signals")
        self.assertEqual(response.status_code, 200)
        self.assertIn("短线复盘", response.text)
        self.assertIn("收益路径", response.text)
        self.assertIn("系统原因", response.text)
        self.assertIn("可信度 / 复盘", response.text)
        self.assertIn("机会", response.text)
        self.assertIn("风险", response.text)
        self.assertIn("AI状态", response.text)
        self.assertIn("初筛通过", response.text)
        self.assertIn("可信度", response.text)
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
                "performance": {},
            }
            for index in range(120)
        ]
        with patch("web_app.app.get_signal_runs", return_value=[]), patch(
            "web_app.app.get_recent_signals", side_effect=[[], [], fake_signals]
        ), patch("web_app.app.get_short_live_push_history", return_value=[]):
            response = self.client.get("/signals?page=2&start=2026-01-01&industry=银行")

        self.assertEqual(response.status_code, 200)
        self.assertIn("第 2 / 3 页", response.text)
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

    def test_signal_explanation_page_renders(self):
        response = self.client.get("/explain/signal/20260525/000012.SZ")
        self.assertEqual(response.status_code, 200)
        self.assertIn("AI解释文档", response.text)
        self.assertIn("看好点", response.text)
        self.assertIn("风险点", response.text)

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


if __name__ == "__main__":
    unittest.main()
