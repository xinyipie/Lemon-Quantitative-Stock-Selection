#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SQLite store for reusable historical stock facts."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_HISTORY_DB_PATH = Path("data") / "stock_history.db"


TABLE_COLUMNS: dict[str, list[str]] = {
    "stock_daily": [
        "trade_date", "ts_code", "open", "high", "low", "close",
        "pre_close", "change", "pct_chg", "vol", "amount",
    ],
    "stock_daily_basic": [
        "trade_date", "ts_code", "turnover_rate", "turnover_rate_f",
        "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm",
        "dv_ratio", "dv_ttm", "total_share", "float_share",
        "free_share", "total_mv", "circ_mv",
    ],
    "stock_moneyflow": [
        "trade_date", "ts_code", "buy_sm_vol", "buy_sm_amount",
        "sell_sm_vol", "sell_sm_amount", "buy_md_vol", "buy_md_amount",
        "sell_md_vol", "sell_md_amount", "buy_lg_vol", "buy_lg_amount",
        "sell_lg_vol", "sell_lg_amount", "buy_elg_vol", "buy_elg_amount",
        "sell_elg_vol", "sell_elg_amount", "net_mf_vol", "net_mf_amount",
    ],
    "index_daily": [
        "trade_date", "ts_code", "open", "high", "low", "close",
        "pre_close", "change", "pct_chg", "vol", "amount",
    ],
    "stock_basic": [
        "ts_code", "symbol", "name", "area", "industry", "market",
        "list_date", "list_status",
    ],
    "fina_indicator": [
        "ts_code", "ann_date", "end_date", "roe", "debt_to_assets",
        "netprofit_yoy", "grossprofit_margin", "netprofit_margin",
    ],
    "income": [
        "ts_code", "ann_date", "end_date", "revenue", "n_income",
        "total_profit", "operate_profit",
    ],
}


TABLE_KEYS: dict[str, list[str]] = {
    "stock_daily": ["trade_date", "ts_code"],
    "stock_daily_basic": ["trade_date", "ts_code"],
    "stock_moneyflow": ["trade_date", "ts_code"],
    "index_daily": ["trade_date", "ts_code"],
    "stock_basic": ["ts_code"],
    "fina_indicator": ["ts_code", "ann_date", "end_date"],
    "income": ["ts_code", "ann_date", "end_date"],
}


class HistoryStore:
    def __init__(self, db_path: str | Path = DEFAULT_HISTORY_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists stock_daily (
                trade_date text not null,
                ts_code text not null,
                open real,
                high real,
                low real,
                close real,
                pre_close real,
                change real,
                pct_chg real,
                vol real,
                amount real,
                primary key(trade_date, ts_code)
            );
            create index if not exists idx_stock_daily_code_date
                on stock_daily(ts_code, trade_date);

            create table if not exists stock_daily_basic (
                trade_date text not null,
                ts_code text not null,
                turnover_rate real,
                turnover_rate_f real,
                volume_ratio real,
                pe real,
                pe_ttm real,
                pb real,
                ps real,
                ps_ttm real,
                dv_ratio real,
                dv_ttm real,
                total_share real,
                float_share real,
                free_share real,
                total_mv real,
                circ_mv real,
                primary key(trade_date, ts_code)
            );
            create index if not exists idx_stock_daily_basic_code_date
                on stock_daily_basic(ts_code, trade_date);

            create table if not exists stock_moneyflow (
                trade_date text not null,
                ts_code text not null,
                buy_sm_vol real,
                buy_sm_amount real,
                sell_sm_vol real,
                sell_sm_amount real,
                buy_md_vol real,
                buy_md_amount real,
                sell_md_vol real,
                sell_md_amount real,
                buy_lg_vol real,
                buy_lg_amount real,
                sell_lg_vol real,
                sell_lg_amount real,
                buy_elg_vol real,
                buy_elg_amount real,
                sell_elg_vol real,
                sell_elg_amount real,
                net_mf_vol real,
                net_mf_amount real,
                primary key(trade_date, ts_code)
            );
            create index if not exists idx_stock_moneyflow_code_date
                on stock_moneyflow(ts_code, trade_date);

            create table if not exists index_daily (
                trade_date text not null,
                ts_code text not null,
                open real,
                high real,
                low real,
                close real,
                pre_close real,
                change real,
                pct_chg real,
                vol real,
                amount real,
                primary key(trade_date, ts_code)
            );
            create index if not exists idx_index_daily_code_date
                on index_daily(ts_code, trade_date);

            create table if not exists stock_basic (
                ts_code text primary key,
                symbol text,
                name text,
                area text,
                industry text,
                market text,
                list_date text,
                list_status text
            );

            create table if not exists fina_indicator (
                ts_code text not null,
                ann_date text not null,
                end_date text not null,
                roe real,
                debt_to_assets real,
                netprofit_yoy real,
                grossprofit_margin real,
                netprofit_margin real,
                primary key(ts_code, ann_date, end_date)
            );
            create index if not exists idx_fina_indicator_code_ann
                on fina_indicator(ts_code, ann_date, end_date);

            create table if not exists income (
                ts_code text not null,
                ann_date text not null,
                end_date text not null,
                revenue real,
                n_income real,
                total_profit real,
                operate_profit real,
                primary key(ts_code, ann_date, end_date)
            );
            create index if not exists idx_income_code_ann
                on income(ts_code, ann_date, end_date);
            """
        )
        self.conn.commit()

    def upsert_dataframe(self, table: str, df: pd.DataFrame) -> int:
        if table not in TABLE_COLUMNS:
            raise ValueError(f"Unsupported history table: {table}")
        if df is None or df.empty:
            return 0

        prepared = self._prepare_dataframe(table, df)
        if prepared.empty:
            return 0

        columns = TABLE_COLUMNS[table]
        placeholders = ", ".join(["?"] * len(columns))
        col_sql = ", ".join(columns)
        key_cols = TABLE_KEYS[table]
        update_cols = [col for col in columns if col not in key_cols]
        update_sql = ", ".join([f"{col}=excluded.{col}" for col in update_cols])
        conflict_sql = ", ".join(key_cols)
        sql = (
            f"insert into {table} ({col_sql}) values ({placeholders}) "
            f"on conflict({conflict_sql}) do update set {update_sql}"
        )

        rows = [tuple(_sqlite_value(row[col]) for col in columns) for _, row in prepared.iterrows()]
        with self.conn:
            self.conn.executemany(sql, rows)
        return len(rows)

    def _prepare_dataframe(self, table: str, df: pd.DataFrame) -> pd.DataFrame:
        columns = TABLE_COLUMNS[table]
        key_cols = TABLE_KEYS[table]
        prepared = df.copy()
        for col in columns:
            if col not in prepared.columns:
                prepared[col] = None
        for col in ("trade_date", "ann_date", "end_date", "list_date"):
            if col in prepared.columns:
                prepared[col] = _normalize_date_series(prepared[col])
        for key in key_cols:
            prepared[key] = prepared[key].astype(str).str.strip()
            prepared = prepared[prepared[key].notna() & (prepared[key] != "") & (prepared[key] != "None")]
        return prepared[columns].drop_duplicates(subset=key_cols, keep="last").reset_index(drop=True)


def _normalize_date_series(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace("-", "", regex=False)
        .str.replace(".0", "", regex=False)
        .str.slice(0, 8)
        .replace({"NaT": "", "nan": "", "None": ""})
    )


def _sqlite_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            return value
    return value
