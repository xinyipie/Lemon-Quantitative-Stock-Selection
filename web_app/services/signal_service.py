#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only signal database services for Web pages."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from history_store import DEFAULT_HISTORY_DB_PATH
from signal_store import DEFAULT_DB_PATH


def get_recent_signals(
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
    limit: int = 50,
    source: str | Sequence[str] | None = None,
    profile: str | Sequence[str] | None = None,
    mode: str | None = None,
    query: str | None = None,
    start: str | None = None,
    end: str | None = None,
    industry: str | None = None,
) -> list[dict]:
    path = Path(signal_db)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        filters = []
        params: list = []
        if source:
            if isinstance(source, str):
                filters.append("r.source = ?")
                params.append(source)
            else:
                source_values = [item for item in source if item]
                if source_values:
                    placeholders = ",".join(["?"] * len(source_values))
                    filters.append(f"r.source in ({placeholders})")
                    params.extend(source_values)
        if profile:
            if isinstance(profile, str):
                filters.append("p.profile = ?")
                params.append(profile)
            else:
                profile_values = [item for item in profile if item]
                if profile_values:
                    placeholders = ",".join(["?"] * len(profile_values))
                    filters.append(f"p.profile in ({placeholders})")
                    params.extend(profile_values)
        if mode:
            filters.append("p.mode = ?")
            params.append(mode)
        if start:
            filters.append("p.trade_date >= ?")
            params.append(str(start).replace("-", "")[:8])
        if end:
            filters.append("p.trade_date <= ?")
            params.append(str(end).replace("-", "")[:8])
        if industry:
            filters.append("p.industry = ?")
            params.append(industry)
        where_sql = "where " + " and ".join(filters) if filters else ""
        fetch_limit = max(limit * 10, 500) if query else limit
        params.append(fetch_limit)
        rows = conn.execute(
            f"""
            select p.trade_date, p.mode, p.profile, p.ts_code, p.name, p.industry,
                   p.rank, p.score, p.pool_type, p.reason, p.factor_json,
                   r.source, r.label
            from signal_pool p
            left join signal_runs r on r.run_id = p.run_id
            {where_sql}
            order by p.trade_date desc, p.mode asc, p.rank asc, p.id desc
            limit ?
            """,
            params,
        ).fetchall()
        signals = _enrich_stock_identity([_row_to_signal(row) for row in rows], history_db)
        if query:
            signals = _filter_signals_by_query(signals, query)
        return signals[:limit]
    finally:
        conn.close()


def get_active_longterm_pool(signal_db: str | Path = DEFAULT_DB_PATH) -> list[dict]:
    path = Path(signal_db)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select mode, profile, ts_code, name, industry, state,
                   first_seen_date, last_seen_date, removed_date,
                   entry_score, latest_score, highest_score,
                   days_in_pool, last_reason
            from pool_state
            where mode = 'longterm' and state = 'active'
            order by latest_score desc, last_seen_date desc
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_signal_runs(
    signal_db: str | Path = DEFAULT_DB_PATH,
    mode: str | None = None,
    source: str | Sequence[str] | None = None,
    profile: str | None = None,
    limit: int = 20,
) -> list[dict]:
    path = Path(signal_db)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        filters = []
        params: list = []
        if mode:
            filters.append("r.mode = ?")
            params.append(mode)
        if source:
            if isinstance(source, str):
                filters.append("r.source = ?")
                params.append(source)
            else:
                values = [item for item in source if item]
                if values:
                    placeholders = ",".join(["?"] * len(values))
                    filters.append(f"r.source in ({placeholders})")
                    params.extend(values)
        if profile:
            filters.append("r.profile = ?")
            params.append(profile)
        where_sql = "where " + " and ".join(filters) if filters else ""
        params.append(limit)
        rows = conn.execute(
            f"""
            select r.run_id, r.trade_date, r.mode, r.profile, r.source, r.label, r.created_at,
                   count(p.id) as signal_count
            from signal_runs r
            left join signal_pool p on p.run_id = r.run_id
            {where_sql}
            group by r.run_id, r.trade_date, r.mode, r.profile, r.source, r.label, r.created_at
            order by r.trade_date desc, r.run_id desc
            limit ?
            """,
            params,
        ).fetchall()
        return [_decorate_signal_run(dict(row)) for row in rows]
    finally:
        conn.close()


def build_default_signal_start(latest_trade_date: str | None, days: int = 100) -> str | None:
    """Build the default lower bound for the short review page."""
    latest = _parse_date(latest_trade_date)
    if latest is None:
        return None
    return (latest - timedelta(days=max(days, 0))).strftime("%Y%m%d")


def get_longterm_runs(signal_db: str | Path = DEFAULT_DB_PATH, limit: int = 20) -> list[dict]:
    path = Path(signal_db)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select r.run_id, r.trade_date, r.profile, r.source, r.label, r.created_at,
                   count(p.id) as signal_count
            from signal_runs r
            left join signal_pool p on p.run_id = r.run_id
            where r.mode = 'longterm'
              and r.run_id in (
                  select max(run_id)
                  from signal_runs
                  where mode = 'longterm'
                  group by trade_date, profile
              )
            group by r.run_id, r.trade_date, r.profile, r.source, r.label, r.created_at
            order by r.trade_date desc, r.run_id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
        return [_decorate_longterm_run(dict(row)) for row in rows]
    finally:
        conn.close()


