"""Build research theses from sector heat and standardized news events."""

from __future__ import annotations

from collections import defaultdict


def build_sector_theses(radar: dict, events: list[dict], limit: int = 12) -> list[dict]:
    """Build sector-level research thesis cards for Market Radar v2."""
    healthy = _by_industry(radar.get("healthy") or [])
    risky = _by_industry(radar.get("risky") or [])
    event_map = _events_by_industry(events)
    industries = []
    for name in list(healthy) + list(risky) + list(event_map):
        if name and name not in industries:
            industries.append(name)

    theses = [
        _build_one_thesis(industry, healthy.get(industry), risky.get(industry), event_map.get(industry) or [])
        for industry in industries
    ]
    theses.sort(key=lambda item: (item["thesis_score"], item["event_score"], item["market_validation_score"]), reverse=True)
    return theses[: max(0, int(limit))]


def _build_one_thesis(industry: str, healthy: dict | None, risky: dict | None, events: list[dict]) -> dict:
    positive_events = [event for event in events if event.get("impact") == "positive"]
    negative_events = [event for event in events if event.get("impact") == "negative"]
    best_event = _best_event(events)
    market_score = _market_validation_score(healthy, risky)
    event_score = _event_score(events)
    risk_score = _risk_score(risky, negative_events, events)
    thesis_score = _clamp(round(market_score * 0.45 + event_score * 0.4 - risk_score * 0.25 + 10))
    if healthy and positive_events and not negative_events:
        thesis_score = max(thesis_score, min(90, round((market_score + event_score) * 0.5 + 22)))
    label, action, conviction = _classify_thesis(healthy, risky, positive_events, negative_events, thesis_score)
    evidence = _evidence(industry, healthy, best_event, positive_events)
    risks = _risks(risky, negative_events, events)
    verification_points = _verification_points(industry, healthy, best_event)
    return {
        "industry": industry,
        "thesis_label": label,
        "research_action": action,
        "conviction": conviction,
        "thesis_score": thesis_score,
        "event_score": event_score,
        "market_validation_score": market_score,
        "risk_score": risk_score,
        "summary": _summary(industry, label, healthy, best_event),
        "evidence": evidence,
        "risks": risks,
        "verification_points": verification_points,
        "events": events[:3],
    }


def _classify_thesis(
    healthy: dict | None,
    risky: dict | None,
    positive_events: list[dict],
    negative_events: list[dict],
    thesis_score: int,
) -> tuple[str, str, str]:
    if negative_events and (risky or not healthy):
        return "风险冲突", "仅复盘", "低"
    if risky:
        return "过热风险", "等回踩确认", "中"
    if healthy and positive_events:
        return "主线共振", "可重点跟踪", "高" if thesis_score >= 75 else "中"
    if healthy:
        return "趋势主线", "可重点跟踪" if thesis_score >= 70 else "先放观察池", "中"
    if positive_events:
        return "消息待验证", "先放观察池", "中"
    return "无主线", "仅复盘", "低"


def _market_validation_score(healthy: dict | None, risky: dict | None) -> int:
    if healthy:
        heat = _num(healthy.get("heat_score"), 60.0)
        volume = _num(healthy.get("volume_ratio"), 1.0)
        return _clamp(round(heat * 0.75 + min(volume, 2.0) * 12))
    if risky:
        heat = _num(risky.get("heat_score"), 55.0)
        return _clamp(round(heat * 0.35))
    return 0


def _event_score(events: list[dict]) -> int:
    if not events:
        return 0
    score = 0
    for event in events[:4]:
        score += {"A": 34, "B": 24, "C": 14, "D": 6}.get(str(event.get("materiality") or "D"), 6)
        if event.get("source_quality") in {"官方/监管", "公司公告"}:
            score += 8
        if event.get("mapping_confidence") == "broad":
            score -= 8
        if event.get("impact") == "negative":
            score -= 10
    return _clamp(score)


def _risk_score(risky: dict | None, negative_events: list[dict], events: list[dict]) -> int:
    score = 0
    if risky:
        score += 35
    score += len(negative_events) * 28
    score += sum(12 for event in events if event.get("mapping_confidence") == "broad")
    return _clamp(score)


def _evidence(industry: str, healthy: dict | None, best_event: dict | None, positive_events: list[dict]) -> list[str]:
    rows = []
    if healthy:
        stage = str(healthy.get("stage") or "趋势改善")
        rows.append(f"{industry}处于{stage}，量价热度进入可观察区。")
    if best_event:
        rows.append(f"{best_event.get('materiality', '-') }级事件：{best_event.get('title', '')}")
    if len(positive_events) > 1:
        rows.append(f"同方向正面事件 {len(positive_events)} 条，具备连续跟踪价值。")
    return rows


def _risks(risky: dict | None, negative_events: list[dict], events: list[dict]) -> list[str]:
    rows = []
    if risky:
        rows.append("板块热度偏高或处于风险阶段，避免按新闻热度追高。")
    for event in negative_events[:2]:
        rows.append(f"负面事件：{event.get('title', '')}")
    for event in events:
        note = str(event.get("risk_note") or "").strip()
        if event.get("mapping_confidence") == "broad" and note and note not in rows:
            rows.append(note)
    return rows


def _verification_points(industry: str, healthy: dict | None, best_event: dict | None) -> list[str]:
    rows = []
    if best_event:
        rows.extend([str(item) for item in best_event.get("verification_points") or [] if item])
    if healthy:
        rows.append(f"跟踪{industry}是否继续强于市场并保持成交承接。")
    else:
        rows.append(f"先验证{industry}是否从消息热度扩散到量价承接。")
    return rows[:4]


def _summary(industry: str, label: str, healthy: dict | None, best_event: dict | None) -> str:
    event_part = f"，核心事件为{best_event.get('title')}" if best_event else ""
    if healthy:
        return f"{industry}属于{label}，已有市场热度支撑{event_part}。"
    return f"{industry}属于{label}，当前主要来自消息线索{event_part}。"


def _events_by_industry(events: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for event in events or []:
        if not isinstance(event, dict):
            continue
        for industry in event.get("mapped_industries") or []:
            name = str(industry or "").strip()
            if name:
                result[name].append(event)
    return result


def _by_industry(rows: list[dict]) -> dict[str, dict]:
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("industry") or "").strip()
        if name:
            result[name] = row
    return result


def _best_event(events: list[dict]) -> dict | None:
    if not events:
        return None
    return sorted(events, key=lambda event: (_materiality_rank(event.get("materiality")), _num(event.get("strength"), 0)), reverse=True)[0]


def _materiality_rank(value) -> int:
    return {"A": 4, "B": 3, "C": 2, "D": 1}.get(str(value), 0)


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: int | float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))
