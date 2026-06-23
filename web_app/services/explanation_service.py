#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AI explanation documents for Web signal pages."""

from __future__ import annotations

import json
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests

import config
from history_store import DEFAULT_HISTORY_DB_PATH
from signal_store import DEFAULT_DB_PATH
from web_app.services.signal_service import (
    get_active_longterm_pool,
    get_longterm_runs,
    get_recent_signals,
    get_signal_runs,
    get_stock_signals,
)


SYSTEM_EXPLANATION_ANALYST = (
    "你是专业但克制的A股量化信号解释员。你的任务不是鼓吹买入，而是把系统已有数据解释清楚。"
    "必须面向普通用户，用短句、结论先行、风险明确的中文表达。"
    "只能基于输入JSON中的事实解释，不得编造新闻、政策、财务或盘口细节。"
    "禁止使用必涨、稳赚、满仓、梭哈、无脑买入等表达。"
    "输出必须是合法JSON对象，不要markdown，不要代码块。"
)

PROMPT_VERSION = "signal_explanation_v1"
DAILY_BRIEF_PROMPT_VERSION = "daily_brief_v1"

SYSTEM_DAILY_BRIEF_ANALYST = (
    "你是专业但克制的A股策略值班研究员。你的任务是把今日本地量化事实总结成盘前/盘后决策摘要。"
    "必须结论先行、风险明确、语言短，不得编造新闻、政策、盘口或财务事实。"
    "只能解释输入JSON中的信号、池子、数据状态和市场状态，不生成交易执行指令。"
    "禁止使用必涨、稳赚、满仓、梭哈、无脑买入等表达。"
    "输出必须是合法JSON对象，不要markdown，不要代码块。"
)


def get_or_create_signal_explanation(
    trade_date: str,
    ts_code: str,
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
    ai_config: dict | None = None,
    post: Callable[..., Any] | None = None,
    force: bool = False,
) -> dict:
    """Return cached AI explanation, or generate one from factual signal data."""
    signal = _find_signal(trade_date, ts_code, signal_db, history_db)
    if not signal:
        return {
            "source": "not_found",
            "doc": {
                "title": "未找到信号",
                "summary": "本地信号库中没有找到这条记录，无法生成解释文档。",
                "positives": [],
                "risks": ["请确认日期和股票代码是否正确。"],
                "watch_plan": "返回短线复盘页重新选择记录。",
                "invalidation": "-",
                "style": "无记录",
                "confidence_note": "没有事实数据时不生成分析结论。",
            },
            "signal": {},
        }

    cache_key = _cache_key(signal)
    cfg = ai_config or config.AI_CONFIG
    facts = _facts_from_signal(signal)
    input_hash = _input_hash(facts)
    cached = None if force else _read_cached(cache_key, signal_db, allow_fallback=not bool(cfg.get("api_key")))
    if cached:
        return {"source": "cache", "doc": cached, "signal": signal}

    doc = _call_ai_document(facts, cfg, post or requests.post)
    source = "ai"
    if not doc:
        doc = build_fallback_explanation(signal)
        source = "fallback"
    _write_cache(cache_key, signal, doc, source, signal_db, model=cfg.get("model", ""), input_hash=input_hash)
    return {"source": source, "doc": doc, "signal": signal}


