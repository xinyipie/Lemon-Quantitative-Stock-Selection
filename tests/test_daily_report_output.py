import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["LEMON_SKIP_TUSHARE_INIT"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from main import _write_daily_report
import main


class DailyReportOutputTest(unittest.TestCase):
    def test_short_report_uses_actual_count_and_v9_score_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_reports_dir = config.REPORTS_DIR
            config.REPORTS_DIR = tmpdir
            try:
                _write_daily_report(
                    "20260603",
                    [
                        {
                            "code": "002326",
                            "name": "永太科技",
                            "industry": "化工原料",
                            "close": 21.95,
                            "score": 36.21,
                            "original_score": 58.27,
                            "experiment_score": 36.21,
                            "factor_profile": "profile_v9_sector_quality_guard",
                            "style_gate": "adaptive_quality_v6",
                            "risk": "中等",
                            "sentiment": "正面",
                            "target_price": 23.33,
                            "stop_loss_price": 20.59,
                            "expected_gain_pct": 6,
                            "reason": "测试说明",
                        }
                    ],
                    [],
                    sentiment_data=None,
                    market_style="sideways",
                )
            finally:
                config.REPORTS_DIR = old_reports_dir

            report = Path(tmpdir, "report_20260603.txt").read_text(encoding="utf-8")

        self.assertIn("短线建议 Top1（Top3候选不足，持有 1-3 天）", report)
        self.assertIn("v9重排分：36分", report)
        self.assertIn("原始短线分：58分 → v9重排分：36分", report)
        self.assertNotIn("技术基础分", report)
        self.assertNotIn("最终综合评分", report)

    def test_short_report_explains_candidate_as_decision_card(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_reports_dir = config.REPORTS_DIR
            config.REPORTS_DIR = tmpdir
            try:
                _write_daily_report(
                    "20260603",
                    [
                        {
                            "code": "002326",
                            "name": "永太科技",
                            "industry": "化工原料",
                            "close": 21.95,
                            "score": 36.21,
                            "original_score": 58.27,
                            "experiment_score": 36.21,
                            "factor_profile": "profile_v9_sector_quality_guard",
                            "risk": "中等",
                            "sentiment": "正面",
                            "volume_ratio": 1.87,
                            "drawdown_from_high": 12.5,
                            "main_net_inflow": 2893,
                            "factor_sector": 50,
                            "factor_pattern": 63.33,
                            "target_price": 23.33,
                            "stop_loss_price": 20.59,
                            "expected_gain_pct": 6,
                            "reason": "测试说明",
                        }
                    ],
                    [],
                    sentiment_data=None,
                    market_style="sideways",
                )
            finally:
                config.REPORTS_DIR = old_reports_dir

            report = Path(tmpdir, "report_20260603.txt").read_text(encoding="utf-8")

        self.assertIn("结论：可关注，但不是强进攻票", report)
        self.assertIn("入选原因：原始短线分58分，资金流为净流入，量比1.87合格", report)
        self.assertIn("v9降权原因：回撤12.5%偏深", report)
        self.assertIn("当前风险：Top3候选不足，仅剩Top1", report)
        self.assertIn("操作理解：轻仓观察", report)
        self.assertIn("主力资金：+2893万元（主力净流入）", report)

    def test_short_report_renders_ai_execution_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_reports_dir = config.REPORTS_DIR
            config.REPORTS_DIR = tmpdir
            try:
                _write_daily_report(
                    "20260603",
                    [
                        {
                            "code": "002326",
                            "name": "永太科技",
                            "industry": "化工原料",
                            "close": 21.95,
                            "score": 56,
                            "original_score": 58,
                            "factor_profile": "profile_v9_sector_quality_guard",
                            "risk": "中等",
                            "sentiment": "正面",
                            "target_price": 23.33,
                            "stop_loss_price": 20.59,
                            "expected_gain_pct": 6,
                            "buy_condition": "次日平开后站稳22元再考虑。",
                            "avoid_condition": "高开超过3%或跌破21元放弃。",
                            "stop_plan": "跌破20.59元且不能收回则退出。",
                            "take_profit_plan": "接近23.33元先锁定利润。",
                            "position_advice": "正常小仓位，分批参与。",
                            "reason": "测试说明",
                        }
                    ],
                    [],
                    sentiment_data=None,
                    market_style="sideways",
                )
            finally:
                config.REPORTS_DIR = old_reports_dir

            report = Path(tmpdir, "report_20260603.txt").read_text(encoding="utf-8")

        self.assertIn("【明日执行计划】", report)
        self.assertIn("可买条件：次日平开后站稳22元再考虑。", report)
        self.assertIn("放弃条件：高开超过3%或跌破21元放弃。", report)
        self.assertIn("止损纪律：跌破20.59元且不能收回则退出。", report)
        self.assertIn("止盈/移动止损：接近23.33元先锁定利润。", report)
        self.assertIn("仓位倾向：正常小仓位，分批参与。", report)

    def test_longterm_report_marks_elite_alert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_reports_dir = config.REPORTS_DIR
            config.REPORTS_DIR = tmpdir
            try:
                _write_daily_report(
                    "20260612",
                    [],
                    [
                        {
                            "code": "000001",
                            "name": "长线A",
                            "industry": "AI",
                            "score": 88,
                            "trend_strength": 76,
                            "risk": "中等",
                            "sentiment": "正面",
                            "close": 10.0,
                            "buy_price_low": 9.8,
                            "buy_price_high": 10.2,
                            "target_price": 13.0,
                            "expected_gain_pct": 30,
                            "hold_weeks": 12,
                            "stop_loss_price": 9.0,
                            "compression_score": 91,
                            "elite_alert": True,
                            "reason": "测试说明",
                        }
                    ],
                    sentiment_data=None,
                    market_style="sideways",
                )
            finally:
                config.REPORTS_DIR = old_reports_dir

            report = Path(tmpdir, "report_20260612.txt").read_text(encoding="utf-8")

        self.assertIn("Elite", report)
        self.assertIn("91", report)

    def test_report_says_longterm_disabled_without_legacy_swing_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_reports_dir = config.REPORTS_DIR
            config.REPORTS_DIR = tmpdir
            try:
                _write_daily_report(
                    "20260612",
                    [],
                    [],
                    sentiment_data=None,
                    market_style="sideways",
                    include_longterm=False,
                )
            finally:
                config.REPORTS_DIR = old_reports_dir

            report = Path(tmpdir, "report_20260612.txt").read_text(encoding="utf-8")

        self.assertIn("长线观察池未启用", report)
        self.assertNotIn("暂无波段候选", report)
        self.assertNotIn("波段策略暂停", report)


class PlainLogRecordTest(unittest.TestCase):
    def test_plain_log_record_converts_numpy_like_scalars(self):
        class FakeScalar:
            def item(self):
                return 58.276

        record = main._plain_log_record({"code": "000001.SZ", "score": FakeScalar(), "name": "平安银行"})

        self.assertEqual(record["score"], 58.28)
        self.assertEqual(record["code"], "000001.SZ")


if __name__ == "__main__":
    unittest.main()
