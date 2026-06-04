import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from longterm_trade_diagnostics import build_report, load_trades


class LongtermTradeDiagnosticsTest(unittest.TestCase):
    def test_report_summarizes_score_quality_and_exit_reasons(self):
        df = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "select_date": "20250102", "profit_pct": 12.0, "profit_after_fee": 11.7, "hold_days": 21, "exit_reason": "trailing_stop", "longterm_score": 82},
                {"ts_code": "000002.SZ", "select_date": "20250103", "profit_pct": -8.0, "profit_after_fee": -8.3, "hold_days": 10, "exit_reason": "stop_loss", "longterm_score": 78},
                {"ts_code": "000003.SZ", "select_date": "20250104", "profit_pct": 4.0, "profit_after_fee": 3.7, "hold_days": 30, "exit_reason": "hold_days", "longterm_score": 64},
                {"ts_code": "000004.SZ", "select_date": "20250105", "profit_pct": -3.0, "profit_after_fee": -3.3, "hold_days": 25, "exit_reason": "time_stop", "longterm_score": 61},
            ]
        )

        report = build_report(df, title="波段诊断测试")

        self.assertIn("# 波段诊断测试", report)
        self.assertIn("总交易 `4` 笔", report)
        self.assertIn("longterm_score 分布", report)
        self.assertIn("高分亏损", report)
        self.assertIn("退出原因", report)
        self.assertIn("stop_loss", report)

    def test_load_trades_normalizes_required_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "trades.csv")
            pd.DataFrame(
                [{"ts_code": "000001.SZ", "profit_pct": "5.2", "hold_days": "12", "longterm_score": "70"}]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            df = load_trades(path)

        self.assertEqual(float(df.loc[0, "profit_pct"]), 5.2)
        self.assertEqual(float(df.loc[0, "longterm_score"]), 70.0)


if __name__ == "__main__":
    unittest.main()
