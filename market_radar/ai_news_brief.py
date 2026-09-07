"""市场雷达 AI 消息面研判：独立解释，不进入量化评分。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from market_radar.evidence_pack import build_evidence_pack, build_input_audit
import config


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
    compact["brief_schema_version"] = "tiered-model-v1"
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
    event_assessments, batch_errors = _assess_event_batches_v2(compact["events"], ai_call)
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
    raw = _invoke_ai_stage(
        ai_call,
        _build_prompt_v2(compact),
        "你是A股消息面研究员。只做证据归纳、板块与候选股二次筛选，不修改量化分数，不给交易指令。",
        stage="summary",
    )
    parsed = _parse_json_object(raw)
    validated = _validate_result_v2(parsed, compact)
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
        "ai_models": {
            "event_assessment": str(config.AI_CONFIG.get("fast_model") or config.AI_CONFIG.get("model") or ""),
            "final_brief": str(config.AI_CONFIG.get("reasoning_model") or config.AI_CONFIG.get("model") or ""),
        },
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
                "news_logic": "只描述证据与公司或所属行业的真实关系",
                "evidence_ids": ["必须来自event_assessments；没有相关证据时必须为空"],
                "validation": "验证条件",
                "risk": "主要风险",
            }
        ],
    }
    return (
        "根据首轮新闻价值研判和市场事实生成独立消息面研判。最多5个板块、6只股票。"
        "消息价值和量价验证必须分开描述；股票只能从输入候选中选择，不得修改量化分数和排名。"
        "只有公司名称或代码直接命中，或者消息明确映射到股票所属行业，才可作为个股消息依据；"
        "宏观联想、跨行业推导或无关新闻不得包装成直接利好。"
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
    assessments_by_id = {
        str(item.get("evidence_id")): item
        for item in compact.get("event_assessments") or []
        if isinstance(item, dict) and item.get("evidence_id")
    }
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
        evidence_ids = _valid_evidence_ids(row.get("evidence_ids"), allowed_evidence)
        relation_level, relation_label = _classify_stock_relation(
            stock,
            evidence_ids,
            evidence_by_id,
            assessments_by_id,
        )
        if relation_level in {"weak", "none"} and stance == "优先观察":
            stance = "等待确认"
        stock_focus.append(
            {
                "ts_code": ts_code,
                "name": stock["name"],
                "industry": stock["industry"],
                "candidate_score": stock.get("candidate_score"),
                "stance": stance if stance in {"优先观察", "等待确认", "回避"} else "等待确认",
                "relation_level": relation_level,
                "relation_label": relation_label,
                "reason": str(row.get("reason") or stock.get("reason") or "")[:180],
                "news_logic": str(row.get("news_logic") or "")[:160],
                "evidence_ids": evidence_ids,
                "evidence_titles": [evidence_by_id[item]["title"] for item in evidence_ids][:3],
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


def _classify_stock_relation(
    stock: dict,
    evidence_ids: list[str],
    evidence_by_id: dict[str, dict],
    assessments_by_id: dict[str, dict],
) -> tuple[str, str]:
    """确定性校验个股与消息的关系，防止弱联想被包装成直接催化。"""
    if not evidence_ids:
        return "none", "暂无消息共振"
    name = str(stock.get("name") or "").strip()
    code = str(stock.get("ts_code") or "").split(".", 1)[0]
    industry = str(stock.get("industry") or "").strip()
    for evidence_id in evidence_ids:
        event = evidence_by_id.get(evidence_id) or {}
        text = f"{event.get('title') or ''} {event.get('summary') or ''}"
        if (name and name in text) or (len(code) == 6 and code in text):
            return "direct", "公司直接相关"
    for evidence_id in evidence_ids:
        event = evidence_by_id.get(evidence_id) or {}
        assessment = assessments_by_id.get(evidence_id) or {}
        mapped = {str(item).strip() for item in assessment.get("mapped_industries") or [] if str(item).strip()}
        mapped.update(str(item).strip() for item in event.get("mapped_industries") or [] if str(item).strip())
        text = f"{event.get('title') or ''} {event.get('summary') or ''}"
        if industry and (industry in mapped or industry in text):
            return "industry", "行业直接相关"
    return "weak", "间接线索"


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
                "mapped_industries": ["明确关联的A股行业，不确定则留空"],
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
                "禁止跨行业牵强映射，无法确定行业时 mapped_industries 必须留空。"
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


def _focus_statement_fallbacks(sector_focus: list[dict], stock_focus: list[dict]) -> tuple[list[str], list[dict], list[str], list[dict]]:
    """从已通过证据校验的研判中补齐顶部驱动与风险，避免接受残缺的 AI 输出。"""
    driver_details = []
    risk_details = []
    driver_keys = set()
    risk_keys = set()

    def add(target: list[dict], seen: set[tuple], text: str, evidence_ids) -> None:
        cleaned = str(text or "").strip()[:160]
        ids = [str(item) for item in evidence_ids or [] if item][:5]
        key = (cleaned, tuple(ids))
        if cleaned and ids and key not in seen and len(target) < 4:
            target.append({"text": cleaned, "evidence_ids": ids})
            seen.add(key)

    for item in sector_focus:
        industry = str(item.get("industry") or "").strip()
        relation = str(item.get("relation") or "")
        stance = str(item.get("stance") or "")
        reason = str(item.get("reason") or "").strip()
        evidence_ids = item.get("evidence_ids") or []
        if stance == "谨慎" or "风险" in relation:
            add(risk_details, risk_keys, f"{industry}：{reason}", evidence_ids)
        else:
            add(driver_details, driver_keys, f"{industry}：{reason}", evidence_ids)

    for item in stock_focus:
        name = str(item.get("name") or "").strip()
        direction = str(item.get("impact_direction") or "")
        reason = str(item.get("news_logic") or item.get("reason") or "").strip()
        evidence_ids = item.get("evidence_ids") or []
        if direction == "利空":
            add(risk_details, risk_keys, f"{name}：{reason}", evidence_ids)
        elif direction == "利多":
            add(driver_details, driver_keys, f"{name}：{reason}", evidence_ids)

    if not driver_details:
        source = next((item for item in sector_focus if item.get("evidence_ids")), None)
        if source:
            industry = str(source.get("industry") or "相关板块").strip()
            add(
                driver_details,
                driver_keys,
                f"当前未形成集中利多驱动，重点观察{industry}等已验证消息线索。",
                source.get("evidence_ids"),
            )

    if not risk_details:
        source = next((item for item in sector_focus if item.get("evidence_ids")), None)
        if source:
            invalidation = str(source.get("invalidation") or "后续消息未获量价承接").strip()
            add(
                risk_details,
                risk_keys,
                f"当前未识别到集中利空，主要风险是{invalidation}。",
                source.get("evidence_ids"),
            )

    drivers = [item["text"] for item in driver_details]
    risks = [item["text"] for item in risk_details]
    return drivers, driver_details, risks, risk_details


def _summary_fallback(sector_focus: list[dict], stock_focus: list[dict], drivers: list[str], risks: list[str]) -> str:
    sectors = []
    for item in sector_focus:
        industry = str(item.get("industry") or "").strip()
        if industry and industry not in sectors:
            sectors.append(industry)
        if len(sectors) >= 3:
            break
    focus_text = "、".join(sectors) or "已验证消息线索"
    bullish_count = sum(1 for item in stock_focus if item.get("impact_direction") == "利多")
    risk_count = sum(1 for item in stock_focus if item.get("impact_direction") == "利空")
    stock_text = f"个股层面识别到{bullish_count}条利多、{risk_count}条利空线索"
    risk_text = "已识别明确风险" if risk_count else "暂未识别集中利空"
    return f"消息面重点关注{focus_text}，{stock_text}；{risk_text}，所有结论仍需量价验证。"[:240]


def _build_prompt_v2(compact: dict) -> str:
    schema = {
        "summary": "一句话消息面结论",
        "drivers": [{"text": "具体事件及其主要传导结果", "evidence_ids": ["EV-..."]}],
        "risks": [{"text": "具体风险事件及影响对象", "evidence_ids": ["EV-..."]}],
        "sector_focus": [{"industry": "来自sectors或event_assessments.mapped_industries", "stance": "关注/观察/谨慎", "confidence": "高/中/低", "reason": "具体事件事实", "impact_chain": "事件如何传导至该行业", "evidence_ids": ["EV-..."], "validation": "结合输入量价事实的确认条件", "invalidation": "可执行的失效条件"}],
        "stock_focus": [{"ts_code": "来自stocks", "direction": "利多/利空/中性", "stance": "优先观察/等待量价确认/等待消息确认/风险回避", "reason": "直接相关的具体事件事实", "news_logic": "事件到公司收入成本或估值的传导链", "evidence_ids": ["EV-..."], "validation": "结合该股真实量价字段的确认条件", "risk": "该事件最可能的失效原因"}],
    }
    return (
        "根据新闻价值判断和市场事实生成独立消息面研判，最多5个板块、8只股票。"
        "板块既可来自行情sectors，也可来自首轮研判明确给出的mapped_industries；后者即使尚未量价共振也应作为消息关注保留，但不得写成高置信主线。"
        "股票有两条入口：新闻直接点名的公司，以及原有量价候选；优先输出直接点名和消息量价共振标的。"
        "不得修改candidate_score。每只股票必须给出direction；利空必须标为风险回避，不能伪装成推荐。"
        "无消息关联的量价候选只能等待消息确认；直接利多消息但无量价承接只能等待量价确认。"
        "行业消息只能验证同行业量价候选，不能凭行业联想新增个股。"
        "文案必须回答发生了什么、如何影响该板块或公司、当前量价是否承接、什么情况确认或证伪。"
        "禁止使用‘新闻直接提及该公司’‘等待确认’‘观察价格量能’等无事实的套话；同一事件映射多个行业时必须分别说明传导差异。"
        "只能引用输入中已有的数值，不得编造阈值。结论必须引用evidence_id，不给交易指令。只返回JSON。\n"
        f"输出结构：{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}\n"
        f"输入事实：{json.dumps(compact, ensure_ascii=False, separators=(',', ':'), default=str)}"
    )


def _assess_event_batches_v2(events, ai_call, batch_size=12):
    """逐批评估全部新鲜消息，由 AI 判断价值而不是预先过度筛选。"""
    assessments, errors = [], []
    schema = {"items": [{"evidence_id": "来自输入", "value_level": "高/中/低/噪音", "direction": "利多/利空/中性/不确定", "event_type": "类型", "mapped_industries": ["明确关联行业"], "horizon": "时效", "confidence": "高/中/低", "reason": "判断"}]}
    for start in range(0, len(events), batch_size):
        batch = events[start:start + batch_size]
        raw = _invoke_ai_stage(
            ai_call,
            ("逐条研判消息，不得遗漏evidence_id。可信且新鲜只代表可读，价值和方向由内容决定；禁止牵强映射。只返回JSON。\n" + f"输出结构：{json.dumps(schema, ensure_ascii=False)}\n输入消息：{json.dumps(batch, ensure_ascii=False, default=str)}"),
            "你是A股新闻事实研究员。完整阅读输入，只判断消息价值和真实关联，不给交易指令。",
            stage="event",
        )
        parsed = _parse_json_object(raw)
        allowed = {item["evidence_id"] for item in batch}
        valid = []
        for row in parsed.get("items") or []:
            if not isinstance(row, dict) or row.get("evidence_id") not in allowed:
                continue
            valid.append({"evidence_id": row["evidence_id"], "value_level": str(row.get("value_level") or "低")[:8], "direction": str(row.get("direction") or "不确定")[:8], "event_type": str(row.get("event_type") or "")[:30], "mapped_industries": [str(item) for item in row.get("mapped_industries") or [] if item][:6], "horizon": str(row.get("horizon") or "")[:20], "confidence": str(row.get("confidence") or "中")[:8], "reason": str(row.get("reason") or "")[:220]})
        assessments.extend(valid)
        missing = allowed - {item["evidence_id"] for item in valid}
        if missing:
            errors.append(f"batch_{start // batch_size + 1}: missing {len(missing)} events")
    return assessments, errors


def _invoke_ai_stage(ai_call, prompt: str, system: str, stage: str):
    """按研判阶段路由模型，同时兼容测试和历史注入函数。"""
    if stage == "summary":
        model = str(config.AI_CONFIG.get("reasoning_model") or config.AI_CONFIG.get("model") or "")
        thinking = True
    else:
        model = str(config.AI_CONFIG.get("fast_model") or config.AI_CONFIG.get("model") or "")
        thinking = False
    try:
        return ai_call(
            prompt=prompt,
            system=system,
            model=model,
            thinking=thinking,
            json_mode=True,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return ai_call(prompt=prompt, system=system)


def _validate_result_v2(parsed, compact):
    if not isinstance(parsed, dict):
        return None
    market_sectors = {item["industry"]: item for item in compact["sectors"]}
    allowed_stocks = {item["ts_code"]: item for item in compact["stocks"]}
    evidence_by_id = {item["evidence_id"]: item for item in compact["events"]}
    allowed_evidence = set(evidence_by_id)
    assessments = {str(item.get("evidence_id")): item for item in compact.get("event_assessments") or [] if isinstance(item, dict) and item.get("evidence_id")}
    mapped_evidence = {}
    for evidence_id, assessment in assessments.items():
        if str(assessment.get("value_level") or "") == "噪音":
            continue
        for sector in assessment.get("mapped_industries") or []:
            industry = str(sector or "").strip()
            if industry:
                mapped_evidence.setdefault(industry, []).append(evidence_id)
    allowed_sectors = set(market_sectors) | set(mapped_evidence)
    risky = set(compact["risky_industries"])
    sector_focus = []
    seen_sectors = set()
    for row in parsed.get("sector_focus") or []:
        if not isinstance(row, dict):
            continue
        industry = str(row.get("industry") or "").strip()
        evidence_ids = _valid_evidence_ids(row.get("evidence_ids"), allowed_evidence)
        if industry not in allowed_sectors or not evidence_ids or industry in seen_sectors:
            continue
        if industry in mapped_evidence:
            evidence_ids = [item for item in evidence_ids if item in mapped_evidence[industry]]
        if not evidence_ids:
            continue
        if industry in risky:
            relation = "风险共振" if industry in market_sectors else "消息风险"
        elif industry in market_sectors and industry in mapped_evidence:
            relation = "消息量价共振"
        elif industry in mapped_evidence:
            relation = "消息关注"
        else:
            relation = "量价待消息确认"
        confidence = str(row.get("confidence") or "中")
        if relation not in {"消息量价共振", "风险共振"} and confidence == "高":
            confidence = "中"
        sector_focus.append({"industry": industry, "stance": "谨慎" if industry in risky else str(row.get("stance") or "观察"), "confidence": confidence if confidence in {"高", "中", "低"} else "中", "relation": relation, "reason": str(row.get("reason") or "")[:180], "evidence_ids": evidence_ids, "evidence_titles": [evidence_by_id[item]["title"] for item in evidence_ids][:3], "validation": str(row.get("validation") or "等待板块量价确认")[:140], "invalidation": str(row.get("invalidation") or "消息未获行情响应")[:140]})
        seen_sectors.add(industry)
        if len(sector_focus) >= 5:
            break
    if len(sector_focus) < 5:
        for industry, evidence_ids in mapped_evidence.items():
            if industry in seen_sectors:
                continue
            linked = [assessments[item] for item in evidence_ids if item in assessments]
            reason = next((str(item.get("reason") or "").strip() for item in linked if item.get("reason")), "新鲜消息明确关联该行业，等待行情验证。")
            confidence = "中" if any(str(item.get("confidence") or "") in {"高", "中"} for item in linked) else "低"
            if industry in risky:
                relation, stance = ("风险共振" if industry in market_sectors else "消息风险"), "谨慎"
            elif industry in market_sectors:
                relation, stance = "消息量价共振", "关注"
            else:
                relation, stance = "消息关注", "观察"
            valid_ids = _valid_evidence_ids(evidence_ids, allowed_evidence)
            if not valid_ids:
                continue
            sector_focus.append({"industry": industry, "stance": stance, "confidence": confidence, "relation": relation, "reason": reason[:180], "evidence_ids": valid_ids, "evidence_titles": [evidence_by_id[item]["title"] for item in valid_ids][:3], "validation": "观察板块成交、相对强度和个股扩散是否形成承接。", "invalidation": "后续无行情响应或消息被证伪。"})
            seen_sectors.add(industry)
            if len(sector_focus) >= 5:
                break
    stock_focus, seen = [], set()
    for row in parsed.get("stock_focus") or []:
        if not isinstance(row, dict):
            continue
        ts_code = str(row.get("ts_code") or "").strip()
        stock = allowed_stocks.get(ts_code)
        if not stock or ts_code in seen:
            continue
        evidence_ids = _valid_evidence_ids(row.get("evidence_ids"), allowed_evidence)
        level, label = _classify_stock_relation_v2(stock, evidence_ids, evidence_by_id, assessments)
        stock_focus.append(_stock_focus_row_v2(stock, row, evidence_ids, level, label, evidence_by_id, assessments))
        seen.add(ts_code)
        if len(stock_focus) >= 8:
            break
    for stock in allowed_stocks.values():
        if stock.get("direct_evidence_ids") and stock["ts_code"] not in seen:
            evidence_ids = _valid_evidence_ids(stock.get("direct_evidence_ids"), allowed_evidence)
            if evidence_ids:
                direction = next((str(assessments.get(item, {}).get("direction") or "") for item in evidence_ids), "")
                fallback = {"direction": direction, "stance": "风险回避" if direction == "利空" else "等待量价确认", "reason": stock.get("reason"), "news_logic": "新闻直接提及该公司，已由消息入口独立纳入。", "validation": "观察价格、量能和所属板块是否形成承接。", "risk": "消息真实不等于价格一定响应，需防止事件已被计价。"}
                stock_focus.append(_stock_focus_row_v2(stock, fallback, evidence_ids, "direct", "公司直接相关", evidence_by_id, assessments))
                seen.add(stock["ts_code"])
        if len(stock_focus) >= 8:
            break
    stock_focus.sort(key=lambda item: ({"利多": 0, "中性": 1, "利空": 2}.get(item["impact_direction"], 3), {"消息×量价": 0, "消息驱动": 1, "仅量价候选": 2}.get(item["focus_type"], 3), -float(item.get("candidate_score") or 0)))
    sector_facts = {str(item.get("industry") or ""): item for item in compact.get("sectors") or []}
    stock_facts = {str(item.get("ts_code") or ""): item for item in compact.get("stocks") or []}
    sector_focus = [
        _enrich_sector_focus_v2(item, evidence_by_id, assessments, sector_facts.get(str(item.get("industry") or "")) or {})
        for item in sector_focus
    ]
    stock_focus = [
        _enrich_stock_focus_v2(item, evidence_by_id, assessments, stock_facts.get(str(item.get("ts_code") or "")) or {})
        for item in stock_focus
    ]
    if not sector_focus and not stock_focus:
        return None
    drivers, driver_details = _validated_statements(parsed.get("drivers"), allowed_evidence)
    risks, risk_details = _validated_statements(parsed.get("risks"), allowed_evidence)
    fallback_drivers, fallback_driver_details, fallback_risks, fallback_risk_details = _focus_statement_fallbacks(
        sector_focus,
        stock_focus,
    )
    if not drivers:
        drivers, driver_details = fallback_drivers, fallback_driver_details
    if not risks:
        risks, risk_details = fallback_risks, fallback_risk_details
    summary = str(parsed.get("summary") or "").strip()[:240]
    if not summary:
        summary = _summary_fallback(sector_focus, stock_focus, drivers, risks)
    return {"summary": summary, "drivers": drivers, "driver_details": driver_details, "risks": risks, "risk_details": risk_details, "sector_focus": sector_focus, "stock_focus": stock_focus, "bullish_focus": [item for item in stock_focus if item["impact_direction"] == "利多"], "risk_focus": [item for item in stock_focus if item["impact_direction"] == "利空"], "neutral_focus": [item for item in stock_focus if item["impact_direction"] == "中性"], "news_driven_focus": [item for item in stock_focus if item["focus_type"] == "消息驱动"], "resonant_focus": [item for item in stock_focus if item["focus_type"] == "消息×量价"], "quant_only_focus": [item for item in stock_focus if item["focus_type"] == "仅量价候选"]}


def _is_generic_research_copy(text):
    """识别会降低信息密度的通用兜底文案。"""
    value = str(text or "").strip()
    generic_fragments = (
        "新闻直接提及该公司", "量价仅用于后续验证", "等待候选条件继续成立",
        "观察价格、量能和所属板块", "消息真实不等于价格一定响应",
        "观察板块成交、相对强度和个股扩散", "后续无行情响应或消息被证伪",
    )
    return not value or any(fragment in value for fragment in generic_fragments)


def _number_text(value, suffix=""):
    """安全格式化证据包中的数值，不制造不存在的精度。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}{suffix}"