def get_or_create_daily_brief(
    trade_date: str,
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
    ai_config: dict | None = None,
    post: Callable[..., Any] | None = None,
    force: bool = False,
) -> dict:
    """Return cached daily dashboard brief, or generate one from local facts."""
    date_text = _date_text(trade_date)
    cache_key = f"daily_brief:{date_text}"
    cfg = ai_config or config.AI_CONFIG
    facts = build_daily_brief_facts(date_text, signal_db=signal_db, history_db=history_db)
    input_hash = _input_hash(facts)
    cached = None if force else _read_cached(cache_key, signal_db, allow_fallback=not bool(cfg.get("api_key")))
    if cached:
        return {"source": "cache", "doc": cached, "facts": facts}

    doc = _call_ai_document(
        facts,
        cfg,
        post or requests.post,
        system=SYSTEM_DAILY_BRIEF_ANALYST,
        prompt_builder=_build_daily_brief_prompt,
    )
    source = "ai"
    if not doc:
        doc = build_fallback_daily_brief(facts)
        source = "fallback"
    _write_document_cache(
        cache_key=cache_key,
        doc=doc,
        source=source,
        signal_db=signal_db,
        doc_type="daily_brief",
        trade_date=date_text,
        ts_code=None,
        mode="dashboard",
        profile="daily_brief",
        source_ref=cache_key,
        model=cfg.get("model", ""),
        prompt_version=DAILY_BRIEF_PROMPT_VERSION,
        input_hash=input_hash,
    )
    return {"source": source, "doc": doc, "facts": facts}


def get_daily_brief(
    trade_date: str,
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
) -> dict:
    """Read cached daily brief for dashboard; use fallback preview without calling AI."""
    date_text = _date_text(trade_date)
    cache_key = f"daily_brief:{date_text}"
    facts = build_daily_brief_facts(date_text, signal_db=signal_db, history_db=history_db)
    cached = _read_cached(cache_key, signal_db, allow_fallback=True)
    if cached:
        return {"source": "cache", "doc": cached, "facts": facts}
    return {"source": "fallback_preview", "doc": build_fallback_daily_brief(facts), "facts": facts}


def build_daily_brief_facts(
    trade_date: str,
    signal_db: str | Path = DEFAULT_DB_PATH,
    history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH,
) -> dict:
    date_text = _date_text(trade_date)
    live_short_signals = get_recent_signals(
        signal_db,
        history_db=history_db,
        limit=8,
        source="live",
        mode="short",
        start=date_text,
        end=date_text,
    )
    longterm_pool = get_active_longterm_pool(signal_db)
    short_runs = [
        item
        for item in get_signal_runs(signal_db, mode="short", source="live", limit=10)
        if str(item.get("trade_date")) == date_text
    ]
    longterm_runs = [
        item
        for item in get_longterm_runs(signal_db, limit=10)
        if str(item.get("trade_date")) == date_text
    ]
    elite_count = sum(1 for item in longterm_pool if "elite" in str(item.get("profile") or "").lower())
    watch_count = len(longterm_pool) - elite_count
    return {
        "trade_date": date_text,
        "latest_live_short_run": short_runs[0] if short_runs else None,
        "live_short_count": len(live_short_signals),
        "live_short_signals": [_brief_signal_item(item) for item in live_short_signals[:5]],
        "longterm_pool_count": len(longterm_pool),
        "longterm_elite_count": elite_count,
        "longterm_watch_count": watch_count,
        "longterm_pool": [_brief_longterm_item(item) for item in longterm_pool[:5]],
        "longterm_runs": longterm_runs[:3],
        "freshness": {},
    }


