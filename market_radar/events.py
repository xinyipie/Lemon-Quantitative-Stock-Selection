"""Standardize cached market news into research events."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher


def build_events_from_news_payload(payload: dict, limit: int = 20) -> list[dict]:
    """Build deduplicated research events from a news_sector cache payload."""
    if not isinstance(payload, dict):
        return []
    raw_index = _raw_news_index(payload)
    merged: dict[str, dict] = {}
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("news") or item.get("title") or "").strip()
        if not title:
            continue
        sectors = _string_list(item.get("sectors"))
        if not sectors:
            continue
        impact = str(item.get("impact") or "mixed").strip() or "mixed"
        strength = _int(item.get("strength"))
        event_type = str(item.get("type") or "未分类").strip() or "未分类"
        key = _normalize_title(title)
        current = merged.get(key)
        if current is None:
            raw_source = _find_raw_source(title, raw_index, str(item.get("reason") or ""))
            current = {
                "title": title[:120],
                "event_type": event_type,
                "impact": impact if impact in {"positive", "negative", "mixed"} else "mixed",
                "strength": strength,
                "duration": str(item.get("duration") or "未知").strip() or "未知",
                "mapped_industries": [],
                "reasons": [],
                "raw_sources": [],
            }
            if raw_source:
                current["raw_sources"].append(raw_source)
            merged[key] = current
        if strength > int(current.get("strength") or 0):
            current["strength"] = strength
            current["event_type"] = event_type
            current["impact"] = impact if impact in {"positive", "negative", "mixed"} else current["impact"]
            current["duration"] = str(item.get("duration") or current.get("duration") or "未知")
        for sector in sectors:
            if sector not in current["mapped_industries"]:
                current["mapped_industries"].append(sector)
        reason = str(item.get("reason") or "").strip()
        if reason and reason not in current["reasons"]:
            current["reasons"].append(reason)
        raw_source = _find_raw_source(title, raw_index, reason)
        if raw_source and raw_source not in current["raw_sources"]:
            current["raw_sources"].append(raw_source)

    events = [_decorate_event(item, payload) for item in merged.values()]
    events.sort(key=lambda item: (_materiality_rank(item["materiality"]), item["strength"], item["source_score"]), reverse=True)
    return events[: max(0, int(limit))]


def build_event_summary(events: list[dict]) -> dict:
    """Summarize standardized events for the Web service layer."""
    rows = [item for item in events or [] if isinstance(item, dict)]
    materialities = [str(item.get("materiality") or "D") for item in rows]
    source_urls = {
        source.get("url")
        for item in rows
        for source in item.get("evidence_urls") or []
        if source.get("url")
    }
    industries = Counter(
        industry
        for item in rows
        for industry in item.get("mapped_industries") or []
        if industry
    )
    return {
        "event_count": len(rows),
        "positive_count": sum(1 for item in rows if item.get("impact") == "positive"),
        "negative_count": sum(1 for item in rows if item.get("impact") == "negative"),
        "mixed_count": sum(1 for item in rows if item.get("impact") == "mixed"),
        "top_materiality": _top_materiality(materialities),
        "source_count": len(source_urls),
        "top_industries": [name for name, _count in industries.most_common(5)],
    }


def _decorate_event(item: dict, payload: dict) -> dict:
    sectors = item.get("mapped_industries") or []
    reasons = item.get("reasons") or []
    raw_sources = item.get("raw_sources") or []
    mapping_confidence = _mapping_confidence(sectors, item.get("event_type"), " ".join(reasons))
    source_quality = _source_quality(raw_sources)
    source_score = max((_num(source.get("news_value_score")) or 0.0 for source in raw_sources), default=0.0)
    materiality = _materiality(item.get("strength"), item.get("event_type"), source_quality, mapping_confidence)
    title = str(item.get("title") or "")
    event_id = _event_id(title, item.get("event_type"), payload.get("date"))
    source_meta = _source_meta(raw_sources, payload)
    catalyst_age_days = _catalyst_age_days(source_meta.get("publish_time"), payload.get("date"))
    impact = item.get("impact") or "mixed"
    evidence_urls = _evidence_urls(raw_sources)
    source_url = evidence_urls[0]["url"] if evidence_urls else ""
    freshness_bucket = _freshness_bucket(catalyst_age_days)
    source_channel = _source_channel(source_meta)
    source_confidence_note = _source_confidence_note(source_meta, source_url)
    trade_priority = _trade_priority(impact, materiality, source_meta, source_url, freshness_bucket)
    return {
        "event_id": event_id,
        "title": title,
        "event_type": str(item.get("event_type") or "未分类"),
        "impact": impact,
        "impact_label": _impact_label(impact),
        "impact_tone": _impact_tone(impact),
        "materiality": materiality,
        "impact_degree_text": _impact_degree_text(impact, materiality),
        "duration": str(item.get("duration") or "未知"),
        "novelty": _novelty(title),
        "source_quality": source_quality,
        "source_score": source_score,
        "mapped_industries": sectors,
        "mapping_confidence": mapping_confidence,
        "evidence_urls": evidence_urls,
        "verification_points": _verification_points(impact, sectors),
        "invalidation_points": _invalidation_points(impact, sectors),
        "risk_note": _risk_note(mapping_confidence, impact),
        "strength": int(item.get("strength") or 0),
        "reasons": reasons[:3],
        "source_date": str(payload.get("date") or ""),
        "source_name": source_meta["source_name"],
        "original_source": source_meta["original_source"],
        "collection_source": source_meta["collection_source"],
        "source_url": source_url,
        "publish_time": source_meta["publish_time"],
        "collected_at": source_meta["collected_at"],
        "catalyst_age_days": catalyst_age_days,
        "catalyst_clock": _catalyst_clock(catalyst_age_days),
        "freshness_bucket": freshness_bucket,
        "freshness_label": _freshness_label(catalyst_age_days),
        "source_channel": source_channel,
        "source_confidence_note": source_confidence_note,
        "trade_priority": trade_priority,
        "event_bucket": _event_bucket(impact, source_quality, source_meta, source_url, freshness_bucket),
        "effect_summary": _effect_summary(impact, materiality, sectors, mapping_confidence),
        "industry_anchor": _anchor("thesis", sectors[0] if sectors else ""),
        "stock_anchor": _anchor("sector", sectors[0] if sectors else ""),
    }


def _impact_label(impact: str | None) -> str:
    return {"positive": "利好", "negative": "利空", "mixed": "冲突"}.get(str(impact or ""), "中性")


def _impact_tone(impact: str | None) -> str:
    return {"positive": "ok", "negative": "bad", "mixed": "warn"}.get(str(impact or ""), "neutral")


def _impact_degree_text(impact: str | None, materiality: str) -> str:
    label = _impact_label(impact)
    if materiality == "A":
        detail = "可能改变板块风险偏好" if impact == "negative" else "可能成为主线级催化"
    elif materiality == "B":
        detail = "可作为催化线索，但需量价验证"
    elif materiality == "C":
        detail = "只作背景观察，不进入重点跟踪"
    else:
        detail = "信息强度较低，仅作背景"
    return f"{materiality}级{label}：{detail}"


def _event_bucket(impact: str | None, source_quality: str, source_meta: dict) -> str:
    if source_meta.get("original_source") == "未知":
        return "unverified"
    if impact == "negative":
        return "risk"
    if impact == "positive":
        return "positive"
    return "mixed"


def _event_bucket(
    impact: str | None,
    source_quality: str,
    source_meta: dict,
    source_url: str,
    freshness_bucket: str,
) -> str:
    if _source_has_gap(source_meta, source_url):
        return "unverified"
    if freshness_bucket == "background":
        return "background"
    if impact == "negative":
        return "risk"
    if impact == "positive":
        return "positive"
    return "mixed"


def _trade_priority(
    impact: str | None,
    materiality: str,
    source_meta: dict,
    source_url: str,
    freshness_bucket: str,
) -> str:
    if _source_has_gap(source_meta, source_url):
        return "source_gap"
    if freshness_bucket == "background":
        return "background"
    if impact == "negative" and materiality in {"A", "B"}:
        return "risk"
    if impact == "positive" and materiality in {"A", "B"}:
        return "catalyst"
    return "watch"


def _freshness_bucket(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= 0:
        return "today"
    if age_days <= 2:
        return "active"
    return "background"


def _freshness_label(age_days: int | None) -> str:
    if age_days is None:
        return "时效待核验"
    if age_days <= 0:
        return "D0 今日催化"
    if age_days <= 2:
        return f"D{age_days} 发酵中"
    if age_days <= 5:
        return f"D{age_days} 背景观察"
    return f"D{age_days} 过期背景"


def _source_channel(source_meta: dict) -> str:
    collection = str(source_meta.get("collection_source") or "")
    if not collection or _is_unknown_source(collection):
        return "新闻缓存"
    if "缓存" in collection or "缂撳瓨" in collection:
        return "新闻缓存"
    return collection


def _source_confidence_note(source_meta: dict, source_url: str) -> str:
    if not source_url:
        return "缺原文，降级为待核验"
    if _is_unknown_source(source_meta.get("original_source")):
        return "原始媒体待核验"
    return "原文可核验"


def _source_has_gap(source_meta: dict, source_url: str) -> bool:
    return (not source_url) or _is_unknown_source(source_meta.get("original_source"))


def _is_unknown_source(value) -> bool:
    text = str(value or "").strip()
    return (not text) or text in {"未知", "鏈煡", "unknown", "Unknown", "UNKNOWN"}


def _effect_summary(impact: str | None, materiality: str, sectors: list[str], mapping_confidence: str) -> str:
    sector_text = "、".join(sectors[:3]) if sectors else "相关行业"
    if impact == "negative":
        return f"压制{sector_text}风险偏好，先看风险是否继续释放。"
    if impact == "positive":
        if materiality in {"A", "B"}:
            return f"强化{sector_text}催化线索，需看板块是否放量承接。"
        return f"{sector_text}偏背景利好，等待量价确认。"
    if mapping_confidence == "broad":
        return f"{sector_text}映射较泛，先当背景线索处理。"
    return f"{sector_text}方向仍有分歧，等待后续来源确认。"


def _anchor(prefix: str, value: str) -> str:
    text = str(value or "").strip()
    return f"{prefix}-{text}" if text else ""


def _materiality(strength, event_type: str, source_quality: str, mapping_confidence: str) -> str:
    score = int(strength or 0)
    text = str(event_type or "")
    if any(token in text for token in ("政策", "监管", "订单", "业绩", "价格", "产业")):
        score += 1
    if source_quality in {"官方/监管", "公司公告"}:
        score += 1
    if mapping_confidence == "broad":
        score -= 1
    if score >= 8:
        return "A"
    if score >= 6:
        return "B"
    if score >= 3:
        return "C"
    return "D"


def _mapping_confidence(sectors: list[str], event_type: str | None, reason: str) -> str:
    text = f"{event_type or ''} {reason or ''}".lower()
    generic_terms = ("ai", "算力", "人工智能", "科技", "出口", "产业链", "基建")
    if len(sectors) >= 4:
        return "broad"
    if len(sectors) >= 3 and any(term in text for term in generic_terms):
        return "broad"
    if len(sectors) == 1:
        return "precise"
    return "medium"


def _source_quality(raw_sources: list[dict]) -> str:
    text = " ".join(
        str(source.get(key) or "")
        for source in raw_sources
        for key in ("provider", "source", "title")
    ).lower()
    if any(token in text for token in ("official", "交易所", "证监", "监管", "发改委", "工信部", "央行")):
        return "官方/监管"
    if any(token in text for token in ("公告", "公司", "董秘")):
        return "公司公告"
    if any(token in text for token in ("caixin", "财新", "证券时报", "上证报", "中证报", "第一财经")):
        return "主流财经"
    if raw_sources:
        return "普通媒体"
    return "来源待核验"


def _verification_points(impact: str | None, sectors: list[str]) -> list[str]:
    direction = "承接" if impact == "positive" else "风险释放" if impact == "negative" else "分歧"
    sector_text = "、".join(sectors[:3]) if sectors else "相关行业"
    return [
        f"观察{sector_text}是否出现放量{direction}",
        "跟踪消息是否有后续权威来源或细则确认",
        "检查策略信号是否在同方向行业内扩散",
    ]


def _invalidation_points(impact: str | None, sectors: list[str]) -> list[str]:
    sector_text = "、".join(sectors[:3]) if sectors else "相关行业"
    if impact == "positive":
        return [f"{sector_text}未放量或高开低走", "后续新闻被证伪或缺少政策/订单细节"]
    if impact == "negative":
        return [f"{sector_text}未继续走弱", "负面消息影响范围被澄清"]
    return [f"{sector_text}没有形成一致方向", "事件影响路径无法确认"]


def _risk_note(mapping_confidence: str, impact: str | None) -> str:
    if mapping_confidence == "broad":
        return "行业映射偏泛化，适合作背景线索，不宜单独作为强催化。"
    if impact == "negative":
        return "负面事件需要先看风险释放，不宜只按反弹线索理解。"
    return "仍需用量价承接验证，新闻本身不构成买入依据。"


def _evidence_urls(raw_sources: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for source in raw_sources:
        url = str(source.get("url") or "").strip()
        title = str(source.get("title") or "").strip()
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "title": title,
                "source": str(source.get("source") or source.get("provider") or "").strip(),
                "provider": str(source.get("provider") or "").strip(),
                "url": url,
                "publish_time": str(source.get("publish_time") or "").strip(),
                "collected_at": str(source.get("collected_at") or "").strip(),
            }
        )
    return result


def _source_meta(raw_sources: list[dict], payload: dict) -> dict:
    source = raw_sources[0] if raw_sources else {}
    original_source = str(source.get("source") or source.get("provider") or "").strip() or "未知"
    source_name = original_source if original_source != "未知" else "本地新闻缓存"
    publish_time = str(
        source.get("publish_time")
        or source.get("datetime")
        or source.get("time")
        or source.get("date")
        or ""
    ).strip()
    if not publish_time:
        publish_time = _publish_time_from_url(source.get("url"))
    collected_at = str(
        source.get("collected_at")
        or payload.get("collected_at")
        or payload.get("updated_at")
        or payload.get("date")
        or ""
    ).strip()
    return {
        "source_name": source_name,
        "original_source": original_source,
        "collection_source": "本地新闻缓存",
        "publish_time": publish_time or "未知",
        "collected_at": collected_at or "未知",
    }


def _publish_time_from_url(url: str | None) -> str:
    text = str(url or "")
    match = re.search(r"/((?:20)\d{2})-(\d{2})-(\d{2})/", text)
    if match:
        return "-".join(match.groups())
    match = re.search(r"((?:20)\d{2})(\d{2})(\d{2})", text)
    if match:
        return "-".join(match.groups())
    return ""


def _catalyst_age_days(publish_time: str | None, source_date: str | None) -> int | None:
    publish_dt = _parse_date(publish_time)
    source_dt = _parse_date(source_date)
    if not publish_dt or not source_dt:
        return None
    return max(0, (source_dt.date() - publish_dt.date()).days)


def _catalyst_clock(age_days: int | None) -> str:
    if age_days is None:
        return "时效未知"
    if age_days <= 0:
        return "D0 新催化"
    if age_days <= 2:
        return f"D{age_days} 发酵中"
    if age_days <= 5:
        return f"D{age_days} 谨防兑现"
    return "过期，仅作背景"


def _parse_date(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text or text == "未知":
        return None
    formats = (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y%m%d%H%M%S", 14),
        ("%Y%m%d", 8),
    )
    for fmt, width in formats:
        try:
            return datetime.strptime(text[:width], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _raw_news_index(payload: dict) -> dict[str, dict]:
    result = {}
    for item in payload.get("raw_news") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        result[_normalize_title(title)] = item
    return result


def _find_raw_source(title: str, raw_index: dict[str, dict], reason: str = "") -> dict | None:
    key = _normalize_title(title)
    if key in raw_index:
        return raw_index[key]
    for raw_key, item in raw_index.items():
        if key and (key in raw_key or raw_key in key):
            return item
    query_key = _normalize_title(f"{title} {reason}")
    best_item = None
    best_score = 0.0
    for raw_key, item in raw_index.items():
        score = max(
            SequenceMatcher(None, key, raw_key).ratio(),
            SequenceMatcher(None, query_key, raw_key).ratio(),
            _char_overlap_score(query_key, raw_key),
        )
        if score > best_score:
            best_score = score
            best_item = item
    if best_score >= 0.20:
        return best_item
    return None


def _char_overlap_score(query: str, candidate: str) -> float:
    query_chars = {char for char in str(query or "") if char.isalnum()}
    candidate_chars = {char for char in str(candidate or "") if char.isalnum()}
    if not query_chars or not candidate_chars:
        return 0.0
    return len(query_chars & candidate_chars) / len(query_chars)


def _event_id(title: str, event_type: str | None, date: str | None) -> str:
    raw = f"{date or ''}|{event_type or ''}|{title or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_title(title: str) -> str:
    return "".join(str(title or "").split()).lower()


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _top_materiality(values: list[str]) -> str:
    if not values:
        return "-"
    return sorted(values, key=_materiality_rank, reverse=True)[0]


def _materiality_rank(value: str) -> int:
    return {"A": 4, "B": 3, "C": 2, "D": 1}.get(str(value), 0)


def _novelty(title: str) -> str:
    text = str(title or "")
    if any(token in text for token in ("再", "继续", "延续")):
        return "延续事件"
    return "新事件"


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _num(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
