"""批量补齐 index_daily 缓存。

原下载器按“交易日 * 指数代码”逐个请求，历史区间会非常慢。本脚本按指数代码
拉取整段区间，再按 trade_date 拆回 data/cache/index_daily/YYYYMMDD.parquet。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_downloader as dl


FIELDS = "ts_code,trade_date,open,high,low,close,pct_chg"
SW_COLUMNS = ["ts_code", "trade_date", "open", "high", "low", "close", "pct_chg"]


def _date_chunks(start_date: str, end_date: str, max_days: int = 900):
    """把长日期区间拆成接口可接受的小段。"""
    cur = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days - 1), end)
        yield cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")
        cur = chunk_end + timedelta(days=1)


def _fetch_index_range_once(pro, code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """按单个指数代码拉取一个短区间。"""
    if code.endswith(".SI"):
        df = dl._retry(
            lambda: pro.query(
                "sw_daily",
                ts_code=code,
                start_date=start_date,
                end_date=end_date,
            ),
            retries=3,
            wait=5.0,
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"pct_change": "pct_chg"})
        return df[[col for col in SW_COLUMNS if col in df.columns]].copy()

    df = dl._retry(
        lambda: pro.index_daily(
            ts_code=code,
            start_date=start_date,
            end_date=end_date,
            fields=FIELDS,
        ),
        retries=3,
        wait=5.0,
    )
    if df is None:
        return pd.DataFrame()
    return df


def _fetch_index_range(pro, code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """按单个指数代码分段拉取整段区间。"""
    frames = []
    for chunk_start, chunk_end in _date_chunks(start_date, end_date):
        df = _fetch_index_range_once(pro, code, chunk_start, chunk_end)
        if not df.empty:
            frames.append(df)
        time.sleep(0.2)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fill_index_daily(start_date: str, end_date: str, force: bool, buffer_days: int, pause: float) -> None:
    """补齐指定区间及前置缓冲期的 index_daily 日频缓存。"""
    import main as stock_main

    pro = stock_main.pro
    dl._ensure_dirs()

    fetch_start = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=buffer_days)).strftime("%Y%m%d")
    trade_dates = set(dl._get_trade_dates(pro, fetch_start, end_date))
    dl.logger.info(
        "批量补齐 index_daily：%s -> %s（含缓冲起点 %s，交易日 %d 天）",
        start_date,
        end_date,
        fetch_start,
        len(trade_dates),
    )

    frames = []
    for idx, code in enumerate(dl.INDEX_CODES, 1):
        dl.logger.info("[%02d/%02d] 下载指数 %s 区间数据...", idx, len(dl.INDEX_CODES), code)
        df = _fetch_index_range(pro, code, fetch_start, end_date)
        if not df.empty:
            frames.append(df)
            dl.logger.info("  ✓ %s：%d 行", code, len(df))
        else:
            dl.logger.warning("  ⚠ %s：0 行", code)
        time.sleep(pause)

    if not frames:
        dl.logger.error("index_daily 区间接口未返回任何数据")
        return

    all_df = pd.concat(frames, ignore_index=True)
    all_df["trade_date"] = all_df["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    all_df = all_df[all_df["trade_date"].isin(trade_dates)].copy()

    written = skipped = 0
    min_rows = dl._index_cache_min_rows()
    for trade_date, group in all_df.groupby("trade_date"):
        path = dl._daily_path("index_daily", trade_date)
        if not force and dl._cache_has_rows(path, min_rows=min_rows):
            skipped += 1
            continue
        group = group.sort_values("ts_code").reset_index(drop=True)
        dl._save(group, path)
        written += 1

    expected = len(trade_dates)
    available = len(set(all_df["trade_date"]))
    dl.logger.info(
        "index_daily 补齐结束：写入 %d 天，跳过 %d 天，接口覆盖 %d/%d 个交易日",
        written,
        skipped,
        available,
        expected,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="批量补齐 index_daily 历史缓存")
    parser.add_argument("--start", required=True, help="开始日期 YYYYMMDD")
    parser.add_argument("--end", required=True, help="结束日期 YYYYMMDD")
    parser.add_argument("--force", action="store_true", help="覆盖已有 index_daily 文件")
    parser.add_argument("--buffer-days", type=int, default=120, help="开始日期前置缓冲天数")
    parser.add_argument("--pause", type=float, default=0.8, help="指数代码之间的限速秒数")
    args = parser.parse_args()

    fill_index_daily(args.start, args.end, args.force, args.buffer_days, args.pause)


if __name__ == "__main__":
    main()
