import argparse
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_web_update


def _args(mode: str) -> argparse.Namespace:
    return argparse.Namespace(
        mode=mode,
        end="20260701",
        start=None,
        history_db=Path("data/stock_history.db"),
        signal_db=Path("data/stock_signals.db"),
        cache_dir=Path("data/cache"),
        dry_run=False,
        skip_download=False,
        skip_history_import=False,
        skip_market_context=True,
        skip_main=True,
        skip_ai_explanations=True,
        ai_explanation_limit=0,
        skip_short_review=True,
        skip_longterm_audit=True,
        skip_daily_report=False,
        skip_financial=False,
        full_history=False,
        short_start=None,
        fast=False,
    )


class DailyWebUpdateModeTest(unittest.TestCase):
    def test_dragon_mode_updates_core_history_before_refreshing_dragon_pool(self):
        calls = []

        def fake_run_command(command, dry_run=False):
            calls.append(command)
            return daily_web_update.RunResult(command[1], 0)

        with (
            patch.object(daily_web_update, "today_text", return_value="20260701"),
            patch.object(daily_web_update, "latest_history_trade_date", side_effect=["20260630", "20260701"]),
            patch.object(daily_web_update, "run_command", side_effect=fake_run_command),
        ):
            daily_web_update.run_update(_args("dragon"))

        command_text = [" ".join(command) for command in calls]
        self.assertIn("data_downloader.py --start 20260701 --end 20260701 --core-only", command_text[0])
        self.assertIn("history_db_importer.py", command_text[1])
        self.assertIn("--tables daily daily_basic moneyflow stock_basic", command_text[1])
        self.assertIn("limit_pool_collector.py --date 20260701", command_text[2])

    def test_radar_mode_updates_core_history_before_refreshing_market_context(self):
        calls = []

        def fake_run_command(command, dry_run=False):
            calls.append(command)
            return daily_web_update.RunResult(command[1], 0)

        with (
            patch.object(daily_web_update, "today_text", return_value="20260701"),
            patch.object(daily_web_update, "latest_history_trade_date", side_effect=["20260630", "20260701"]),
            patch.object(daily_web_update, "run_command", side_effect=fake_run_command),
            patch.object(daily_web_update, "refresh_market_radar_snapshot") as refresh_radar,
        ):
            daily_web_update.run_update(_args("radar"))

        command_text = [" ".join(command) for command in calls]
        self.assertIn("data_downloader.py --start 20260701 --end 20260701 --core-only", command_text[0])
        self.assertIn("history_db_importer.py", command_text[1])
        refresh_radar.assert_called_once()
        report_index = next(i for i, text in enumerate(command_text) if "daily_research_report.py" in text)
        self.assertIn("--report-date 20260701", command_text[report_index])
        self.assertIn("--market-date 20260701", command_text[report_index])
        self.assertIn("--slot morning", command_text[report_index])
        self.assertIn("--retry-if-missing", command_text[report_index])

    def test_full_mode_generates_report_after_review_and_longterm_import(self):
        calls = []
        args = _args("full")
        args.start = "20260701"
        args.skip_download = True
        args.skip_history_import = True
        args.skip_short_review = False
        args.skip_longterm_audit = False

        def fake_run_command(command, dry_run=False):
            calls.append(command)
            return daily_web_update.RunResult(command[1], 0)

        with (
            patch.object(daily_web_update, "latest_history_trade_date", return_value="20260701"),
            patch.object(daily_web_update, "latest_short_backtest_date", return_value="20260701"),
            patch.object(daily_web_update, "run_command", side_effect=fake_run_command),
        ):
            daily_web_update.run_update(args)

        command_text = [" ".join(map(str, command)) for command in calls]
        report_index = next(i for i, text in enumerate(command_text) if "daily_research_report.py" in text)
        outcome_index = next(i for i, text in enumerate(command_text) if "short_signal_outcome_refresher.py" in text)
        import_indexes = [i for i, text in enumerate(command_text) if "longterm_history_importer.py" in text]
        self.assertGreater(report_index, outcome_index)
        self.assertGreater(report_index, max(import_indexes))
        self.assertIn("--slot night", command_text[report_index])
        self.assertNotIn("--retry-if-missing", command_text[report_index])

    def test_skip_daily_report_disables_radar_retry(self):
        calls = []
        args = _args("radar")
        args.skip_daily_report = True

        with (
            patch.object(daily_web_update, "latest_history_trade_date", side_effect=["20260630", "20260701"]),
            patch.object(daily_web_update, "run_command", side_effect=lambda command, dry_run=False: calls.append(command)),
            patch.object(daily_web_update, "refresh_market_radar_snapshot"),
        ):
            daily_web_update.run_update(args)

        self.assertFalse(any("daily_research_report.py" in " ".join(map(str, command)) for command in calls))


if __name__ == "__main__":
    unittest.main()
