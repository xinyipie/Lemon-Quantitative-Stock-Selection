import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from daily_web_update import (
    _refresh_dragon_limit_pool,
    build_longterm_periods,
    current_half_year_period,
    latest_history_trade_date,
    latest_short_backtest_date,
    next_calendar_day,
    run_update,
)


class DailyWebUpdateTest(unittest.TestCase):
    def test_current_half_year_period(self):
        self.assertEqual(current_half_year_period("20260615"), ("2026H1", "20260101", "20260615"))
        self.assertEqual(current_half_year_period("20260702"), ("2026H2", "20260701", "20260702"))

    def test_full_history_periods_include_fixed_halves_and_current_half(self):
        periods = build_longterm_periods("20260615", full_history=True)

        self.assertEqual(periods[0], ("2024H1", "20240101", "20240630"))
        self.assertEqual(periods[-1], ("2026H1", "20260101", "20260615"))
        self.assertNotIn(("2026H2", "20260701", "20260615"), periods)

    def test_next_calendar_day(self):
        self.assertEqual(next_calendar_day("20260529"), "20260530")

    def test_latest_history_trade_date_treats_empty_sqlite_as_empty_history(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "stock_history.db"
            db_path.touch()

            self.assertIsNone(latest_history_trade_date(db_path))

    def test_latest_short_backtest_date_treats_empty_sqlite_as_empty_signal_db(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "stock_signals.db"
            db_path.touch()

            self.assertIsNone(latest_short_backtest_date(db_path))

    def test_run_update_refreshes_market_context_before_main(self):
        calls = []
        args = Namespace(
            end="20260616",
            start="20260616",
            skip_download=True,
            skip_history_import=True,
            skip_market_context=False,
            skip_main=True,
            skip_short_review=True,
            skip_longterm_audit=True,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260616"
        ):
            run_update(args)

        self.assertTrue(any("market_context_snapshot.py" in command for command in calls))

    def test_daily_mode_skips_heavy_review_layers_by_default(self):
        calls = []
        args = Namespace(
            end="20260616",
            start="20260616",
            skip_download=True,
            skip_history_import=True,
            skip_market_context=True,
            skip_main=True,
            skip_short_review=False,
            skip_longterm_audit=False,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260616"
        ):
            run_update(args)

        flat = " ".join(" ".join(command) for command in calls)
        self.assertNotIn("test.py", flat)
        self.assertNotIn("longterm_pool_quality_audit.py", flat)

    def test_missing_start_backfills_from_next_history_day(self):
        calls = []
        args = Namespace(
            end="20260622",
            start=None,
            skip_download=False,
            skip_history_import=False,
            skip_market_context=True,
            skip_main=True,
            skip_short_review=True,
            skip_longterm_audit=True,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", side_effect=["20260615", "20260617"]
        ):
            run_update(args)

        command_texts = [" ".join(command) for command in calls]
        self.assertTrue(any("data_downloader.py --start 20260616 --end 20260622" in text for text in command_texts))
        self.assertTrue(any("history_db_importer.py" in text and "--start 20260616 --end 20260622" in text for text in command_texts))

    def test_market_context_uses_effective_history_date_when_history_lags(self):
        calls = []
        args = Namespace(
            end="20260622",
            start=None,
            skip_download=True,
            skip_history_import=True,
            skip_market_context=False,
            skip_main=True,
            skip_short_review=True,
            skip_longterm_audit=True,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260617"
        ):
            run_update(args)

        command_texts = [" ".join(command) for command in calls]
        self.assertTrue(any("market_context_snapshot.py --date 20260617" in text for text in command_texts))
        self.assertFalse(any("market_context_snapshot.py --date 20260622" in text for text in command_texts))

    def test_daily_mode_backfills_today_ai_explanations_after_main(self):
        calls = []
        args = Namespace(
            end="20260616",
            start="20260616",
            skip_download=True,
            skip_history_import=True,
            skip_market_context=True,
            skip_main=False,
            skip_short_review=True,
            skip_longterm_audit=True,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260616"
        ):
            run_update(args)

        command_texts = [" ".join(command) for command in calls]
        main_index = next(i for i, text in enumerate(command_texts) if "main.py" in text)
        self.assertIn("--local-data-live", command_texts[main_index])
        self.assertIn("--cache-dir data\\cache", command_texts[main_index])
        explanation_indexes = [i for i, text in enumerate(command_texts) if "backfill_signal_explanations.py" in text]
        brief_indexes = [i for i, text in enumerate(command_texts) if "daily_ai_brief.py" in text]
        self.assertEqual(len(explanation_indexes), 2)
        self.assertEqual(len(brief_indexes), 1)
        self.assertTrue(all(index > main_index for index in explanation_indexes))
        self.assertTrue(all(index > explanation_indexes[-1] for index in brief_indexes))
        self.assertTrue(any("--mode short" in text and "--source live" in text for text in command_texts))
        self.assertTrue(any("--mode longterm" in text and "--source live" in text for text in command_texts))
        self.assertTrue(all("--start 20260616 --end 20260616" in text for text in command_texts if "backfill_signal_explanations.py" in text))
        self.assertTrue(any("--date 20260616" in text for text in command_texts if "daily_ai_brief.py" in text))

    def test_daily_mode_refreshes_market_radar_snapshot_after_main(self):
        calls = []
        args = Namespace(
            end="20260624",
            start="20260624",
            skip_download=True,
            skip_history_import=True,
            skip_market_context=True,
            skip_main=False,
            skip_short_review=True,
            skip_longterm_audit=True,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260623"
        ), patch("daily_web_update.refresh_market_radar_snapshot") as refresh_radar:
            run_update(args)

        command_texts = [" ".join(command) for command in calls]
        self.assertTrue(any("main.py" in text for text in command_texts))
        refresh_radar.assert_called_once_with(args.history_db, args.signal_db, "20260623", dry_run=False)

    def test_fast_daily_mode_uses_core_download_and_skips_heavy_context_layers(self):
        calls = []
        args = Namespace(
            end="20260624",
            start="20260624",
            skip_download=False,
            skip_history_import=False,
            skip_market_context=False,
            skip_main=False,
            skip_short_review=True,
            skip_longterm_audit=True,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            fast=True,
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260624"
        ), patch("daily_web_update.refresh_market_radar_snapshot") as refresh_radar:
            run_update(args)

        command_texts = [" ".join(map(str, command)) for command in calls]
        self.assertTrue(any("data_downloader.py" in text and "--core-only" in text for text in command_texts))
        importer = next(text for text in command_texts if "history_db_importer.py" in text)
        self.assertIn("daily daily_basic moneyflow stock_basic", importer)
        self.assertNotIn("index_daily", importer)
        self.assertTrue(any("main.py" in text for text in command_texts))
        self.assertFalse(any("market_context_snapshot.py" in text for text in command_texts))
        self.assertFalse(any("backfill_signal_explanations.py" in text for text in command_texts))
        self.assertFalse(any("daily_ai_brief.py" in text for text in command_texts))
        refresh_radar.assert_not_called()

    def test_dragon_mode_updates_core_history_then_refreshes_dragon_limit_pool(self):
        calls = []
        args = Namespace(
            end="20260624",
            start="20260624",
            skip_download=False,
            skip_history_import=False,
            skip_market_context=False,
            skip_main=False,
            skip_short_review=False,
            skip_longterm_audit=False,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="dragon",
            fast=False,
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260624"
        ), patch("daily_web_update.refresh_market_radar_snapshot") as refresh_radar, patch(
            "daily_web_update._dragon_limit_pool_collector_path", return_value=Path("E:/代码项目/stock-strategy-research/research/limit_pool_collector.py")
        ):
            run_update(args)

        command_texts = [" ".join(map(str, command)) for command in calls]
        self.assertEqual(len(command_texts), 3)
        self.assertIn("data_downloader.py --start 20260624 --end 20260624 --core-only", command_texts[0])
        self.assertIn("history_db_importer.py", command_texts[1])
        self.assertIn("daily daily_basic moneyflow stock_basic", command_texts[1])
        self.assertIn("limit_pool_collector.py", command_texts[2])
        self.assertIn("--date 20260624", command_texts[2])
        self.assertFalse(any("main.py" in text for text in command_texts))
        refresh_radar.assert_not_called()

    def test_dragon_mode_fails_when_collector_is_missing(self):
        args = Namespace(
            end="20260624",
            start="20260624",
            skip_download=False,
            skip_history_import=False,
            skip_market_context=False,
            skip_main=False,
            skip_short_review=False,
            skip_longterm_audit=False,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="dragon",
            fast=False,
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.latest_history_trade_date", return_value="20260624"), patch(
            "daily_web_update._dragon_limit_pool_collector_path", return_value=None
        ):
            with self.assertRaisesRegex(SystemExit, "limit_pool_collector"):
                run_update(args)

    def test_radar_mode_updates_core_history_then_refreshes_market_context_and_radar_snapshot(self):
        calls = []
        args = Namespace(
            end="20260624",
            start="20260624",
            skip_download=False,
            skip_history_import=False,
            skip_market_context=False,
            skip_main=False,
            skip_short_review=False,
            skip_longterm_audit=False,
            skip_ai_explanations=False,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="radar",
            fast=False,
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260623"
        ), patch("daily_web_update.refresh_market_radar_snapshot") as refresh_radar, patch(
            "daily_web_update._dragon_limit_pool_collector_path"
        ) as dragon_path:
            run_update(args)

        command_texts = [" ".join(map(str, command)) for command in calls]
        self.assertEqual(len(command_texts), 3)
        self.assertIn("data_downloader.py --start 20260624 --end 20260624 --core-only", command_texts[0])
        self.assertIn("history_db_importer.py", command_texts[1])
        self.assertIn("daily daily_basic moneyflow stock_basic", command_texts[1])
        self.assertIn("market_context_snapshot.py --date 20260623", command_texts[2])
        self.assertFalse(any("main.py" in text for text in command_texts))
        refresh_radar.assert_called_once_with(args.history_db, args.signal_db, "20260623", dry_run=False)
        dragon_path.assert_not_called()

    def test_daily_mode_refreshes_dragon_limit_pool_after_main_when_research_tree_exists(self):
        calls = []
        args = Namespace(
            end="20260624",
            start="20260624",
            skip_download=True,
            skip_history_import=True,
            skip_market_context=True,
            skip_main=False,
            skip_short_review=True,
            skip_longterm_audit=True,
            skip_ai_explanations=True,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260624"
        ), patch("daily_web_update.refresh_market_radar_snapshot"), patch(
            "daily_web_update._dragon_limit_pool_collector_path", return_value=Path("E:/代码项目/stock-strategy-research/research/limit_pool_collector.py")
        ):
            run_update(args)

        command_texts = [" ".join(map(str, command)) for command in calls]
        main_index = next(i for i, text in enumerate(command_texts) if "main.py" in text)
        dragon_indexes = [i for i, text in enumerate(command_texts) if "limit_pool_collector.py" in text]
        self.assertEqual(len(dragon_indexes), 1)
        self.assertGreater(dragon_indexes[0], main_index)
        self.assertIn("--date 20260624", command_texts[dragon_indexes[0]])

    def test_optional_dragon_limit_pool_failure_does_not_fail_daily_update(self):
        args = Namespace(dry_run=False)

        with patch(
            "daily_web_update._dragon_limit_pool_collector_path",
            return_value=Path("E:/stock/research/limit_pool_collector.py"),
        ), patch("daily_web_update.run_command", side_effect=SystemExit("collector failed")):
            _refresh_dragon_limit_pool("python", args, "20260624", required=False)

    def test_required_dragon_limit_pool_failure_still_fails(self):
        args = Namespace(dry_run=False)

        with patch(
            "daily_web_update._dragon_limit_pool_collector_path",
            return_value=Path("E:/stock/research/limit_pool_collector.py"),
        ), patch("daily_web_update.run_command", side_effect=SystemExit("collector failed")):
            with self.assertRaisesRegex(SystemExit, "collector failed"):
                _refresh_dragon_limit_pool("python", args, "20260624", required=True)

    def test_skip_ai_explanations_disables_daily_backfill(self):
        calls = []
        args = Namespace(
            end="20260616",
            start="20260616",
            skip_download=True,
            skip_history_import=True,
            skip_market_context=True,
            skip_main=False,
            skip_short_review=True,
            skip_longterm_audit=True,
            skip_ai_explanations=True,
            ai_explanation_limit=0,
            skip_financial=True,
            mode="daily",
            cache_dir=Path("data/cache"),
            history_db=Path("data/stock_history.db"),
            signal_db=Path("data/stock_signals.db"),
            dry_run=False,
            short_start=None,
            full_history=False,
        )

        with patch("daily_web_update.run_command", side_effect=lambda command, dry_run=False: calls.append(command)), patch(
            "daily_web_update.latest_history_trade_date", return_value="20260616"
        ):
            run_update(args)

        flat = " ".join(" ".join(command) for command in calls)
        self.assertNotIn("backfill_signal_explanations.py", flat)
        self.assertNotIn("daily_ai_brief.py", flat)


if __name__ == "__main__":
    unittest.main()
