import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from web_app.app import app
from web_app.services.dragon_service import build_dragon_observation


class DragonWebTest(unittest.TestCase):
    def test_dragon_service_builds_page_display_groups_from_latest_limit_pool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            limit_dir = root / "limit_pool"
            limit_dir.mkdir()
            pd.DataFrame(
                [
                    {
                        "trade_date": "20260624",
                        "source": "zt_pool",
                        "ts_code": "000001.SZ",
                        "name": "Alpha",
                        "industry": "AI",
                        "pct_chg": 10.0,
                        "turnover_rate": 5.0,
                        "amount": 3000,
                        "first_limit_time": "09:35:00",
                        "open_count": 0,
                        "limit_days": 2,
                        "seal_amount": 500,
                    },
                    {
                        "trade_date": "20260624",
                        "source": "zt_pool",
                        "ts_code": "000002.SZ",
                        "name": "Beta",
                        "industry": "AI",
                        "pct_chg": 10.0,
                        "turnover_rate": 5.0,
                        "amount": 2500,
                        "first_limit_time": "10:20:00",
                        "open_count": 2,
                        "limit_days": 1,
                        "seal_amount": 200,
                    },
                    {
                        "trade_date": "20260624",
                        "source": "zt_pool",
                        "ts_code": "000003.SZ",
                        "name": "Risky",
                        "industry": "AI",
                        "pct_chg": 10.0,
                        "turnover_rate": 35.0,
                        "amount": 1800,
                        "first_limit_time": "14:30:00",
                        "open_count": 7,
                        "limit_days": 1,
                        "seal_amount": 20,
                    },
                    {
                        "trade_date": "20260624",
                        "source": "strong_pool",
                        "ts_code": "000004.SZ",
                        "name": "Gamma",
                        "industry": "AI",
                        "pct_chg": 8.0,
                        "turnover_rate": 8.0,
                        "amount": 1600,
                        "first_limit_time": "11:00:00",
                        "open_count": 1,
                        "limit_days": 1,
                        "seal_amount": 100,
                    },
                ]
            ).to_parquet(limit_dir / "20260624.parquet", index=False)

            result = build_dragon_observation(limit_dir=limit_dir)

        self.assertEqual(result["trade_date"], "20260624")
        self.assertEqual(result["summary"]["source_quality"], "real")
        self.assertEqual(result["display_groups"]["priority"][0]["ts_code"], "000001.SZ")
        self.assertEqual(result["display_groups"]["caution"][0]["ts_code"], "000002.SZ")
        self.assertEqual(result["summary"]["hidden_count"], 1)
        self.assertEqual(result["buckets"]["focus"][0]["ts_code"], "000001.SZ")
        self.assertIn("二板确认", result["display_groups"]["priority"][0]["action"])

    def test_dragon_service_builds_emotion_snapshot_and_theme_radar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            limit_dir = Path(tmpdir)
            frame = pd.DataFrame(
                [
                    {
                        "trade_date": "20260630",
                        "source": "zt_pool",
                        "ts_code": "000001.SZ",
                        "name": "先锋科技",
                        "industry": "机械设备",
                        "concept": "机器人",
                        "limit_up_reason": "机器人",
                        "pct_chg": 10.0,
                        "turnover_rate": 6.0,
                        "amount": 1200000,
                        "first_limit_time": "09:35:00",
                        "open_count": 0,
                        "limit_days": 1,
                        "seal_amount": 50000,
                    },
                    {
                        "trade_date": "20260630",
                        "source": "zt_pool",
                        "ts_code": "000002.SZ",
                        "name": "确认股份",
                        "industry": "机械设备",
                        "concept": "机器人",
                        "limit_up_reason": "机器人",
                        "pct_chg": 10.0,
                        "turnover_rate": 12.0,
                        "amount": 900000,
                        "first_limit_time": "10:10:00",
                        "open_count": 1,
                        "limit_days": 2,
                        "seal_amount": 30000,
                    },
                    {
                        "trade_date": "20260630",
                        "source": "strong_pool",
                        "ts_code": "000003.SZ",
                        "name": "补涨制造",
                        "industry": "机械设备",
                        "concept": "机器人",
                        "limit_up_reason": "机器人",
                        "pct_chg": 8.2,
                        "turnover_rate": 7.0,
                        "amount": 700000,
                        "first_limit_time": "",
                        "open_count": 0,
                        "limit_days": 1,
                        "seal_amount": 0,
                    },
                ]
            )
            frame.to_parquet(limit_dir / "20260630.parquet", index=False)

            payload = build_dragon_observation(limit_dir=limit_dir)

        self.assertIn("emotion_snapshot", payload)
        self.assertIn(payload["emotion_snapshot"]["emotion_phase"], {"启动", "发酵", "高潮", "分歧", "修复", "退潮"})
        self.assertGreaterEqual(len(payload["themes"]), 1)
        self.assertEqual(payload["themes"][0]["theme_name"], "机器人")
        self.assertIn("lifecycle_groups", payload)
        self.assertTrue(
            any(
                item["lifecycle"] in {"首板高质量", "二板确认", "主线补涨"}
                for item in payload["lifecycle_groups"]["early_opportunity"]
            )
        )

    def test_dragon_page_renders_observation_board(self):
        payload = {
            "trade_date": "20260624",
            "summary": {
                "source_quality": "real",
                "priority_count": 1,
                "caution_count": 1,
                "research_count": 1,
                "hidden_count": 1,
                "focus_count": 1,
                "wait_count": 2,
                "avoid_count": 1,
                "headline": "龙头观察：已有优先关注样本",
                "note": "read only",
            },
            "display_group_meta": {
                "priority": {"title": "优先关注", "hint": "strong", "metric": "3日均值 +10.18%"},
                "caution": {"title": "谨慎观察", "hint": "watch", "metric": "等待确认"},
                "research": {"title": "研究样本", "hint": "sample", "metric": "辅助观察"},
            },
            "display_groups": {
                "priority": [
                    {
                        "ts_code": "000001.SZ",
                        "name": "Alpha",
                        "industry": "AI",
                        "action": "二板确认且题材有合力",
                        "badges": ["优先关注"],
                        "score": 88,
                        "lifecycle": "二板确认",
                        "theme_name": "机器人",
                        "theme_score": 82,
                        "turnover_rate": "5.00%",
                        "first_limit_time": "09:35:00",
                        "open_count": 0,
                        "limit_days": 2,
                    }
                ],
                "caution": [],
                "research": [],
            },
            "buckets": {"focus": [], "wait": [], "avoid": []},
            "emotion_snapshot": {
                "emotion_phase": "发酵",
                "mainline_state": "强主线",
                "risk_state": "正常",
                "next_day_bias": "看优先关注，找低位扩散",
                "summary_text": "机器人方向形成主线。",
            },
            "themes": [
                {
                    "theme_name": "机器人",
                    "primary_industry": "机械设备",
                    "theme_state": "主线确认",
                    "theme_score": 82.0,
                    "limit_up_count": 3,
                    "strong_count": 1,
                    "board_2_count": 1,
                    "board_3_plus_count": 0,
                    "fragile_count": 0,
                    "leader_codes": [
                        {"name": "先锋科技", "ts_code": "000001.SZ", "score": 88, "lifecycle": "首板高质量", "action": "观察", "badges": []}
                    ],
                    "risk_notes": [],
                }
            ],
            "lifecycle_groups": {"early_opportunity": [], "emotion_anchor": [], "risk_sample": []},
            "study": {
                "page_sample_count": "178",
                "page_avg_3d": "+3.41%",
                "priority_avg_3d": "+10.18%",
                "priority_win_3d": "83.33%",
                "priority_top1_avg_3d": "+10.77%",
                "baseline_next_limit": "21.3%",
                "low_turnover_next_limit": "29.4%",
                "low_turnover_decapatated": "14.1%",
            },
        }
        with patch("web_app.app.build_dragon_observation", return_value=payload):
            response = TestClient(app).get("/dragon")

        self.assertEqual(response.status_code, 200)
        self.assertIn("dragon-board", response.text)
        self.assertIn("Alpha", response.text)
        self.assertIn("优先关注", response.text)
        self.assertIn("谨慎观察", response.text)
        self.assertIn("研究样本", response.text)
        self.assertIn("二板确认且题材有合力", response.text)
        self.assertIn("机器人", response.text)
        self.assertIn("+10.18%", response.text)
        self.assertIn('action="/dragon/update"', response.text)
        self.assertIn("data-background-update-form", response.text)
        self.assertIn('data-update-status-url="/update/status"', response.text)
        self.assertIn("更新行情并刷新龙头池", response.text)

    def test_dragon_update_button_starts_dragon_refresh_and_returns_to_page(self):
        with patch("web_app.app.start_web_update") as start_update:
            start_update.return_value = {"state": "running", "started": True}
            response = TestClient(app).post("/dragon/update", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/dragon")
        start_update.assert_called_once_with(mode="dragon")

    def test_dragon_update_button_can_start_without_page_redirect_for_ajax(self):
        with patch("web_app.app.start_web_update") as start_update:
            start_update.return_value = {"state": "running", "started": True, "mode": "dragon"}
            response = TestClient(app).post("/dragon/update", headers={"Accept": "application/json"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "dragon")
        start_update.assert_called_once_with(mode="dragon")


if __name__ == "__main__":
    unittest.main()