def get_longterm_events(
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
    limit: int = 50,
) -> list[dict]:
    path = Path(signal_db)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select event_date, profile, ts_code, event_type, old_state, new_state,
                   old_score, new_score, message, created_at
            from pool_events
            where mode = 'longterm'
            order by event_date desc, id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
        events = [_decorate_longterm_event(dict(row)) for row in rows]
        return _enrich_stock_identity(events, history_db)
    finally:
        conn.close()


def get_longterm_audit_summary(
    signal_db: str | Path = DEFAULT_DB_PATH,
    limit: int = 12,
    half_year_only: bool = True,
) -> dict:
    path = Path(signal_db)
    if not path.exists():
        return {"total_samples": 0, "runs": []}
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_longterm_audit_schema(conn)
        period_filter = "where period glob '20[0-9][0-9]H[12]'" if half_year_only else ""
        runs = [
            _decorate_longterm_audit_run(dict(row))
            for row in conn.execute(
                f"""
                select id, period, profile, source_file, sample_count,
                       date_start, date_end, avg_ret_10d, avg_ret_40d,
                       avg_ret_80d, win_rate_80d, outperform_rate_80d,
                       created_at
                from longterm_audit_runs
                {period_filter}
                order by created_at desc, id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
        ]
        total_sql = f"select coalesce(sum(sample_count), 0) from longterm_audit_runs {period_filter}"
        total = conn.execute(total_sql).fetchone()[0]
        return {"total_samples": int(total or 0), "runs": runs}
    finally:
        conn.close()


def get_longterm_audit_samples(
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
    limit: int = 50,
    half_year_only: bool = True,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    path = Path(signal_db)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_longterm_audit_schema(conn)
        period_filter = "and r.period glob '20[0-9][0-9]H[12]'" if half_year_only else ""
        date_filters = []
        params: list = []
        if start:
            date_filters.append("s.select_date >= ?")
            params.append(str(start).replace("-", "")[:8])
        if end:
            date_filters.append("s.select_date <= ?")
            params.append(str(end).replace("-", "")[:8])
        date_filter_sql = ("and " + " and ".join(date_filters)) if date_filters else ""
        params.append(limit)
        rows = conn.execute(
            f"""
            select s.select_date, s.ts_code, s.name, s.industry, s.profile,
                   s.pool_type, s.regime, s.score, s.pool_rank_score,
                   s.industry_rs, s.drawdown_from_high,
                   s.ret_10d, s.ret_40d, s.ret_80d, s.mfe_80d, s.mae_80d,
                   s.excess_ret_80d, s.outperform_80d, s.factor_json,
                   r.period
            from longterm_audit_samples s
            join longterm_audit_runs r on r.id = s.run_id
            where 1 = 1
            {period_filter}
            {date_filter_sql}
            order by s.select_date desc, s.score desc
            limit ?
            """,
            params,
        ).fetchall()
        samples = [_decorate_longterm_audit_sample(dict(row)) for row in rows]
        _attach_longterm_current_paths(samples, history_db)
        _attach_longterm_lifecycle_labels(samples, conn)
        return samples
    finally:
        conn.close()


def summarize_longterm_audit_sample_filter(samples: list[dict], filters: dict | None = None) -> dict:
    """Build a user-facing summary for the longterm sample detail filter."""
    filters = filters or {}
    start = str(filters.get("start") or "").strip()
    end = str(filters.get("end") or "").strip()
    dates = sorted(str(item.get("select_date") or "") for item in samples if item.get("select_date"))
    return {
        "is_filtered": bool(start or end),
        "requested_start": start,
        "requested_end": end,
        "sample_count": len(samples),
        "actual_start": dates[0] if dates else None,
        "actual_end": dates[-1] if dates else None,
    }


def build_longterm_pool_status(pool: list[dict], runs: list[dict]) -> dict:
    """Build the top-level human summary for the longterm pool page."""
    latest_run = runs[0] if runs else {}
    latest_date = str(latest_run.get("trade_date") or "")
    active_count = len(pool or [])
    if active_count:
        elite_count = len(split_longterm_pool(pool)["elite"])
        watch_count = len(split_longterm_pool(pool)["watch"])
        return {
            "title": f"当前长线池：{active_count} 只观察标的",
            "subtitle": f"最新扫描 {latest_date or 'NA'}，Elite {elite_count} / Watch {watch_count}",
            "description": "长线池已有 active 标的，重点看是否处于强提醒、观察还是降级边缘。",
            "tone": "ok" if elite_count else "watch",
        }
    if latest_run:
        return {
            "title": "当前长线池：空仓",
            "subtitle": f"最新扫描 {latest_date or 'NA'}，{latest_run.get('status_label') or '无入池标的'}",
            "description": "脚本已运行，但 v18 规则未放行标的。长线池为空时，系统价值是提醒不要为了持仓而硬买。",
            "tone": "neutral",
        }
    return {
        "title": "当前长线池：未运行",
        "subtitle": "暂无长线扫描记录",
        "description": "请先运行 daily_web_update.py 或 main.py 写入长线扫描记录。",
        "tone": "warn",
    }


def get_stock_signals(
    ts_code: str,
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
    limit: int = 50,
) -> list[dict]:
    path = Path(signal_db)
    if not path.exists():
        return []
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select p.trade_date, p.mode, p.profile, p.ts_code, p.name, p.industry,
                   p.rank, p.score, p.pool_type, p.reason, p.factor_json,
                   r.source, r.label
            from signal_pool p
            left join signal_runs r on r.run_id = p.run_id
            where p.ts_code = ?
            order by p.trade_date desc, p.rank asc, p.id desc
            limit ?
            """,
            (ts_code, limit),
        ).fetchall()
        signals = [_row_to_signal(row) for row in rows]
        return _enrich_stock_identity(signals, history_db)
    finally:
        conn.close()


def split_longterm_pool(pool: list[dict]) -> dict[str, list[dict]]:
    buckets = {"elite": [], "watch": [], "other": []}
    for item in pool:
        profile = str(item.get("profile") or "").lower()
        score = item.get("latest_score") or 0
        if "elite" in profile or score >= 85:
            buckets["elite"].append(item)
        elif "watch" in profile or "longterm" in profile:
            buckets["watch"].append(item)
        else:
            buckets["other"].append(item)
    return buckets


def _decorate_longterm_run(item: dict) -> dict:
    signal_count = int(item.get("signal_count") or 0)
    item["status_label"] = "有入池标的" if signal_count else "无入池标的"
    item["profile_label"] = "Elite强提醒" if "elite" in str(item.get("profile") or "") else "Watch观察"
    return item


def _decorate_signal_run(item: dict) -> dict:
    signal_count = int(item.get("signal_count") or 0)
    item["status_label"] = "有入池标的" if signal_count else "无入池标的"
    item["source_label"] = "历史回测" if item.get("source") == "backtest_ic_short" else "实盘记录"
    return item


def _decorate_longterm_event(item: dict) -> dict:
    labels = {
        "NEW": "新入池",
        "REMOVED": "移出池",
        "UPDATED": "更新",
        "UPGRADED": "升级强提醒",
        "DOWNGRADED": "降级观察",
    }
    item["event_type_label"] = labels.get(str(item.get("event_type") or ""), str(item.get("event_type") or "-"))
    item["score_delta"] = _score_delta(item.get("old_score"), item.get("new_score"))
    item["state_path_label"] = _state_path_label(item.get("event_type"), item.get("old_state"), item.get("new_state"))
    item["event_tone"] = _event_tone(item.get("event_type"))
    item["display_name"] = item.get("ts_code")
    item["display_code"] = item.get("ts_code")
    return item


def _decorate_longterm_audit_run(item: dict) -> dict:
    item["source_name"] = Path(str(item.get("source_file") or "")).name
    item["avg_ret_80d_text"] = _pct_text(item.get("avg_ret_80d"))
    item["win_rate_80d_text"] = _ratio_text(item.get("win_rate_80d"))
    item["outperform_rate_80d_text"] = _ratio_text(item.get("outperform_rate_80d"))
    return item


def _decorate_longterm_audit_sample(item: dict) -> dict:
    item["factors"] = _json_dict(item.pop("factor_json", None))
    item["display_name"] = item.get("name") or item.get("ts_code")
    item["display_code"] = item.get("ts_code")
    item["ret_80d_text"] = _maturity_pct_text(item.get("ret_80d"))
    item["ret_40d_text"] = _maturity_pct_text(item.get("ret_40d"))
    item["ret_10d_text"] = _maturity_pct_text(item.get("ret_10d"))
    item["ret_80d_tone"] = _pct_tone(item.get("ret_80d"))
    item["ret_40d_tone"] = _pct_tone(item.get("ret_40d"))
    item["ret_10d_tone"] = _pct_tone(item.get("ret_10d"))
    item["mfe_80d_text"] = _maturity_pct_text(item.get("mfe_80d"))
    item["mae_80d_text"] = _maturity_pct_text(item.get("mae_80d"))
    item["mae_pain_tone"] = _mae_pain_tone(item.get("mae_80d"))
    item["excess_80d_text"] = _excess_text(item.get("excess_ret_80d"))
    item["excess_80d_tone"] = _pct_tone(item.get("excess_ret_80d"))
    item["stage_return_text"] = "80日观察完成" if item.get("ret_80d") is not None else "未满"
    item["stage_return_tone"] = "muted" if item.get("ret_80d") is None else _pct_tone(item.get("ret_80d"))
    item["elapsed_days"] = None
    item["lifecycle_label"] = "80日观察完成" if item.get("ret_80d") is not None else "观察中"
    item["outperform_label"] = "跑赢" if item.get("outperform_80d") else "未跑赢"
    item["reason_text"] = _longterm_reason_text(item)
    return item


def _attach_longterm_current_paths(samples: list[dict], history_db: str | Path | None) -> None:
    if not samples or not history_db or not Path(history_db).exists():
        return
    conn = sqlite3.connect(history_db)
    conn.row_factory = sqlite3.Row
    try:
        for item in samples:
            path = _query_stock_path_since(conn, item.get("ts_code"), item.get("select_date"))
            if not path:
                continue
            item["elapsed_days"] = path["elapsed_days"]
            item["current_ret"] = path["current_ret"]
            item["current_ret_text"] = f"{path['current_ret']:+.2f}%"
            item["current_ret_tone"] = _pct_tone(path["current_ret"])
            if item.get("ret_80d") is None:
                item["stage_return_text"] = f"当前{path['current_ret']:+.2f}%(t+{path['elapsed_days']})"
                item["stage_return_tone"] = _pct_tone(path["current_ret"])
                item["lifecycle_label"] = f"观察中 t+{path['elapsed_days']}"
            for days in (10, 40, 80):
                key = f"ret_{days}d"
                if item.get(key) is None:
                    item[f"{key}_text"] = _progress_text(path["elapsed_days"], days)
                    item[f"{key}_tone"] = "muted"
    finally:
        conn.close()


def _attach_longterm_lifecycle_labels(samples: list[dict], conn: sqlite3.Connection) -> None:
    if not samples:
        return
    exists = conn.execute(
        "select name from sqlite_master where type='table' and name='pool_events'"
    ).fetchone()
    if not exists:
        return
    for item in samples:
        removed = conn.execute(
            """
            select event_date, message
            from pool_events
            where mode = 'longterm'
              and ts_code = ?
              and event_type = 'REMOVED'
              and event_date >= ?
            order by event_date asc
            limit 1
            """,
            (item.get("ts_code"), item.get("select_date")),
        ).fetchone()
        if removed:
            item["lifecycle_label"] = f"已移出 {removed['event_date']}"


def _query_stock_path_since(conn: sqlite3.Connection, ts_code: str | None, select_date: str | None) -> dict | None:
    if not ts_code or not select_date:
        return None
    rows = conn.execute(
        """
        select trade_date, close
        from stock_daily
        where ts_code = ? and trade_date >= ?
        order by trade_date asc
        """,
        (ts_code, select_date),
    ).fetchall()
    if len(rows) < 2:
        return None
    start_close = _num(rows[0]["close"])
    latest_close = _num(rows[-1]["close"])
    if not start_close or latest_close is None:
        return None
    return {
        "elapsed_days": len(rows) - 1,
        "current_ret": (latest_close - start_close) / start_close * 100,
        "latest_trade_date": rows[-1]["trade_date"],
    }


def _ensure_longterm_audit_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists longterm_audit_runs (
            id integer primary key autoincrement,
            period text not null,
            profile text not null,
            source_file text not null unique,
            sample_count integer not null default 0,
            date_start text,
            date_end text,
            avg_ret_10d real,
            avg_ret_40d real,
            avg_ret_80d real,
            win_rate_80d real,
            outperform_rate_80d real,
            created_at text not null
        );

        create table if not exists longterm_audit_samples (
            id integer primary key autoincrement,
            run_id integer not null,
            select_date text not null,
            ts_code text not null,
            name text,
            industry text,
            profile text,
            pool_type text,
            regime text,
            score real,
            pool_rank_score real,
            industry_rs real,
            drawdown_from_high real,
            ret_10d real,
            ret_40d real,
            ret_80d real,
            mfe_80d real,
            mae_80d real,
            benchmark_ret_80d real,
            excess_ret_80d real,
            outperform_80d integer,
            factor_json text,
            created_at text not null,
            unique(run_id, select_date, ts_code)
        );
        """
    )


def build_signal_summary(recent_signals: list[dict], longterm_pool: list[dict]) -> dict:
    short_signals = [item for item in recent_signals if item.get("mode") == "short"]
    live_short = [item for item in short_signals if item.get("source") != "backtest_ic_short"]
    backtest_short = [item for item in short_signals if item.get("source") == "backtest_ic_short"]
    longterm_buckets = split_longterm_pool(longterm_pool)
    latest_signal_date = live_short[0]["trade_date"] if live_short else None
    latest_backtest_date = backtest_short[0]["trade_date"] if backtest_short else None
    return {
        "latest_signal_date": latest_signal_date,
        "latest_backtest_date": latest_backtest_date,
        "short_count": len(short_signals),
        "live_short_count": len(live_short),
        "backtest_short_count": len(backtest_short),
        "longterm_active": len(longterm_pool),
        "longterm_elite": len(longterm_buckets["elite"]),
        "longterm_watch": len(longterm_buckets["watch"]),
        "longterm_other": len(longterm_buckets["other"]),
    }


def build_data_freshness(
    status: dict,
    latest_live_short_run: dict | None,
    signal_summary: dict,
    lag_warning_days: int = 7,
) -> dict:
    """Summarize whether the dashboard data sources are in sync."""
    history_date = str(status.get("latest_trade_date") or "") or None
    live_date = str((latest_live_short_run or {}).get("trade_date") or "") or None
    backtest_date = str(signal_summary.get("latest_backtest_date") or "") or None
    live_lag_days = _days_between(history_date, live_date)
    backtest_lag_days = _days_between(history_date, backtest_date)
    warnings: list[str] = []
    notes: list[str] = []
    if live_lag_days is not None and live_lag_days > 1:
        warnings.append(f"实盘信号落后行情数据 {live_lag_days} 天，请确认是否已运行 main.py。")
    elif live_lag_days is not None:
        notes.append("今日实盘记录已更新；若无推荐，表示规则当天没有留下可入池标的。")
    if backtest_lag_days is not None and backtest_lag_days > lag_warning_days:
        notes.append(f"短线事后复盘样本最新到 {backtest_date}，比行情少 {backtest_lag_days} 天；这是未来收益未满期，不等同于今日实盘数据滞后。")
    if history_date is None:
        warnings.append("历史行情库暂无最新交易日，请先检查数据导入状态。")
    return {
        "history_date": history_date,
        "live_date": live_date,
        "backtest_date": backtest_date,
        "live_lag_days": live_lag_days,
        "backtest_lag_days": backtest_lag_days,
        "notes": notes,
        "warnings": warnings,
        "is_fresh": not warnings,
    }


def build_admission_diagnostics(
    latest_live_short_run: dict | None,
    live_signals: list[dict],
    longterm_runs: list[dict],
    longterm_pool: list[dict],
    backtest_signals: list[dict],
) -> dict:
    """Explain the actionable state using only facts persisted in the signal DB."""
    short_live_count = len(live_signals)
    latest_longterm_date = str((longterm_runs[0] if longterm_runs else {}).get("trade_date") or "")
    latest_longterm_runs = [
        item for item in (longterm_runs or []) if str(item.get("trade_date") or "") == latest_longterm_date
    ]
    longterm_latest_count = sum(int(item.get("signal_count") or 0) for item in latest_longterm_runs)
    longterm_active_count = len(longterm_pool or [])
    items: list[dict] = []

    if latest_live_short_run:
        trade_date = latest_live_short_run.get("trade_date")
        signal_count = int(latest_live_short_run.get("signal_count") or 0)
        text = f"短线 v9 已在 {trade_date} 运行，入池 {signal_count} 只。"
        if signal_count == 0:
            text += " 这代表当天没有通过最终入池规则的短线标的。"
        items.append({"label": "短线实盘", "value": signal_count, "text": text, "tone": "ok" if signal_count else "warn"})
    else:
        items.append({"label": "短线实盘", "value": 0, "text": "尚未找到短线实盘运行记录。", "tone": "bad"})

    if latest_longterm_runs:
        text = f"长线 v18 最近运行日 {latest_longterm_date}，Elite/Watch 合计入池 {longterm_latest_count} 只。"
        if longterm_latest_count == 0:
            text += " 当前长线规则没有留下可观察标的。"
        items.append({"label": "长线扫描", "value": longterm_latest_count, "text": text, "tone": "ok" if longterm_latest_count else "warn"})
    else:
        items.append({"label": "长线扫描", "value": 0, "text": "尚未找到长线扫描运行记录。", "tone": "bad"})

    latest_backtest = (backtest_signals[0] if backtest_signals else {}).get("trade_date")
    if latest_backtest:
        items.append({
            "label": "短线复盘",
            "value": latest_backtest,
            "text": f"历史复盘样本最新到 {latest_backtest}，用于评估策略温度，不替代今日推荐。",
            "tone": "",
        })

    items.append({
        "label": "诊断边界",
        "value": "-",
        "text": "当前数据库保存的是最终入池结果；若要看到逐层过滤原因，需要后续让 main.py 持久化候选漏斗。",
        "tone": "",
    })
    return {
        "short_live_count": short_live_count,
        "longterm_latest_count": longterm_latest_count,
        "longterm_active_count": longterm_active_count,
        "is_empty_day": short_live_count == 0 and longterm_active_count == 0,
        "items": items,
    }


def build_longterm_run_funnel(runs: list[dict], pool: list[dict]) -> dict:
    """Summarize the latest longterm run as an operational admission funnel."""
    latest_date = str((runs[0] if runs else {}).get("trade_date") or "")
    latest_runs = [item for item in (runs or []) if str(item.get("trade_date") or "") == latest_date]
    entry_count = sum(int(item.get("signal_count") or 0) for item in latest_runs)
    active_count = len(pool or [])
    steps = [
        {"label": "长线扫描已运行", "value": len(latest_runs), "hint": latest_date or "暂无运行记录", "tone": "ok" if latest_runs else "bad"},
        {"label": "本次入池候选", "value": entry_count, "hint": "Elite 与 Watch 合计", "tone": "ok" if entry_count else "warn"},
        {"label": "当前仍 active", "value": active_count, "hint": "生命周期池内仍保留的标的", "tone": "ok" if active_count else "warn"},
        {"label": "逐层过滤明细", "value": "未采集", "hint": "需要 main.py 额外写入候选漏斗 telemetry", "tone": ""},
    ]
    return {
        "trade_date": latest_date or None,
        "run_count": len(latest_runs),
        "entry_count": entry_count,
        "active_count": active_count,
        "steps": steps,
    }


def summarize_short_signal_performance(signals: list[dict], limit: int = 50) -> dict:
    """Compute a compact review summary for recent short signals."""
    scoped = list(signals or [])[:limit]
    ret_values = []
    mfe_values = []
    mae_values = []
    for item in scoped:
        perf = item.get("performance") or {}
        ret = _num(perf.get("ret_5d"))
        mfe = _num(perf.get("mfe_pct"))
        mae = _num(perf.get("mae_pct"))
        if ret is not None:
            ret_values.append(ret)
        if mfe is not None:
            mfe_values.append(mfe)
        if mae is not None:
            mae_values.append(mae)
    win_count = sum(1 for value in ret_values if value > 0)
    loss_count = sum(1 for value in ret_values if value < 0)
    avg_mfe = _avg(mfe_values)
    avg_mae = _avg(mae_values)
    return {
        "count": len(scoped),
        "closed_count": len(ret_values),
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": _avg_ratio(win_count, len(ret_values)),
        "avg_ret_5d": _avg(ret_values),
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "opportunity_risk_ratio": _opportunity_risk_ratio(avg_mfe, avg_mae),
        "target_touch_rate": _avg_ratio(sum(1 for value in mfe_values if value >= 5), len(mfe_values)),
    }


def summarize_stock_strategy_history(stock_signals: list[dict]) -> dict:
    """Summarize how a stock has interacted with stored strategy signals."""
    signals = list(stock_signals or [])
    short_signals = [item for item in signals if item.get("mode") == "short"]
    longterm_signals = [item for item in signals if item.get("mode") == "longterm"]
    ret_values = []
    mfe_values = []
    for item in signals:
        perf = item.get("performance") or {}
        ret = _num(perf.get("ret_5d") if item.get("mode") == "short" else perf.get("ret_80d"))
        mfe = _num(perf.get("mfe_pct") or perf.get("mfe_80d"))
        if ret is not None:
            ret_values.append(ret)
        if mfe is not None:
            mfe_values.append(mfe)
    latest = signals[0] if signals else {}
    return {
        "total": len(signals),
        "short_count": len(short_signals),
        "longterm_count": len(longterm_signals),
        "profitable_count": sum(1 for value in ret_values if value > 0),
        "win_rate": _avg_ratio(sum(1 for value in ret_values if value > 0), len(ret_values)),
        "best_mfe": max(mfe_values) if mfe_values else None,
        "latest_date": latest.get("trade_date"),
        "latest_profile": latest.get("profile"),
        "latest_outcome": latest.get("outcome_label"),
    }


def build_dashboard_decision(
    latest_live_short_run: dict | None,
    live_signals: list[dict],
    longterm_pool: list[dict],
    backtest_signals: list[dict],
) -> dict:
    """Build a user-facing daily action layer from stored signal facts."""
    live_count = len(live_signals)
    longterm_buckets = split_longterm_pool(longterm_pool)
    elite_count = len(longterm_buckets["elite"])
    watch_count = len(longterm_buckets["watch"])

    reasons: list[str] = []
    if live_count:
        reasons.append(f"短线实盘出现 {live_count} 个入池信号")
    elif latest_live_short_run:
        reasons.append("短线 v9 未产生入池信号")
    else:
        reasons.append("暂无短线实盘运行记录")

    if elite_count:
        reasons.append(f"长线 Elite 池有 {elite_count} 个标的")
    elif watch_count:
        reasons.append(f"长线 Watch 池有 {watch_count} 个观察标的")
    else:
        reasons.append("长线严格池当前为空")

    if live_count or elite_count:
        level = "有可关注信号"
        stance = "只看入池标的，仍需按你的人工交易纪律确认买卖点。"
        tone = "ok"
    elif watch_count:
        level = "只观察不追买"
        stance = "长线有观察标的，但没有达到强提醒层级。"
        tone = "watch"
    else:
        level = "今日不宜开新仓"
        stance = "强信号为空时，系统的价值是提醒你别硬做；可以把精力放到自选股体检和历史复盘。"
        tone = "caution"

    next_actions = [
        {"label": "批量体检自选股", "href": "/stock/000001", "hint": "先用单股体检查已有关注票的风险和历史信号。"},
        {"label": "查看短线复盘", "href": "/signals", "hint": "复盘近期 v9 信号，找出更适合人工跟踪的形态。"},
        {"label": "查看长线池验证", "href": "/longterm", "hint": "确认长线规则最近为什么没有 active 标的。"},
    ]
    if backtest_signals:
        latest_backtest = backtest_signals[0].get("trade_date")
        reasons.append(f"历史复盘样本最新到 {latest_backtest}")

    return {
        "level": level,
        "tone": tone,
        "stance": stance,
        "reasons": reasons,
        "next_actions": next_actions,
    }


def _row_to_signal(row: sqlite3.Row) -> dict:
    item = dict(row)
    raw = item.pop("factor_json", None)
    item["factors"] = _json_dict(raw)
    item["display_name"] = item.get("name") or item.get("ts_code")
    item["display_code"] = item.get("ts_code")
    item["basis_text"] = _basis_text(item)
    item["basis_summary"] = _basis_summary(item)
    item["performance"] = _performance(item["factors"])
    item["final_return_text"] = _final_return_text(item["performance"])
    item["final_return_tone"] = _final_return_tone(item["performance"])
    item["mfe_text"] = _short_path_text(item["performance"].get("mfe_pct"), pending="待观察")
    item["mae_text"] = _short_path_text(item["performance"].get("mae_pct"), pending="待观察")
    item["process_text"] = _process_text(item["performance"])
    item["performance_text"] = _performance_text(item["performance"])
    item["quality_label"] = _quality_label(item)
    item["outcome_label"] = _outcome_label(item)
    item["process_label"] = _process_label(item)
    item["process_tone"] = _process_tone(item["process_label"])
    item["mae_risk_label"] = _mae_risk_label(item)
    item["mae_risk_tone"] = _mae_risk_tone(item["mae_risk_label"])
    item["result_tag"] = _result_tag(item)
    item["source_label"] = "历史回测" if item.get("source") == "backtest_ic_short" else "实盘记录"
    return item


def _enrich_stock_identity(signals: list[dict], history_db: str | Path | None) -> list[dict]:
    if not signals or not history_db or not Path(history_db).exists():
        return signals
    codes = sorted({item.get("ts_code") for item in signals if item.get("ts_code")})
    if not codes:
        return signals
    placeholders = ",".join(["?"] * len(codes))
    conn = sqlite3.connect(history_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"select ts_code, name, industry from stock_basic where ts_code in ({placeholders})",
            codes,
        ).fetchall()
        mapping = {row["ts_code"]: dict(row) for row in rows}
    finally:
        conn.close()
    for item in signals:
        info = mapping.get(item.get("ts_code"), {})
        if not item.get("name"):
            item["name"] = info.get("name", "")
        if not item.get("industry"):
            item["industry"] = info.get("industry", "")
        item["display_name"] = item.get("name") or item.get("ts_code")
        item["display_code"] = item.get("ts_code")
    return signals


def _filter_signals_by_query(signals: list[dict], query: str) -> list[dict]:
    keyword = str(query or "").strip().lower()
    if not keyword:
        return signals
    return [
        item
        for item in signals
        if keyword in str(item.get("ts_code") or "").lower()
        or keyword in str(item.get("display_code") or "").lower()
        or keyword in str(item.get("name") or "").lower()
        or keyword in str(item.get("display_name") or "").lower()
    ]


def _basis_text(item: dict) -> str:
    factors = item.get("factors") or {}
    parts = []
    score = item.get("score")
    if score is not None:
        parts.append(f"v9分 {float(score):.1f}")
    original = factors.get("original_score")
    if original is not None:
        parts.append(f"原始分 {float(original):.1f}")
    for key, label in [
        ("factor_inflow", "资金"),
        ("factor_sector", "板块"),
        ("factor_pattern", "形态"),
    ]:
        value = factors.get(key)
        if value is not None:
            parts.append(f"{label}{float(value):.0f}")
    return " / ".join(parts) if parts else (item.get("reason") or "-")


def _basis_summary(item: dict) -> str:
    score = _num(item.get("score"))
    if score is not None:
        return f"v9分 {score:.1f}"
    return "v9分 -"


def _performance(factors: dict) -> dict:
    keys = ["ret_5d", "ret_10d", "ret_20d", "mfe_pct", "mae_pct", "window_end_pct"]
    return {key: _num(factors.get(key)) for key in keys}


def _final_return_text(perf: dict) -> str:
    for key, label in [
        ("ret_5d", "5日"),
        ("ret_10d", "10日"),
        ("ret_20d", "20日"),
        ("window_end_pct", "窗口期末"),
    ]:
        value = perf.get(key)
        if value is not None:
            return f"{label}{value:+.2f}%"
    return "待满5日"


def _final_return_tone(perf: dict) -> str:
    for key in ["ret_5d", "ret_10d", "ret_20d", "window_end_pct"]:
        value = perf.get(key)
        if value is not None:
            if value > 0:
                return "market-up"
            if value < 0:
                return "market-down"
            return "muted"
    return "muted"


def _short_path_text(value, pending: str = "-") -> str:
    number = _num(value)
    if number is None:
        return pending
    return f"{number:+.2f}%"


def _process_text(perf: dict) -> str:
    parts = []
    if perf.get("mfe_pct") is not None:
        parts.append(f"MFE{perf['mfe_pct']:+.2f}%")
    if perf.get("mae_pct") is not None:
        parts.append(f"MAE{perf['mae_pct']:+.2f}%")
    return " / ".join(parts) if parts else "-"


def _performance_text(perf: dict) -> str:
    parts = []
    for key, label in [("ret_5d", "5日"), ("ret_10d", "10日"), ("ret_20d", "20日")]:
        value = perf.get(key)
        if value is not None:
            parts.append(f"{label}{value:+.2f}%")
    if perf.get("mfe_pct") is not None:
        parts.append(f"MFE{perf['mfe_pct']:+.2f}%")
    if perf.get("mae_pct") is not None:
        parts.append(f"MAE{perf['mae_pct']:+.2f}%")
    return " / ".join(parts) if parts else "-"


def _quality_label(item: dict) -> str:
    score = _num(item.get("score")) or 0
    if score < 30:
        return "弱信号"
    if score < 45:
        return "观察信号"
    return "有效信号"


def _outcome_label(item: dict) -> str:
    perf = item.get("performance") or {}
    ret5 = perf.get("ret_5d")
    window_end = perf.get("window_end_pct")
    primary = ret5 if ret5 is not None else window_end
    if primary is None:
        return "窗口未满"
    if primary >= 3:
        return "短线盈利"
    if primary <= -5:
        return "短线亏损"
    return "震荡"


def _process_label(item: dict) -> str:
    perf = item.get("performance") or {}
    ret5 = perf.get("ret_5d")
    mfe = perf.get("mfe_pct")
    mae = perf.get("mae_pct")
    if mfe is not None and mfe >= 8 and ret5 is not None and ret5 < 0:
        return "曾冲高回落"
    if mfe is not None and mfe >= 8:
        return "盘中给过机会"
    if mae is not None and mae <= -8:
        return "回撤偏大"
    if ret5 is None and mfe is None and mae is None:
        return "待观察"
    return "波动正常"


def _process_tone(label: str) -> str:
    if label == "盘中给过机会":
        return "ok"
    if label == "曾冲高回落":
        return "warn"
    if label == "回撤偏大":
        return "risk-high"
    return ""


def _mae_risk_label(item: dict) -> str:
    mae = (item.get("performance") or {}).get("mae_pct")
    if mae is None:
        return "未评估"
    if mae <= -10:
        return "风险偏高"
    if mae <= -7:
        return "需警惕"
    return "可接受"


def _mae_risk_tone(label: str) -> str:
    return {"风险偏高": "risk-high", "需警惕": "risk-watch", "可接受": "risk-ok"}.get(label, "")


def _result_tag(item: dict) -> str:
    return f"{item.get('quality_label')}/{item.get('outcome_label')}"


def _json_dict(raw) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _longterm_reason_text(item: dict) -> str:
    factors = item.get("factors") or {}
    raw = str(factors.get("v16_lifecycle_reasons") or factors.get("reason") or "").strip()
    if not raw:
        return str(item.get("pool_type") or "-")
    labels = {
        "elastic_midcap_quality_industry_pullback": "中市值质量趋势 + 行业同步 + 健康回调",
        "market_sync_quality": "市场同步 + 质量趋势",
        "quality_trend": "质量趋势",
        "pullback": "健康回调",
        "industry": "行业同步",
    }
    return labels.get(raw, raw.replace("_", " "))


def _score_delta(old_score, new_score) -> str:
    old_value = _num(old_score)
    new_value = _num(new_score)
    if old_value is None and new_value is None:
        return "-"
    if old_value is None:
        return f"{new_value:.1f}"
    if new_value is None:
        return f"{old_value:.1f} → -"
    return f"{old_value:.1f} → {new_value:.1f}"


def _state_path_label(event_type, old_state, new_state) -> str:
    event = str(event_type or "")
    if event == "NEW":
        old = "移出" if old_state == "removed" else "未入池"
        return f"{old} → 入池"
    if event == "REMOVED":
        return "入池 → 移出"
    if event == "UPGRADED":
        return "观察 → 强提醒"
    if event == "DOWNGRADED":
        return "强提醒 → 观察"
    return f"{_state_label(old_state)} → {_state_label(new_state)}"


def _state_label(state) -> str:
    labels = {
        None: "未入池",
        "active": "入池",
        "removed": "移出",
        "watch": "观察",
        "elite": "强提醒",
        "other": "其他",
    }
    return labels.get(state, str(state or "-"))


def _event_tone(event_type) -> str:
    return {
        "NEW": "ok",
        "UPGRADED": "ok",
        "DOWNGRADED": "warn",
        "REMOVED": "bad",
    }.get(str(event_type or ""), "")


def _pct_text(value) -> str:
    number = _num(value)
    if number is None:
        return "-"
    return f"{number:+.2f}%"


def _maturity_pct_text(value) -> str:
    number = _num(value)
    if number is None:
        return "未满"
    return f"{number:+.2f}%"


def _excess_text(value) -> str:
    number = _num(value)
    if number is None:
        return "未满"
    return f"{number:+.2f}%"


def _progress_text(elapsed_days, target_days: int) -> str:
    elapsed = int(elapsed_days or 0)
    if elapsed < target_days:
        return f"t+{elapsed}/{target_days}"
    return "待回填"


def _pct_tone(value) -> str:
    number = _num(value)
    if number is None or number == 0:
        return "muted"
    return "market-up" if number > 0 else "market-down"


def _mae_pain_tone(value) -> str:
    number = _num(value)
    if number is None:
        return "muted"
    if number <= -15:
        return "risk-high"
    if number <= -8:
        return "risk-watch"
    return "risk-ok"


def _ratio_text(value) -> str:
    number = _num(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def _parse_date(value) -> datetime | None:
    text = str(value or "").replace("-", "")[:8]
    if not (len(text) == 8 and text.isdigit()):
        return None
    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None


def _days_between(later, earlier) -> int | None:
    later_date = _parse_date(later)
    earlier_date = _parse_date(earlier)
    if later_date is None or earlier_date is None:
        return None
    return max((later_date - earlier_date).days, 0)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _avg_ratio(count: int, total: int) -> float | None:
    if not total:
        return None
    return count / total * 100


def _opportunity_risk_ratio(avg_mfe: float | None, avg_mae: float | None) -> float | None:
    if avg_mfe is None or avg_mae is None or avg_mae == 0:
        return None
    return avg_mfe / abs(avg_mae)


def _num(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
