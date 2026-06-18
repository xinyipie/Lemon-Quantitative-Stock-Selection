import unittest

import pandas as pd

from sector_heat_diagnostics import (
    build_markdown_report,
    calculate_sector_heat,
    rank_sector_stocks,
)


def make_daily(code: str, closes: list[float], amounts: list[float] | None = None) -> list[dict]:
    rows = []
    amounts = amounts or [1000.0 for _ in closes]
    prev = None
    for idx, close in enumerate(closes, start=1):
        trade_date = f"202501{idx:02d}"
        pct_chg = 0.0 if prev is None else (close - prev) / prev * 100
        rows.append(
            {
                "trade_date": trade_date,
                "ts_code": code,
                "open": close,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "pct_chg": pct_chg,
                "amount": amounts[idx - 1],
            }
        )
        prev = close
    return rows


class SectorHeatDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        trend = [
            ("000001.SZ", "稳步A", [10, 10.1, 10.3, 10.5, 10.8, 11.0, 11.3, 11.6, 11.9, 12.2, 12.5, 12.8]),
            ("000002.SZ", "稳步B", [9, 9.1, 9.3, 9.5, 9.7, 10.0, 10.2, 10.5, 10.7, 11.0, 11.2, 11.4]),
            ("000003.SZ", "稳步C", [8, 8.1, 8.2, 8.4, 8.6, 8.7, 8.9, 9.1, 9.3, 9.5, 9.7, 9.9]),
            ("000004.SZ", "稳步D", [7, 7.0, 7.1, 7.2, 7.4, 7.5, 7.7, 7.9, 8.1, 8.2, 8.4, 8.6]),
        ]
        hot = [
            ("000011.SZ", "冲高A", [10, 10, 10.1, 10.2, 10.4, 10.7, 11.2, 12.5, 14.5, 16.5, 18.5, 20.5]),
            ("000012.SZ", "冲高B", [9, 9, 9.1, 9.2, 9.4, 9.8, 10.4, 11.5, 12.8, 14.0, 15.3, 16.8]),
            ("000013.SZ", "冲高C", [8, 8, 8.1, 8.2, 8.3, 8.6, 9.1, 9.9, 11.0, 12.2, 13.5, 14.9]),
            ("000014.SZ", "冲高D", [7, 7, 7.0, 7.1, 7.2, 7.5, 7.9, 8.6, 9.5, 10.5, 11.6, 12.8]),
        ]
        weak = [
            ("000021.SZ", "弱A", [10, 9.9, 9.7, 9.5, 9.2, 9.0, 8.8, 8.7, 8.5, 8.3, 8.1, 8.0]),
            ("000022.SZ", "弱B", [9, 8.9, 8.8, 8.6, 8.5, 8.3, 8.2, 8.0, 7.9, 7.8, 7.7, 7.6]),
            ("000023.SZ", "弱C", [8, 7.9, 7.8, 7.7, 7.5, 7.4, 7.2, 7.1, 7.0, 6.9, 6.8, 6.7]),
        ]
        all_rows = []
        basics = []
        daily_basic = []
        moneyflow = []
        for code, name, closes in trend + hot + weak:
            all_rows.extend(make_daily(code, closes, amounts=[1000, 1000, 1000, 1000, 1000, 1100, 1150, 1200, 1250, 1300, 1350, 1600]))
            industry = "稳步主线" if code.startswith("00000") else "过热题材" if code.startswith("00001") else "退潮板块"
            basics.append({"ts_code": code, "name": name, "industry": industry, "list_status": "L"})
            daily_basic.append({"trade_date": "20250112", "ts_code": code, "turnover_rate": 4.0, "volume_ratio": 1.5, "total_mv": 100000})
            moneyflow.append({"trade_date": "20250112", "ts_code": code, "net_mf_amount": 2000 if industry != "退潮板块" else -1000})
        self.daily = pd.DataFrame(all_rows)
        self.basic = pd.DataFrame(basics)
        self.daily_basic = pd.DataFrame(daily_basic)
        self.moneyflow = pd.DataFrame(moneyflow)
        self.index_daily = pd.DataFrame(make_daily("000300.SH", [10, 10, 10.1, 10.1, 10.2, 10.3, 10.3, 10.4, 10.5, 10.5, 10.6, 10.7]))

    def test_calculate_sector_heat_marks_healthy_and_overheated_sectors(self):
        heat, stocks = calculate_sector_heat(
            self.daily,
            self.basic,
            daily_basic=self.daily_basic,
            moneyflow=self.moneyflow,
            index_daily=self.index_daily,
            end_date="20250112",
            min_stocks=3,
        )

        by_sector = {row["industry"]: row for row in heat.to_dict("records")}
        self.assertEqual(by_sector["稳步主线"]["stage"], "趋势延续")
        self.assertEqual(by_sector["过热题材"]["stage"], "过热高潮")
        self.assertEqual(by_sector["退潮板块"]["stage"], "退潮中")
        self.assertGreater(by_sector["稳步主线"]["heat_score"], by_sector["退潮板块"]["heat_score"])
        self.assertIn("sector_ret_10d", stocks.columns)

    def test_rank_sector_stocks_avoids_blindly_chasing_extreme_gain(self):
        heat, stocks = calculate_sector_heat(
            self.daily,
            self.basic,
            daily_basic=self.daily_basic,
            moneyflow=self.moneyflow,
            index_daily=self.index_daily,
            end_date="20250112",
            min_stocks=3,
        )

        ranked = rank_sector_stocks(stocks, heat, top_sectors=3, top_stocks=3)
        hot = ranked[ranked["industry"] == "过热题材"].sort_values("candidate_rank")
        self.assertEqual(len(hot), 3)
        self.assertNotEqual(hot.iloc[0]["ts_code"], "000011.SZ")
        self.assertIn("不追高", hot.iloc[0]["risk_note"])

    def test_markdown_report_contains_plain_chinese_sections(self):
        heat, stocks = calculate_sector_heat(
            self.daily,
            self.basic,
            daily_basic=self.daily_basic,
            moneyflow=self.moneyflow,
            index_daily=self.index_daily,
            end_date="20250112",
            min_stocks=3,
        )
        ranked = rank_sector_stocks(stocks, heat, top_sectors=3, top_stocks=3)

        report = build_markdown_report(heat, ranked, end_date="20250112")

        self.assertIn("## 先看结论", report)
        self.assertIn("## 健康主线 Top", report)
        self.assertIn("## 板块内候选 Top3", report)


if __name__ == "__main__":
    unittest.main()
