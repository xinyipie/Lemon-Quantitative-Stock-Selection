import math
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from reproduce_strategy import (
    Variant,
    compute_forward_outcomes,
    combine_yearly_outputs,
    score_candidate,
    select_top_n,
    usable_signal_dates,
    value_below_minimum,
)


class ScoreCandidateTest(unittest.TestCase):
    def test_momentum_score_matches_historical_weights(self):
        factors = {
            "volume_ratio": 50.0,
            "drawdown": 100.0,
            "inflow": 80.0,
            "turnover": 60.0,
            "sector": 70.0,
            "pattern": 40.0,
            "counter_trend": 20.0,
            "wyckoff": 30.0,
            "accel": 10.0,
        }
        score = score_candidate("momentum", factors, Variant("x", 1.2))
        self.assertAlmostEqual(score, 57.5)

    def test_single_factor_ablation_does_not_renormalize(self):
        factors = {name: 100.0 for name in (
            "volume_ratio", "drawdown", "inflow", "turnover", "sector",
            "pattern", "counter_trend", "wyckoff", "accel"
        )}
        baseline = score_candidate("momentum", factors, Variant("base", 1.2))
        ablated = score_candidate(
            "momentum", factors, Variant("no_inflow", 1.2, ablate="inflow")
        )
        self.assertEqual(baseline, 100.0)
        self.assertEqual(ablated, 80.0)


class SelectionTest(unittest.TestCase):
    def test_positive_position_always_keeps_at_least_one(self):
        rows = [{"code": "a", "score": 90}, {"code": "b", "score": 80}]
        selected = select_top_n(rows, position_multiplier=0.33, top_n=3)
        self.assertEqual([row["code"] for row in selected], ["a"])

    def test_usable_dates_require_open_calendar_and_nonempty_prices(self):
        dates = usable_signal_dates(
            common_file_dates=["20260220", "20260223", "20260224"],
            open_dates=["20260220", "20260224"],
            nonempty_price_dates=["20260220", "20260224"],
            start_date="20260220",
            end_date="20260224",
        )
        self.assertEqual(dates, ["20260220", "20260224"])

    def test_missing_value_is_below_minimum_for_audit_reason(self):
        self.assertTrue(value_below_minimum(None, 1.2))
        self.assertTrue(value_below_minimum(float("nan"), 1.2))
        self.assertFalse(value_below_minimum(1.31, 1.2))


class ForwardOutcomeTest(unittest.TestCase):
    def test_t_plus_one_open_and_horizon_closes(self):
        prices = [
            {"trade_date": "20260102", "open": 10.0, "high": 10.4, "low": 9.8, "close": 10.2, "pct_chg": 2.0},
            {"trade_date": "20260105", "open": 10.0, "high": 10.3, "low": 9.5, "close": 10.1, "pct_chg": -1.0},
            {"trade_date": "20260106", "open": 10.1, "high": 10.8, "low": 10.0, "close": 10.5, "pct_chg": 4.0},
            {"trade_date": "20260107", "open": 10.5, "high": 11.2, "low": 10.4, "close": 11.0, "pct_chg": 4.8},
            {"trade_date": "20260108", "open": 11.0, "high": 11.1, "low": 10.7, "close": 10.8, "pct_chg": -1.8},
            {"trade_date": "20260109", "open": 10.8, "high": 11.6, "low": 10.7, "close": 11.5, "pct_chg": 6.5},
            {"trade_date": "20260112", "open": 11.5, "high": 11.7, "low": 11.2, "close": 11.6, "pct_chg": 0.9},
            {"trade_date": "20260113", "open": 11.6, "high": 12.0, "low": 11.4, "close": 11.9, "pct_chg": 2.6},
            {"trade_date": "20260114", "open": 11.9, "high": 12.2, "low": 11.8, "close": 12.0, "pct_chg": 0.8},
        ]
        result = compute_forward_outcomes(prices)
        self.assertEqual(result["buy_date"], "20260105")
        self.assertAlmostEqual(result["return_3d"], 10.0)
        self.assertAlmostEqual(result["return_5d"], 15.0)
        self.assertAlmostEqual(result["return_8d"], 20.0)
        self.assertAlmostEqual(result["mae_3d"], -5.0)

    def test_t_plus_one_limit_up_is_not_tradeable(self):
        prices = [
            {"trade_date": "20260102", "open": 10, "high": 10, "low": 10, "close": 10, "pct_chg": 0},
            {"trade_date": "20260105", "open": 11, "high": 11, "low": 11, "close": 11, "pct_chg": 10.0},
        ]
        self.assertEqual(compute_forward_outcomes(prices)["failure_reason"], "t1_limit_up")


class CombineYearlyTest(unittest.TestCase):
    def test_combines_yearly_machine_readable_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            yearly_dirs = []
            for year, ret in (("2023", 2.0), ("2024", -1.0)):
                directory = root / year
                directory.mkdir()
                yearly_dirs.append(directory)
                signal = {"variant": "D_pure_quant_vr1.2", "select_date": f"{year}0103", "ts_code": "000001.SZ"}
                pd.DataFrame([signal]).to_csv(directory / "signals.csv", index=False)
                trade = {
                    **signal, "failure_reason": "", "buy_date": f"{year}0104", "buy_price": 10,
                    "return_3d": ret, "return_5d": ret, "return_8d": ret,
                    "mae_3d": -2, "mae_5d": -2, "mae_8d": -2,
                    "exit_date_3d": f"{year}0106", "exit_date_5d": f"{year}0110", "exit_date_8d": f"{year}0113",
                }
                pd.DataFrame([trade]).to_csv(directory / "trades.csv", index=False)
                pd.DataFrame().to_csv(directory / "guangxun_case.csv", index=False)
                (directory / "experiment_metadata.json").write_text(json.dumps({
                    "actual_signal_start": f"{year}0103", "actual_signal_end": f"{year}1231",
                    "common_date_count": 1, "price_forward_end": f"{year}1231",
                }), encoding="utf-8")
            output = root / "combined"
            combine_yearly_outputs(yearly_dirs, output)
            combined = pd.read_csv(output / "trades.csv")
            self.assertEqual(len(combined), 2)
            summary = pd.read_csv(output / "variant_summary.csv")
            row = summary[(summary.variant == "D_pure_quant_vr1.2") & (summary.period == "all") & (summary.horizon_days == 5)].iloc[0]
            self.assertEqual(row.signal_count, 2)
            machine_summary = json.loads((output / "variant_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["variant"] == "D_pure_quant_vr1.2" for item in machine_summary))


if __name__ == "__main__":
    unittest.main()
