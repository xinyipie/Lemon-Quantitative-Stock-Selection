"""市场雷达 AI 使用的统一可信证据包。"""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")

SOURCE_ALIASES = {
    "cls_key": "财联社",
    "cls_all": "财联社",
    "财联社重点": "财联社",
    "财联社重要": "财联社",
    "财联社电报": "财联社",
    "eastmoney": "东方财富",
    "东方财富网": "东方财富",
    "caixin": "财新",
    "财新网": "财新",
    "cctv": "央视新闻",
    "央视网": "央视新闻",
    "cninfo_announcements": "巨潮资讯",
    "csrc_policy": "中国证监会",
    "ndrc_policy": "国家发改委",
    "miit_policy": "工业和信息化部",
    "pbc_policy": "中国人民银行",
}


def build_evidence_pack(
    radar: dict,
    concept_news: dict,
    target_date: str,
    previous_brief: dict | None = None,
) -> dict:
    """汇总全部可读、新鲜且来源可识别的消息及市场验证信息。"""
    collected = _collect_news_rows(concept_news)
    eligible_events, excluded = _normalize_events(collected, target_date)
    events = _select_ai_events(eligible_events, limit=30)
    healthy = list(radar.get("healthy") or [])[:12]
    risky = list(radar.get("risky") or [])[:12]
    sectors = _sector_rows(healthy, risky)
    quant_candidates = _candidate_rows(list(radar.get("candidates") or [])[:24])
    direct_candidates = _direct_news_candidate_rows(
        events, list(radar.get("news_stock_universe") or []), quant_candidates, limit=12,
    )
    candidates = _merge_candidate_rows(quant_candidates, direct_candidates, limit=36)
    concepts = _concept_rows(concept_news.get("concepts") or {})
    themes = _theme_rows(concept_news.get("theme_filter") or {})
    pipeline = dict(concept_news.get("pipeline_health") or {})
    previous = _previous_context(previous_brief or {})
    source_names = sorted({source for event in events for source in event.get("sources") or [] if source})
    cached_count = sum(1 for event in events if event.get("is_cached"))
    mapped_count = sum(1 for event in events if event.get("mapped_industries"))
    audit = {
        "raw_count": len(collected),
        "deduplicated_count": max(len(collected) - len(events) - len(excluded["invalid"]), 0),
        "expired_count": len(excluded["expired"]),
        "unverified_count": sum(1 for event in events if event.get("verification_status") == "待核验"),
        "eligible_count": len(eligible_events),
        "sent_to_ai_count": len(events),
        "source_count": len(source_names),
        "cached_count": cached_count,
        "mapped_count": mapped_count,
        "concept_count": len(concepts),
        "theme_count": len(themes),
        "sector_count": len(sectors),
        "candidate_count": len(candidates),
        "quant_candidate_count": sum(1 for item in candidates if item.get("quant_selected")),
        "direct_news_candidate_count": sum(1 for item in candidates if item.get("direct_evidence_ids")),
        "date_alignment": bool((concept_news.get("pipeline_health") or {}).get("date_alignment", True)),
        "excluded_reasons": {
            "invalid_or_missing_source": len(excluded["invalid"]),
            "expired": len(excluded["expired"]),
        },
        "source_pipeline": _source_pipeline_audit(collected, eligible_events, events),
    }
    return {
        "target_date": _date_key(target_date),
        "market_summary": str((radar.get("summary") or {}).get("headline") or ""),
        "events": events,
        "concepts": concepts,
        "themes": themes,
        "sectors": sectors,
        "stocks": candidates,
        "healthy_industries": [row["industry"] for row in sectors if not row["risk"]],
        "risky_industries": [row["industry"] for row in sectors if row["risk"]],
        "pipeline_health": _compact_pipeline(pipeline),
        "previous_brief": previous,
        "input_audit": audit,
        "source_message": str((concept_news.get("news") or {}).get("source_message") or pipeline.get("source_message") or ""),
    }


def build_input_audit(pack: dict) -> dict:
    """返回可安全写入页面缓存的输入审计摘要。"""
    return dict(pack.get("input_audit") or {})


