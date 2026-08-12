"""市场雷达 AI 使用的统一可信证据包。"""

from __future__ import annotations

import hashlib
import re
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
}


def build_evidence_pack(
    radar: dict,
    concept_news: dict,
    target_date: str,
    previous_brief: dict | None = None,
) -> dict:
    """汇总全部可读、新鲜且来源可识别的消息及市场验证信息。"""
    collected = _collect_news_rows(concept_news)
    events, excluded = _normalize_events(collected, target_date)
    healthy = list(radar.get("healthy") or [])[:12]
    risky = list(radar.get("risky") or [])[:12]
    sectors = _sector_rows(healthy, risky)
    candidates = _candidate_rows(list(radar.get("candidates") or [])[:24])
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
        "eligible_count": len(events),
        "sent_to_ai_count": len(events),
        "source_count": len(source_names),
        "cached_count": cached_count,
        "mapped_count": mapped_count,
        "concept_count": len(concepts),
        "theme_count": len(themes),
        "sector_count": len(sectors),
        "candidate_count": len(candidates),
        "date_alignment": bool((concept_news.get("pipeline_health") or {}).get("date_alignment", True)),
        "excluded_reasons": {
            "invalid_or_missing_source": len(excluded["invalid"]),
            "expired": len(excluded["expired"]),
        },
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
        if not _is_fresh(parsed_time, row):
            excluded["expired"].append(title or "-")
            continue
        key = _event_key(title or summary)
        sectors = _string_list(row.get("mapped_industries") or row.get("sectors") or row.get("industries"), 6)
        url = _first_text(row, "source_url", "url", "link", "original_url")
        existing = grouped.get(key)
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
    } for item in candidates if item.get("ts_code")]


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
    now = datetime.now(SHANGHAI)
    event_type = _first_text(row, "event_type", "type")
    long_lived = any(word in event_type for word in ("公告", "政策", "监管", "合同"))
    window = timedelta(days=3) if long_lived else timedelta(hours=72)
    return now - timedelta(hours=2) <= value + window and value <= now + timedelta(days=1)


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
