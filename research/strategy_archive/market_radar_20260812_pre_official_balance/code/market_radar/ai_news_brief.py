"""市场雷达 AI 消息面研判：独立解释，不进入量化评分。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from market_radar.evidence_pack import build_evidence_pack, build_input_audit


DEFAULT_CACHE_DIR = Path("logs") / "cache"


def generate_ai_news_brief(
    radar: dict,
    concept_news: dict,
    target_date: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    call_ai_api_fn: Callable | None = None,
) -> dict:
    """生成或复用当日消息面研判缓存。"""
    date_text = _date_key(target_date or radar.get("end_date"))
    refresh_slot, refresh_slot_text = _refresh_slot()
    target = Path(cache_dir) / f"ai_news_brief_{date_text}.json"
    existing = _read_json(target)
    compact = build_evidence_pack(radar, concept_news, date_text, previous_brief=existing)
    compact["refresh_slot"] = refresh_slot
    checked_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    fingerprint = hashlib.sha256(
        json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if existing.get("status") == "ok" and existing.get("input_fingerprint") == fingerprint:
        result = dict(existing)
        result["cache_status"] = "reused"
        result["cache_status_text"] = f"{refresh_slot_text}输入未变化，已复用缓存"
        result["last_checked_at"] = checked_at
        result["last_refresh_slot"] = refresh_slot
        result["last_refresh_slot_text"] = refresh_slot_text
        result["last_refresh_status"] = "reused"
        _write_json(target, result)
        return result

    if not compact["events"]:
        if existing.get("status") == "ok":
            result = dict(existing)
            result["cache_status"] = "stale_fallback"
            result["cache_status_text"] = f"{refresh_slot_text}新闻抓取为空，继续展示上一次有效研判"
            result["last_checked_at"] = checked_at
            result["last_refresh_slot"] = refresh_slot
            result["last_refresh_slot_text"] = refresh_slot_text
            result["last_refresh_status"] = "failed"
            _write_json(target, result)
            return result
        failure = _failure_payload(
            date_text,
            compact.get("source_message") or "没有通过时效检查的新闻，未调用 AI。",
            len(compact["events"]),
            refresh_slot,
            refresh_slot_text,
        )
        failure["last_checked_at"] = checked_at
        _write_json(target, failure)
        return failure

    ai_call = call_ai_api_fn
    if ai_call is None:
        from market_context_snapshot import call_ai_api

        ai_call = call_ai_api
    event_assessments, batch_errors = _assess_event_batches(compact["events"], ai_call)
    if not event_assessments:
        if existing.get("status") == "ok":
            result = dict(existing)
            result["cache_status"] = "stale_fallback"
            result["cache_status_text"] = "新闻首轮 AI 研判失败，保留当日上一次有效结果"
            result["last_checked_at"] = checked_at
            result["last_refresh_status"] = "failed"
            result["batch_errors"] = batch_errors
            _write_json(target, result)
            return result
        failure = _failure_payload(date_text, "新闻首轮 AI 研判未返回有效结果。", len(compact["events"]), refresh_slot, refresh_slot_text)
        failure["input_audit"] = build_input_audit(compact)
        failure["batch_errors"] = batch_errors
        _write_json(target, failure)
        return failure
    compact["event_assessments"] = event_assessments
    raw = ai_call(
        prompt=_build_prompt(compact),
        system="你是A股消息面研究员。只做证据归纳、板块与候选股二次筛选，不修改量化分数，不给交易指令。",
    )
    parsed = _parse_json_object(raw)
    validated = _validate_result(parsed, compact)
    if not validated:
        if existing.get("status") == "ok":
            result = dict(existing)
            result["cache_status"] = "stale_fallback"
            result["cache_status_text"] = "本次 AI 生成失败，保留当日上一次有效结果"
            result["last_checked_at"] = checked_at
            result["last_refresh_slot"] = refresh_slot
            result["last_refresh_slot_text"] = refresh_slot_text
            result["last_refresh_status"] = "failed"
            _write_json(target, result)
            return result
        failure = _failure_payload(
            date_text,
            "AI 未返回可校验的板块或候选股研判。",
            len(compact["events"]),
            refresh_slot,
            refresh_slot_text,
        )
        failure["last_checked_at"] = checked_at
        _write_json(target, failure)
        return failure

    payload = {
        "status": "ok",
        "message": "",
        "target_date": date_text,
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "refresh_slot": refresh_slot,
        "refresh_slot_text": refresh_slot_text,
        "last_checked_at": checked_at,
        "last_refresh_slot": refresh_slot,
        "last_refresh_slot_text": refresh_slot_text,
        "last_refresh_status": "ok",
        "input_fingerprint": fingerprint,
        "news_count": len(compact["events"]),
        "sector_fact_count": len(compact["sectors"]),
        "candidate_count": len(compact["stocks"]),
        "cache_status": "generated",
        "cache_status_text": f"{refresh_slot_text}已基于最新输入生成",
        "input_audit": build_input_audit(compact),
        "evidence_catalog": _evidence_catalog(compact["events"]),
        "event_assessments": event_assessments,
        "batch_errors": batch_errors,
        **validated,
    }
    _write_json(target, payload)
    return payload


def load_ai_news_brief(
    target_date: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
) -> dict:
    """页面只读取指定交易日缓存，绝不在请求中调用 AI。"""
    date_text = _date_key(target_date)
    payload = _read_json(Path(cache_dir) / f"ai_news_brief_{date_text}.json")
    if payload.get("status") == "ok":
        result = dict(payload)
        if result.get("last_refresh_status") == "failed":
            result["cache_status"] = "stale_fallback"
        else:
            result["cache_status"] = "loaded"
            result["cache_status_text"] = "已读取定时生成缓存"
        return result
    if payload:
        result = _failure_payload(date_text, str(payload.get("message") or "本批次生成失败。"), int(payload.get("news_count") or 0))
        result.update(payload)
        return result
    return _failure_payload(date_text, "该交易日尚未生成 AI 消息面研判。", 0)


def _build_compact_input(radar: dict, concept_news: dict, target_date: str) -> dict:
    healthy = list(radar.get("healthy") or [])[:8]
    risky = list(radar.get("risky") or [])[:8]
    candidates = list(radar.get("candidates") or [])[:24]
    reading_events = list(concept_news.get("reading_events") or concept_news.get("events") or [])
    news = []
    mapped_news_sectors = set()
    seen_titles = set()
    for event in reading_events:
        if not isinstance(event, dict):
            continue
        title = str(event.get("title") or "").strip()
        if not title or title in seen_titles or str(event.get("freshness_bucket") or "") == "unknown":
            continue
        seen_titles.add(title)
        sectors = [str(item) for item in event.get("mapped_industries") or [] if item][:4]
        mapped_news_sectors.update(sectors)
        news.append(
            {
                "title": title[:120],
                "publish_time": str(event.get("publish_time") or ""),
                "freshness": str(event.get("freshness_label") or ""),
                "impact": str(event.get("impact_label") or "方向待定"),
                "event_type": str(event.get("event_type") or "行业动态"),
                "sectors": sectors,
                "summary": str(event.get("effect_summary") or "")[:160],
            }
        )
        if len(news) >= 30:
            break

    sectors = [
        {
            "industry": str(item.get("industry") or ""),
            "stage": str(item.get("stage") or ""),
            "heat_score": item.get("heat_score"),
            "ret_5d": item.get("avg_ret_5d"),
            "relative_10d": item.get("rel_ret_10d"),
            "risk": False,
        }
        for item in healthy
        if item.get("industry")
    ]
    sectors.extend(
        {
            "industry": str(item.get("industry") or ""),
            "stage": str(item.get("stage") or ""),
            "heat_score": item.get("heat_score"),
            "ret_5d": item.get("avg_ret_5d"),
            "relative_10d": item.get("rel_ret_10d"),
            "risk": True,
        }
        for item in risky
        if item.get("industry")
    )
    stocks = [
        {
            "ts_code": str(item.get("ts_code") or ""),
            "name": str(item.get("name") or ""),
            "industry": str(item.get("industry") or ""),
            "candidate_score": item.get("candidate_score"),
            "ret_5d": item.get("ret_5d"),
            "ret_10d": item.get("ret_10d"),
            "stock_vs_sector_10d": item.get("stock_vs_sector_10d"),
            "reason": str(item.get("candidate_reason") or "")[:120],
        }
        for item in candidates
        if item.get("ts_code")
    ]
    return {
        "target_date": target_date,
        "market_summary": str((radar.get("summary") or {}).get("headline") or ""),
        "news": news,
        "sectors": sectors,
        "stocks": stocks,
        "healthy_industries": [str(item.get("industry")) for item in healthy if item.get("industry")],
        "risky_industries": [str(item.get("industry")) for item in risky if item.get("industry")],
        "mapped_news_sectors": sorted(mapped_news_sectors),
        "source_message": str((concept_news.get("news") or {}).get("source_message") or ""),
    }


def _build_prompt(compact: dict) -> str:
    schema = {
        "summary": "一句话消息面结论",
        "drivers": [{"text": "最多4条主要驱动", "evidence_ids": ["必须来自event_assessments"]}],
        "risks": [{"text": "最多4条风险或不确定性", "evidence_ids": ["必须来自event_assessments"]}],
        "sector_focus": [
            {
                "industry": "必须来自输入sectors",
                "stance": "关注/观察/谨慎",
                "confidence": "高/中/低",
                "reason": "原因",
                "evidence_ids": ["必须来自event_assessments"],
                "validation": "下一步验证条件",
                "invalidation": "失效条件",
            }
        ],
        "stock_focus": [
            {
                "ts_code": "必须来自输入stocks",
                "stance": "优先观察/等待确认/回避",
                "reason": "量化候选事实解释",
                "news_logic": "关联消息逻辑",
                "evidence_ids": ["必须来自event_assessments，可为空表示没有直接消息"],
                "validation": "验证条件",
                "risk": "主要风险",
            }
        ],
    }
    return (
        "根据首轮新闻价值研判和市场事实生成独立消息面研判。最多5个板块、6只股票。"
        "消息价值和量价验证必须分开描述；股票只能从输入候选中选择。"
        "每条驱动、风险和板块结论必须引用真实evidence_id。"
        "不要输出买入、卖出、仓位或目标价。只返回JSON对象，不要Markdown。\n"
        f"输出结构：{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}\n"
        f"输入事实：{json.dumps(compact, ensure_ascii=False, separators=(',', ':'), default=str)}"
    )


def _validate_result(parsed: dict, compact: dict) -> dict | None:
    if not isinstance(parsed, dict):
        return None
    allowed_sectors = {item["industry"]: item for item in compact["sectors"]}
    allowed_stocks = {item["ts_code"]: item for item in compact["stocks"]}
    evidence_by_id = {item["evidence_id"]: item for item in compact["events"]}
    allowed_evidence = set(evidence_by_id)
    mapped = {sector for item in compact.get("event_assessments") or [] for sector in item.get("mapped_industries") or []}
    risky = set(compact["risky_industries"])
    sector_focus = []
    for row in parsed.get("sector_focus") or []:
        if not isinstance(row, dict):
            continue
        industry = str(row.get("industry") or "").strip()
        if industry not in allowed_sectors:
            continue
        confidence = str(row.get("confidence") or "中")
        stance = "谨慎" if industry in risky else str(row.get("stance") or "观察")
        relation = "共振" if industry in mapped and industry not in risky else "量价待确认"
        if relation != "共振" and confidence == "高":
            confidence = "中"
        evidence_ids = _valid_evidence_ids(row.get("evidence_ids"), allowed_evidence)
        if not evidence_ids:
            continue
        sector_focus.append(
            {
                "industry": industry,
                "stance": stance if stance in {"关注", "观察", "谨慎"} else "观察",
                "confidence": confidence if confidence in {"高", "中", "低"} else "中",
                "relation": relation,
                "reason": str(row.get("reason") or "")[:180],
                "evidence_ids": evidence_ids,
                "evidence_titles": [evidence_by_id[item]["title"] for item in evidence_ids][:3],
                "validation": str(row.get("validation") or "等待板块量价确认")[:140],
                "invalidation": str(row.get("invalidation") or "消息未获行情响应")[:140],
            }
        )
        if len(sector_focus) >= 5:
            break

    stock_focus = []
    for row in parsed.get("stock_focus") or []:
        if not isinstance(row, dict):
            continue
        ts_code = str(row.get("ts_code") or "").strip()
        stock = allowed_stocks.get(ts_code)
        if not stock:
            continue
        stance = str(row.get("stance") or "等待确认")
        stock_focus.append(
            {
                "ts_code": ts_code,
                "name": stock["name"],
                "industry": stock["industry"],
                "candidate_score": stock.get("candidate_score"),
                "stance": stance if stance in {"优先观察", "等待确认", "回避"} else "等待确认",
                "reason": str(row.get("reason") or stock.get("reason") or "")[:180],
                "news_logic": str(row.get("news_logic") or "")[:160],
                "evidence_ids": _valid_evidence_ids(row.get("evidence_ids"), allowed_evidence),
                "validation": str(row.get("validation") or "等待候选条件继续成立")[:140],
                "risk": str(row.get("risk") or "消息与价格可能不同步")[:140],
            }
        )
        if len(stock_focus) >= 6:
            break
    if not sector_focus and not stock_focus:
        return None
    drivers, driver_details = _validated_statements(parsed.get("drivers"), allowed_evidence)
    risks, risk_details = _validated_statements(parsed.get("risks"), allowed_evidence)
    return {
        "summary": str(parsed.get("summary") or "消息面存在可观察线索，但仍需量价验证。")[:240],
        "drivers": drivers,
        "driver_details": driver_details,
        "risks": risks,
        "risk_details": risk_details,
        "sector_focus": sector_focus,
        "stock_focus": stock_focus,
    }


def _assess_event_batches(events: list[dict], ai_call: Callable, batch_size: int = 12) -> tuple[list[dict], list[str]]:
    """让 AI 逐批阅读全部准入消息，不在调用前按价值淘汰。"""
    assessments = []
    errors = []
    schema = {
        "items": [{
            "evidence_id": "必须逐字来自输入",
            "value_level": "高/中/低/噪音",
            "direction": "利多/利空/中性/不确定",
            "event_type": "事件类型",
            "mapped_industries": ["A股行业"],
            "horizon": "盘中/1-3天/1周以上/背景",
            "confidence": "高/中/低",
            "reason": "基于内容的价值判断",
        }]
    }
    for start in range(0, len(events), batch_size):
        batch = events[start:start + batch_size]
        raw = ai_call(
            prompt=(
                "逐条研判输入消息，不得遗漏任何evidence_id。判断新闻价值、方向、行业关联、持续时间和可信度。"
                "来源可信且日期新不代表一定利多；请根据内容独立判断。只返回JSON对象，不要Markdown。\n"
                f"输出结构：{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}\n"
                f"输入消息：{json.dumps(batch, ensure_ascii=False, separators=(',', ':'), default=str)}"
            ),
            system="你是A股新闻事实研判员。完整阅读每条输入，只做消息价值判断，不给交易指令。",
        )
        parsed = _parse_json_object(raw)
        allowed = {item["evidence_id"] for item in batch}
        valid = []
        for row in parsed.get("items") or []:
            if not isinstance(row, dict) or row.get("evidence_id") not in allowed:
                continue
            valid.append({
                "evidence_id": row["evidence_id"],
                "value_level": str(row.get("value_level") or "低")[:8],
                "direction": str(row.get("direction") or "不确定")[:8],
                "event_type": str(row.get("event_type") or "")[:30],
                "mapped_industries": [str(item) for item in row.get("mapped_industries") or [] if item][:6],
                "horizon": str(row.get("horizon") or "")[:20],
                "confidence": str(row.get("confidence") or "中")[:8],
                "reason": str(row.get("reason") or "")[:220],
            })
        assessments.extend(valid)
        missing = allowed - {item["evidence_id"] for item in valid}
        if missing:
            errors.append(f"batch_{start // batch_size + 1}: missing {len(missing)} events")
    return assessments, errors


def _valid_evidence_ids(values, allowed: set[str]) -> list[str]:
    return [str(item) for item in values or [] if str(item) in allowed][:5]


def _validated_statements(values, allowed: set[str]) -> tuple[list[str], list[dict]]:
    texts = []
    details = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:160]
        evidence_ids = _valid_evidence_ids(item.get("evidence_ids"), allowed)
        if not text or not evidence_ids:
            continue
        texts.append(text)
        details.append({"text": text, "evidence_ids": evidence_ids})
        if len(texts) >= 4:
            break
    return texts, details


def _evidence_catalog(events: list[dict]) -> list[dict]:
    return [{
        "evidence_id": item.get("evidence_id"),
        "title": item.get("title"),
        "sources": item.get("sources"),
        "source_urls": item.get("source_urls"),
        "publish_time": item.get("publish_time"),
    } for item in events]


def _parse_json_object(raw) -> dict:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            value = json.loads(match.group())
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def _failure_payload(
    target_date: str,
    message: str,
    news_count: int,
    refresh_slot: str = "",
    refresh_slot_text: str = "",
) -> dict:
    return {
        "status": "unavailable",
        "message": message,
        "target_date": target_date,
        "generated_at": "",
        "refresh_slot": refresh_slot,
        "refresh_slot_text": refresh_slot_text,
        "news_count": news_count,
        "sector_fact_count": 0,
        "candidate_count": 0,
        "cache_status": "missing",
        "cache_status_text": "本批次失败，等待下次刷新",
        "input_audit": {},
        "evidence_catalog": [],
        "event_assessments": [],
        "summary": "",
        "drivers": [],
        "risks": [],
        "sector_focus": [],
        "stock_focus": [],
    }


def _date_key(value) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    return text[:8]


def _refresh_slot(now: datetime | None = None) -> tuple[str, str]:
    """把夜间、早盘和午盘刷新分成独立 AI 缓存批次。"""
    current = now or datetime.now().astimezone()
    if current.hour < 8:
        return "overnight", "夜间全量批次"
    if current.hour < 12:
        return "morning", "早盘批次"
    return "noon", "午盘批次"


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