def build_fallback_daily_brief(facts: dict) -> dict:
    trade_date = str(facts.get("trade_date") or "")
    live_count = int(facts.get("live_short_count") or len(facts.get("live_short_signals") or []))
    longterm_count = int(facts.get("longterm_pool_count") or len(facts.get("longterm_pool") or []))
    short_names = [
        str(item.get("display_name") or item.get("name") or item.get("ts_code"))
        for item in (facts.get("live_short_signals") or [])[:3]
        if item
    ]
    positives = []
    risks = []
    if live_count:
        positives.append(f"短线 live 信号有 {live_count} 条，代表系统发现了可重点跟踪的局部机会。")
        if short_names:
            positives.append(f"当前重点观察：{'、'.join(short_names)}。")
    else:
        risks.append("短线 live 信号为空，说明当天不适合强行寻找短线机会。")
    if longterm_count:
        positives.append(f"长线池有 {longterm_count} 只 active 标的，可继续跟踪生命周期变化。")
    else:
        risks.append("长线严格池为空，说明中期条件尚未放行，不宜为了持仓而硬买。")
    freshness = facts.get("freshness") or {}
    for warning in freshness.get("warnings") or []:
        risks.append(str(warning))
    if not positives:
        positives.append("系统已完成扫描，空信号本身也是有效的风险提示。")
    if not risks:
        risks.append("即使有信号，也需要等待次日承接和板块扩散确认，不能把入池等同于确定收益。")
    stance = "今日有短线可关注信号" if live_count else "今日更适合防守和观察"
    if longterm_count:
        stance += "，长线池保持跟踪"
    else:
        stance += "，长线池暂未放行"
    return {
        "title": f"{trade_date} 今日AI摘要",
        "summary": f"{stance}。本摘要只解释本地量化事实，用来帮助你决定先看哪里、哪里需要克制。",
        "positives": positives[:3],
        "risks": risks[:3],
        "watch_plan": "先看今日入池标的的次日承接、板块是否扩散，以及长线池是否出现新入池或升级强提醒。",
        "invalidation": "若短线信号低开走弱、板块同步退潮或数据状态提示滞后，应降低参与欲望并回到观察。",
        "style": "今日观察",
        "confidence_note": "基于本地信号和市场数据，不构成收益承诺或交易指令。",
    }


def build_fallback_explanation(signal: dict) -> dict:
    name = signal.get("display_name") or signal.get("name") or signal.get("ts_code")
    code = signal.get("display_code") or signal.get("ts_code")
    outcome = signal.get("outcome_label") or "未满5日"
    process = signal.get("process_label") or "等走势确认"
    quality = signal.get("quality_label") or "线索不足"
    basis = signal.get("basis_text") or "-"
    performance = signal.get("performance_text") or "-"
    confidence_label = str(signal.get("confidence_label") or "").strip()
    confidence_summary = str(signal.get("confidence_summary") or "").strip()
    score_explain = signal.get("score_explain") or {}
    rule_reasons = [str(item) for item in (score_explain.get("rule_reasons") or []) if str(item).strip()]
    risk_reasons = [str(item) for item in (score_explain.get("risk_reasons") or []) if str(item).strip()]
    action_hint = str(score_explain.get("action_hint") or "").strip()

    positives = []
    risks = []
    positives.extend(rule_reasons[:3])
    risks.extend(risk_reasons[:3])
    if quality in {"初筛通过", "通过初筛", "有效信号"}:
        positives.append("系统评分达到初筛通过层级，说明当时至少有若干因子形成共振。")
    elif quality in {"线索不足", "只观察", "观察信号"}:
        positives.append("信号具备部分线索，但强度还不足以视为高置信机会。")
    else:
        risks.append("系统评分偏低，更适合作为复盘样本，而不是重点关注对象。")

    if confidence_label:
        confidence_text = f"可信度：{confidence_label}"
        if confidence_label in {"重点看", "强信号"}:
            positives.append(confidence_text)
        else:
            risks.append(confidence_text)
    if confidence_summary:
        for part in [item.strip() for item in confidence_summary.split("；") if item.strip()]:
            if any(token in part for token in ("风险", "亏损", "回撤", "窗口未满", "未满5日", "排除", "偏低")):
                risks.append(part)
            else:
                positives.append(part)

    if "资金" in basis:
        positives.append("入选依据中包含资金线索，可作为短线活跃度参考。")
    if outcome == "短线亏损":
        risks.append("事后短线收益为负，说明入选后的承接或时机并不理想。")
    if process in {"曾冲高回落", "回撤偏大"}:
        risks.append(f"过程标签为“{process}”，说明追高或持有体验存在明显压力。")
    if not risks:
        risks.append("即使信号有效，也需要等待次日走势确认，不能把历史入选等同于确定收益。")

    rule_summary = signal.get("recommend_reason") or "系统保留了这条信号，但结构化推荐原因不足。"
    confidence_clause = f"可信度：{confidence_label}（{confidence_summary}）。" if confidence_label else ""
    summary = (
        f"{name}这条记录属于{quality}，{confidence_clause}规则原因是：{rule_summary}。事后结果为{outcome}，过程表现是{process}。"
        f"它更适合用于理解系统当时为什么关注，而不是直接复制为买入指令。"
    )
    return {
        "title": f"{name} {code} 信号解释",
        "summary": summary,
        "positives": positives[:3],
        "risks": risks[:3],
        "watch_plan": f"{action_hint or '后续只在重新出现资金、板块和形态共振时继续观察'}；当前复盘表现为：{performance}。",
        "invalidation": "若次日不能站稳关键位、放量下跌或继续冲高回落，应放弃该信号。",
        "style": "短线观察",
        "confidence_note": "本解释只基于本地信号和复盘数据，不构成收益承诺或交易指令。",
    }


