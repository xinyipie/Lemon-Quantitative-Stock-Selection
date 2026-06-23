"""Build stock-level evidence cards for Market Radar v2."""

from __future__ import annotations


def build_stock_evidence(candidates: list[dict], sector_theses: list[dict], limit: int = 12) -> list[dict]:
    """Convert sector candidates into research evidence cards."""
    thesis_map = {str(item.get("industry") or ""): item for item in sector_theses or [] if isinstance(item, dict)}
    cards = [_build_one_card(dict(item), thesis_map.get(str(item.get("industry") or ""))) for item in candidates or [] if isinstance(item, dict)]
    cards.sort(key=lambda item: (item["evidence_score"], _num(item.get("candidate_score"))), reverse=True)
    return cards[: max(0, int(limit))]


def _build_one_card(candidate: dict, thesis: dict | None) -> dict:
    role = _stock_role(candidate)
    event_relevance = _event_relevance(thesis)
    market_behavior = _market_behavior(candidate)
    strategy_alignment = _strategy_alignment(candidate)
    risks = _risks(candidate, thesis, role, event_relevance)
    action = _research_action(candidate, thesis, role, risks)
    reason_cards = _reason_cards(candidate, thesis, role, event_relevance, market_behavior, strategy_alignment)
    evidence_score = _evidence_score(candidate, thesis, role, event_relevance, market_behavior, risks)
    resonance = _resonance(thesis, role, event_relevance, strategy_alignment, risks)
    validation_conditions = _validation_conditions(candidate, thesis, resonance, action, role, risks)
    return {
        "ts_code": str(candidate.get("ts_code") or ""),
        "name": str(candidate.get("name") or ""),
        "industry": str(candidate.get("industry") or ""),
        "candidate_score": _num(candidate.get("candidate_score")),
        "stock_role": role,
        "event_relevance": event_relevance,
        "market_behavior": market_behavior,
        "strategy_alignment": strategy_alignment,
        "research_action": action,
        "resonance_level": resonance["level"],
        "resonance_label": resonance["label"],
        "validation_conditions": validation_conditions,
        "evidence_score": evidence_score,
        "reason_cards": reason_cards,
        "risks": risks,
        "source_candidate": candidate,
        "sector_thesis": thesis or {},
    }


def _resonance(thesis: dict | None, role: str, event_relevance: str, strategy_alignment: str, risks: list[str]) -> dict:
    if risks and event_relevance == "椋庨櫓鐩稿叧":
        return {"level": "冲突", "label": "策略触发但事件/主线冲突"}
    if not thesis:
        return {"level": "★", "label": "孤儿信号"}
    has_event = event_relevance in {"琛屼笟涓荤嚎鍙楃泭", "浜嬩欢鐩稿叧", "行业主线受益", "事件相关"}
    is_mainline = str(thesis.get("thesis_label") or "") in {"涓荤嚎鍏辨尟", "瓒嬪娍涓荤嚎", "主线共振", "趋势主线"}
    is_strategy = strategy_alignment != "浠呮澘鍧楀€欓€?"
    if is_mainline and has_event and role in {"棰嗘定", "璺熼殢", "领涨", "跟随"}:
        return {"level": "★★★", "label": "策略+主线+事件共振"}
    if is_mainline or has_event:
        return {"level": "★★", "label": "策略+主线待补事件"}
    return {"level": "★", "label": "孤儿信号" if not is_strategy else "策略信号待补主线"}


def _validation_conditions(
    candidate: dict,
    thesis: dict | None,
    resonance: dict,
    action: str,
    role: str,
    risks: list[str],
) -> list[str]:
    industry = str(candidate.get("industry") or "所属行业")
    conditions = []
    if resonance.get("level") == "★★★":
        conditions.append(f"盘中观察：{industry}前60分钟成交额是否高于近5日同段均值。")
        conditions.append("验证条件：个股相对板块保持领先，放量后不快速回落。")
    elif resonance.get("label") == "孤儿信号":
        conditions.append("先补证据：等待所属行业进入健康主线或出现权威来源催化。")
        conditions.append("验证条件：策略信号不能只靠单股量价，需有板块扩散。")
    else:
        conditions.append(f"验证条件：{industry}继续承接，事件线索有后续来源确认。")
    if role == "杩囩儹" or action == "绛夊洖韪╃‘璁?":
        conditions.append("冷却条件：回踩后不破关键均线，再观察承接质量。")
    if risks:
        conditions.append("失效条件：" + "；".join(risks[:2]))
    return _unique(conditions)[:4]


def _stock_role(candidate: dict) -> str:
    note = str(candidate.get("risk_note") or "")
    ret_5d = _num(candidate.get("ret_5d"))
    ret_10d = _num(candidate.get("ret_10d"))
    relative = _num(candidate.get("stock_vs_sector_10d"))
    if "不追高" in note or ret_5d >= 15 or ret_10d >= 25:
        return "过热"
    if relative <= -8:
        return "掉队"
    if relative >= 5 and ret_10d >= 8:
        return "领涨"
    if relative >= 0:
        return "跟随"
    return "补涨"


