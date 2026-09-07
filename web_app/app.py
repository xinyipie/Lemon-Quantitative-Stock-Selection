#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FastAPI entrypoint for the local read-only stock dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import pickle
import time
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock, Timeout as FileLockTimeout

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from history_store import DEFAULT_HISTORY_DB_PATH
from market_radar.store import get_latest_market_radar_snapshot, save_market_radar_snapshot
from signal_store import DEFAULT_DB_PATH as DEFAULT_SIGNAL_DB_PATH
from web_app.services.history_service import get_db_status, get_stock_detail
from web_app.services.explanation_service import (
    ExplanationCacheBusyError,
    get_daily_brief,
    get_or_create_signal_explanation,
    get_signal_explanation,
)
from web_app.services.sector_service import (
    build_concept_news_radar,
    build_market_radar_decision,
    build_sector_radar,
    build_strategy_overlap,
)
from web_app.services.update_service import decorate_update_status_with_freshness, read_update_status, start_web_update
from web_app.services.report_service import build_report_archive_context, build_report_detail_context
from web_app.services.ui_service import (
    build_page_time_context,
    display_source_label,
    format_date_input,
    format_optional,
    normalize_date_input,
    paginate_items,
    validate_date_range,
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
    summarize_short_strategy_cards,
    summarize_longterm_audit_sample_filter,
    summarize_stock_strategy_history,
    split_longterm_pool,
)


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="A股策略研究看板", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _app_path(request: Request, path: str) -> str:
    """拼接 ASGI 挂载前缀，使直连和网关下的链接都指向当前应用。"""
    root_path = str(request.scope.get("root_path") or "").rstrip("/")
    suffix = "/" + str(path or "").lstrip("/")
    return f"{root_path}{suffix}" or "/"


templates.env.globals["app_path"] = _app_path


def _app_url_for(request: Request, name: str, **path_params):
    """从子应用解析路由名称，再加挂载前缀，避免被网关同名路由遮蔽。"""
    path = app.url_path_for(name, **path_params)
    return request.url.replace(path=_app_path(request, str(path)), query="")


templates.env.globals["app_url_for"] = _app_url_for


def _static_asset_version(path: str) -> str:
    """按静态文件内容生成版本号，发布后自动绕过旧浏览器缓存。"""
    asset = (BASE_DIR / "static" / Path(path).name).resolve()
    return hashlib.sha256(asset.read_bytes()).hexdigest()[:12]


templates.env.globals["static_asset_version"] = _static_asset_version


def _request_has_web_token(request: Request, token: str) -> bool:
    """同时接受 API 常用的 Bearer 和浏览器原生支持的 Basic。"""
    scheme, _, credential = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer":
        return hmac.compare_digest(credential.strip().encode("utf-8"), token.encode("utf-8"))
    if scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(credential.strip(), validate=True)
    except ValueError:
        return False
    username, separator, password = decoded.partition(b":")
    supplied = password if separator and password else username
    return hmac.compare_digest(supplied, token.encode("utf-8"))


def _is_loopback_client(request: Request) -> bool:
    host = str(request.client.host if request.client else "")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _is_same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    parsed = urlsplit(origin)
    return parsed.scheme == request.url.scheme and parsed.netloc.lower() == request.url.netloc.lower()


@app.middleware("http")
async def enforce_web_access(request: Request, call_next):
    """显式令牌保护全部请求；默认只读，开发环境可单独允许本机写入。"""
    token = os.environ.get("STOCK_WEB_TOKEN", "").strip()
    if token and not _request_has_web_token(request, token):
        return JSONResponse(
            {"detail": "需要登录后才能访问当前服务"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="stock-dashboard"'},
        )
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        allow_local_write = os.environ.get("STOCK_WEB_ALLOW_LOCAL_WRITE", "").strip() == "1"
        if not token and (not allow_local_write or not _is_loopback_client(request)):
            return JSONResponse({"detail": "当前服务为只读模式，未启用写操作"}, status_code=403)
        if not _is_same_origin(request):
            return JSONResponse({"detail": "拒绝来自其他站点的写操作"}, status_code=403)
    return await call_next(request)


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
_SECTOR_PAGE_DISK_CACHE = Path("data") / "web_sector_page_cache.pkl"
_SECTOR_PAGE_CACHE_VERSION = 6
_SECTOR_BUILDERS = (
    build_sector_radar,
    build_concept_news_radar,
    build_market_radar_decision,
    build_strategy_overlap,
)


def _wants_json(request: Request) -> bool:
    return "application/json" in str(request.headers.get("accept") or "").lower()


def _update_start_response(request: Request, status: dict | None, redirect_url: str):
    if _wants_json(request):
        return JSONResponse(status or {"state": "running"})
    return RedirectResponse(url=redirect_url, status_code=303)


@app.get("/reports")
def report_archive(request: Request, q: str = "", start: str = "", end: str = ""):
    date_error = validate_date_range(start, end)
    if date_error:
        context = {
            "items": [],
            "query": q,
            "start": normalize_date_input(start),
            "end": normalize_date_input(end),
        }
    else:
        context = build_report_archive_context(DEFAULT_SIGNAL_DB_PATH, q, start, end)
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"request": request, "active_nav": "reports", "date_error": date_error, **context},
    )