def _linked_evidence_details(evidence_ids, evidence_by_id, assessments):
    """生成页面可展开的完整证据摘要。"""
    details = []
    for evidence_id in evidence_ids:
        event = evidence_by_id.get(evidence_id) or {}
        assessment = assessments.get(evidence_id) or {}
        details.append({
            "evidence_id": evidence_id,
            "title": str(event.get("title") or "").strip(),
            "sources": list(event.get("sources") or []),
            "source_urls": list(event.get("source_urls") or []),
            "publish_time": str(event.get("publish_time") or "").strip(),
            "event_type": str(assessment.get("event_type") or event.get("event_type") or "").strip(),
            "value_level": str(assessment.get("value_level") or "").strip(),
            "direction": str(assessment.get("direction") or "").strip(),
            "horizon": str(assessment.get("horizon") or "").strip(),
            "confidence": str(assessment.get("confidence") or "").strip(),
            "assessment_reason": str(assessment.get("reason") or "").strip(),
        })
    return details


def _primary_evidence(evidence_ids, evidence_by_id, assessments):
    """优先选取价值和置信度更高的关联事件。"""
    value_order = {"高": 3, "中": 2, "低": 1}
    confidence_order = {"高": 3, "中": 2, "低": 1}
    rows = []
    for evidence_id in evidence_ids:
        event = evidence_by_id.get(evidence_id) or {}
        assessment = assessments.get(evidence_id) or {}
        rows.append((
            value_order.get(str(assessment.get("value_level") or ""), 0),
            confidence_order.get(str(assessment.get("confidence") or ""), 0),
            str(event.get("publish_time") or ""),
            event,
            assessment,
        ))
    rows.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return (rows[0][3], rows[0][4]) if rows else ({}, {})


