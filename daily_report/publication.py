"""构建公开事实投影并校验最终文章。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


REQUIRED_SECTIONS = (
    "core_judgement",
    "market_context",
    "focus",
    "performance_risk",
    "watch_points",
)

SOURCE_LABELS = {
    "short_formal": "短周期正式观察",
    "short_auxiliary": "短周期辅助观察",
    "longterm_active": "中期观察",
    "market_radar": "市场活跃度观察",
    "dragon_priority": "高活跃度重点观察",
    "dragon_caution": "高活跃度风险观察",
}

STATE_LABELS = {
    "available": "本期有可供分析的观察结果",
    "completed_with_results": "本期有可供分析的观察结果",
    "completed_empty": "本期扫描完成，暂未发现高置信度标的",
    "not_triggered": "当前市场环境未满足该周期的观察条件",
    "disabled": "本期未启用该周期观察",
    "empty": "本期没有新增观察结果",
    "missing": "本期数据不完整",
    "failed": "本期数据暂不可用",
}

REGIME_LABELS = {
    "BULL_TREND": "趋势环境偏强",
    "BULL_PULLBACK": "上行结构中的回调",
    "BEAR_BOUNCE": "弱势环境中的修复",
    "BEAR_TREND": "趋势环境偏弱",
    "BEAR_BOUNCE_OVERRIDE": "弱势环境中的快速修复",
    "BULL_PULLBACK_OVERRIDE": "弱势环境中的强修复",
}

STYLE_LABELS = {
    "momentum": "动量占优",
    "sideways": "震荡分化",
    "bear": "防御占优",
}

BANNED_PATTERN = re.compile(
    r"AI(?:生成|撰写|研判|输出|模型)|Agent|模型|数据库|缓存|\bAPI\b|profile|v\d+|"
    r"BULL_TREND|BULL_PULLBACK|BEAR_BOUNCE|BEAR_TREND|"
    r"(?:formal|auxiliary|medium|activity|leadership|caution)_view|"
    r"score|评分|阈值|权重|买入|卖出|仓位|目标价|稳赚|必涨",
    re.IGNORECASE,
)

FILLER_PHRASES = (
    "作为一个",
    "根据输入JSON",
    "综合来看",
    "值得注意的是",
    "需要指出的是",
)

MARKETING_WORDS = ("重磅", "爆发", "必看", "翻倍", "暴涨")


def build_public_facts(facts: dict) -> dict:
    """仅按白名单重建可交给撰稿环节的事实，不复制内部字典。"""
    market = facts.get("market") or {}
    sentiment = market.get("sentiment") or {}
    public_evidence = {}
    for evidence_id, evidence in (facts.get("evidence_index") or {}).items():
        alias = _public_evidence_id(evidence_id)
        public_evidence[alias] = {
            "label": str(evidence.get("label") or "事实依据"),
            "values": _public_evidence_values(evidence_id, evidence, facts),
        }
    market_view = _clean_market_view(facts.get("market_radar_decision") or {})
    market_view_values = [
        market_view.get("alignment"),
        market_view.get("confidence"),
        *(market_view.get("focus_industries") or []),
        market_view.get("explanation"),
    ]
    public_evidence["market_view"] = {
        "label": "市场综合观察",
        "values": [value for value in market_view_values if value],
    }

    source_states = []
    for source, status in (facts.get("source_status") or {}).items():
        if source not in SOURCE_LABELS and source not in {"dragon", "news"}:
            continue
        label = SOURCE_LABELS.get(source, "活跃度观察" if source == "dragon" else "公开事件观察")
        state = str(status.get("state") or "missing")
        source_states.append({"label": label, "state": STATE_LABELS.get(state, "本期数据不完整"), "count": int(status.get("count") or 0)})

    observations = []
    allowed_entity_refs: list[str] = []
    allowed_risk_refs: list[str] = []
    allowed_validation_refs: list[str] = []
    allowed_stock_codes: list[str] = []
    for item in facts.get("observations") or []:
        code = str(item.get("ts_code") or "")
        stock_ref = f"stock:{code}"
        allowed_entity_refs.append(stock_ref)
        allowed_stock_codes.append(code)
        industry = str(item.get("industry") or "")
        if industry:
            allowed_entity_refs.append(f"industry:{industry}")
        risk_items = []
        for index, text in enumerate(item.get("risks") or []):
            ref = f"{stock_ref}:risk:{index}"
            risk_items.append({"ref": ref, "text": str(text)})
            allowed_risk_refs.append(ref)
            public_evidence[ref] = {"label": f"{item.get('name') or code}风险观察", "values": [str(text)]}
        conflict_items = []
        for index, text in enumerate(item.get("conflicts") or []):
            ref = f"{stock_ref}:conflict:{index}"
            conflict_items.append({"ref": ref, "text": str(text)})
            allowed_risk_refs.append(ref)
            public_evidence[ref] = {"label": f"{item.get('name') or code}分歧观察", "values": [str(text)]}
        validation_items = []
        for index, text in enumerate(item.get("validation") or []):
            ref = f"{stock_ref}:validation:{index}"
            validation_items.append({"ref": ref, "text": str(text)})
            allowed_validation_refs.append(ref)
            public_evidence[ref] = {"label": f"{item.get('name') or code}后续验证", "values": [str(text)]}
        observations.append(
            {
                "entity_ref": stock_ref,
                "code": code,
                "name": str(item.get("name") or ""),
                "industry": industry,
                "observation_views": [SOURCE_LABELS[source] for source in item.get("sources") or [] if source in SOURCE_LABELS],
                "evidence_ids": [
                    _public_evidence_id(f"stock:{code}:{source}")
                    for source in item.get("sources") or []
                    if f"stock:{code}:{source}" in (facts.get("evidence_index") or {})
                ],
                "resonance": [str(value) for value in item.get("resonance") or []],
                "risks": risk_items,
                "conflicts": conflict_items,
                "validation": validation_items,
            }
        )

    sectors = []
    for group, label in (("healthy", "趋势观察"), ("risky", "风险观察")):
        for sector in (facts.get("sectors") or {}).get(group) or []:
            name = str(sector.get("industry") or "")
            if name:
                allowed_entity_refs.append(f"industry:{name}")
            sectors.append(
                {
                    "entity_ref": f"industry:{name}" if name else "",
                    "industry": name,
                    "stage": str(sector.get("stage") or ""),
                    "view": label,
                    "evidence_id": _public_evidence_id(f"sector:{name}:{'healthy' if group == 'healthy' else 'risk'}"),
                }
            )

    events = []
    for index, event in enumerate(facts.get("events") or [], 1):
        events.append(
            {
                "title": str(event.get("title") or ""),
                "industry": str(event.get("industry") or event.get("industry_anchor") or ""),
                "impact": str(event.get("impact") or event.get("direction") or ""),
                "effect_summary": str(event.get("effect_summary") or ""),
                "source_name": str(event.get("source_name") or event.get("original_source") or ""),
                "source_url": str(event.get("source_url") or ""),
                "publish_time": str(event.get("publish_time") or ""),
                "mapped_industries": [str(value) for value in event.get("mapped_industries") or [] if value],
                "verification_points": [str(value) for value in event.get("verification_points") or [] if value],
                "risk_note": str(event.get("risk_note") or ""),
                "evidence_id": f"event:{index}",
            }
        )

    performance = {}
    short = (facts.get("performance") or {}).get("short") or {}
    if short.get("closed_count"):
        performance["short_cycle"] = {
            **_performance_scope(short, "backtest_ic_short"),
            "sample_count": short.get("closed_count"),
            "win_rate": _rounded(short.get("win_rate")),
            "average_return": _rounded(short.get("avg_ret_5d")),
            "average_upside": _rounded(short.get("avg_mfe")),
            "average_drawdown": _rounded(short.get("avg_mae")),
            "evidence_id": "performance:short:recent",
        }
    longterm = (facts.get("performance") or {}).get("longterm") or {}
    if longterm.get("total_samples"):
        performance["medium_cycle"] = {
            **_performance_scope(longterm, "backtest_longterm"),
            "sample_count": longterm.get("total_samples"),
            "completed_periods": [
                {
                    "period": run.get("period"),
                    "sample_count": run.get("sample_count"),
                    "average_return": _rounded(run.get("avg_ret_40d")),
                    "date_start": run.get("date_start"),
                    "date_end": run.get("date_end"),
                }
                for run in (longterm.get("runs") or [])[:6]
            ],
            "evidence_id": "performance:longterm:completed",
        }

    risk_keywords = []
    for item in observations:
        for risk in item["risks"] + item["conflicts"]:
            if "波动" in risk["text"]:
                risk_keywords.append("波动风险")
            if "回撤" in risk["text"]:
                risk_keywords.append("回撤风险")
            if "高热" in risk["text"] or "退潮" in risk["text"]:
                risk_keywords.append("高热风险")

    return {
        "report_date": facts.get("report_date"),
        "market_date": facts.get("market_date"),
        "cutoffs": facts.get("cutoffs") or {},
        "confidence_cap": (facts.get("completeness") or {}).get("confidence_cap", "中"),
        "market": {
            "trend_environment": REGIME_LABELS.get(str(market.get("regime") or ""), "市场方向仍需确认"),
            "style": STYLE_LABELS.get(str(market.get("market_style") or ""), "结构分化"),
            "sentiment": str(sentiment.get("sentiment") or ""),
            "limit_up_count": sentiment.get("limit_up_count"),
            "limit_down_count": sentiment.get("limit_down_count"),
            "evidence_id": "market:state",
        },
        "market_view": market_view,
        "source_states": source_states,
        "sectors": sectors,
        "events": events,
        "observations": observations,
        "performance": performance,
        "evidence": public_evidence,
        "allowed_entity_refs": list(dict.fromkeys(ref for ref in allowed_entity_refs if ref)),
        "allowed_risk_refs": list(dict.fromkeys(allowed_risk_refs)),
        "allowed_validation_refs": list(dict.fromkeys(allowed_validation_refs)),
        "allowed_stock_codes": list(dict.fromkeys(allowed_stock_codes)),
        "risk_keywords": list(dict.fromkeys(risk_keywords)),
    }


def validate_report(document: dict, facts: dict, public_facts: dict) -> list[str]:
    """对文章结构、来源边界、数字和措辞执行确定性校验。"""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["document must be an object"]
    if not isinstance(document.get("title"), str):
        errors.append("title must be a string")
    title = str(document.get("title") or "").strip()
    visible_title = re.sub(r"\s+", "", title)
    if not 12 <= len(visible_title) <= 24:
        errors.append("title length must be 12-24 visible characters")
    if any(word in title for word in MARKETING_WORDS):
        errors.append("title contains marketing language")
    errors.extend(_language_errors(title, "title"))

    if not isinstance(document.get("keywords", []), list):
        errors.append("keywords must be a list")
    sections = document.get("sections")
    if not isinstance(sections, list):
        return errors + ["sections must be a list"]
    keys = [str(section.get("key") or "") for section in sections if isinstance(section, dict)]
    if tuple(keys) != REQUIRED_SECTIONS:
        errors.append("section keys or order are invalid")

    allowed_entities = set(public_facts.get("allowed_entity_refs") or [])
    allowed_risks = set(public_facts.get("allowed_risk_refs") or [])
    allowed_validations = set(public_facts.get("allowed_validation_refs") or [])
    allowed_codes = {str(code).split(".")[0] for code in public_facts.get("allowed_stock_codes") or []}
    public_evidence = public_facts.get("evidence") or {}

    def heading_evidence(items):
        resolved = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("paragraphs"), list):
                continue
            for paragraph in item["paragraphs"]:
                if not isinstance(paragraph, dict) or not isinstance(paragraph.get("evidence_ids"), list):
                    continue
                for ref in paragraph["evidence_ids"]:
                    if isinstance(ref, str) and _public_evidence_id(ref) in public_evidence:
                        resolved.append(public_evidence[_public_evidence_id(ref)])
        return resolved

    errors.extend(_numeric_errors(title, heading_evidence(sections), facts))

    for section in sections:
        if not isinstance(section, dict):
            errors.append("section must be an object")
            continue
        section_key = str(section.get("key") or "")
        heading = section.get("heading", "")
        if not isinstance(heading, str):
            errors.append("section heading must be a string")
        else:
            errors.extend(_language_errors(heading, "heading"))
            errors.extend(_numeric_errors(heading, heading_evidence([section]), facts))
            if section_key == "performance_risk" and "验证" in heading:
                errors.extend(_historical_validation_errors(heading))
        paragraphs = section.get("paragraphs")
        if not isinstance(paragraphs, list) or not paragraphs:
            errors.append(f"section has no paragraphs: {section_key}")
            continue
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                errors.append(f"paragraph must be an object: {section_key}")
                continue
            if not isinstance(paragraph.get("text"), str):
                errors.append("paragraph text must be a string")
                continue
            text = str(paragraph.get("text") or "").strip()
            if not text:
                errors.append(f"empty paragraph: {section_key}")
                continue
            errors.extend(_language_errors(text, section_key))
            malformed = False
            for field in ("evidence_ids", "entity_refs", "risk_refs", "validation_refs", "gap_refs"):
                refs = paragraph.get(field, [])
                if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                    errors.append(f"{field} must be a list of strings: {section_key}")
                    malformed = True
            if malformed:
                continue
            evidence_ids = paragraph.get("evidence_ids") or []
            if not evidence_ids:
                errors.append(f"paragraph lacks evidence: {section_key}")
            resolved_evidence = []
            for evidence_id in evidence_ids:
                alias = _public_evidence_id(evidence_id)
                if alias in public_evidence:
                    resolved_evidence.append(public_evidence[alias])
                else:
                    errors.append(f"unknown evidence id: {evidence_id}")
            for entity_ref in paragraph.get("entity_refs") or []:
                if entity_ref not in allowed_entities:
                    errors.append(f"unknown entity ref: {entity_ref}")
            for code in re.findall(r"(?<![\d.])(\d{6})(?!\d)", text):
                if code not in allowed_codes:
                    errors.append(f"unapproved stock code: {code}")
            errors.extend(_numeric_errors(text, resolved_evidence, facts))
            if any(ref.startswith("performance:") for ref in evidence_ids):
                if not all(term in text for term in ("历史回测", "区间", "样本", "验证")):
                    errors.append("historical performance must state source, period, sample and validation limits")
                errors.extend(_historical_validation_errors(text))
                if re.search(r"(?:说明|表明|证明|意味着).{0,15}(?:当前|今日|市场活跃度)", text):
                    errors.append("historical performance cannot explain current market")
            if section_key == "focus" and any(
                str(ref).startswith("stock:") for ref in paragraph.get("entity_refs") or []
            ):
                risk_refs = set(paragraph.get("risk_refs") or [])
                validation_refs = set(paragraph.get("validation_refs") or [])
                gap_refs = set(paragraph.get("gap_refs") or [])
                evidence_refs = set(evidence_ids)
                if not (
                    (risk_refs & allowed_risks)
                    or (validation_refs & allowed_validations)
                    or (evidence_refs & (allowed_risks | allowed_validations))
                    or gap_refs
                ):
                    errors.append("stock focus paragraph lacks risk or validation reference")
            for ref in paragraph.get("risk_refs") or []:
                if ref not in allowed_risks:
                    errors.append(f"unknown risk ref: {ref}")
            for ref in paragraph.get("validation_refs") or []:
                if ref not in allowed_validations:
                    errors.append(f"unknown validation ref: {ref}")
    return list(dict.fromkeys(errors))


def report_to_plain_text(document: dict) -> str:
    lines = [str(document.get("title") or "").strip()]
    for section in document.get("sections") or []:
        heading = str(section.get("heading") or "").strip()
        if heading:
            lines.append(heading)
        for paragraph in section.get("paragraphs") or []:
            text = str(paragraph.get("text") or "").strip()
            if text:
                lines.append(text)
    return "\n\n".join(line for line in lines if line)


def extract_search_keywords(document: dict, public_facts: dict) -> list[str]:
    allowed = set(public_facts.get("risk_keywords") or [])
    codes = []
    for observation in public_facts.get("observations") or []:
        for value in (observation.get("name"), observation.get("industry")):
            if value:
                allowed.add(str(value))
        if observation.get("code"):
            codes.append(str(observation["code"]))
    for sector in public_facts.get("sectors") or []:
        if sector.get("industry"):
            allowed.add(str(sector["industry"]))
    for event in public_facts.get("events") or []:
        if event.get("title"):
            allowed.add(str(event["title"]))
    result = []
    for value in list(document.get("keywords") or []) + codes:
        keyword = str(value).strip()
        if keyword and (keyword in allowed or keyword in codes) and not BANNED_PATTERN.search(keyword):
            result.append(keyword)
    return list(dict.fromkeys(result))[:40]


def _public_evidence_id(evidence_id: str) -> str:
    replacements = {
        "short_formal": "formal_view",
        "short_auxiliary": "auxiliary_view",
        "longterm_active": "medium_view",
        "market_radar": "activity_view",
        "dragon_priority": "leadership_view",
        "dragon_caution": "caution_view",
    }
    result = str(evidence_id)
    for internal, public in replacements.items():
        result = result.replace(internal, public)
    return result


def _safe_values(values: list) -> list:
    return [value for value in values if isinstance(value, (str, int, float, bool))]


def _public_evidence_values(evidence_id: str, evidence: dict, facts: dict) -> list:
    """按证据类型提取公开值，剔除名次、内部数值和状态枚举。"""
    payload = evidence.get("payload") if isinstance(evidence.get("payload"), dict) else {}
    if evidence_id == "market:state":
        market = facts.get("market") or {}
        sentiment = market.get("sentiment") or {}
        return _safe_values(
            [
                REGIME_LABELS.get(str(market.get("regime") or ""), "市场方向仍需确认"),
                STYLE_LABELS.get(str(market.get("market_style") or ""), "结构分化"),
                sentiment.get("sentiment"),
                sentiment.get("limit_up_count"),
                sentiment.get("limit_down_count"),
            ]
        )
    if evidence_id.startswith("sector:"):
        parts = evidence_id.split(":")
        industry = parts[1] if len(parts) > 2 else ""
        group = "healthy" if evidence_id.endswith(":healthy") else "risky"
        sector = next(
            (
                item
                for item in ((facts.get("sectors") or {}).get(group) or [])
                if str(item.get("industry") or "") == industry
            ),
            {},
        )
        return _safe_values([industry, sector.get("stage")])
    if evidence_id.startswith("stock:"):
        source = evidence_id.rsplit(":", 1)[-1]
        allowed_fields = {
            "short_formal": ("reason",),
            "short_auxiliary": ("reason", "observation_reason"),
            "longterm_active": ("days_in_pool", "last_reason", "first_seen_date", "last_seen_date"),
            "market_radar": ("stage", "pct_chg", "change"),
            "dragon_priority": ("stage", "theme_state", "action", "badges", "turnover_rate"),
            "dragon_caution": ("stage", "theme_state", "action", "badges", "turnover_rate"),
        }.get(source, ())
        values = []
        for field in allowed_fields:
            value = payload.get(field)
            if isinstance(value, (list, tuple)):
                values.extend(value)
            elif value is not None:
                values.append(value)
        if not values:
            values = [value for value in evidence.get("values") or [] if isinstance(value, str)]
        return [value for value in _safe_values(values) if not BANNED_PATTERN.search(str(value))]
    if evidence_id.startswith("event:"):
        values = [
            payload.get("title"), payload.get("industry") or payload.get("industry_anchor"),
            payload.get("impact") or payload.get("direction"), payload.get("effect_summary"),
            payload.get("source_name") or payload.get("original_source"), payload.get("publish_time"),
            *(payload.get("mapped_industries") or []), *(payload.get("verification_points") or []),
            payload.get("risk_note"),
        ]
        return _safe_values(values) if any(value is not None for value in values) else _safe_values(evidence.get("values") or [])
    if evidence_id == "performance:short:recent":
        short = (facts.get("performance") or {}).get("short") or {}
        return list(_performance_scope(short, "backtest_ic_short").values()) + _safe_values([short.get("closed_count"), _rounded(short.get("win_rate")), _rounded(short.get("avg_ret_5d")), _rounded(short.get("avg_mfe")), short.get("avg_mae")])
    if evidence_id == "performance:longterm:completed":
        longterm = (facts.get("performance") or {}).get("longterm") or {}
        values = list(_performance_scope(longterm, "backtest_longterm").values()) + [longterm.get("total_samples")]
        for run in (longterm.get("runs") or [])[:6]:
            values.extend([run.get("period"), run.get("sample_count"), run.get("avg_ret_40d")])
        return _safe_values(values)
    return []


def _clean_market_view(view: dict) -> dict:
    return {
        "alignment": str(view.get("alignment") or ""),
        "confidence": str(view.get("confidence") or ""),
        "focus_industries": [str(value) for value in view.get("focus_industries") or []],
        "explanation": str(view.get("explanation") or ""),
    }


def _language_errors(text: str, location: str) -> list[str]:
    errors = []
    banned_match = BANNED_PATTERN.search(text)
    if banned_match:
        errors.append(f"banned language in {location}: {banned_match.group(0)}")
    if any(phrase in text for phrase in FILLER_PHRASES):
        errors.append(f"filler language in {location}")
    return errors


def _numeric_errors(text: str, evidence: list[dict], facts: dict) -> list[str]:
    tokens = set(re.findall(r"(?<![a-zA-Z0-9_.])[-+]?\d+(?:\.\d+)?%?", text))
    if not tokens:
        return []
    allowed_text = []
    for item in evidence:
        allowed_text.extend(str(value) for value in item.get("values") or [])
    allowed_text.extend(str(value) for value in (facts.get("cutoffs") or {}).values())
    allowed_text.extend([str(facts.get("report_date") or ""), str(facts.get("market_date") or "")])
    allowed_tokens = set()
    for value in allowed_text:
        allowed_tokens.update(re.findall(r"[-+]?\d+(?:\.\d+)?%?", value))
    errors = []
    normalized_allowed = {value.rstrip("%") for value in allowed_tokens}
    for token in tokens:
        normalized = token.rstrip("%")
        if token in allowed_tokens or normalized in normalized_allowed:
            continue
        try:
            token_value = float(normalized)
            decimal_places = len(normalized.split(".", 1)[1]) if "." in normalized else 0
            matched = False
            for value in allowed_tokens:
                allowed_value = float(value.rstrip("%"))
                candidates = [allowed_value]
                if token.endswith("%") and not value.endswith("%"):
                    candidates.append(allowed_value * 100)
                if any(round(candidate, decimal_places) == round(token_value, decimal_places) for candidate in candidates):
                    matched = True
                    break
            if matched:
                continue
        except ValueError:
            pass
        errors.append(f"untraceable numeric token: {token}")
    return errors


def safe_source_url(value: str) -> str:
    """公开链接仅允许不含凭据的 HTTP(S) 地址。"""
    value = str(value or "").strip()
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username is not None or parsed.password is not None or any(ord(c) < 32 for c in value):
            return ""
        return value
    except ValueError:
        return ""


def build_evidence_snapshot(document: dict, public_facts: dict) -> dict:
    """只保存本次文章引用的公开投影，禁止复制内部原始对象。"""
    evidence = public_facts.get("evidence") or {}
    events = {item["evidence_id"]: item for item in public_facts.get("events") or []}
    snapshot = {}
    for section in document["sections"]:
        for paragraph in section["paragraphs"]:
            for ref in paragraph["evidence_ids"]:
                item = evidence.get(_public_evidence_id(ref))
                if not item:
                    continue
                event = events.get(ref, {})
                snapshot[ref] = {
                    "label": str(item.get("label") or "事实依据")[:120],
                    "text": "；".join(str(value) for value in item.get("values") or [] if isinstance(value, (str, int, float)))[:800],
                    "source_url": safe_source_url(event.get("source_url")),
                    "published_at": str(event.get("publish_time") or "")[:80],
                }
    return snapshot


def _rounded(value):
    return round(value, 2) if isinstance(value, (int, float)) else value


def _performance_scope(performance: dict, source: str) -> dict:
    return {
        "source": source,
        "source_label": "短周期历史回测" if source == "backtest_ic_short" else "中期历史回测",
        "date_start": str(performance.get("date_start") or "未记录"),
        "date_end": str(performance.get("date_end") or "未记录"),
        "validation_limit": "历史回测尚未按当前版本重新验证，不代表当前行情或实盘成绩，不能推断当前市场兑现能力",
        "period_scope": "日期区间仅覆盖已加载的回测记录；总样本量可能包含其他历史批次" if source == "backtest_longterm" else "日期区间为本次已成熟样本的信号日期",
    }


def _historical_validation_errors(text: str) -> list[str]:
    """历史绩效固定为未重跑状态，要求明确保留该状态而非推测验证结论。"""
    if "尚未按当前版本重新验证" not in text:
        return ["historical performance must retain unverified current-version status"]
    if re.search(r"(?:已|已经|现已)(?:通过|完成).{0,12}验证|验证(?:已|已经)(?:通过|完成|有效)", text):
        return ["historical performance cannot claim completed validation"]
    return []
