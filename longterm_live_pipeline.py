#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Live long-term watchlist compression and elite alert helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from longterm_pool_alert_audit import filter_elite_alerts
from longterm_pool_compression_audit import compress_snapshot_pool


@dataclass
class LongtermLiveWatchlists:
    watchlist: pd.DataFrame
    elite: pd.DataFrame


def build_live_watchlists(
    longterm_pool: pd.DataFrame,
    trade_date: str,
    history: pd.DataFrame | None = None,
    max_watch: int = 3,
    max_industry: int = 2,
    lookback_days: int = 20,
    elite_min_score: float = 80.0,
    elite_min_industry_rs: float = 8.0,
    elite_min_drawdown: float = 7.0,
    elite_max_drawdown: float = 15.0,
) -> LongtermLiveWatchlists:
    """Build today's live long-term observation and high-confidence alert lists."""
    current = _normalize_live_pool(longterm_pool, trade_date)
    if current.empty:
        empty = pd.DataFrame()
        return LongtermLiveWatchlists(watchlist=empty, elite=empty)

    frames = []
    if history is not None and not history.empty:
        frames.append(_normalize_live_pool(history, trade_date=None))
    frames.append(current)
    data = pd.concat(frames, ignore_index=True, sort=False)

    compressed = compress_snapshot_pool(
        data,
        max_active=max_watch,
        max_industry_active=max_industry,
        lookback_days=lookback_days,
    )
    if compressed.empty:
        empty = pd.DataFrame()
        return LongtermLiveWatchlists(watchlist=empty, elite=empty)

    today = _normalize_date(trade_date)
    watch = compressed[compressed["select_date"].astype(str).map(_normalize_date) == today].copy()
    if watch.empty:
        empty = pd.DataFrame()
        return LongtermLiveWatchlists(watchlist=empty, elite=empty)

    watch["pool_type"] = "longterm_watch"
    watch["alert_tier"] = "watch"
    watch["elite_alert"] = False
    watch = watch.sort_values(["snapshot_rank", "compression_score"], ascending=[True, False]).reset_index(drop=True)

    elite = filter_elite_alerts(
        watch,
        min_score=elite_min_score,
        min_industry_rs=elite_min_industry_rs,
        min_drawdown=elite_min_drawdown,
        max_drawdown=elite_max_drawdown,
    )
    if not elite.empty:
        elite = elite.copy()
        elite["pool_type"] = "longterm_elite"
        elite["alert_tier"] = "elite"
        elite_codes = set(elite["ts_code"].astype(str))
        watch.loc[watch["ts_code"].astype(str).isin(elite_codes), "elite_alert"] = True
        watch.loc[watch["ts_code"].astype(str).isin(elite_codes), "alert_tier"] = "elite"

    return LongtermLiveWatchlists(watchlist=watch, elite=elite)


def _normalize_live_pool(df: pd.DataFrame, trade_date: str | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    if "select_date" not in data.columns:
        if trade_date is None:
            data["select_date"] = ""
        else:
            data["select_date"] = _normalize_date(trade_date)
    else:
        data["select_date"] = data["select_date"].astype(str).map(_normalize_date)

    if "ts_code" not in data.columns:
        if "code" in data.columns:
            data["ts_code"] = data["code"].astype(str).map(_to_ts_code)
        else:
            data["ts_code"] = ""
    else:
        data["ts_code"] = data["ts_code"].astype(str).map(_to_ts_code)
    if "code" not in data.columns:
        data["code"] = data["ts_code"].astype(str).str.split(".").str[0]

    if "pool_rank_score" not in data.columns:
        if "longterm_score" in data.columns:
            data["pool_rank_score"] = data["longterm_score"]
        elif "score" in data.columns:
            data["pool_rank_score"] = data["score"]
        else:
            data["pool_rank_score"] = 0

    if "quality_rank_score" not in data.columns:
        data["quality_rank_score"] = data["pool_rank_score"]

    for col in ["name", "industry"]:
        if col not in data.columns:
            data[col] = ""

    return data


def _normalize_date(value) -> str:
    return str(value).replace("-", "")[:8]


def _to_ts_code(value: str) -> str:
    code = str(value).strip()
    if "." in code:
        return code
    raw = code.zfill(6)
    suffix = "SH" if raw.startswith(("6", "9")) else "SZ"
    return f"{raw}.{suffix}"
