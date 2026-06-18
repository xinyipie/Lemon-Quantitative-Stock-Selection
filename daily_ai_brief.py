#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate cached AI daily brief for the Web dashboard."""

from __future__ import annotations

import argparse
from pathlib import Path

from history_store import DEFAULT_HISTORY_DB_PATH
from signal_store import DEFAULT_DB_PATH
from web_app.services.explanation_service import get_or_create_daily_brief


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成并缓存首页今日AI摘要")
    parser.add_argument("--date", required=True, help="交易日 YYYYMMDD")
    parser.add_argument("--signal-db", default=str(DEFAULT_DB_PATH), help="信号数据库路径")
    parser.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB_PATH), help="历史行情数据库路径")
    parser.add_argument("--force", action="store_true", help="忽略缓存，强制重新生成")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = get_or_create_daily_brief(
        args.date,
        signal_db=Path(args.signal_db),
        history_db=Path(args.history_db),
        force=args.force,
    )
    doc = result.get("doc") or {}
    print(f"今日AI摘要：{args.date} -> {result.get('source')}")
    print(doc.get("summary", ""))


if __name__ == "__main__":
    main()
