#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""One-command updater for the local Web dashboard data.

This script keeps three dashboard layers aligned:
1. market history database;
2. live short/longterm signal snapshots from main.py;
3. historical short review and longterm pool audit tables.
"""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_SIGNAL_DB = Path("data") / "stock_signals.db"
DEFAULT_HISTORY_DB = Path("data") / "stock_history.db"
DEFAULT_CACHE_DIR = Path("data") / "cache"
SHORT_PROFILE = "short_v9_final"
SHORT_SCENARIO = "profile_v4_adaptive_quality_v9_sector_quality_guard"
LONGTERM_PROFILE = "longterm_quality_lifecycle_v18_market_sync"


@dataclass
class RunResult:
    name: str
    returncode: int


def normalize_date(value: str) -> str:
    return str(value).replace("-", "")[:8]


def today_text() -> str:
    return datetime.now().strftime("%Y%m%d")


def next_calendar_day(value: str) -> str:
    date = datetime.strptime(normalize_date(value), "%Y%m%d")
    return (date + timedelta(days=1)).strftime("%Y%m%d")


def current_half_year_period(end_date: str) -> tuple[str, str, str]:
    end_text = normalize_date(end_date)
    year = end_text[:4]
    if end_text[4:6] <= "06":
        return f"{year}H1", f"{year}0101", end_text
    return f"{year}H2", f"{year}0701", end_text


def build_longterm_periods(end_date: str, full_history: bool = False) -> list[tuple[str, str, str]]:
    current = current_half_year_period(end_date)
    if not full_history:
        return [current]
    fixed = [
        ("2024H1", "20240101", "20240630"),
        ("2024H2", "20240701", "20241231"),
        ("2025H1", "20250101", "20250630"),
        ("2025H2", "20250701", "20251231"),
    ]
    periods = [item for item in fixed if item[1] <= normalize_date(end_date)]
    if current[0] not in {item[0] for item in periods}:
        periods.append(current)
    return periods


def latest_history_trade_date(history_db: Path = DEFAULT_HISTORY_DB) -> str | None:
    if not history_db.exists():
        return None
    conn = sqlite3.connect(history_db)
    try:
        row = conn.execute("select max(trade_date) from stock_daily").fetchone()
        return str(row[0]) if row and row[0] else None
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    finally:
        conn.close()


def resolve_update_window(end_date: str, start_date: str | None, history_db: Path = DEFAULT_HISTORY_DB) -> tuple[str, str]:
    target_end = normalize_date(end_date)
    if start_date:
        return normalize_date(start_date), target_end

    latest = latest_history_trade_date(history_db)
    if latest and normalize_date(latest) < target_end:
        return next_calendar_day(latest), target_end
    return target_end, target_end


def latest_short_backtest_date(signal_db: Path = DEFAULT_SIGNAL_DB) -> str | None:
    if not signal_db.exists():
        return None
    conn = sqlite3.connect(signal_db)
    try:
        row = conn.execute(
            """
            select max(p.trade_date)
            from signal_pool p
            join signal_runs r on r.run_id = p.run_id
            where p.mode = 'short'
              and p.profile = ?
              and r.source = 'backtest_ic_short'
            """,
            (SHORT_PROFILE,),
        ).fetchone()
        return str(row[0]) if row and row[0] else None
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return None
        raise
    finally:
        conn.close()


def refresh_market_radar_snapshot(
    history_db: Path = DEFAULT_HISTORY_DB,
    signal_db: Path = DEFAULT_SIGNAL_DB,
    radar_date: str | None = None,
    dry_run: bool = False,
) -> int | None:
    """Build and persist the latest Market Radar snapshot for the dashboard."""
    if dry_run:
        print(f"> refresh_market_radar_snapshot --date {radar_date or 'latest'}")
        return None

    from market_radar.store import save_market_radar_snapshot
    from web_app.services.sector_service import (
        build_concept_news_radar,
        build_market_radar_decision,
        build_sector_radar,
    )

    end_date = normalize_date(radar_date) if radar_date else None
    radar = build_sector_radar(history_db, end_date=end_date)
    concept_news = build_concept_news_radar(signal_db, today=end_date)
    decision = build_market_radar_decision(radar, concept_news)
    brief = decision.get("research_brief") if isinstance(decision, dict) else None
    if not isinstance(brief, dict) or not brief:
        print("市场雷达快照跳过：未生成研究简报。")
        return None

    snapshot_date = normalize_date(str(radar.get("end_date") or end_date or today_text()))
    row_id = save_market_radar_snapshot(signal_db, snapshot_date, brief, decision)
    print(f"市场雷达快照已更新：date={snapshot_date} row_id={row_id}")
    return row_id


def run_command(args: list[str], dry_run: bool = False) -> RunResult:
    print("\n> " + " ".join(args))
    if dry_run:
        return RunResult(args[1] if len(args) > 1 else args[0], 0)
    completed = subprocess.run(args, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"命令失败，退出码 {completed.returncode}: {' '.join(args)}")
    return RunResult(args[1] if len(args) > 1 else args[0], completed.returncode)


def latest_ic_short_file(since_mtime: float | None = None) -> Path | None:
    files = sorted(Path("backtest_results").glob("ic_short_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        if since_mtime is None or path.stat().st_mtime >= since_mtime:
            return path
    return None


def refresh_core_history_data(py: str, args: argparse.Namespace, target_start: str, target_end: str) -> str:
    if not args.skip_download:
        download_cmd = [py, "data_downloader.py", "--start", target_start, "--end", target_end, "--core-only"]
        if args.skip_financial:
            download_cmd.append("--skip-financial")
        run_command(download_cmd, args.dry_run)

    if not args.skip_history_import:
        run_command(
            [
                py,
                "history_db_importer.py",
                "--cache-dir",
                str(args.cache_dir),
                "--db",
                str(args.history_db),
                "--start",
                target_start,
                "--end",
                target_end,
                "--tables",
                "daily",
                "daily_basic",
                "moneyflow",
                "stock_basic",
            ],
            args.dry_run,
        )

    return target_end if args.dry_run else latest_history_trade_date(args.history_db) or target_end


def run_update(args: argparse.Namespace) -> None:
    target_end = normalize_date(args.end or today_text())
    target_start, target_end = resolve_update_window(target_end, args.start, args.history_db)
    py = sys.executable
    update_mode = getattr(args, "mode", "daily")
    fast_mode = bool(getattr(args, "fast", False))

    if update_mode in ("dragon", "radar"):
        effective_end = refresh_core_history_data(py, args, target_start, target_end)
        print(f"\n有效最新交易日：{effective_end}")
        if update_mode == "dragon":
            _refresh_dragon_limit_pool(py, args, effective_end, required=True)
            print("\n热门龙头更新流程完成。")
            return
        if not args.skip_market_context:
            run_command([py, "market_context_snapshot.py", "--date", effective_end], args.dry_run)
        refresh_market_radar_snapshot(args.history_db, args.signal_db, effective_end, dry_run=args.dry_run)
        print("\n市场雷达更新流程完成。")
        return

    if fast_mode:
        refresh_core_history_data(py, args, target_start, target_end)
    else:
        if not args.skip_download:
            download_cmd = [py, "data_downloader.py", "--start", target_start, "--end", target_end]
            if args.skip_financial:
                download_cmd.append("--skip-financial")
            run_command(download_cmd, args.dry_run)

        if not args.skip_history_import:
            run_command(
                [
                    py,
                    "history_db_importer.py",
                    "--cache-dir",
                    str(args.cache_dir),
                    "--db",
                    str(args.history_db),
                    "--start",
                    target_start,
                    "--end",
                    target_end,
                    "--tables",
                    "daily",
                    "daily_basic",
                    "moneyflow",
                    "stock_basic",
                    "index_daily",
                ],
                args.dry_run,
            )

    effective_end = target_end if args.dry_run else latest_history_trade_date(args.history_db) or target_end
    print(f"\n有效最新交易日：{effective_end}")

    if effective_end != target_end:
        print(f"\n提示：目标日期 {target_end} 的行情未完整落库，市场上下文按有效行情日 {effective_end} 生成。")

    if not args.skip_market_context and not fast_mode:
        run_command(
            [
                py,
                "market_context_snapshot.py",
                "--date",
                effective_end,
            ],
            args.dry_run,
        )

    if not args.skip_main:
        run_command([py, "main.py", "--local-data-live", "--cache-dir", str(args.cache_dir)], args.dry_run)
        if not args.skip_ai_explanations and not fast_mode:
            _backfill_today_ai_explanations(py, args, effective_end)
            _generate_daily_ai_brief(py, args, effective_end)
        _refresh_dragon_limit_pool(py, args, effective_end)
        if not fast_mode:
            refresh_market_radar_snapshot(args.history_db, args.signal_db, effective_end, dry_run=args.dry_run)

    if update_mode == "daily":
        print("\n日常轻量同步：跳过短线复盘回测和长线历史审计。需要补历史时请使用 --mode full。")

    if update_mode != "daily" and not args.skip_short_review:
        short_start = normalize_date(args.short_start) if args.short_start else _default_short_start(args.signal_db, effective_end)
        if short_start <= effective_end:
            before = datetime.now().timestamp()
            run_command(
                [
                    py,
                    "test.py",
                    "--scenario",
                    SHORT_SCENARIO,
                    "--exit-profile",
                    "baseline",
                    "--topn",
                    "3",
                    "--start",
                    short_start,
                    "--end",
                    effective_end,
                    "--label",
                    f"web_short_v9_{effective_end}",
                ],
                args.dry_run,
            )
            if args.dry_run:
                print("> signal_backfill.py 会在回测后自动使用最新 ic_short_*.csv")
            else:
                ic_file = latest_ic_short_file(before)
                if ic_file is None:
                    print("未找到新的 ic_short_*.csv，跳过短线复盘回填。")
                else:
                    run_command(
                        [
                            py,
                            "signal_backfill.py",
                            "--source",
                            str(ic_file),
                            "--db",
                            str(args.signal_db),
                            "--profile",
                            SHORT_PROFILE,
                            "--top",
                            "3",
                        ],
                        args.dry_run,
                    )
        else:
            print(f"短线复盘已到 {effective_end}，跳过回测回填。")

    if update_mode != "daily" and not args.skip_longterm_audit:
        for period, start, end in build_longterm_periods(effective_end, full_history=args.full_history):
            output = Path("reports") / f"longterm_pool_quality_{period}_v18_market_sync_full.md"
            csv_output = Path("reports") / f"longterm_pool_quality_{period}_v18_market_sync_full.csv"
            run_command(
                [
                    py,
                    "longterm_pool_quality_audit.py",
                    "--start",
                    start,
                    "--end",
                    end,
                    "--longterm-profile",
                    LONGTERM_PROFILE,
                    "--forward-days",
                    "10",
                    "40",
                    "80",
                    "--sample-step",
                    "1",
                    "--output",
                    str(output),
                    "--csv-output",
                    str(csv_output),
                ],
                args.dry_run,
            )
            run_command(
                [
                    py,
                    "longterm_history_importer.py",
                    "--source",
                    str(csv_output),
                    "--db",
                    str(args.signal_db),
                ],
                args.dry_run,
            )

    print("\nWeb 数据同步流程完成。")


def _default_short_start(signal_db: Path, effective_end: str) -> str:
    latest = latest_short_backtest_date(signal_db)
    if latest:
        return next_calendar_day(latest)
    return f"{effective_end[:4]}0101"


def _backfill_today_ai_explanations(py: str, args: argparse.Namespace, effective_end: str) -> None:
    for mode in ("short", "longterm"):
        command = [
            py,
            "backfill_signal_explanations.py",
            "--signal-db",
            str(args.signal_db),
            "--history-db",
            str(args.history_db),
            "--start",
            effective_end,
            "--end",
            effective_end,
            "--mode",
            mode,
            "--source",
            "live",
        ]
        if args.ai_explanation_limit and int(args.ai_explanation_limit) > 0:
            command.extend(["--limit", str(args.ai_explanation_limit)])
        run_command(command, args.dry_run)


def _generate_daily_ai_brief(py: str, args: argparse.Namespace, effective_end: str) -> None:
    run_command(
        [
            py,
            "daily_ai_brief.py",
            "--date",
            effective_end,
            "--signal-db",
            str(args.signal_db),
            "--history-db",
            str(args.history_db),
        ],
        args.dry_run,
    )


def _dragon_limit_pool_collector_path() -> Path | None:
    candidates = [
        Path("research") / "limit_pool_collector.py",
        Path("..") / "stock-strategy-research" / "research" / "limit_pool_collector.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _refresh_dragon_limit_pool(py: str, args: argparse.Namespace, effective_end: str, required: bool = False) -> None:
    collector = _dragon_limit_pool_collector_path()
    if collector is None:
        message = "未找到 limit_pool_collector.py，无法刷新热门龙头观察池。请部署 research/limit_pool_collector.py 或 stock-strategy-research。"
        if required:
            raise SystemExit(message)
        print(f"\n龙头观察池：{message}")
        return
    output_root = collector.resolve().parents[1] / "data_research"
    try:
        run_command(
            [
                py,
                str(collector),
                "--date",
                effective_end,
                "--output-root",
                str(output_root),
            ],
            args.dry_run,
        )
    except SystemExit as exc:
        if required:
            raise
        print(f"\n龙头观察池：刷新失败，已跳过（不影响行情同步）：{exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键同步 Web 前端所需的行情、实盘、短线复盘、长线审计数据")
    parser.add_argument("--start", default=None, help="行情补数起始日，默认等于 --end")
    parser.add_argument("--end", default=None, help="目标日期 YYYYMMDD，默认今天")
    parser.add_argument("--short-start", default=None, help="短线复盘回测起始日，默认从库内最新复盘日后一日开始")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--history-db", type=Path, default=DEFAULT_HISTORY_DB)
    parser.add_argument("--signal-db", type=Path, default=DEFAULT_SIGNAL_DB)
    parser.add_argument("--mode", choices=["daily", "dragon", "radar", "full"], default="daily", help="daily=轻量日更；dragon=只更新热门龙头；radar=只更新市场雷达；full=补齐短线复盘和长线审计")
    parser.add_argument("--full-history", action="store_true", help="重跑并导入 2024H1 起所有半年度长线审计")
    parser.add_argument("--fast", action="store_true", help="线上极速同步：跳过限频重接口、市场上下文和AI解释，只刷新核心信号")
    parser.add_argument("--skip-financial", action="store_true", default=True, help="日常更新默认跳过财务下载")
    parser.add_argument("--with-financial", dest="skip_financial", action="store_false", help="同时下载财务数据")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-history-import", action="store_true")
    parser.add_argument("--skip-market-context", action="store_true")
    parser.add_argument("--skip-main", action="store_true")
    parser.add_argument("--skip-ai-explanations", action="store_true", help="跳过日常同步后的AI解释文档生成")
    parser.add_argument("--ai-explanation-limit", type=int, default=0, help="每类信号最多生成多少条AI解释，0表示不限")
    parser.add_argument("--skip-short-review", action="store_true")
    parser.add_argument("--skip-longterm-audit", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    return parser.parse_args()


def main() -> None:
    run_update(parse_args())


if __name__ == "__main__":
    main()
