#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Import local parquet cache into the reusable SQLite history database."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterable

import pandas as pd

from history_store import DEFAULT_HISTORY_DB_PATH, HistoryStore


logger = logging.getLogger("history_db_importer")


SOURCE_TO_TABLE = {
    "daily": "stock_daily",
    "daily_basic": "stock_daily_basic",
    "moneyflow": "stock_moneyflow",
    "index_daily": "index_daily",
    "stock_basic": "stock_basic",
    "fina_indicator": "fina_indicator",
    "income": "income",
}

DAILY_SOURCES = {"daily", "daily_basic", "moneyflow", "index_daily"}
STATIC_SOURCES = {"stock_basic", "fina_indicator", "income"}


def import_history_cache(
    cache_dir: str | Path = Path("data") / "cache",
    db_path: str | Path = DEFAULT_HISTORY_DB_PATH,
    start: str | None = None,
    end: str | None = None,
    tables: Iterable[str] | None = None,
) -> dict[str, int]:
    cache_dir = Path(cache_dir)
    selected_sources = list(tables or SOURCE_TO_TABLE.keys())
    store = HistoryStore(db_path)
    summary: dict[str, int] = {}
    try:
        for source in selected_sources:
            if source not in SOURCE_TO_TABLE:
                raise ValueError(f"Unsupported import source: {source}")
            table = SOURCE_TO_TABLE[source]
            if source in DAILY_SOURCES:
                count = _import_daily_source(store, cache_dir, source, table, start, end)
            else:
                count = _import_static_source(store, cache_dir, source, table)
            summary[table] = count
    finally:
        store.close()
    return summary


def _import_daily_source(
    store: HistoryStore,
    cache_dir: Path,
    source: str,
    table: str,
    start: str | None,
    end: str | None,
) -> int:
    source_dir = cache_dir / source
    if not source_dir.exists():
        logger.warning("历史缓存目录不存在：%s", source_dir)
        return 0

    total = 0
    for path in sorted(source_dir.glob("*.parquet")):
        date = path.stem
        if start and date < start:
            continue
        if end and date > end:
            continue
        df = pd.read_parquet(path)
        if "trade_date" not in df.columns and not df.empty:
            df = df.copy()
            df["trade_date"] = date
        total += store.upsert_dataframe(table, df)
    return total


def _import_static_source(store: HistoryStore, cache_dir: Path, source: str, table: str) -> int:
    path = cache_dir / f"{source}.parquet"
    if not path.exists():
        logger.warning("历史缓存文件不存在：%s", path)
        return 0
    df = pd.read_parquet(path)
    return store.upsert_dataframe(table, df)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import parquet cache into stock_history.db")
    parser.add_argument("--cache-dir", default=str(Path("data") / "cache"), help="本地 parquet 缓存目录")
    parser.add_argument("--db", default=str(DEFAULT_HISTORY_DB_PATH), help="SQLite 历史数据库路径")
    parser.add_argument("--start", default=None, help="起始交易日 YYYYMMDD，仅影响日频目录")
    parser.add_argument("--end", default=None, help="结束交易日 YYYYMMDD，仅影响日频目录")
    parser.add_argument(
        "--tables",
        nargs="+",
        default=None,
        choices=sorted(SOURCE_TO_TABLE.keys()),
        help="要导入的数据源，默认全部",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    summary = import_history_cache(
        cache_dir=args.cache_dir,
        db_path=args.db,
        start=args.start,
        end=args.end,
        tables=args.tables,
    )

    print("历史数据库导入完成：")
    for table, count in summary.items():
        print(f"  {table}: {count} 行")
    print(f"数据库：{args.db}")


if __name__ == "__main__":
    main()