def _collect_news_rows(concept_news: dict) -> list[dict]:
    news = concept_news.get("news") or {}
    groups = [
        concept_news.get("reading_events"),
        concept_news.get("events"),
        news.get("reading_events"),
        news.get("events"),
        news.get("raw_news"),
        news.get("unverified_news"),
        news.get("unverified"),
        news.get("post_target_news"),
        news.get("items"),
    ]
    rows = []
    for group in groups:
        for row in group or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _normalize_events(rows: list[dict], target_date: str) -> tuple[list[dict], dict]:
    grouped: dict[str, dict] = {}
    excluded = {"invalid": [], "expired": []}
    for row in rows:
        title = _first_text(row, "title", "name", "headline")
        summary = _first_text(row, "content", "summary", "effect_summary", "description", "digest", "reason")
        source = _normalize_source(_first_text(row, "source", "source_name", "provider", "media", "original_media"))
        if not source:
            source = _normalize_source(_source_from_url(_first_text(row, "source_url", "url", "link", "original_url")))
        published = _first_text(row, "publish_time", "published_at", "datetime", "pub_time", "date", "source_date")
        parsed_time = _parse_time(published, target_date)
        if not (title or summary) or not source or parsed_time is None:
            excluded["invalid"].append(title or summary or "-")
            continue
        freshness_row = dict(row)
        freshness_row["source"] = source
        if not _is_fresh(parsed_time, freshness_row):
            excluded["expired"].append(title or "-")
            continue
        key = _event_key(title or summary)
        sectors = _string_list(row.get("mapped_industries") or row.get("sectors") or row.get("industries"), 6)
        url = _first_text(row, "source_url", "url", "link", "original_url")
        existing = grouped.get(key) or _find_semantic_duplicate(
            grouped.values(),
            title=title,
            summary=summary,
            source=source,
            parsed_time=parsed_time,
        )
        if existing:
            if source not in existing["sources"]:
                existing["sources"].append(source)
            if url and url not in existing["source_urls"]:
                existing["source_urls"].append(url)
            existing["mapped_industries"] = _unique(existing["mapped_industries"] + sectors)[:6]
            if len(summary) > len(existing["summary"]):
                existing["summary"] = summary[:900]
            existing["latest_time"] = max(existing["latest_time"], parsed_time.isoformat())
            existing["earliest_time"] = min(existing["earliest_time"], parsed_time.isoformat())
            continue
        evidence_id = "EV-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10].upper()
        grouped[key] = {
            "evidence_id": evidence_id,
            "title": title[:180] or summary[:180],
            "summary": summary[:900],
            "sources": [source],
            "source_urls": [url] if url else [],
            "source_tier": _first_text(row, "source_tier", "source_quality") or "可信渠道",
            "publish_time": parsed_time.isoformat(),
            "earliest_time": parsed_time.isoformat(),
            "latest_time": parsed_time.isoformat(),
            "collected_at": _first_text(row, "collected_at", "crawl_time", "fetched_at", "collect_time"),
            "event_type": _first_text(row, "event_type", "type"),
            "freshness": _first_text(row, "freshness_label", "freshness_bucket"),
            "verification_status": _verification_status(row),
            "materiality": _first_text(row, "materiality", "grade"),
            "impact_direction": _first_text(row, "impact", "direction", "impact_label"),
            "impact_reason": _first_text(row, "impact_reason", "effect_summary", "risk_note"),
            "mapped_industries": sectors,
            "mapping_confidence": _first_text(row, "mapping_confidence"),
            "is_cached": bool(row.get("is_cached") or row.get("source_reused")),
        }
    return list(grouped.values()), excluded


def _sector_rows(healthy: list[dict], risky: list[dict]) -> list[dict]:
    rows = []
    for risk, items in ((False, healthy), (True, risky)):
        for item in items:
            industry = str(item.get("industry") or "").strip()
            if not industry:
                continue
            rows.append({
                "industry": industry,
                "stage": str(item.get("stage") or ""),
                "heat_score": item.get("heat_score"),
                "ret_5d": item.get("avg_ret_5d"),
                "relative_10d": item.get("rel_ret_10d"),
                "risk": risk,
            })
    return rows


def _candidate_rows(candidates: list[dict]) -> list[dict]:
    return [{
        "ts_code": str(item.get("ts_code") or ""),
        "name": str(item.get("name") or ""),
        "industry": str(item.get("industry") or ""),
        "candidate_score": item.get("candidate_score"),
        "ret_5d": item.get("ret_5d"),
        "ret_10d": item.get("ret_10d"),
        "stock_vs_sector_10d": item.get("stock_vs_sector_10d"),
        "reason": str(item.get("candidate_reason") or "")[:180],
        "candidate_source": "quant",
        "quant_selected": True,
        "direct_evidence_ids": [],
    } for item in candidates if item.get("ts_code")]


