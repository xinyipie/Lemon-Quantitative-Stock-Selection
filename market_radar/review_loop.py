"""Build review-loop summaries for Market Radar v2."""

from __future__ import annotations


def build_review_loop(decision: dict) -> dict:
    """Summarize validation, failure reasons, and next watch points."""
    theses = [item for item in decision.get("sector_theses") or [] if isinstance(item, dict)]
    stocks = [item for item in decision.get("stock_watchlist") or [] if isinstance(item, dict)]
    data_alignment = decision.get("data_alignment") if isinstance(decision.get("data_alignment"), dict) else {}
    validated = [_validated_mainline(item) for item in theses if _is_validated(item)]
    unverified = [_unverified_or_failed(item) for item in theses if not _is_validated(item)]
    risk_audit = _risk_audit(theses, stocks)
    next_points = _next_day_watch_points(theses, stocks, risk_audit)
    data_quality = _data_quality(data_alignment)
    return {
        "closing_judgement": _closing_judgement(validated, unverified, risk_audit, data_quality),
        "validated_mainlines": validated,
        "unverified_or_failed": unverified,
        "risk_audit": risk_audit,
        "next_day_watch_points": next_points,
        "data_quality": data_quality,
        "audit_note": "复盘闭环只记录研究验证状态，不构成交易执行建议。",
    }


def _is_validated(thesis: dict) -> bool:
    return (
        thesis.get("thesis_label") == "主线共振"
        and _num(thesis.get("market_validation_score")) >= 60
        and _num(thesis.get("event_score")) >= 30
        and thesis.get("research_action") == "可重点跟踪"
    )


def _validated_mainline(thesis: dict) -> dict:
    industry = str(thesis.get("industry") or "")
    return {
        "industry": industry,
        "status": "已验证",
        "reason": f"{industry}同时具备事件强度和量价验证。",
        "market_validation_score": _num(thesis.get("market_validation_score")),
        "event_score": _num(thesis.get("event_score")),
        "next_check": _first(thesis.get("verification_points"), f"观察{industry}是否延续承接。"),
    }


def _unverified_or_failed(thesis: dict) -> dict:
    industry = str(thesis.get("industry") or "")
    reason = _failure_reason(thesis)
    return {
        "industry": industry,
        "status": "待验证" if "未验证" in reason else "需复盘",
        "reason": reason,
        "market_validation_score": _num(thesis.get("market_validation_score")),
        "event_score": _num(thesis.get("event_score")),
        "next_check": _first(thesis.get("verification_points"), f"继续核验{industry}是否获得市场确认。"),
    }


def _failure_reason(thesis: dict) -> str:
    label = str(thesis.get("thesis_label") or "")
    market_score = _num(thesis.get("market_validation_score"))
    event_score = _num(thesis.get("event_score"))
    if label in {"风险冲突", "过热风险", "退潮风险"}:
        risks = "；".join(str(item) for item in thesis.get("risks") or [] if item)
        return risks or f"{label}，先做风险复盘。"
    if event_score >= 50 and market_score < 40:
        return "量价未验证，新闻线索暂不能升级为主线。"
    if market_score >= 50 and event_score < 30:
        return "有量价热度但缺少事件支撑，需防止纯情绪扩散。"
    return "证据不足，继续观察。"


def _risk_audit(theses: list[dict], stocks: list[dict]) -> list[dict]:
    rows = []
    for thesis in theses:
        if thesis.get("thesis_label") in {"风险冲突", "过热风险", "退潮风险"} or _num(thesis.get("risk_score")) >= 60:
            rows.append(
                {
                    "type": "行业风险",
                    "industry": str(thesis.get("industry") or ""),
                    "target": str(thesis.get("industry") or ""),
                    "reason": _failure_reason(thesis),
                }
            )
    for stock in stocks:
        risks = [str(item) for item in stock.get("risks") or [] if item]
        if stock.get("research_action") in {"等回踩确认", "仅复盘"} or risks:
            rows.append(
                {
                    "type": "个股风险",
                    "industry": str(stock.get("industry") or ""),
                    "target": f"{stock.get('name') or ''} {stock.get('ts_code') or ''}".strip(),
                    "reason": "；".join(risks) or str(stock.get("research_action") or "需复盘"),
                }
            )
    return rows[:8]


def _next_day_watch_points(theses: list[dict], stocks: list[dict], risk_audit: list[dict]) -> list[str]:
    points = []
    for thesis in theses[:5]:
        point = _first(thesis.get("verification_points"), "")
        if point:
            points.append(point)
    for stock in stocks[:5]:
        if stock.get("research_action") == "可重点跟踪":
            points.append(f"复核{stock.get('name') or stock.get('ts_code')}是否继续保持事件、量价、策略证据一致。")
        elif stock.get("research_action") == "等回踩确认":
            points.append(f"观察{stock.get('name') or stock.get('ts_code')}是否消化高位风险。")
    for row in risk_audit[:3]:
        points.append(f"复盘{row.get('target')}：{row.get('reason')}")
    return _unique(points)[:8]


def _data_quality(data_alignment: dict) -> dict:
    aligned = bool(data_alignment.get("aligned", True))
    message = str(data_alignment.get("message") or "")
    reasons = [] if aligned else [message or "数据日期不一致，复盘结论降置信。"]
    return {
        "aligned": aligned,
        "tone": "ok" if aligned else "warn",
        "reasons": reasons,
    }


def _closing_judgement(validated: list[dict], unverified: list[dict], risk_audit: list[dict], data_quality: dict) -> str:
    if risk_audit and not validated:
        return "风险优先"
    if validated and data_quality.get("tone") == "ok":
        return "主线已验证"
    if unverified:
        return "仍待验证"
    if data_quality.get("tone") == "warn":
        return "数据待校准"
    return "无明确主线"


def _first(values, fallback: str) -> str:
    if isinstance(values, list):
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
    return fallback


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _unique(values: list[str]) -> list[str]:
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result
