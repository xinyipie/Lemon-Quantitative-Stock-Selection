"""市场雷达统一时效判定。"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


BEIJING_TZ = ZoneInfo("Asia/Shanghai")
NEWS_FRESH_HOURS = 24.0
NEWS_MAX_AGE_HOURS = 48.0


def _now(value=None) -> datetime:
    if value is None:
        return datetime.now(BEIJING_TZ)
    parsed = parse_datetime(value)
    return parsed or datetime.now(BEIJING_TZ)


def parse_datetime(value) -> datetime | None:
    """把常见新闻时间统一为北京时间。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=BEIJING_TZ)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00").replace("/", "-")
        parsed = None
        for candidate in (normalized, normalized.replace("T", " ")):
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except ValueError:
                pass
        if parsed is None:
            for fmt in ("%Y%m%d%H%M%S", "%Y%m%d", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(normalized, fmt)
                    break
                except ValueError:
                    pass
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ)


def normalize_date(value) -> str:
    text = str(value or "").strip().replace("-", "").replace("/", "")
    return text[:8] if len(text) >= 8 and text[:8].isdigit() else ""


def classify_news_time(value, now=None) -> dict:
    """新闻仅在发布时间可靠且不超过48小时时允许进入交易判断。"""
    published = parse_datetime(value)
    reference = _now(now)
    if published is None:
        return {
            "as_of_time": "",
            "age_hours": None,
            "age_text": "发布时间待核验",
            "freshness_status": "unknown",
            "freshness_label": "待核验",
            "decision_eligible": False,
            "freshness_factor": 0.0,
            "freshness_reason": "缺少可靠发布时间，不能作为当日消息依据。",
        }
    age_hours = (reference - published).total_seconds() / 3600.0
    if age_hours < -1:
        status, label, eligible, factor, reason = (
            "mismatched",
            "时间异常",
            False,
            0.0,
            "发布时间晚于页面基准时间。",
        )
    elif age_hours <= NEWS_FRESH_HOURS:
        status, label, eligible, factor, reason = "fresh", "24小时内", True, 1.0, "发布时间可靠且在24小时内。"
    elif age_hours <= NEWS_MAX_AGE_HOURS:
        status, label, eligible, factor, reason = "aging", "持续影响", True, 0.5, "发布时间超过24小时，影响权重减半。"
    else:
        status, label, eligible, factor, reason = "stale", "已过期", False, 0.0, "发布时间超过48小时。"
    safe_age = max(0.0, age_hours)
    age_text = f"{safe_age:.0f}小时前" if safe_age < 24 else f"{safe_age / 24:.1f}天前"
    return {
        "as_of_time": published.strftime("%Y-%m-%d %H:%M:%S"),
        "age_hours": round(safe_age, 1),
        "age_text": age_text,
        "freshness_status": status,
        "freshness_label": label,
        "decision_eligible": eligible,
        "freshness_factor": factor,
        "freshness_reason": reason,
    }


def classify_trade_date(value, target_date) -> dict:
    actual = normalize_date(value)
    target = normalize_date(target_date)
    if not actual:
        status, eligible, reason = "unknown", False, "没有可验证的数据日期。"
    elif not target:
        status, eligible, reason = "unknown", False, "没有市场雷达目标交易日。"
    elif actual == target:
        status, eligible, reason = "fresh", True, "数据日期与市场雷达目标日一致。"
    else:
        status, eligible, reason = "mismatched", False, f"数据日期{actual}与目标交易日{target}不一致。"
    return {
        "as_of_time": actual,
        "target_date": target,
        "age_hours": None,
        "freshness_status": status,
        "freshness_label": {"fresh": "已对齐", "unknown": "待更新", "mismatched": "日期错配"}.get(status, status),
        "decision_eligible": eligible,
        "freshness_reason": reason,
    }


def build_market_freshness(radar: dict, concept_news: dict, strategy_overlap: dict, now=None) -> dict:
    target = normalize_date(radar.get("end_date"))
    news = concept_news.get("news") or {}
    concepts = concept_news.get("concepts") or {}
    theme = concept_news.get("theme_filter") or {}
    modules = {
        "market": classify_trade_date(radar.get("end_date"), target),
        "news": classify_trade_date(news.get("source_date"), target),
        "concepts": classify_trade_date(concepts.get("source_date"), target),
        "theme": classify_trade_date(theme.get("source_date"), target),
        "strategy": classify_trade_date(strategy_overlap.get("source_date"), target),
    }
    modules["market"].update({"name": "行业行情", "display_time": modules["market"]["as_of_time"]})
    modules["news"].update({"name": "消息雷达", "display_time": modules["news"]["as_of_time"]})
    modules["concepts"].update({"name": "概念热度", "display_time": modules["concepts"]["as_of_time"]})
    modules["theme"].update({"name": "题材筛选", "display_time": modules["theme"]["as_of_time"]})
    modules["strategy"].update({"name": "策略信号", "display_time": modules["strategy"]["as_of_time"]})
    core_ok = modules["market"]["decision_eligible"]
    supporting_ok = all(modules[key]["decision_eligible"] for key in ("news", "concepts"))
    if not core_ok:
        overall_status = "blocked"
        summary = "行业行情未对齐，市场雷达已停止输出当日综合结论。"
    elif supporting_ok:
        overall_status = "fresh"
        optional_lag = [modules[key]["name"] for key in ("theme", "strategy") if not modules[key]["decision_eligible"]]
        summary = "行情、消息和概念日期已对齐。"
        if optional_lag:
            summary += " 可选模块较旧，不影响核心雷达：" + "、".join(optional_lag)
    else:
        overall_status = "degraded"
        missing = [modules[key]["name"] for key in ("news", "concepts") if not modules[key]["decision_eligible"]]
        summary = "仅输出可验证数据；缺失或错配模块：" + "、".join(missing)
    return {
        "target_date": target,
        "generated_at": _now(now).strftime("%Y-%m-%d %H:%M:%S"),
        "overall_status": overall_status,
        "decision_eligible": core_ok,
        "summary": summary,
        "modules": modules,
    }