def _find_signal(
    trade_date: str,
    ts_code: str,
    signal_db: str | Path,
    history_db: str | Path | None,
) -> dict | None:
    normalized = _normalize_ts_code(ts_code)
    rows = get_stock_signals(normalized, signal_db=signal_db, history_db=history_db, limit=200)
    target_date = str(trade_date).replace("-", "")[:8]
    for item in rows:
        if str(item.get("trade_date")) == target_date:
            return item
    return None


def _facts_from_signal(signal: dict) -> dict:
    return {
        "trade_date": signal.get("trade_date"),
        "mode": signal.get("mode"),
        "profile": signal.get("profile"),
        "code": signal.get("display_code") or signal.get("ts_code"),
        "name": signal.get("display_name") or signal.get("name"),
        "industry": signal.get("industry"),
        "rank": signal.get("rank"),
        "score": signal.get("score"),
        "pool_type": signal.get("pool_type"),
        "basis_text": signal.get("basis_text"),
        "recommend_reason": signal.get("recommend_reason"),
        "risk_reason_text": signal.get("risk_reason_text"),
        "score_explain": signal.get("score_explain"),
        "score_tooltip": signal.get("score_tooltip"),
        "performance_text": signal.get("performance_text"),
        "quality_label": signal.get("quality_label"),
        "outcome_label": signal.get("outcome_label"),
        "process_label": signal.get("process_label"),
        "confidence_label": signal.get("confidence_label"),
        "confidence_summary": signal.get("confidence_summary"),
        "factors": signal.get("factors") or {},
    }


def _brief_signal_item(item: dict) -> dict:
    return {
        "trade_date": item.get("trade_date"),
        "ts_code": item.get("ts_code"),
        "display_name": item.get("display_name") or item.get("name") or item.get("ts_code"),
        "display_code": item.get("display_code") or item.get("ts_code"),
        "industry": item.get("industry"),
        "rank": item.get("rank"),
        "score": item.get("score"),
        "quality_label": item.get("quality_label"),
        "confidence_label": item.get("confidence_label"),
        "confidence_summary": item.get("confidence_summary"),
        "recommend_reason": item.get("recommend_reason"),
        "risk_reason_text": item.get("risk_reason_text"),
    }


def _brief_longterm_item(item: dict) -> dict:
    return {
        "ts_code": item.get("ts_code"),
        "name": item.get("name") or item.get("ts_code"),
        "industry": item.get("industry"),
        "latest_score": item.get("latest_score"),
        "days_in_pool": item.get("days_in_pool"),
        "state": item.get("state"),
        "last_reason": item.get("last_reason"),
    }


def _date_text(value: str) -> str:
    return str(value or "").replace("-", "")[:8]


