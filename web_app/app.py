#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FastAPI entrypoint for the local read-only stock dashboard."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from history_store import DEFAULT_HISTORY_DB_PATH
from market_radar.store import get_latest_market_radar_snapshot, save_market_radar_snapshot
from signal_store import DEFAULT_DB_PATH as DEFAULT_SIGNAL_DB_PATH
from web_app.services.history_service import get_db_status, get_stock_detail
from web_app.services.explanation_service import get_daily_brief, get_or_create_signal_explanation
from web_app.services.sector_service import (
    build_concept_news_radar,
    build_market_radar_decision,
    build_sector_radar,
    build_strategy_overlap,
)
from web_app.services.update_service import decorate_update_status_with_freshness, read_update_status, start_web_update
from web_app.services.ui_service import (
    display_source_label,
    format_date_input,
    format_optional,
    normalize_date_input,
    paginate_items,
)
from web_app.services.dragon_service import build_dragon_observation
from web_app.services.signal_service import (
    build_admission_diagnostics,
    build_dashboard_decision,
    build_data_freshness,
    build_default_signal_start,
    build_longterm_pool_status,
    build_longterm_run_funnel,
    build_observation_candidate_card,
    build_signal_summary,
    build_strong_recommendation_card,
    get_active_longterm_pool,
    get_longterm_audit_samples,
    get_longterm_audit_summary,
    get_longterm_events,
    get_longterm_runs,
    get_recent_signals,
    get_short_live_push_history,
    get_signal_runs,
    get_stock_signals,
    summarize_short_signal_performance,
    summarize_longterm_audit_sample_filter,
    summarize_stock_strategy_history,
    split_longterm_pool,
)


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="A股策略研究看板", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fmt_date(value):
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text or "NA"


templates.env.filters["fmt_date"] = _fmt_date
templates.env.filters["fmt_optional"] = format_optional
templates.env.filters["fmt_date_input"] = format_date_input
templates.env.filters["display_source_label"] = display_source_label

_SECTOR_PAGE_CACHE_TTL_SECONDS = 120
_sector_page_cache: dict[tuple, tuple[float, dict]] = {}


def _wants_json(request: Request) -> bool:
    return "application/json" in str(request.headers.get("accept") or "").lower()


def _update_start_response(request: Request, status: dict | None, redirect_url: str):
    if _wants_json(request):
        return JSONResponse(status or {"state": "running"})
    return RedirectResponse(url=redirect_url, status_code=303)


@app.get("/")
def dashboard(request: Request):
    status = get_db_status(DEFAULT_HISTORY_DB_PATH)
    update_status = read_update_status()
    live_signals = get_recent_signals(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=10,
        source="live",
        mode="short",
    )
    live_short_runs = get_signal_runs(
        DEFAULT_SIGNAL_DB_PATH,
        mode="short",
        source="live",
        limit=3,
    )
    latest_live_short_run = live_short_runs[0] if live_short_runs else None
    if latest_live_short_run and int(latest_live_short_run.get("signal_count") or 0) == 0:
        live_signals = []
    observe_signals = get_recent_signals(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=10,
        source="live_observe",
        profile="short_live_observe_best_balance",
        mode="short",
    )
    observe_runs = get_signal_runs(
        DEFAULT_SIGNAL_DB_PATH,
        mode="short",
        source="live_observe",
        profile="short_live_observe_best_balance",
        limit=3,
    )
    latest_observe_run = observe_runs[0] if observe_runs else None
    if latest_observe_run and int(latest_observe_run.get("signal_count") or 0) == 0:
        observe_signals = []
    backtest_signals = get_recent_signals(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=8,
        source="backtest_ic_short",
        profile="short_v9_final",
        mode="short",
    )
    longterm_pool = get_active_longterm_pool(DEFAULT_SIGNAL_DB_PATH)
    longterm_runs = get_longterm_runs(DEFAULT_SIGNAL_DB_PATH, limit=8)
    signal_summary = build_signal_summary(live_signals + backtest_signals, longterm_pool)
    longterm_buckets = split_longterm_pool(longterm_pool)
    longterm_pool_status = build_longterm_pool_status(longterm_pool, longterm_runs)
    decision = build_dashboard_decision(latest_live_short_run, live_signals, longterm_pool, backtest_signals)
    strong_recommendation = build_strong_recommendation_card(latest_live_short_run, live_signals)
    observation_candidates = build_observation_candidate_card(latest_observe_run, observe_signals)
    admission_diagnostics = build_admission_diagnostics(
        latest_live_short_run,
        live_signals,
        longterm_runs,
        longterm_pool,
        backtest_signals,
    )
    freshness = build_data_freshness(status, latest_live_short_run, signal_summary)
    update_status = decorate_update_status_with_freshness(update_status, freshness)
    short_stats = summarize_short_signal_performance(backtest_signals)
    brief_date = (
        latest_live_short_run.get("trade_date")
        if latest_live_short_run
        else status.get("latest_trade_date")
    )
    daily_brief = get_daily_brief(
        brief_date,
        signal_db=DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
    ) if brief_date else None
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "status": status,
            "live_signals": live_signals,
            "latest_live_short_run": latest_live_short_run,
            "backtest_signals": backtest_signals,
            "longterm_pool": longterm_pool,
            "signal_summary": signal_summary,
            "decision": decision,
            "strong_recommendation": strong_recommendation,
            "observation_candidates": observation_candidates,
            "admission_diagnostics": admission_diagnostics,
            "freshness": freshness,
            "short_stats": short_stats,
            "daily_brief": daily_brief,
            "longterm_buckets": longterm_buckets,
            "longterm_pool_status": longterm_pool_status,
            "update_status": update_status,
            "active_nav": "dashboard",
        },
    )


