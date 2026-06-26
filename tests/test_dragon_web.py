import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from web_app.app import app
from web_app.services.dragon_service import build_dragon_observation


class DragonWebTest(unittest.TestCase):
    def test_dragon_service_builds_action_buckets_from_latest_limit_pool(self):
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
                        "turnover_rate": 2.0,
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
                        "source": "zt_pool",
                        "ts_code": "000004.SZ",
                        "name": "Gamma",
                        "industry": "AI",
                        "pct_chg": 10.0,
                        "turnover_rate": 8.0,
                        "amount": 1600,
                        "first_limit_time": "11:00:00",
                        "open_count": 1,
                        "limit_days": 1,
                        "seal_amount": 100,
                    },
                    {
                        "trade_date": "20260624",
                        "source": "zt_pool",
                        "ts_code": "000005.SZ",
                        "name": "Delta",
                        "industry": "AI",
                        "pct_chg": 10.0,
                        "turnover_rate": 10.0,
                        "amount": 1400,
                        "first_limit_time": "11:15:00",
                        "open_count": 1,
                        "limit_days": 1,
                        "seal_amount": 90,
                    },
                ]
            ).to_parquet(limit_dir / "20260624.parquet", index=False)

            result = build_dragon_observation(limit_dir=limit_dir)

        self.assertEqual(result["trade_date"], "20260624")
        self.assertEqual(result["summary"]["source_quality"], "real")
        self.assertEqual(result["buckets"]["focus"][0]["ts_code"], "000001.SZ")
        self.assertEqual(result["buckets"]["avoid"][0]["ts_code"], "000003.SZ")
        self.assertIn("small gap", result["buckets"]["focus"][0]["action"])

    def test_dragon_page_renders_observation_board(self):
        payload = {
            "trade_date": "20260624",
            "summary": {
                "source_quality": "real",
                "focus_count": 1,
                "wait_count": 1,
                "avoid_count": 1,
                "headline": "research board",
                "note": "read only",
            },
            "buckets": {
                "focus": [{"ts_code": "000001.SZ", "name": "Alpha", "industry": "AI", "action": "small gap ok", "badges": ["low turnover"], "score": 88}],
                "wait": [{"ts_code": "000002.SZ", "name": "Beta", "industry": "AI", "action": "wait confirm", "badges": [], "score": 70}],
                "avoid": [{"ts_code": "000003.SZ", "name": "Risky", "industry": "AI", "action": "do not chase", "badges": [], "score": 20}],
            },
            "study": {"baseline_next_limit": "21.3%", "low_turnover_next_limit": "29.4%", "low_turnover_decapatated": "14.1%"},
        }
        with patch("web_app.app.build_dragon_observation", return_value=payload):
            response = TestClient(app).get("/dragon")

        self.assertEqual(response.status_code, 200)
        self.assertIn("dragon-board", response.text)
        self.assertIn("Alpha", response.text)
        self.assertIn("small gap ok", response.text)
        self.assertIn("29.4%", response.text)
        self.assertIn('action="/dragon/update"', response.text)
        self.assertIn("刷新龙头池", response.text)

    def test_dragon_update_button_starts_dragon_refresh_and_returns_to_page(self):
        with patch("web_app.app.start_web_update") as start_update:
            start_update.return_value = {"state": "running", "started": True}
            response = TestClient(app).post("/dragon/update", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/dragon")
        start_update.assert_called_once_with(mode="dragon")


if __name__ == "__main__":
    unittest.main()
