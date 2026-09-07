from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from daily_report.facts import FactSources, build_daily_report_facts


def _fake_sources(empty_formal=False):
    snapshot = {
        "trade_date": "20260722",
        "created_at": "2026-07-23T02:05:00+08:00",
        "market": {
            "market_state": "normal",
            "market_style": "sideways",
            "macro_mode": "cautious",
            "regime": "BULL_TREND",
            "regime_data": {"price_vs_ma60_pct": 1.2},
            "operation_mode": "light",
            "sentiment": {"limit_up_count": 45, "limit_down_count": 8},
        },
        "short_scan": {
            "status": "completed_empty" if empty_formal else "completed_with_results",
            "formal_count": 0 if empty_formal else 1,
            "observe_count": 0 if empty_formal else 1,
        },
        "longterm_scan": {
            "status": "not_triggered" if empty_formal else "completed_with_results",
            "raw_count": 0 if empty_formal else 1,
            "watch_count": 0 if empty_formal else 1,
            "elite_count": 0,
        },
    }

    def recent_signals(*args, **kwargs):
        source = kwargs.get("source")
        if source == "live":
            return [] if empty_formal else [{
                "ts_code": "000001.SZ", "name": "平安银行", "industry": "银行",
                "rank": 1, "score": 81, "reason": "资金承接稳定",
            }]
        if source == "live_observe":
            return [] if empty_formal else [{
                "ts_code": "000002.SZ", "name": "万科A", "industry": "房地产",
                "rank": 1, "score": 63, "reason": "仅观察修复",
            }]
        return [
            {"performance": {"ret_5d": 4.0, "mfe_pct": 7.0, "mae_pct": -2.0}},
            {"performance": {"ret_5d": -1.0, "mfe_pct": 2.0, "mae_pct": -4.0}},
        ]

    active = [] if empty_formal else [{
        "ts_code": "000001.SZ", "name": "平安银行", "industry": "银行",
        "latest_score": 79, "days_in_pool": 4, "last_reason": "趋势仍在",
        "profile": "longterm_watch", "state": "active",
    }]
    candidates = [
        {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行", "stage": "趋势延续", "pct_chg": 1.1},
        {"ts_code": "600519.SH", "name": "贵州茅台", "industry": "白酒", "stage": "低位启动", "pct_chg": 0.8},
    ]
    dragon = {"trade_date": "20260722", "display_groups": {
        "priority": [] if empty_formal else [{
            "ts_code": "000001.SZ", "name": "平安银行", "industry": "银行",
            "late_or_fragile": True, "stage": "高位分歧",
        }],
        "caution": [],
    }}
    return FactSources(
        selection_snapshot=lambda *args, **kwargs: snapshot,
        recent_signals=recent_signals,
        active_longterm=lambda *args, **kwargs: active,
        signal_runs=lambda *args, **kwargs: [],
        longterm_runs=lambda *args, **kwargs: [],
        longterm_events=lambda *args, **kwargs: [],
        longterm_audit_summary=lambda *args, **kwargs: {"total_samples": 12, "runs": [{"period": "2026H1", "sample_count": 12, "avg_ret_40d": 3.2}]},
        sector_radar=lambda *args, **kwargs: {
            "end_date": "20260722", "summary": {"market_breadth": "分化"},
            "healthy": [{"industry": "银行", "stage": "趋势延续", "heat_score": 72}],
            "risky": [{"industry": "银行", "stage": "过热高潮", "heat_score": 88}],
            "candidates": candidates,
        },
        concept_news=lambda *args, **kwargs: {
            "events": [{"title": "行业政策更新", "industry": "银行", "impact": "中性"}],
            "reading_events": [{"title": "行业政策更新", "industry": "银行", "impact": "中性"}],
            "news": {"source_date": "20260723"},
        },
        radar_decision=lambda radar, news: {"alignment": "主线分裂", "confidence": "中", "focus_industries": ["银行"]},
        dragon_observation=lambda *args, **kwargs: dragon,
        short_performance=lambda signals, limit: {
            "count": 2, "closed_count": 2, "win_rate": 0.5,
            "avg_ret_5d": 1.5, "avg_mfe": 4.5, "avg_mae": -3.0,
        },
    )


class DailyReportFactsTest(unittest.TestCase):
    def test_merges_all_allowed_sources_and_marks_conflict(self):
        with TemporaryDirectory() as tmp:
            facts = build_daily_report_facts(
                "20260723", "20260722", Path(tmp) / "signals.db", Path(tmp) / "history.db",
                sources=_fake_sources(),
            )
        self.assertEqual(len(facts["observations"]), 3)
        pingan = next(item for item in facts["observations"] if item["ts_code"] == "000001.SZ")
        self.assertEqual(
            set(pingan["sources"]),
            {"short_formal", "longterm_active", "market_radar", "dragon_priority"},
        )
        self.assertTrue(pingan["conflicts"])
        self.assertEqual(facts["source_status"]["short_formal"]["state"], "available")
        self.assertTrue(facts["completeness"]["can_publish"])
        self.assertNotIn("combined_score", pingan)

    def test_radar_does_not_fill_empty_formal_pool(self):
        with TemporaryDirectory() as tmp:
            facts = build_daily_report_facts(
                "20260723", "20260722", Path(tmp) / "signals.db", Path(tmp) / "history.db",
                sources=_fake_sources(empty_formal=True),
            )
        maotai = next(item for item in facts["observations"] if item["ts_code"] == "600519.SH")
        self.assertEqual(maotai["sources"], ["market_radar"])
        self.assertEqual(facts["source_status"]["short_formal"]["state"], "completed_empty")
        self.assertEqual(facts["source_status"]["longterm_active"]["state"], "not_triggered")
        self.assertEqual(facts["source_status"]["short_formal"]["count"], 0)

    def test_caution_group_is_always_exposed_as_a_conflict(self):
        sources = _fake_sources(empty_formal=True)
        sources.dragon_observation = lambda *args, **kwargs: {
            "trade_date": "20260722",
            "display_groups": {
                "priority": [],
                "caution": [{
                    "ts_code": "300001.SZ",
                    "name": "风险样本",
                    "industry": "电子",
                    "stage": "高活跃",
                    "action": "等待分歧收敛",
                }],
            },
        }
        with TemporaryDirectory() as tmp:
            facts = build_daily_report_facts(
                "20260723", "20260722", Path(tmp) / "signals.db", Path(tmp) / "history.db",
                sources=sources,
            )
        sample = next(item for item in facts["observations"] if item["ts_code"] == "300001.SZ")
        self.assertEqual(sample["sources"], ["dragon_caution"])
        self.assertTrue(sample["conflicts"])
        self.assertTrue(sample["risks"])


if __name__ == "__main__":
    unittest.main()