def _call_ai_document(
    facts: dict,
    ai_config: dict,
    post: Callable[..., Any],
    system: str = SYSTEM_EXPLANATION_ANALYST,
    prompt_builder: Callable[[dict], str] | None = None,
) -> dict | None:
    api_key = ai_config.get("api_key")
    if not api_key:
        return None
    prompt = (prompt_builder or _build_prompt)(facts)
    payload = {
        "model": ai_config.get("model", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": ai_config.get("temperature", 0.1),
        "max_tokens": min(int(ai_config.get("max_tokens", 1600) or 1600), 2000),
    }
    try:
        response = post(
            url=ai_config.get("base_url"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {api_key}",
            },
            json=payload,
            timeout=ai_config.get("timeout", 60),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None
    return _parse_doc(content)


def _build_prompt(facts: dict) -> str:
    schema = {
        "title": "一句标题，含股票名和代码",
        "summary": "80-120字，一句话结论开头，解释为什么当时入选以及现在如何看待",
        "positives": ["2-3条看好点，只能基于输入事实"],
        "risks": ["2-3条风险点，必须包含数据不支持追买时的提醒"],
        "watch_plan": "普通人能执行的观察计划，必须是条件式，不生成交易指令",
        "invalidation": "信号失效条件，说明什么情况应放弃观察",
        "style": "短线观察/长线观察/历史复盘/暂避",
        "confidence_note": "一句免责声明：基于历史和信号数据，不承诺收益",
    }
    return (
        "请把下面这条量化信号解释成专业但易懂的中文文档。"
        "你只能解释输入里的事实，不能补充外部新闻或臆测。\n\n"
        f"输入事实：\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
        f"输出JSON字段：\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )


def _build_daily_brief_prompt(facts: dict) -> str:
    schema = {
        "title": "一句标题，含日期",
        "summary": "80-140字，结论先行，说明今天该重点看什么、哪里要克制",
        "positives": ["2-3条正向事实，只能基于输入事实"],
        "risks": ["2-3条风险或克制点，必须包含空信号或数据滞后时的提醒"],
        "watch_plan": "普通人能执行的今日观察计划，必须是条件式，不生成交易指令",
        "invalidation": "今日观点失效条件，说明什么情况应回到观察",
        "style": "今日观察/偏防守/可关注/暂避",
        "confidence_note": "一句免责声明：基于本地信号和市场数据，不承诺收益",
    }
    return (
        "请把下面的本地量化事实总结成首页今日AI摘要。"
        "你只能解释输入里的事实，不能补充外部新闻或臆测。\n\n"
        f"输入事实：\n{json.dumps(facts, ensure_ascii=False, indent=2, default=str)}\n\n"
        f"输出JSON字段：\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )


def _parse_doc(content: str) -> dict | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None
    required = ["title", "summary", "positives", "risks", "watch_plan", "invalidation", "style", "confidence_note"]
    if not all(key in parsed for key in required):
        return None
    parsed["positives"] = _ensure_list(parsed.get("positives"))
    parsed["risks"] = _ensure_list(parsed.get("risks"))
    for key in ["title", "summary", "watch_plan", "invalidation", "style", "confidence_note"]:
        parsed[key] = str(parsed.get(key) or "")
    return parsed


def _ensure_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return []


def _cache_key(signal: dict) -> str:
    return f"signal:{signal.get('trade_date')}:{signal.get('ts_code')}"


def _input_hash(facts: dict) -> str:
    raw = json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists ai_analysis_documents (
            id integer primary key autoincrement,
            doc_type text not null,
            cache_key text not null unique,
            trade_date text,
            ts_code text,
            mode text,
            profile text,
            source_ref text,
            source text,
            model text,
            prompt_version text,
            input_hash text,
            doc_json text not null,
            summary text,
            created_at text not null,
            updated_at text not null
        )
        """
    )
    _migrate_legacy_documents(conn)
    conn.commit()


def _read_cached(cache_key: str, signal_db: str | Path, allow_fallback: bool = True) -> dict | None:
    path = Path(signal_db)
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    try:
        _init_schema(conn)
        row = conn.execute("select doc_json, source from ai_analysis_documents where cache_key = ?", (cache_key,)).fetchone()
        if not row:
            legacy = _read_legacy_cached(conn, cache_key)
            if not legacy:
                return None
            row = legacy
        if row[1] != "ai" and not allow_fallback:
            return None
        return _parse_doc(row[0])
    finally:
        conn.close()


def _read_legacy_cached(conn: sqlite3.Connection, cache_key: str):
    exists = conn.execute(
        "select name from sqlite_master where type = 'table' and name = 'ai_explanations'"
    ).fetchone()
    if not exists:
        return None
    return conn.execute("select doc_json, source from ai_explanations where cache_key = ?", (cache_key,)).fetchone()


def _migrate_legacy_documents(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "select name from sqlite_master where type = 'table' and name = 'ai_explanations'"
    ).fetchone()
    if not exists:
        return
    rows = conn.execute(
        """
        select cache_key, trade_date, ts_code, mode, profile, source,
               doc_json, created_at, updated_at
        from ai_explanations
        """
    ).fetchall()
    for row in rows:
        doc = _parse_doc(row[6])
        summary = doc.get("summary", "") if doc else ""
        conn.execute(
            """
            insert or ignore into ai_analysis_documents(
                doc_type, cache_key, trade_date, ts_code, mode, profile,
                source_ref, source, model, prompt_version, input_hash,
                doc_json, summary, created_at, updated_at
            )
            values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "signal_explanation",
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[0],
                row[5],
                "",
                "legacy_ai_explanations",
                "",
                row[6],
                summary,
                row[7],
                row[8],
            ),
        )


def _write_cache(
    cache_key: str,
    signal: dict,
    doc: dict,
    source: str,
    signal_db: str | Path,
    model: str = "",
    input_hash: str = "",
) -> None:
    _write_document_cache(
        cache_key=cache_key,
        doc=doc,
        source=source,
        signal_db=signal_db,
        doc_type="signal_explanation",
        trade_date=signal.get("trade_date"),
        ts_code=signal.get("ts_code"),
        mode=signal.get("mode"),
        profile=signal.get("profile"),
        source_ref=cache_key,
        model=model,
        prompt_version=PROMPT_VERSION,
        input_hash=input_hash,
    )


def _write_document_cache(
    cache_key: str,
    doc: dict,
    source: str,
    signal_db: str | Path,
    doc_type: str,
    trade_date: str | None = None,
    ts_code: str | None = None,
    mode: str | None = None,
    profile: str | None = None,
    source_ref: str | None = None,
    model: str = "",
    prompt_version: str = "",
    input_hash: str = "",
) -> None:
    path = Path(signal_db)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(path)
    try:
        _init_schema(conn)
        with conn:
            conn.execute(
                """
                insert into ai_analysis_documents(
                    doc_type, cache_key, trade_date, ts_code, mode, profile,
                    source_ref, source, model, prompt_version, input_hash,
                    doc_json, summary, created_at, updated_at
                )
                values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(cache_key) do update set
                    source = excluded.source,
                    model = excluded.model,
                    prompt_version = excluded.prompt_version,
                    input_hash = excluded.input_hash,
                    doc_json = excluded.doc_json,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (
                    doc_type,
                    cache_key,
                    trade_date,
                    ts_code,
                    mode,
                    profile,
                    source_ref or cache_key,
                    source,
                    model or "",
                    prompt_version or PROMPT_VERSION,
                    input_hash,
                    json.dumps(doc, ensure_ascii=False, sort_keys=True),
                    doc.get("summary", ""),
                    now,
                    now,
                ),
            )
    finally:
        conn.close()


def _normalize_ts_code(value: str) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        code, suffix = text.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    raw = text.zfill(6)
    suffix = "SH" if raw.startswith(("6", "9")) else "SZ"
    return f"{raw}.{suffix}"