@app.post("/update/run")
def run_update(request: Request, mode: str = "daily"):
    status = start_web_update(mode=mode)
    return _update_start_response(request, status, "/")


@app.get("/update/status")
def update_status():
    return _read_decorated_update_status()


def _read_decorated_update_status() -> dict:
    status = get_db_status(DEFAULT_HISTORY_DB_PATH)
    update_status = read_update_status()
    latest_runs = get_signal_runs(
        DEFAULT_SIGNAL_DB_PATH,
        mode="short",
        source="live",
        limit=1,
    )
    latest_live_short_run = latest_runs[0] if latest_runs else None
    backtest_signals = get_recent_signals(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=1,
        source="backtest_ic_short",
        profile="short_v9_final",
        mode="short",
    )
    longterm_pool = get_active_longterm_pool(DEFAULT_SIGNAL_DB_PATH)
    signal_summary = build_signal_summary(backtest_signals, longterm_pool)
    freshness = build_data_freshness(status, latest_live_short_run, signal_summary)
    return decorate_update_status_with_freshness(update_status, freshness)


@app.get("/db")
def db_status(request: Request):
    status = get_db_status(DEFAULT_HISTORY_DB_PATH)
    return templates.TemplateResponse(
        request,
        "db_status.html",
        {
            "request": request,
            "status": status,
            "update_status": read_update_status(),
            "active_nav": "db",
        },
    )


@app.get("/sectors")
def sectors(request: Request, end: str = ""):
    payload = _get_sector_page_payload(end)
    return templates.TemplateResponse(
        request,
        "sectors.html",
        {
            "request": request,
            **payload,
            "filters": {"end": end},
            "update_status": read_update_status(),
            "active_nav": "sectors",
        },
    )


def _get_sector_page_payload(end: str = "") -> dict:
    key = _sector_page_cache_key(end)
    cached = _sector_page_cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _SECTOR_PAGE_CACHE_TTL_SECONDS:
        return cached[1]

    payload = _build_sector_page_payload(end)
    _sector_page_cache[key] = (now, payload)
    return payload


def _sector_page_cache_key(end: str = "") -> tuple:
    return (
        str(end or "latest"),
        id(build_sector_radar),
        id(build_concept_news_radar),
        id(build_market_radar_decision),
        id(build_strategy_overlap),
    )