def _sector_market_check(fact):
    """把行业行情事实压缩成一句可读校验。"""
    parts = []
    if fact.get("stage"):
        parts.append(f"阶段为{fact['stage']}")
    for label, key in (("5日表现", "ret_5d"), ("10日相对强度", "relative_10d"), ("热度", "heat_score")):
        value = _number_text(fact.get(key), "%" if key != "heat_score" else "")
        if value:
            parts.append(f"{label}{value}")
    return "；".join(parts) if parts else "当前证据包没有该板块的量价主线数据，仅能作为消息观察。"


def _stock_market_check(stock):
    """把个股候选的真实行情字段压缩成一句可读校验。"""
    parts = []
    for label, key in (("5日", "ret_5d"), ("10日", "ret_10d"), ("相对行业10日", "stock_vs_sector_10d")):
        value = _number_text(stock.get(key), "%")
        if value:
            parts.append(f"{label}{value}")
    amount_ratio = _number_text(stock.get("amount_ratio_5d"), "倍")
    if amount_ratio:
        parts.append(f"量能为5日均值{amount_ratio}")
    moneyflow = _number_text(stock.get("net_mf_amount"), "万元")
    if moneyflow:
        parts.append(f"主力净流{moneyflow}")
    if stock.get("above_ma20") is not None:
        parts.append("位于20日线上" if stock.get("above_ma20") else "仍在20日线下")
    return "；".join(parts) if parts else "当前仅有事件证据，尚无可用量价承接数据。"