def _direct_news_candidate_rows(events, universe, quant_candidates, limit=12) -> list[dict]:
    """只把新闻正文明确提及的公司纳入消息入口，行业泛化消息不点名个股。"""
    quant_by_code = {str(item.get("ts_code") or ""): item for item in quant_candidates}
    matches = {}
    for stock in universe:
        ts_code = str(stock.get("ts_code") or "").strip()
        name = str(stock.get("name") or "").strip()
        code = ts_code.split(".", 1)[0]
        if not ts_code:
            continue
        evidence_ids = []
        for event in events:
            text = f"{event.get('title') or ''} {event.get('summary') or ''}"
            if (len(name) >= 3 and name in text) or (len(code) == 6 and code in text):
                evidence_ids.append(str(event.get("evidence_id") or ""))
        evidence_ids = [item for item in evidence_ids if item][:5]
        if not evidence_ids:
            continue
        quant = quant_by_code.get(ts_code) or {}
        matches[ts_code] = {
            "ts_code": ts_code, "name": name or ts_code,
            "industry": str(stock.get("industry") or quant.get("industry") or ""),
            "candidate_score": quant.get("candidate_score"),
            "ret_5d": stock.get("ret_5d"), "ret_10d": stock.get("ret_10d"),
            "stock_vs_sector_10d": quant.get("stock_vs_sector_10d"),
            "reason": str(quant.get("reason") or "新闻直接提及该公司，量价仅用于后续验证。")[:180],
            "candidate_source": "quant_and_news" if quant else "news_direct",
            "quant_selected": bool(quant), "direct_evidence_ids": evidence_ids,
            "above_ma20": bool(stock.get("above_ma20")),
            "amount_ratio_5d": stock.get("amount_ratio_5d"),
            "net_mf_amount": stock.get("net_mf_amount"),
        }
        if len(matches) >= int(limit):
            break
    return list(matches.values())


def _merge_candidate_rows(quant_rows, direct_rows, limit) -> list[dict]:
    """合并双入口；同股保留量化分数并补充直接消息证据。"""
    merged = {str(item.get("ts_code") or ""): dict(item) for item in quant_rows}
    for row in direct_rows:
        ts_code = str(row.get("ts_code") or "")
        if ts_code in merged:
            merged[ts_code]["candidate_source"] = "quant_and_news"
            merged[ts_code]["direct_evidence_ids"] = list(row.get("direct_evidence_ids") or [])
        else:
            merged[ts_code] = dict(row)
    rows = list(merged.values())
    rows.sort(key=lambda item: (
        0 if item.get("candidate_source") == "quant_and_news" else 1 if item.get("candidate_source") == "news_direct" else 2,
        -float(item.get("candidate_score") or 0),
    ))
    return rows[:int(limit)]


def _concept_rows(payload: dict) -> list[dict]:
    return [{
        "name": _first_text(item, "concept_name", "name", "theme"),
        "heat": item.get("heat_score", item.get("heat")),
        "change_pct": item.get("change_pct", item.get("pct_chg")),
        "status": _first_text(item, "status", "stage", "label"),
    } for item in list(payload.get("items") or [])[:12] if isinstance(item, dict)]


def _theme_rows(payload: dict) -> list[dict]:
    return [{
        "theme": str(item.get("theme") or ""),
        "level": str(item.get("level") or ""),
        "horizon": str(item.get("horizon") or ""),
        "verdict": str(item.get("verdict") or ""),
        "reason": str(item.get("reason") or "")[:240],
    } for item in list(payload.get("items") or [])[:12] if isinstance(item, dict)]


def _previous_context(payload: dict) -> dict:
    if payload.get("status") != "ok":
        return {}
    return {
        "target_date": payload.get("target_date"),
        "summary": payload.get("summary"),
        "sector_focus": list(payload.get("sector_focus") or [])[:5],
    }


def _compact_pipeline(payload: dict) -> dict:
    keys = ("source_state", "source_label", "source_message", "ai_status", "ai_message", "raw_count", "ai_candidate_count", "mapped_count", "positive_count", "negative_count", "neutral_count")
    return {key: payload.get(key) for key in keys if key in payload}


def _is_fresh(value: datetime, row: dict) -> bool:
    from market_radar.freshness import classify_news_time

    return bool(classify_news_time(value, record=row).get("decision_eligible"))


def _select_ai_events(events: list[dict], limit: int = 30) -> list[dict]:
    """控制 AI 证据总量，同时保证公告和政策不会被媒体快讯淹没。"""
    maximum = max(0, int(limit))
    buckets = {"media": [], "announcement": [], "policy": []}
    for event in events:
        buckets[_event_bucket(event)].append(event)
    for rows in buckets.values():
        rows.sort(key=lambda item: str(item.get("publish_time") or ""), reverse=True)
    quotas = {"media": min(16, maximum), "announcement": min(8, maximum), "policy": min(6, maximum)}
    selected = []
    selected_ids = set()
    for bucket in ("announcement", "policy", "media"):
        for event in buckets[bucket][: quotas[bucket]]:
            selected.append(event)
            selected_ids.add(event["evidence_id"])
    for event in sorted(events, key=lambda item: str(item.get("publish_time") or ""), reverse=True):
        if len(selected) >= maximum:
            break
        if event.get("evidence_id") not in selected_ids:
            selected.append(event)
            selected_ids.add(event.get("evidence_id"))
    return sorted(selected, key=lambda item: str(item.get("publish_time") or ""), reverse=True)[:maximum]