@app.get("/reports/{report_date}")
def report_detail(request: Request, report_date: str):
    context = build_report_detail_context(DEFAULT_SIGNAL_DB_PATH, report_date)
    if context is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return templates.TemplateResponse(
        request,
        "report_detail.html",
        {"request": request, "active_nav": "reports", **context},
    )


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
    backtest_runs = get_signal_runs(
        DEFAULT_SIGNAL_DB_PATH,
        mode="short",
        source="backtest_ic_short",
        profile="short_v9_final",
        limit=1,
    )
    latest_backtest_run = backtest_runs[0] if backtest_runs else None
    longterm_pool = get_active_longterm_pool(DEFAULT_SIGNAL_DB_PATH)
    longterm_runs = get_longterm_runs(DEFAULT_SIGNAL_DB_PATH, limit=8)
    signal_summary = build_signal_summary(
        live_signals + backtest_signals,
        longterm_pool,
        latest_backtest_run=latest_backtest_run,
    )
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
    backtest_runs = get_signal_runs(
        DEFAULT_SIGNAL_DB_PATH,
        mode="short",
        source="backtest_ic_short",
        profile="short_v9_final",
        limit=1,
    )
    latest_backtest_run = backtest_runs[0] if backtest_runs else None
    longterm_pool = get_active_longterm_pool(DEFAULT_SIGNAL_DB_PATH)
    signal_summary = build_signal_summary(
        backtest_signals,
        longterm_pool,
        latest_backtest_run=latest_backtest_run,
    )
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
            "update_status": _read_decorated_update_status(),
            "active_nav": "db",
        },
    )


@app.get("/sectors")
def sectors(request: Request, end: str = ""):
    normalized_end = normalize_date_input(end)
    payload = _get_sector_page_payload(
        normalized_end,
        use_persisted_cache=request.url.hostname != "testserver",
    )
    return templates.TemplateResponse(
        request,
        "sectors.html",
        {
            "request": request,
            **payload,
            "filters": {"end": normalized_end},
            "update_status": read_update_status(),
            "active_nav": "sectors",
        },
    )


def _get_sector_page_payload(end: str = "", use_persisted_cache: bool = True) -> dict:
    key = _sector_page_cache_key(end)
    cached = _sector_page_cache.get(key)
    now = time.monotonic()
    if (
        cached
        and now - cached[0] < _SECTOR_PAGE_CACHE_TTL_SECONDS
        and _is_current_sector_page_payload(cached[1])
    ):
        return cached[1]

    disk_key = _sector_page_disk_cache_key(end)
    if use_persisted_cache and _using_default_sector_builders():
        persisted = load_sector_page_cache(_SECTOR_PAGE_DISK_CACHE, disk_key)
        if _is_current_sector_page_payload(persisted):
            _sector_page_cache[key] = (now, persisted)
            return persisted

    payload = _build_sector_page_payload(end)
    _sector_page_cache[key] = (now, payload)
    if use_persisted_cache and _using_default_sector_builders():
        save_sector_page_cache(_SECTOR_PAGE_DISK_CACHE, disk_key, payload)
    return payload


def _is_current_sector_page_payload(payload: dict | None) -> bool:
    """拒绝字段不完整的旧版页面缓存，避免模板升级后直接返回500。"""
    required = {
        "radar",
        "concept_news",
        "decision",
        "strategy_overlap",
        "latest_radar_snapshot",
        "freshness",
        "ai_news_brief",
    }
    return isinstance(payload, dict) and required.issubset(payload)