def _enrich_sector_focus_v2(item, evidence_by_id, assessments, fact):
    """保留高质量 AI 文案，并为通用文案补齐事实和验证链。"""
    row = dict(item)
    evidence_ids = list(row.get("evidence_ids") or [])
    event, assessment = _primary_evidence(evidence_ids, evidence_by_id, assessments)
    title = str(event.get("title") or "").strip()
    impact_chain = str(row.get("impact_chain") or assessment.get("reason") or "").strip()
    if _is_generic_research_copy(row.get("reason")) and title:
        row["reason"] = title[:220]
    row["impact_chain"] = impact_chain[:220]
    row["market_check"] = _sector_market_check(fact)
    if _is_generic_research_copy(row.get("validation")):
        if fact:
            row["validation"] = "后续关注相对强度能否维持、成交是否扩散到板块内更多个股。"
        else:
            row["validation"] = "先等待板块相对强度转正并出现成交扩散，再判断消息是否被市场承接。"
    if _is_generic_research_copy(row.get("invalidation")):
        row["invalidation"] = "若消息未获权威来源确认，或板块相对强度持续走弱且无个股扩散，则该逻辑失效。"
    row["evidence_details"] = _linked_evidence_details(evidence_ids, evidence_by_id, assessments)
    return row


def _enrich_stock_focus_v2(item, evidence_by_id, assessments, stock):
    """把个股卡从通用提示升级为事件事实、传导和量价校验。"""
    row = dict(item)
    evidence_ids = list(row.get("evidence_ids") or [])
    event, assessment = _primary_evidence(evidence_ids, evidence_by_id, assessments)
    title = str(event.get("title") or "").strip()
    assessment_reason = str(assessment.get("reason") or "").strip()
    if _is_generic_research_copy(row.get("reason")) and title:
        row["reason"] = title[:220]
    if _is_generic_research_copy(row.get("news_logic")):
        row["news_logic"] = assessment_reason[:220] or "事件与公司存在直接文字关联，但经营传导仍需进一步确认。"
    row["market_check"] = _stock_market_check(stock)
    if _is_generic_research_copy(row.get("validation")):
        if stock.get("quant_selected"):
            row["validation"] = "量化候选条件需继续成立，同时观察相对行业强度、20日线和量能是否同步改善。"
        else:
            row["validation"] = "当前仅由事件入口纳入；需出现价格站稳20日线、量能改善或资金持续流入后再升级。"
    if _is_generic_research_copy(row.get("risk")):
        confidence = str(assessment.get("confidence") or "").strip()
        if confidence == "低":
            row["risk"] = "事件置信度较低，若无公告或第二可信来源确认，关联关系可能不成立。"
        else:
            row["risk"] = "若事件已被提前计价，或后续量价与消息方向背离，短期影响可能迅速衰减。"
    row["evidence_details"] = _linked_evidence_details(evidence_ids, evidence_by_id, assessments)
    return row