def _event_bucket(event: dict) -> str:
    sources = set(event.get("sources") or [])
    if "巨潮资讯" in sources:
        return "announcement"
    if sources & {"中国证监会", "国家发改委", "工业和信息化部", "中国人民银行"}:
        return "policy"
    return "media"


def _source_pipeline_audit(collected: list[dict], eligible: list[dict], sent: list[dict]) -> list[dict]:
    """记录各来源抓取、有效和送入 AI 的数量，便于页面诊断。"""
    fetched: dict[str, int] = {}
    for row in collected:
        source = _normalize_source(_first_text(row, "source", "source_name", "provider", "media", "original_media")) or "未知来源"
        fetched[source] = fetched.get(source, 0) + 1
    effective: dict[str, int] = {}
    for event in eligible:
        for source in event.get("sources") or []:
            effective[source] = effective.get(source, 0) + 1
    ai_counts: dict[str, int] = {}
    for event in sent:
        for source in event.get("sources") or []:
            ai_counts[source] = ai_counts.get(source, 0) + 1
    names = sorted(set(fetched) | set(effective) | set(ai_counts))
    return [
        {"source": name, "fetched": fetched.get(name, 0), "eligible": effective.get(name, 0), "sent_to_ai": ai_counts.get(name, 0)}
        for name in names
    ]


def _parse_time(value: str, target_date: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("年", "-").replace("月", "-").replace("日", " ").replace("/", "-").replace("T", " ")
    if re.fullmatch(r"\d{8}", normalized):
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    if re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", normalized):
        date = _date_key(target_date)
        normalized = f"{date[:4]}-{date[4:6]}-{date[6:]} {normalized}"
    try:
        parsed = datetime.fromisoformat(normalized.strip())
    except ValueError:
        digits = re.sub(r"\D", "", normalized)
        if len(digits) < 8:
            return None
        try:
            parsed = datetime.strptime(digits[:14].ljust(14, "0"), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def _event_key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(value).lower())[:100]


def _find_semantic_duplicate(
    events,
    title: str,
    summary: str,
    source: str,
    parsed_time: datetime,
) -> dict | None:
    """保守合并跨媒体的同一事件，避免相似主题被误删。"""
    title_key = _event_key(title)
    summary_key = _event_key(summary)[:240]
    if len(title_key) < 8:
        return None
    for event in events:
        if source in set(event.get("sources") or []):
            continue
        try:
            event_time = datetime.fromisoformat(str(event.get("latest_time") or event.get("publish_time")))
        except (TypeError, ValueError):
            continue
        if abs((parsed_time - event_time).total_seconds()) > 36 * 3600:
            continue
        existing_title = _event_key(event.get("title"))
        title_ratio = SequenceMatcher(None, title_key, existing_title).ratio()
        if title_ratio >= 0.68:
            return event
        existing_summary = _event_key(event.get("summary"))[:240]
        if not summary_key or not existing_summary:
            continue
        summary_ratio = SequenceMatcher(None, summary_key, existing_summary).ratio()
        if title_ratio >= 0.38 and summary_ratio >= 0.78:
            return event
    return None


def _verification_status(row: dict) -> str:
    value = _first_text(row, "verification_status", "source_quality")
    if row.get("verified") is True or "原文" in value or "可信" in value:
        return "可核验"
    return value or "待AI判断"


def _source_from_url(value: str) -> str:
    match = re.search(r"https?://([^/]+)", value)
    return match.group(1).lower() if match else ""


def _normalize_source(value: str) -> str:
    """把同一媒体的采集通道归并为统一来源名。"""
    source = str(value or "").strip()
    if not source:
        return ""
    lowered = source.lower()
    if lowered in SOURCE_ALIASES:
        return SOURCE_ALIASES[lowered]
    if source in SOURCE_ALIASES:
        return SOURCE_ALIASES[source]
    if "cls.cn" in lowered or "财联社" in source:
        return "财联社"
    if "eastmoney" in lowered or "东方财富" in source:
        return "东方财富"
    if "caixin" in lowered or "财新" in source:
        return "财新"
    if "cctv" in lowered or "央视" in source:
        return "央视新闻"
    return source


def _first_text(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _string_list(value: Any, limit: int) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[,，、;/；]", value)
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return _unique([str(item).strip() for item in values if str(item).strip()])[:limit]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _date_key(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))[:8]