def _build_sector_page_payload(end: str = "") -> dict:
    radar = build_sector_radar(DEFAULT_HISTORY_DB_PATH, end_date=end or None)
    concept_news = build_concept_news_radar(DEFAULT_SIGNAL_DB_PATH, today=end or None)
    decision = build_market_radar_decision(radar, concept_news)
    strategy_overlap = build_strategy_overlap(DEFAULT_SIGNAL_DB_PATH, radar, concept_news)
    latest_radar_snapshot = None
    brief = decision.get("research_brief") if isinstance(decision, dict) else None
    if isinstance(brief, dict) and brief:
        radar_date = str(radar.get("end_date") or end or "").replace("-", "")[:8]
        try:
            save_market_radar_snapshot(DEFAULT_SIGNAL_DB_PATH, radar_date, brief, decision)
            latest_radar_snapshot = get_latest_market_radar_snapshot(DEFAULT_SIGNAL_DB_PATH)
        except Exception:
            latest_radar_snapshot = None
    return {
        "radar": radar,
        "concept_news": concept_news,
        "decision": decision,
        "strategy_overlap": strategy_overlap,
        "latest_radar_snapshot": latest_radar_snapshot,
    }


def refresh_market_radar_snapshot_for_page(end: str = "") -> int | None:
    radar = build_sector_radar(DEFAULT_HISTORY_DB_PATH, end_date=end or None)
    concept_news = build_concept_news_radar(DEFAULT_SIGNAL_DB_PATH, today=end or None)
    decision = build_market_radar_decision(radar, concept_news)
    brief = decision.get("research_brief") if isinstance(decision, dict) else None
    if not isinstance(brief, dict) or not brief:
        return None
    radar_date = str(radar.get("end_date") or end or "").replace("-", "")[:8]
    return save_market_radar_snapshot(DEFAULT_SIGNAL_DB_PATH, radar_date, brief, decision)


@app.post("/sectors/update")
def update_market_radar(request: Request, end: str = ""):
    _sector_page_cache.clear()
    status = start_web_update(mode="radar")
    redirect_url = "/sectors"
    if end:
        redirect_url = f"{redirect_url}?end={end}"
    return _update_start_response(request, status, redirect_url)


@app.get("/stock")
def stock_redirect(code: str = ""):
    if not code:
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url=f"/stock/{code}", status_code=303)


@app.get("/stock/{code}")
def stock_detail(request: Request, code: str):
    detail = get_stock_detail(code, history_db=DEFAULT_HISTORY_DB_PATH, signal_db=DEFAULT_SIGNAL_DB_PATH)
    stock_signals = get_stock_signals(
        detail["stock"]["ts_code"],
        signal_db=DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=20,
    )
    strategy_summary = summarize_stock_strategy_history(stock_signals)
    return templates.TemplateResponse(
        request,
        "stock_detail.html",
        {
            "request": request,
            "detail": detail,
            "stock_signals": stock_signals,
            "strategy_summary": strategy_summary,
            "active_nav": "stock",
        },
    )


@app.get("/signals")
def signals(
    request: Request,
    q: str = "",
    start: str = "",
    end: str = "",
    industry: str = "",
    page: str = "1",
):
    default_window_days = 100
    review_sources = ["backtest_ic_short", "live"]
    review_profiles = ["short_v9_final", "profile_v9_sector_quality_guard"]
    latest_runs = get_signal_runs(
        DEFAULT_SIGNAL_DB_PATH,
        source=review_sources,
        mode="short",
        limit=1,
    )
    latest_signal_run = latest_runs[0] if latest_runs else None
    live_short_runs = get_signal_runs(
        DEFAULT_SIGNAL_DB_PATH,
        source="live",
        mode="short",
        limit=1,
    )
    latest_live_short_run = live_short_runs[0] if live_short_runs else None
    live_signals = get_recent_signals(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=10,
        source="live",
        mode="short",
    )
    observe_signals = get_recent_signals(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=10,
        source="live_observe",
        profile="short_live_observe_best_balance",
        mode="short",
    )
    observe_runs = get_signal_runs(
        DEFAULT_SIGNAL_DB_PATH,
        source="live_observe",
        profile="short_live_observe_best_balance",
        mode="short",
        limit=1,
    )
    latest_observe_run = observe_runs[0] if observe_runs else None
    if latest_observe_run and int(latest_observe_run.get("signal_count") or 0) == 0:
        observe_signals = []
    strong_recommendation = build_strong_recommendation_card(latest_live_short_run, live_signals)
    observation_candidates = build_observation_candidate_card(latest_observe_run, observe_signals)
    live_push_history = get_short_live_push_history(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=30,
    )
    latest_signal_date = latest_signal_run["trade_date"] if latest_signal_run else None
    normalized_start = normalize_date_input(start)
    normalized_end = normalize_date_input(end)
    effective_start = normalized_start or build_default_signal_start(latest_signal_date, days=default_window_days)
    all_signals = get_recent_signals(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=300,
        source=review_sources,
        profile=review_profiles,
        mode="short",
        query=q or None,
        start=effective_start or None,
        end=normalized_end or None,
        industry=industry or None,
    )
    short_stats = summarize_short_signal_performance(all_signals, limit=300)
    recent_signals, page_info = paginate_items(all_signals, page, page_size=50)
    return templates.TemplateResponse(
        request,
        "signals.html",
        {
            "request": request,
            "signals": recent_signals,
            "all_signals": all_signals,
            "page_info": page_info,
            "short_stats": short_stats,
            "latest_signal_run": latest_signal_run,
            "strong_recommendation": strong_recommendation,
            "observation_candidates": observation_candidates,
            "live_push_history": live_push_history,
            "update_status": read_update_status(),
            "filters": {
                "q": q,
                "start": normalized_start,
                "end": normalized_end,
                "industry": industry,
                "effective_start": effective_start,
                "default_window_days": default_window_days,
                "is_default_window": not any([start, end, q, industry]),
            },
            "active_nav": "signals",
        },
    )


