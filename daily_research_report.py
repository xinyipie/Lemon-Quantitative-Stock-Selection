#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成并归档每日管理层市场研究报告。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from daily_report.service import generate_daily_report
from daily_web_update import latest_history_trade_date
from history_store import DEFAULT_HISTORY_DB_PATH
from signal_store import DEFAULT_DB_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成每日市场研究报告")
    parser.add_argument("--report-date", help="发布日期 YYYYMMDD，默认上海时区当天")
    parser.add_argument("--market-date", help="行情有效日期 YYYYMMDD，默认历史库最新交易日")
    parser.add_argument("--signal-db", default=str(DEFAULT_DB_PATH), help="信号与报告数据库")
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB_PATH), help="历史行情数据库")
    parser.add_argument("--slot", choices=("night", "morning", "manual"), default="manual", help="生成时段")
    parser.add_argument("--retry-if-missing", action="store_true", help="仅在当日没有有效报告时补偿生成")
    parser.add_argument("--force", action="store_true", help="人工强制生成新版本")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report_date = _normalize_date(
        args.report_date or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    )
    signal_db = Path(args.signal_db)
    history_db = Path(args.history_db)
    if len(report_date) != 8:
        parser.error("--report-date 必须是 YYYYMMDD")
    market_date = _normalize_date(args.market_date) if args.market_date else ""
    if not market_date:
        if not history_db.exists():
            parser.error("历史数据库不存在，无法确定行情有效日期")
        market_date = latest_history_trade_date(history_db) or ""
    if len(market_date) != 8:
        parser.error("--market-date 必须是 YYYYMMDD，且历史库需要包含行情")
    try:
        signal_db.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        parser.error(f"信号数据库路径不可写：{exc}")
    result = generate_daily_report(
        report_date,
        market_date,
        signal_db,
        history_db,
        slot=args.slot,
        retry_if_missing=args.retry_if_missing,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result.get("status") == "failed" else 0


def _normalize_date(value: str | None) -> str:
    return "".join(character for character in str(value or "") if character.isdigit())[:8]


if __name__ == "__main__":
    raise SystemExit(main())