def _event_relevance(thesis: dict | None) -> str:
    if not thesis:
        return "无事件支撑"
    if thesis.get("thesis_label") == "风险冲突":
        return "风险相关"
    events = thesis.get("events") or []
    if any(event.get("impact") == "negative" for event in events):
        return "风险相关"
    if any(event.get("mapping_confidence") == "broad" for event in events):
        return "泛题材"
    if thesis.get("thesis_label") == "主线共振":
        return "行业主线受益"
    if events:
        return "事件相关"
    return "无事件支撑"


def _market_behavior(candidate: dict) -> str:
    volume = _num(candidate.get("volume_ratio"), 1.0)
    ret_10d = _num(candidate.get("ret_10d"))
    relative = _num(candidate.get("stock_vs_sector_10d"))
    if volume >= 1.5 and relative >= 0:
        return "放量承接"
    if ret_10d >= 18 or relative >= 10:
        return "追高"
    if volume <= 0.8 and ret_10d >= 0:
        return "缩量整理"
    if relative < -5:
        return "资金分歧"
    return "正常观察"


def _strategy_alignment(candidate: dict) -> str:
    text = " ".join(str(candidate.get(key) or "") for key in ("mode", "profile", "pool_type", "strategy_signal"))
    if "long" in text.lower() or "longterm" in text.lower() or "v18" in text:
        return "长线共振"
    if "short" in text.lower() or "v9" in text:
        return "短线共振"
    if text.strip():
        return "策略信号待确认"
    return "仅板块候选"


def _research_action(candidate: dict, thesis: dict | None, role: str, risks: list[str]) -> str:
    note = str(candidate.get("risk_note") or "")
    if "不追高" in note or role == "过热":
        return "等回踩确认"
    if thesis and thesis.get("research_action") in {"仅复盘", "暂不参与"}:
        return "仅复盘"
    if role == "掉队" or any("相对板块落后" in item for item in risks):
        return "先放观察池"
    if thesis and thesis.get("research_action") == "可重点跟踪" and _num(candidate.get("candidate_score")) >= 70:
        return "可重点跟踪"
    if thesis and thesis.get("research_action") == "等回踩确认":
        return "等回踩确认"
    return "先放观察池"


def _risks(candidate: dict, thesis: dict | None, role: str, event_relevance: str) -> list[str]:
    risks = []
    note = str(candidate.get("risk_note") or "").strip()
    if _is_risk_note(note):
        risks.append(note)
    if role == "掉队":
        risks.append("相对板块落后")
    if event_relevance == "泛题材":
        risks.append("事件映射偏泛，需避免题材泛化")
    if thesis:
        risks.extend(str(item) for item in thesis.get("risks") or [] if item)
    return _unique(risks)


def _reason_cards(
    candidate: dict,
    thesis: dict | None,
    role: str,
    event_relevance: str,
    market_behavior: str,
    strategy_alignment: str,
) -> list[dict]:
    return [
        {"type": "量价", "label": market_behavior, "detail": _market_detail(candidate, role)},
        {"type": "事件", "label": event_relevance, "detail": _event_detail(thesis)},
        {"type": "策略", "label": strategy_alignment, "detail": "用于和正式短线/长线信号做交叉验证。"},
        {"type": "风险", "label": "需核验", "detail": _risk_detail(candidate)},
    ]


def _risk_detail(candidate: dict) -> str:
    note = str(candidate.get("risk_note") or "").strip()
    return note if _is_risk_note(note) else "暂无额外风险备注。"


def _is_risk_note(note: str) -> bool:
    text = str(note or "")
    return any(token in text for token in ("不追高", "风险", "退潮", "破位", "偏高", "落后", "分歧", "流出", "减持"))


def _market_detail(candidate: dict, role: str) -> str:
    relative = _num(candidate.get("stock_vs_sector_10d"))
    ret_10d = _num(candidate.get("ret_10d"))
    return f"{role}；10日收益{ret_10d:+.2f}%，相对板块{relative:+.2f}%。"


def _event_detail(thesis: dict | None) -> str:
    if not thesis:
        return "暂无明确事件支撑，先看量价是否独立走强。"
    events = thesis.get("events") or []
    if events:
        return str(events[0].get("title") or "事件线索待核验")
    return str(thesis.get("summary") or "行业 thesis 待核验。")


def _evidence_score(candidate: dict, thesis: dict | None, role: str, event_relevance: str, market_behavior: str, risks: list[str]) -> int:
    score = _num(candidate.get("candidate_score"))
    if thesis:
        score += _num(thesis.get("thesis_score")) * 0.25
    if role in {"领涨", "跟随"}:
        score += 8
    if event_relevance == "行业主线受益":
        score += 10
    elif event_relevance == "泛题材":
        score -= 6
    if market_behavior == "放量承接":
        score += 8
    if any("不追高" in item or "相对板块落后" in item for item in risks):
        score -= 12
    return _clamp(score)


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(round(value))))


def _unique(rows: list[str]) -> list[str]:
    result = []
    for row in rows:
        text = str(row or "").strip()
        if text and text not in result:
            result.append(text)
    return result
