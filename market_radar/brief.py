"""Aggregate Market Radar v2 outputs into a page-friendly research brief."""

from __future__ import annotations


def build_research_brief(
    decision: dict,
    concept_news: dict,
    radar: dict,
    strategy_overlap: dict | None = None,
) -> dict:
    """Build a stable research brief for the Market Radar v2 UI."""
    review = decision.get("review_loop") if isinstance(decision.get("review_loop"), dict) else {}
    data_quality = _data_quality(decision, review, concept_news)
    sector_theses = list(decision.get("sector_theses") or [])
    stock_watchlist = list(decision.get("stock_watchlist") or [])
    events = list(concept_news.get("events") or [])
    event_groups = _event_groups(events)
    trade_event_groups = _trade_event_groups(events)
    risk_board = _risk_board(review, sector_theses, stock_watchlist)
    verification = _verification_checklist(review, sector_theses, events)
    risk_blocker = _risk_blocker(data_quality, sector_theses, events, risk_board)
    return {
        "headline": _headline(decision, review, data_quality),
        "market_regime_note": _market_note(decision, radar),
        "risk_blocker": risk_blocker,
        "mainlines": _mainlines(sector_theses),
        "event_watchlist": events[:8],
        "event_groups": event_groups,
        "trade_event_groups": trade_event_groups,
        "sector_theses": sector_theses[:12],
        "stock_watchlist": stock_watchlist[:12],
        "risk_board": risk_board,
        "verification_checklist": verification,
        "data_quality": data_quality,
        "event_summary": concept_news.get("event_summary") or {},
        "snapshot_summary": {
            "event_count": len(events),
            "thesis_count": len(sector_theses),
            "stock_count": len(stock_watchlist),
            "risk_count": len(risk_board),
        },
        "strategy_overlap": strategy_overlap or {},
}


def _trade_event_groups(events: list[dict]) -> dict:
    rows = [item for item in events if isinstance(item, dict)]
    groups = {
        "catalysts": [],
        "risks": [],
        "background": [],
        "source_gaps": [],
        "watch": [],
        "all": rows[:8],
    }
    for event in rows:
        priority = str(event.get("trade_priority") or "")
        if priority == "catalyst":
            groups["catalysts"].append(event)
        elif priority == "risk":
            groups["risks"].append(event)
        elif priority == "background":
            groups["background"].append(event)
        elif priority == "source_gap":
            groups["source_gaps"].append(event)
        else:
            groups["watch"].append(event)
    for key in ("catalysts", "risks", "background", "source_gaps", "watch"):
        groups[key] = groups[key][:6]
    return groups


def _event_groups(events: list[dict]) -> dict:
    rows = [item for item in events if isinstance(item, dict)]
    groups = {
        "risk": [],
        "positive": [],
        "unverified": [],
        "mixed": [],
        "all": rows[:8],
    }
    for event in rows:
        bucket = str(event.get("event_bucket") or "")
        if bucket == "background":
            groups["mixed"].append(event)
            continue
        if bucket == "unverified":
            groups["unverified"].append(event)
            continue
        if bucket == "risk" or event.get("impact") == "negative":
            groups["risk"].append(event)
        elif bucket == "positive" or event.get("impact") == "positive":
            groups["positive"].append(event)
        else:
            groups["mixed"].append(event)
    for key in ("risk", "positive", "unverified", "mixed"):
        groups[key] = groups[key][:6]
    return groups


def _risk_blocker(data_quality: dict, theses: list[dict], events: list[dict], risk_board: list[dict]) -> dict:
    severe_event = _severe_negative_event(theses, events)
    if severe_event:
        return {
            "level": "暂停新关注",
            "tone": "danger",
            "reason": severe_event,
            "research_guardrail": "先记录风险释放和承接修复，不把负面冲击后的反弹当作新机会。",
        }
    if risk_board:
        first = risk_board[0]
        return {
            "level": "谨慎跟踪",
            "tone": "warn",
            "reason": f"{first.get('target') or first.get('type') or '风险项'}：{first.get('reason') or '待核验'}",
            "research_guardrail": "先核验风险是否扩散，再决定是否保留观察。",
        }
    if data_quality.get("tone") == "warn":
        return {
            "level": "谨慎跟踪",
            "tone": "warn",
            "reason": "数据日期或来源置信度需要降权。",
            "research_guardrail": "优先补齐数据，再使用结论。",
        }
    return {
        "level": "可研究",
        "tone": "ok",
        "reason": "暂无强阻断项。",
        "research_guardrail": "仍需用量价承接和后续来源验证。",
    }


