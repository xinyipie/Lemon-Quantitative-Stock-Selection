import unittest

from web_app.app import _build_longterm_result_context, _select_longterm_result_view


class LongtermResultWorkspaceTest(unittest.TestCase):
    def test_completed_sample_exposes_benchmark_path_and_verdict(self):
        samples = [{
            "display_name": "测试股票",
            "ret_10d": 3.0,
            "ret_10d_text": "+3.00%",
            "ret_10d_tone": "market-up",
            "ret_40d": 8.0,
            "ret_40d_text": "+8.00%",
            "ret_40d_tone": "market-up",
            "ret_80d": 20.0,
            "ret_80d_text": "+20.00%",
            "ret_80d_tone": "market-up",
            "excess_ret_80d": 12.0,
            "mae_80d": -6.0,
        }]

        context = _build_longterm_result_context(samples)

        self.assertEqual(context["completed_count"], 1)
        self.assertEqual(samples[0]["benchmark_ret_80d_text"], "+8.00%")
        self.assertEqual(samples[0]["result_label"], "显著跑赢")
        self.assertEqual(samples[0]["result_risk_label"], "80日回撤可控")
        self.assertEqual([point["label"] for point in samples[0]["return_path"]], ["10日", "40日", "80日"])

    def test_risk_view_uses_completed_80_day_mae_only(self):
        completed_deep = {"ret_80d": -2.0, "mae_80d": -18.0, "watch_risk_tone": "ok"}
        completed_current_warning = {"ret_80d": 3.0, "mae_80d": -5.0, "watch_risk_tone": "bad"}
        current_warning = {"ret_80d": None, "mae_80d": None, "watch_risk_tone": "bad"}
        context = _build_longterm_result_context([completed_deep, completed_current_warning, current_warning])

        selected = _select_longterm_result_view(context, "risk")

        self.assertEqual(selected, [completed_deep])


if __name__ == "__main__":
    unittest.main()