def _sector_page_disk_cache_key(end: str = "") -> tuple:
    return (str(end or "latest"), f"v{_SECTOR_PAGE_CACHE_VERSION}")


def _using_default_sector_builders() -> bool:
    return _SECTOR_BUILDERS == (
        build_sector_radar,
        build_concept_news_radar,
        build_market_radar_decision,
        build_strategy_overlap,
    )


def load_sector_page_cache(path: Path, key: tuple) -> dict | None:
    """读取版本与查询键均匹配的雷达页面缓存，损坏时静默降级。"""
    try:
        cached = pickle.loads(Path(path).read_bytes())
    except (OSError, EOFError, pickle.PickleError, ValueError, TypeError):
        return None
    if not isinstance(cached, dict) or cached.get("version") != _SECTOR_PAGE_CACHE_VERSION:
        return None
    if key and str(key[0]) == "latest" and time.time() - float(cached.get("created_at") or 0) > 1800:
        return None
    entries = cached.get("entries")
    if not isinstance(entries, dict):
        return None
    payload = entries.get(tuple(key))
    return payload if isinstance(payload, dict) else None


def save_sector_page_cache(path: Path, key: tuple, payload: dict) -> None:
    """跨进程串行完成读改写，避免并发请求覆盖彼此的缓存键。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(target) + ".lock", timeout=2):
            entries = {}
            try:
                existing = pickle.loads(target.read_bytes())
                if isinstance(existing, dict) and existing.get("version") == _SECTOR_PAGE_CACHE_VERSION:
                    entries = dict(existing.get("entries") or {})
            except (OSError, EOFError, pickle.PickleError, ValueError, TypeError):
                pass
            entries[tuple(key)] = payload
            data = {
                "version": _SECTOR_PAGE_CACHE_VERSION,
                "created_at": time.time(),
                "entries": entries,
            }
            temporary = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
            try:
                temporary.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    except FileLockTimeout:
        # 页面数据已经在内存中可用，持久化锁繁忙时跳过本次落盘即可。
        return


def _sector_page_cache_key(end: str = "") -> tuple:
    return (
        str(end or "latest"),
        id(build_sector_radar),
        id(build_concept_news_radar),
        id(build_market_radar_decision),
        id(build_strategy_overlap),
    )


def _build_sector_page_payload(end: str = "") -> dict:
    from market_radar.ai_news_brief import load_ai_news_brief

    radar = build_sector_radar(DEFAULT_HISTORY_DB_PATH, end_date=end or None)
    target_date = end or str(radar.get("end_date") or "")
    concept_news = build_concept_news_radar(DEFAULT_SIGNAL_DB_PATH, today=target_date or None)
    ai_news_brief = load_ai_news_brief(target_date)
    decision = build_market_radar_decision(radar, concept_news)
    strategy_overlap = build_strategy_overlap(DEFAULT_SIGNAL_DB_PATH, radar, concept_news)
    from market_radar.freshness import build_market_freshness

    freshness = build_market_freshness(radar, concept_news, strategy_overlap)
    decision = dict(decision)
    decision["freshness"] = freshness
    if not freshness["decision_eligible"]:
        decision["alignment"] = "数据未就绪"
        decision["confidence"] = "低"
        decision["primary_action"] = "等待行业行情与目标交易日对齐后再判断。"
    try:
        latest_radar_snapshot = get_latest_market_radar_snapshot(DEFAULT_SIGNAL_DB_PATH)
    except Exception:
        latest_radar_snapshot = None
    return {
        "radar": radar,
        "concept_news": concept_news,
        "decision": decision,
        "strategy_overlap": strategy_overlap,
        "latest_radar_snapshot": latest_radar_snapshot,
        "freshness": freshness,
        "page_time": build_page_time_context(target_date),
        "ai_news_brief": ai_news_brief,
    }


def refresh_market_radar_snapshot_for_page(end: str = "") -> int | None:
    radar = build_sector_radar(DEFAULT_HISTORY_DB_PATH, end_date=end or None)
    target_date = end or str(radar.get("end_date") or "")
    concept_news = build_concept_news_radar(DEFAULT_SIGNAL_DB_PATH, today=target_date or None)
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
def stock_redirect(request: Request, code: str = ""):
    if not code:
        return RedirectResponse(url=_app_path(request, "/"), status_code=303)
    return RedirectResponse(url=_app_path(request, f"/stock/{code}"), status_code=303)


@app.get("/stock/{code}")
def stock_detail(request: Request, code: str):
    detail = get_stock_detail(code, history_db=DEFAULT_HISTORY_DB_PATH, signal_db=DEFAULT_SIGNAL_DB_PATH)
    stock_signals = []
    if detail.get("asset_type") == "stock":
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


def _build_short_result_context(signals: list[dict], view: str = "completed") -> dict:
    """为短线复盘页整理结果筛选、计数和直观结论。"""
    allowed_views = {"completed", "pending", "winning", "losing", "risk", "all"}
    active_view = view if view in allowed_views else "completed"

    def _ret(item: dict):
        return (item.get("performance") or {}).get("ret_5d")

    def _mae(item: dict):
        return (item.get("performance") or {}).get("mae_pct")

    counts = {
        "all": len(signals),
        "completed": sum(1 for item in signals if _ret(item) is not None),
        "pending": sum(1 for item in signals if _ret(item) is None),
        "winning": sum(1 for item in signals if _ret(item) is not None and _ret(item) > 0),
        "losing": sum(1 for item in signals if _ret(item) is not None and _ret(item) < 0),
        "risk": sum(1 for item in signals if _mae(item) is not None and _mae(item) <= -8),
    }

    filters = {
        "completed": lambda item: _ret(item) is not None,
        "pending": lambda item: _ret(item) is None,
        "winning": lambda item: _ret(item) is not None and _ret(item) > 0,
        "losing": lambda item: _ret(item) is not None and _ret(item) < 0,
        "risk": lambda item: _mae(item) is not None and _mae(item) <= -8,
        "all": lambda item: True,
    }
    selected = [item for item in signals if filters[active_view](item)]
    for item in selected:
        ret = _ret(item)
        mae = _mae(item)
        if ret is None:
            item["short_result_label"] = "观察中"
            item["short_result_tone"] = "neutral"
        elif ret >= 5:
            item["short_result_label"] = "强势兑现"
            item["short_result_tone"] = "good"
        elif ret > 0:
            item["short_result_label"] = "正收益"
            item["short_result_tone"] = "good"
        elif ret == 0:
            item["short_result_label"] = "持平"
            item["short_result_tone"] = "neutral"
        else:
            item["short_result_label"] = "未兑现"
            item["short_result_tone"] = "bad"
        item["short_risk_label"] = "高回撤" if mae is not None and mae <= -8 else "回撤可控"
        item["short_risk_tone"] = "bad" if mae is not None and mae <= -8 else "ok"

    return {"items": selected, "view": active_view, "counts": counts}


@app.get("/signals")
def signals(
    request: Request,
    q: str = "",
    start: str = "",
    end: str = "",
    industry: str = "",
    page: str = "1",
    view: str = "completed",
    strategy: str = "all",
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
    date_error = validate_date_range(start, end)
    allowed_strategies = {"all", "steady", "balance", "repair"}
    active_strategy = strategy if strategy in allowed_strategies else "all"
    effective_start = normalized_start or (
        None
        if active_strategy == "repair"
        else build_default_signal_start(latest_signal_date, days=default_window_days)
    )
    history_sources = ["backtest_ic_short", "live", "live_observe", "research_shadow"]
    history_profiles = [
        "short_v9_final",
        "profile_v9_sector_quality_guard",
        "short_live_observe_best_balance",
        "short_defensive_quality_reentry_v16",
    ]
    all_strategy_signals = []
    if not date_error:
        all_strategy_signals = get_recent_signals(
            DEFAULT_SIGNAL_DB_PATH,
            history_db=DEFAULT_HISTORY_DB_PATH,
            limit=900,
            source=history_sources,
            profile=history_profiles,
            mode="short",
            query=q or None,
            start=effective_start or None,
            end=normalized_end or None,
            industry=industry or None,
        )
    strategy_summary_signals = get_recent_signals(
        DEFAULT_SIGNAL_DB_PATH,
        history_db=None,
        limit=3000,
        source=history_sources,
        profile=history_profiles,
        mode="short",
    )
    strategy_cards = summarize_short_strategy_cards(strategy_summary_signals)
    all_signals = (
        all_strategy_signals
        if active_strategy == "all"
        else [item for item in all_strategy_signals if item.get("strategy_key") == active_strategy]
    )
    short_stats = summarize_short_signal_performance(all_signals, limit=len(all_signals))
    result_context = _build_short_result_context(all_signals, view=view)
    recent_signals, page_info = paginate_items(result_context["items"], page, page_size=30)
    return templates.TemplateResponse(
        request,
        "signals.html",
        {
            "request": request,
            "signals": recent_signals,
            "all_signals": all_signals,
            "page_info": page_info,
            "short_stats": short_stats,
            "strategy_cards": strategy_cards,
            "active_strategy": active_strategy,
            "result_view": result_context["view"],
            "result_counts": result_context["counts"],
            "latest_signal_run": latest_signal_run,
            "page_time": build_page_time_context(latest_signal_date),
            "date_error": date_error,
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
                "view": result_context["view"],
                "strategy": active_strategy,
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
            "page_time": build_page_time_context(observation.get("trade_date")),
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
def signal_explanation(request: Request, trade_date: str, ts_code: str):
    try:
        explanation = get_signal_explanation(
            trade_date,
            ts_code,
            signal_db=DEFAULT_SIGNAL_DB_PATH,
            history_db=DEFAULT_HISTORY_DB_PATH,
        )
    except ExplanationCacheBusyError as exc:
        raise HTTPException(
            status_code=503,
            detail="解释缓存正忙，请稍后重试",
            headers={"Retry-After": "2"},
        ) from exc
    return templates.TemplateResponse(
        request,
        "signal_explanation.html",
        {"request": request, "explanation": explanation, "active_nav": "signals"},
    )


@app.post("/explain/signal/{trade_date}/{ts_code}/refresh")
def refresh_signal_explanation(request: Request, trade_date: str, ts_code: str):
    try:
        get_or_create_signal_explanation(
            trade_date,
            ts_code,
            signal_db=DEFAULT_SIGNAL_DB_PATH,
            history_db=DEFAULT_HISTORY_DB_PATH,
            force=True,
        )
    except ExplanationCacheBusyError as exc:
        raise HTTPException(
            status_code=503,
            detail="解释缓存正忙，请稍后重试",
            headers={"Retry-After": "2"},
        ) from exc
    return RedirectResponse(
        url=_app_path(request, f"/explain/signal/{trade_date}/{ts_code}"),
        status_code=303,
    )


def _build_longterm_result_context(samples: list[dict]) -> dict:
    def pct_text(value) -> str:
        return f"{float(value):+.2f}%" if value is not None else "待观察"

    def pct_tone(value) -> str:
        if value is None:
            return "muted"
        return "market-up" if float(value) > 0 else "market-down" if float(value) < 0 else "muted"

    completed = []
    current = []
    for item in samples:
        ret_80d = item.get("ret_80d")
        excess = item.get("excess_ret_80d")
        benchmark = float(ret_80d) - float(excess) if ret_80d is not None and excess is not None else None
        item["benchmark_ret_80d"] = benchmark
        item["benchmark_ret_80d_text"] = pct_text(benchmark)
        item["benchmark_ret_80d_tone"] = pct_tone(benchmark)
        item["return_path"] = [
            {"label": "10日", "text": item.get("ret_10d_text") or "待观察", "tone": item.get("ret_10d_tone") or "muted"},
            {"label": "40日", "text": item.get("ret_40d_text") or "待观察", "tone": item.get("ret_40d_tone") or "muted"},
            {"label": "80日", "text": item.get("ret_80d_text") or "待观察", "tone": item.get("ret_80d_tone") or "muted"},
        ]
        if ret_80d is None:
            item["result_label"] = "观察中"
            item["result_tone"] = "muted"
            item["result_risk_label"] = item.get("watch_risk_label") or "继续观察"
            current.append(item)
            continue
        mae = item.get("mae_80d")
        if mae is None:
            item["result_risk_label"] = "回撤待统计"
        elif float(mae) <= -20:
            item["result_risk_label"] = "80日高回撤"
        elif float(mae) <= -15:
            item["result_risk_label"] = "80日回撤偏深"
        elif float(mae) <= -10:
            item["result_risk_label"] = "80日回撤需注意"
        else:
            item["result_risk_label"] = "80日回撤可控"
        if mae is not None and float(mae) <= -20:
            item["result_label"] = "高回撤"
            item["result_tone"] = "bad"
        elif excess is not None and float(excess) >= 10 and float(ret_80d) > 0:
            item["result_label"] = "显著跑赢"
            item["result_tone"] = "ok"
        elif excess is not None and float(excess) > 0:
            item["result_label"] = "跑赢基准"
            item["result_tone"] = "ok"
        elif float(ret_80d) > 0:
            item["result_label"] = "正收益但跑输"
            item["result_tone"] = "warn"
        else:
            item["result_label"] = "亏损 / 跑输"
            item["result_tone"] = "bad"
        completed.append(item)

    def average(field: str):
        values = [float(item[field]) for item in completed if item.get(field) is not None]
        return sum(values) / len(values) if values else None

    winners = [item for item in completed if float(item.get("ret_80d") or 0) > 0]
    outperformers = [item for item in completed if float(item.get("excess_ret_80d") or 0) > 0]
    risk_rows = [item for item in completed if item.get("mae_80d") is not None and float(item["mae_80d"]) <= -15]
    best = max(completed, key=lambda item: float(item.get("ret_80d") or 0), default=None)
    worst = min(completed, key=lambda item: float(item.get("ret_80d") or 0), default=None)
    count = len(completed)
    return {
        "all": samples,
        "completed": completed,
        "current": current,
        "completed_count": count,
        "current_count": len(current),
        "avg_ret_text": pct_text(average("ret_80d")),
        "avg_ret_tone": pct_tone(average("ret_80d")),
        "win_rate_text": f"{len(winners) / count * 100:.1f}%" if count else "待统计",
        "outperform_rate_text": f"{len(outperformers) / count * 100:.1f}%" if count else "待统计",
        "avg_mae_text": pct_text(average("mae_80d")),
        "risk_count": len(risk_rows),
        "best": best,
        "worst": worst,
    }


def _select_longterm_result_view(result_context: dict, view: str) -> list[dict]:
    """长线风险页只展示已完成80日且最大回撤达到阈值的样本。"""
    if view == "current":
        return result_context["current"]
    if view == "outperform":
        return [item for item in result_context["completed"] if float(item.get("excess_ret_80d") or 0) > 0]
    if view == "risk":
        return [
            item
            for item in result_context["completed"]
            if item.get("mae_80d") is not None and float(item["mae_80d"]) <= -15
        ]
    if view == "all":
        return result_context["all"]
    return result_context["completed"]


@app.get("/longterm")
def longterm_pool(request: Request, start: str = "", end: str = "", page: str = "1", view: str = "completed"):
    pool = get_active_longterm_pool(DEFAULT_SIGNAL_DB_PATH)
    buckets = split_longterm_pool(pool)
    runs = get_longterm_runs(DEFAULT_SIGNAL_DB_PATH, limit=12)
    events = get_longterm_events(DEFAULT_SIGNAL_DB_PATH, history_db=DEFAULT_HISTORY_DB_PATH, limit=30)
    audit_summary = get_longterm_audit_summary(DEFAULT_SIGNAL_DB_PATH, limit=12)
    normalized_start = normalize_date_input(start)
    normalized_end = normalize_date_input(end)
    date_error = validate_date_range(start, end)
    sample_limit = 1000 if (normalized_start or normalized_end) else 100
    all_audit_samples = []
    if not date_error:
        all_audit_samples = get_longterm_audit_samples(
            DEFAULT_SIGNAL_DB_PATH,
            history_db=DEFAULT_HISTORY_DB_PATH,
            limit=sample_limit,
            start=normalized_start or None,
            end=normalized_end or None,
        )
    result_context = _build_longterm_result_context(all_audit_samples)
    selected_view = view if view in {"completed", "current", "outperform", "risk", "all"} else "completed"
    visible_samples = _select_longterm_result_view(result_context, selected_view)
    sample_filters = {"start": normalized_start, "end": normalized_end, "sample_limit": sample_limit, "view": selected_view}
    sample_filter_summary = summarize_longterm_audit_sample_filter(visible_samples, sample_filters)
    audit_samples, page_info = paginate_items(visible_samples, page, page_size=30)
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
            "page_time": build_page_time_context(runs[0].get("trade_date") if runs else None),
            "filters": sample_filters,
            "date_error": date_error,
            "sample_filter_summary": sample_filter_summary,
            "result_context": result_context,
            "current_audit_samples": result_context["current"][:6],
            "selected_view": selected_view,
            "update_status": read_update_status(),
            "active_nav": "longterm",
        },
    )
