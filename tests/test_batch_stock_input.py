import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["LEMON_SKIP_TUSHARE_INIT"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class BatchStockInputTest(unittest.TestCase):
    def test_parse_stock_codes_accepts_pasted_mixed_text_and_deduplicates(self):
        text = """
        # 我的观察池
        000001 平安银行
        sz000002, 600519.SH；sh600000
        300750 宁德时代 // 备注
        000001
        不合法 12345 688001.SH
        """

        parsed = main.parse_stock_codes_from_text(text)

        self.assertEqual(
            parsed.valid_codes,
            ["000001", "000002", "600519", "600000", "300750", "688001"],
        )
        self.assertIn("12345", parsed.invalid_tokens)

    def test_parse_stock_code_args_reads_file_or_direct_codes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "watchlist.txt"
            path.write_text("000001\n600519.SH\n", encoding="utf-8")

            file_parsed = main.parse_stock_code_args([str(path)])
            direct_parsed = main.parse_stock_code_args(["000001,600519", "sh600000"])

        self.assertEqual(file_parsed.valid_codes, ["000001", "600519"])
        self.assertEqual(direct_parsed.valid_codes, ["000001", "600519", "600000"])

    def test_analyze_from_inputs_accepts_direct_code_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "batch.txt"
            old_analyze = main.analyze_batch_stocks
            try:
                seen = {}

                def fake_analyze(codes):
                    seen["codes"] = codes
                    return [
                        {
                            "code": "000001",
                            "name": "平安银行",
                            "rating": "观察",
                            "score": 70,
                            "risk_level": "中",
                            "trend_prediction": "震荡上行",
                            "time_horizon": "短中期",
                            "target_price": 12,
                            "target_gain_pct": 10,
                            "stop_loss_price": 9,
                            "buy_timing": "回踩确认",
                        }
                    ]

                main.analyze_batch_stocks = fake_analyze
                main.analyze_from_inputs(["000001,600519.SH"], output_path=str(output))
            finally:
                main.analyze_batch_stocks = old_analyze

            content = output.read_text(encoding="utf-8")

        self.assertEqual(seen["codes"], ["000001", "600519"])
        self.assertIn("平安银行", content)


if __name__ == "__main__":
    unittest.main()