@app.get("/dragon")
def dragon_leaders(request: Request, end: str = ""):
    observation = build_dragon_observation(end_date=end or None)
    return templates.TemplateResponse(
        request,
        "dragon_leaders.html",
        {
            "request": request,
            "observation": observation,
            "filters": {"end": end},
            "update_status": read_update_status(),
            "active_nav": "dragon",
        },
    )


@app.post("/dragon/update")
def update_dragon_leaders(request: Request):
    status = start_web_update(mode="dragon")
    return _update_start_response(request, status, "/dragon")


@app.get("/explain/signal/{trade_date}/{ts_code}")
def signal_explanation(request: Request, trade_date: str, ts_code: str, refresh: bool = False):
    explanation = get_or_create_signal_explanation(
        trade_date,
        ts_code,
        signal_db=DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        force=refresh,
    )
    return templates.TemplateResponse(
        request,
        "signal_explanation.html",
        {"request": request, "explanation": explanation, "active_nav": "signals"},
    )


@app.get("/longterm")
def longterm_pool(request: Request, start: str = "", end: str = "", page: str = "1"):
    pool = get_active_longterm_pool(DEFAULT_SIGNAL_DB_PATH)
    buckets = split_longterm_pool(pool)
    runs = get_longterm_runs(DEFAULT_SIGNAL_DB_PATH, limit=12)
    events = get_longterm_events(DEFAULT_SIGNAL_DB_PATH, history_db=DEFAULT_HISTORY_DB_PATH, limit=30)
    audit_summary = get_longterm_audit_summary(DEFAULT_SIGNAL_DB_PATH, limit=12)
    normalized_start = normalize_date_input(start)
    normalized_end = normalize_date_input(end)
    sample_limit = 1000 if (normalized_start or normalized_end) else 100
    all_audit_samples = get_longterm_audit_samples(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=DEFAULT_HISTORY_DB_PATH,
        limit=sample_limit,
        start=normalized_start or None,
        end=normalized_end or None,
    )
    sample_filters = {"start": normalized_start, "end": normalized_end, "sample_limit": sample_limit}
    sample_filter_summary = summarize_longterm_audit_sample_filter(all_audit_samples, sample_filters)
    audit_samples, page_info = paginate_items(all_audit_samples, page, page_size=50)
    run_funnel = build_longterm_run_funnel(runs, pool)
    pool_status = build_longterm_pool_status(pool, runs)
    return templates.TemplateResponse(
        request,
        "longterm_pool.html",
        {
            "request": request,
            "pool": pool,
            "buckets": buckets,
            "runs": runs,
            "events": events,
            "audit_summary": audit_summary,
            "audit_samples": audit_samples,
            "all_audit_samples": all_audit_samples,
            "page_info": page_info,
            "run_funnel": run_funnel,
            "pool_status": pool_status,
            "filters": sample_filters,
            "sample_filter_summary": sample_filter_summary,
            "update_status": read_update_status(),
            "active_nav": "longterm",
        },
    )