def _classify_stock_relation_v2(stock, evidence_ids, evidence_by_id, assessments):
    if set(stock.get("direct_evidence_ids") or []).intersection(evidence_ids):
        return "direct", "公司直接相关"
    name, code = str(stock.get("name") or "").strip(), str(stock.get("ts_code") or "").split(".", 1)[0]
    industry = str(stock.get("industry") or "").strip()
    for evidence_id in evidence_ids:
        event = evidence_by_id.get(evidence_id) or {}
        text = f"{event.get('title') or ''} {event.get('summary') or ''}"
        if (len(name) >= 3 and name in text) or (len(code) == 6 and code in text):
            return "direct", "公司直接相关"
    for evidence_id in evidence_ids:
        mapped = {str(item).strip() for item in (assessments.get(evidence_id) or {}).get("mapped_industries") or []}
        mapped.update(str(item).strip() for item in (evidence_by_id.get(evidence_id) or {}).get("mapped_industries") or [])
        if industry and industry in mapped:
            return "industry", "行业直接相关"
    return ("weak", "间接线索") if evidence_ids else ("none", "暂无消息关联")


def _stock_impact_direction_v2(evidence_ids, assessments):
    """以关联消息方向为准；多空冲突或无明确消息时归为中性。"""
    directions = {
        str(assessments.get(evidence_id, {}).get("direction") or "")
        for evidence_id in evidence_ids
    }
    directions &= {"利多", "利空"}
    if directions == {"利多"}:
        return "利多"
    if directions == {"利空"}:
        return "利空"
    return "中性"