def _severe_negative_event(theses: list[dict], events: list[dict]) -> str:
    risk_industries = {
        str(item.get("industry") or "")
        for item in theses
        if str(item.get("thesis_label") or "") in {"风险冲突", "椋庨櫓鍐茬獊", "退潮风险", "閫€娼闄?"}
    }
    for event in events:
        if event.get("event_bucket") == "background" or event.get("trade_priority") == "background":
            continue
        if event.get("impact") != "negative" or event.get("materiality") != "A":
            continue
        industries = [str(item) for item in event.get("mapped_industries") or [] if item]
        hit = [industry for industry in industries if industry in risk_industries]
        if hit:
            return f"{'、'.join(hit[:3])} 命中A级负面事件：{event.get('title') or '未命名事件'}"
    return ""


def _headline(decision: dict, review: dict, data_quality: dict) -> str:
    judgement = str(review.get("closing_judgement") or decision.get("alignment") or "无明确主线")
    alignment = str(decision.get("alignment") or "无明确主线")
    suffix = "，结论需降置信。" if data_quality.get("tone") == "warn" else "。"
    if judgement == alignment:
        return f"{judgement}{suffix}"
    return f"{judgement}：{alignment}{suffix}"


def _market_note(decision: dict, radar: dict) -> str:
    primary = str(decision.get("primary_action") or "")
    radar_headline = str((radar.get("summary") or {}).get("headline") or "")
    if primary and radar_headline:
        return f"{radar_headline}；{primary}"
    return primary or radar_headline or "暂无可用市场摘要。"


def _mainlines(theses: list[dict]) -> list[dict]:
    return [
        item
        for item in theses
        if item.get("thesis_label") in {"主线共振", "趋势主线"} and item.get("research_action") != "仅复盘"
    ][:6]


def _risk_board(review: dict, theses: list[dict], stocks: list[dict]) -> list[dict]:
    rows = list(review.get("risk_audit") or [])
    for thesis in theses:
        if thesis.get("thesis_label") in {"风险冲突", "过热风险", "退潮风险"}:
            rows.append(
                {
                    "type": "行业风险",
                    "target": thesis.get("industry"),
                    "reason": "；".join(str(item) for item in thesis.get("risks") or [] if item)
                    or thesis.get("thesis_label"),
                }
            )
    for stock in stocks:
        if stock.get("research_action") in {"等回踩确认", "仅复盘"}:
            rows.append(
                {
                    "type": "个股风险",
                    "target": f"{stock.get('name') or ''} {stock.get('ts_code') or ''}".strip(),
                    "reason": "；".join(str(item) for item in stock.get("risks") or [] if item)
                    or stock.get("research_action"),
                }
            )
    return _unique_risks(rows)[:10]


def _verification_checklist(review: dict, theses: list[dict], events: list[dict]) -> list[str]:
    points = [str(item) for item in review.get("next_day_watch_points") or [] if item]
    for thesis in theses:
        points.extend(str(item) for item in thesis.get("verification_points") or [] if item)
    for event in events:
        points.extend(str(item) for item in event.get("verification_points") or [] if item)
    return _unique_text(points)[:10]


def _data_quality(decision: dict, review: dict, concept_news: dict) -> dict:
    alignment = decision.get("data_alignment") if isinstance(decision.get("data_alignment"), dict) else {}
    review_quality = review.get("data_quality") if isinstance(review.get("data_quality"), dict) else {}
    aligned = bool(alignment.get("aligned", review_quality.get("aligned", True)))
    reasons = []
    reasons.extend(str(item) for item in review_quality.get("reasons") or [] if item)
    if not aligned and alignment.get("message"):
        reasons.append(str(alignment.get("message")))
    event_summary = concept_news.get("event_summary") or {}
    return {
        "aligned": aligned,
        "tone": "ok" if aligned and not reasons else "warn",
        "sector_date": alignment.get("sector_date"),
        "news_date": alignment.get("news_date"),
        "concept_date": alignment.get("concept_date"),
        "theme_date": alignment.get("theme_date"),
        "event_count": int(event_summary.get("event_count") or 0),
        "news_source_count": int(event_summary.get("source_count") or 0),
        "low_confidence_reasons": _unique_text(reasons),
    }


def _unique_text(values: list[str]) -> list[str]:
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _unique_risks(rows: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for row in rows:
        key = (str(row.get("type") or ""), str(row.get("target") or ""), str(row.get("reason") or ""))
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result
