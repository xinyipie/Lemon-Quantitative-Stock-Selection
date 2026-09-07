#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""财务记录的点时清洗与行情截面合并。"""

from __future__ import annotations

import pandas as pd


FINANCIAL_COLUMNS = ["ts_code", "ann_date", "end_date", "roe", "debt_to_assets", "netprofit_yoy"]


def prepare_financial_events(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame[FINANCIAL_COLUMNS].copy()
    for column in ("ann_date", "end_date"):
        work[column] = work[column].astype("string").str.replace(r"\.0$", "", regex=True)
    work = work[
        work["ann_date"].str.fullmatch(r"\d{8}", na=False)
        & work["end_date"].str.fullmatch(r"\d{8}", na=False)
    ].copy()
    for column in ("roe", "debt_to_assets", "netprofit_yoy"):
        work[column] = pd.to_numeric(work[column], errors="coerce")

    # 每个报告期只使用首次披露版本，避免把后续修订值回填到首次公告日。
    work = (
        work.sort_values(["ts_code", "end_date", "ann_date"])
        .drop_duplicates(["ts_code", "end_date"], keep="first")
        .sort_values(["ts_code", "ann_date", "end_date"])
    )
    end_number = pd.to_numeric(work["end_date"], errors="coerce")
    running_latest = end_number.groupby(work["ts_code"]).cummax()
    work = work[end_number.eq(running_latest)].copy()
    work["previous_netprofit_yoy"] = work.groupby("ts_code")["netprofit_yoy"].shift(1)
    work["profit_growth_delta"] = work["netprofit_yoy"] - work["previous_netprofit_yoy"]
    work["ann_date_key"] = pd.to_numeric(work["ann_date"], errors="coerce")
    return work.sort_values(["ann_date_key", "ts_code"]).reset_index(drop=True)


def merge_point_in_time(panel: pd.DataFrame, financial_events: pd.DataFrame) -> pd.DataFrame:
    left = panel.copy()
    left["trade_date"] = left["trade_date"].astype("string").str.replace(r"\.0$", "", regex=True)
    left["trade_date_key"] = pd.to_numeric(left["trade_date"], errors="coerce")
    left = left.dropna(subset=["trade_date_key", "ts_code"]).sort_values(["trade_date_key", "ts_code"])
    right = financial_events.copy().sort_values(["ann_date_key", "ts_code"])
    merged = pd.merge_asof(
        left,
        right,
        left_on="trade_date_key",
        right_on="ann_date_key",
        by="ts_code",
        direction="backward",
        allow_exact_matches=True,
    )
    trade_dates = pd.to_datetime(merged["trade_date"], format="%Y%m%d", errors="coerce")
    announcement_dates = pd.to_datetime(merged["ann_date"], format="%Y%m%d", errors="coerce")
    merged["days_since_announcement"] = (trade_dates - announcement_dates).dt.days
    return merged