def _stock_focus_row_v2(stock, row, evidence_ids, level, label, evidence_by_id, assessments=None):
    quant = bool(stock.get("quant_selected"))
    if level in {"direct", "industry"} and quant:
        focus_type, source_label = "消息×量价", "双入口共振"
    elif level == "direct":
        focus_type, source_label = "消息驱动", "新闻直接提及"
    else:
        focus_type, source_label = "仅量价候选", "等待消息补证"
    impact_direction = _stock_impact_direction_v2(evidence_ids, assessments or {})
    stance = str(row.get("stance") or "等待消息确认")
    if stance not in {"优先观察", "等待量价确认", "等待消息确认", "风险回避", "回避"}:
        stance = "等待消息确认"
    if impact_direction == "利空":
        stance = "风险回避"
    elif focus_type == "仅量价候选":
        stance = "等待消息确认"
    elif impact_direction == "中性":
        stance = "等待方向确认"
    elif focus_type == "消息驱动" and stance == "优先观察":
        stance = "等待量价确认"
    elif focus_type == "仅量价候选" and stance == "优先观察":
        stance = "等待消息确认"
    return {"ts_code": stock["ts_code"], "name": stock["name"], "industry": stock["industry"], "candidate_score": stock.get("candidate_score"), "stance": stance, "impact_direction": impact_direction, "focus_type": focus_type, "source_label": source_label, "relation_level": level, "relation_label": label, "reason": str(row.get("reason") or stock.get("reason") or "")[:180], "news_logic": str(row.get("news_logic") or "")[:160], "evidence_ids": evidence_ids, "evidence_titles": [evidence_by_id[item]["title"] for item in evidence_ids][:3], "validation": str(row.get("validation") or "等待候选条件继续成立")[:140], "risk": str(row.get("risk") or "消息与价格可能不同步")[:140]}


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
