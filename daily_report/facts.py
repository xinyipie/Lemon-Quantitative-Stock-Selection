"""汇总每日研究报告所需的内部事实快照。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


VALID_SCAN_STATES = {
    "completed_with_results",
    "completed_empty",
    "not_triggered",
    "disabled",
}


@dataclass
class FactSources:
    selection_snapshot: Callable[..., dict | None]
    recent_signals: Callable[..., list[dict]]
    active_longterm: Callable[..., list[dict]]
    signal_runs: Callable[..., list[dict]]
    longterm_runs: Callable[..., list[dict]]
    longterm_events: Callable[..., list[dict]]
    longterm_audit_summary: Callable[..., dict]
    sector_radar: Callable[..., dict]
    concept_news: Callable[..., dict]
    radar_decision: Callable[[dict, dict], dict]
    dragon_observation: Callable[..., dict]
    short_performance: Callable[[list[dict], int], dict]


def default_fact_sources() -> FactSources:
    """延迟导入现有只读服务，避免报告模块改变主流程初始化。"""
    from daily_report.selection_snapshot import get_selection_snapshot
    from web_app.services.dragon_service import build_dragon_observation
    from web_app.services.sector_service import (
        build_concept_news_radar,
        build_market_radar_decision,
        build_sector_radar,
    )
    from web_app.services.signal_service import (
        get_active_longterm_pool,
        get_longterm_audit_summary,
        get_longterm_events,
        get_longterm_runs,
        get_recent_signals,
        get_signal_runs,
        summarize_short_signal_performance,
    )

    return FactSources(
        selection_snapshot=get_selection_snapshot,
        recent_signals=get_recent_signals,
        active_longterm=get_active_longterm_pool,
        signal_runs=get_signal_runs,
        longterm_runs=get_longterm_runs,
        longterm_events=get_longterm_events,
        longterm_audit_summary=get_longterm_audit_summary,
        sector_radar=build_sector_radar,
        concept_news=build_concept_news_radar,
        radar_decision=build_market_radar_decision,
        dragon_observation=build_dragon_observation,
        short_performance=summarize_short_signal_performance,
    )


def build_daily_report_facts(
    report_date: str,
    market_date: str,
    signal_db: str | Path,
    history_db: str | Path,
    now: datetime | None = None,
    sources: FactSources | None = None,
) -> dict:
    """生成一次不可变事实快照，公开文章只能引用其中证据。"""
    adapters = sources or default_fact_sources()
    report_date = _date(report_date)
    market_date = _date(market_date)
    generated_at = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    warnings: list[str] = []

    snapshot, snapshot_error = _safe_call(
        adapters.selection_snapshot, signal_db, market_date, default=None
    )
    if snapshot_error:
        warnings.append("正式扫描快照读取失败")

    short_formal, formal_error = _safe_call(
        adapters.recent_signals,
        signal_db,
        history_db=history_db,
        limit=50,
        source="live",
        mode="short",
        start=market_date,
        end=market_date,
        default=[],
    )
    short_observe, observe_error = _safe_call(
        adapters.recent_signals,
        signal_db,
        history_db=history_db,
        limit=20,
        source="live_observe",
        mode="short",
        start=market_date,
        end=market_date,
        default=[],
    )
    active_longterm, longterm_error = _safe_call(
        adapters.active_longterm, signal_db, default=[]
    )
    radar, radar_error = _safe_call(
        adapters.sector_radar, history_db=history_db, end_date=market_date, default={}
    )
    concept_news, news_error = _safe_call(
        adapters.concept_news,
        signal_db=signal_db,
        today=market_date,
        limit=50,
        default={},
    )
    decision, decision_error = _safe_call(
        adapters.radar_decision, radar or {}, concept_news or {}, default={}
    )
    dragon, dragon_error = _safe_call(
        adapters.dragon_observation, end_date=market_date, default={}
    )

    review_signals, review_error = _safe_call(
        adapters.recent_signals,
        signal_db,
        history_db=history_db,
        limit=300,
        source="backtest_ic_short",
        mode="short",
        default=[],
    )
    short_performance, performance_error = _safe_call(
        adapters.short_performance, review_signals or [], 300, default={}
    )
    longterm_audit, audit_error = _safe_call(
        adapters.longterm_audit_summary, signal_db, limit=12, half_year_only=True, default={}
    )

    optional_errors = {
        "short_formal": formal_error,
        "short_auxiliary": observe_error,
        "longterm_active": longterm_error,
        "market_radar": radar_error or decision_error,
        "news": news_error,
        "dragon": dragon_error,
        "short_performance": review_error or performance_error,
        "longterm_performance": audit_error,
    }
    warnings.extend(f"{name}数据读取失败" for name, error in optional_errors.items() if error)

    snapshot = snapshot or {}
    short_scan = snapshot.get("short_scan") or {}
    longterm_scan = snapshot.get("longterm_scan") or {}
    source_status = {
        "short_formal": _scan_status(short_scan.get("status"), len(short_formal or []), formal_error),
        "short_auxiliary": _optional_status(len(short_observe or []), observe_error),
        "longterm_active": _scan_status(longterm_scan.get("status"), len(active_longterm or []), longterm_error),
        "market_radar": _optional_status(len((radar or {}).get("candidates") or []), radar_error),
        "dragon": _optional_status(_dragon_count(dragon or {}), dragon_error),
        "news": _optional_status(len((concept_news or {}).get("reading_events") or []), news_error),
    }

    observations: dict[str, dict] = {}
    for source_name, rows in (
        ("short_formal", short_formal or []),
        ("short_auxiliary", short_observe or []),
        ("longterm_active", active_longterm or []),
        ("market_radar", (radar or {}).get("candidates") or []),
    ):
        for row in rows:
            _merge_observation(observations, source_name, row)

    groups = (dragon or {}).get("display_groups") or {}
    for group_name, source_name in (("priority", "dragon_priority"), ("caution", "dragon_caution")):
        for row in groups.get(group_name) or []:
            _merge_observation(observations, source_name, row)

    risky_industries = {
        str(item.get("industry") or "")
        for item in (radar or {}).get("risky") or []
        if item.get("industry")
    }
    for item in observations.values():
        if len(item["sources"]) >= 2:
            item["resonance"].append("多个独立观察来源同时出现")
        if "dragon_caution" in item["sources"]:
            item["conflicts"].append("高活跃度观察已将其列入风险关注")
            item["risks"].append("短期分歧尚未充分收敛，波动可能放大")
        if item.get("industry") in risky_industries:
            item["conflicts"].append("所属行业处于高热或退潮观察区")
            item["risks"].append("行业热度与个股信号存在错位风险")
        for source_name in ("dragon_priority", "dragon_caution"):
            evidence = item["source_evidence"].get(source_name) or {}
            if evidence.get("late_or_fragile") or "分歧" in str(evidence.get("stage") or ""):
                item["conflicts"].append("活跃度观察显示高位分歧或承接脆弱")
                item["risks"].append("短期波动和回撤可能放大")
        item["conflicts"] = list(dict.fromkeys(item["conflicts"]))
        item["risks"] = list(dict.fromkeys(item["risks"]))
        item["validation"] = _validation_points(item)

    evidence_index: dict[str, dict] = {}
    market = snapshot.get("market") or {}
    evidence_index["market:state"] = _evidence("市场状态", market)
    for sector in (radar or {}).get("healthy") or []:
        name = str(sector.get("industry") or "未知")
        evidence_index[f"sector:{name}:healthy"] = _evidence(f"{name}行业观察", sector)
    for sector in (radar or {}).get("risky") or []:
        name = str(sector.get("industry") or "未知")
        evidence_index[f"sector:{name}:risk"] = _evidence(f"{name}行业风险", sector)
    for item in observations.values():
        for source_name, source_evidence in item["source_evidence"].items():
            evidence_index[f"stock:{item['ts_code']}:{source_name}"] = _evidence(
                f"{item.get('name') or item['ts_code']}观察", source_evidence
            )
    for index, event in enumerate((concept_news or {}).get("reading_events") or [], 1):
        evidence_index[f"event:{index}"] = _evidence(str(event.get("title") or f"事件{index}"), event)
    if (short_performance or {}).get("closed_count"):
        evidence_index["performance:short:recent"] = _evidence("近期成熟短周期样本", short_performance)
    if (longterm_audit or {}).get("total_samples"):
        evidence_index["performance:longterm:completed"] = _evidence("已完成中期样本", longterm_audit)

    critical_states = [short_scan.get("status"), longterm_scan.get("status")]
    snapshot_valid = bool(snapshot) and snapshot.get("trade_date") == market_date
    states_valid = all(state in VALID_SCAN_STATES for state in critical_states)
    market_valid = bool(market)
    can_publish = snapshot_valid and states_valid and market_valid
    if not snapshot_valid:
        warnings.append("缺少与行情日期一致的正式扫描快照")
    if not states_valid:
        warnings.append("正式扫描状态不完整")
    if not market_valid:
        warnings.append("市场事实缺失")
    confidence_cap = "高"
    missing_optional = sum(bool(error) for error in optional_errors.values())
    if missing_optional >= 3:
        confidence_cap = "低"
    elif missing_optional or not radar or not concept_news:
        confidence_cap = "中"

    facts = {
        "report_date": report_date,
        "market_date": market_date,
        "generated_at": generated_at,
        "cutoffs": {
            "data": str(snapshot.get("created_at") or generated_at),
            "news": str(((concept_news or {}).get("news") or {}).get("source_date") or generated_at),
        },
        "market": market,
        "market_radar_decision": decision or {},
        "sectors": {
            "summary": (radar or {}).get("summary") or {},
            "healthy": (radar or {}).get("healthy") or [],
            "risky": (radar or {}).get("risky") or [],
        },
        "events": (concept_news or {}).get("reading_events") or [],
        "observations": list(observations.values()),
        "source_status": source_status,
        "performance": {
            "short": short_performance or {},
            "longterm": longterm_audit or {},
        },
        "evidence_index": evidence_index,
        "completeness": {
            "can_publish": can_publish,
            "confidence_cap": confidence_cap,
            "warnings": list(dict.fromkeys(warnings)),
        },
    }
    facts["input_hash"] = hashlib.sha256(
        json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return facts


def _safe_call(function: Callable, *args, default, **kwargs):
    try:
        return function(*args, **kwargs), ""
    except Exception as exc:
        return default, f"{type(exc).__name__}: {exc}"


def _date(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))[:8]


def _scan_status(scan_state: str | None, count: int, error: str) -> dict:
    if error:
        state = "failed"
    elif scan_state == "completed_with_results":
        state = "available" if count else "missing"
    elif scan_state in VALID_SCAN_STATES:
        state = scan_state
    else:
        state = "missing"
    return {"state": state, "count": int(count), "scan_state": scan_state or "missing"}


def _optional_status(count: int, error: str) -> dict:
    return {"state": "failed" if error else ("available" if count else "empty"), "count": int(count)}


def _dragon_count(dragon: dict) -> int:
    groups = dragon.get("display_groups") or {}
    return len(groups.get("priority") or []) + len(groups.get("caution") or [])


def _normalize_code(row: dict) -> str:
    code = str(row.get("ts_code") or row.get("code") or "").strip().upper()
    if re.fullmatch(r"\d{6}", code):
        code += ".SH" if code.startswith(("5", "6", "9")) else ".SZ"
    return code


def _merge_observation(target: dict[str, dict], source_name: str, row: dict) -> None:
    code = _normalize_code(row)
    if not re.fullmatch(r"\d{6}\.(SZ|SH|BJ)", code):
        return
    item = target.setdefault(
        code,
        {
            "ts_code": code,
            "name": str(row.get("name") or ""),
            "industry": str(row.get("industry") or ""),
            "sources": [],
            "source_evidence": {},
            "resonance": [],
            "conflicts": [],
            "risks": [],
            "validation": [],
        },
    )
    if not item["name"] and row.get("name"):
        item["name"] = str(row["name"])
    if not item["industry"] and row.get("industry"):
        item["industry"] = str(row["industry"])
    if source_name not in item["sources"]:
        item["sources"].append(source_name)
    item["source_evidence"][source_name] = _clean_evidence(row)


def _clean_evidence(row: dict) -> dict:
    allowed = {
        "rank", "score", "reason", "pool_type", "latest_score", "highest_score",
        "days_in_pool", "last_reason", "first_seen_date", "last_seen_date", "state",
        "stage", "pct_chg", "change", "heat_score", "turnover_rate", "late_or_fragile",
        "theme_name", "theme_state", "observation_reason", "entry_timing",
        "recommendation_layer", "action", "display_rule", "lifecycle", "badges",
    }
    return {key: row.get(key) for key in allowed if row.get(key) is not None}


def _validation_points(item: dict) -> list[str]:
    points = []
    if "market_radar" in item["sources"]:
        points.append("观察行业扩散和成交承接能否延续")
    if "short_formal" in item["sources"] or "short_auxiliary" in item["sources"]:
        points.append("观察次日价格与量能是否继续确认")
    if "longterm_active" in item["sources"]:
        points.append("观察中期趋势结构是否保持")
    if any(source.startswith("dragon_") for source in item["sources"]):
        points.append("观察高活跃阶段的分歧能否收敛")
    return points or ["等待后续行情确认"]


def _evidence(label: str, payload) -> dict:
    return {"label": label, "values": _scalar_values(payload), "payload": payload}


def _scalar_values(value) -> list:
    values: list = []
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_scalar_values(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            values.extend(_scalar_values(item))
    elif value is not None and isinstance(value, (str, int, float, bool)):
        values.append(value)
    return values
