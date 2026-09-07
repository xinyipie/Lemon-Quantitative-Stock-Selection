"""使用两阶段撰稿流程生成高密度研究文章。"""

from __future__ import annotations

import json
from collections.abc import Callable


ANALYST_SYSTEM = """你是A股研究组的内部分析员。只使用输入事实和evidence_id工作。
找出最重要的市场矛盾、跨来源印证、冲突、证据缺口和已成熟表现。
空结果必须保持原来源状态，不能用其他来源补位。
不得创造股票、行业、事件、数字或因果关系。只返回合法JSON。"""

EDITOR_SYSTEM = """你是一名严谨的中文市场研究编辑。把事实和内部分析整理成一篇自然、简洁、信息密度高的文章。
只写证据支持的内容，不创造事实；不出现技术实现、系统、算法或内部规则用语；不提供买卖、仓位、目标价格或收益承诺。
语言要像经验丰富的研究员写给管理层，口语化但专业，删掉套话、总结腔和机械连接词。没有最低字数要求。
个股段落必须同时写清风险、分歧或后续验证条件；证据不足时直接省略该个股。只返回合法JSON。"""


def generate_report_document(
    public_facts: dict,
    ai_config: dict | None = None,
    post: Callable | None = None,
) -> dict | None:
    """先形成分析草稿，再由独立编辑步骤生成最终结构化文章。"""
    base_config = _resolve_config(ai_config)
    analyst_config = _daily_report_stage_config(base_config, "analyst")
    editor_config = _daily_report_stage_config(base_config, "editor")
    if not _valid_config(analyst_config) or not _valid_config(editor_config):
        return None
    public_json = json.dumps(public_facts, ensure_ascii=False, sort_keys=True)
    analyst_prompt = f"""请基于下列公开事实形成内部分析草稿。
输出格式必须是：
{{
  "judgements": [{{"text": "内部判断", "confidence": "高/中/低", "evidence_ids": ["id"]}}],
  "focus_entities": ["stock:000001.SZ"],
  "conflicts": [{{"text": "分歧", "evidence_ids": ["id"]}}],
  "watch_questions": [{{"text": "验证问题", "evidence_ids": ["id"]}}]
}}
公开事实：
{public_json}"""
    draft = _call_json(analyst_prompt, ANALYST_SYSTEM, analyst_config, post, max_tokens=5000)
    if not isinstance(draft, dict):
        return None

    draft_json = json.dumps(draft, ensure_ascii=False, sort_keys=True)
    editor_prompt = f"""请把公开事实和分析草稿编辑成最终文章。
必须返回以下JSON结构，不要Markdown：
{{
  "title": "12至24字事实型标题",
  "sections": [
    {{
      "key": "core_judgement",
      "heading": "核心判断",
      "paragraphs": [
        {{"text": "自然段", "evidence_ids": ["id"], "entity_refs": [], "risk_refs": [], "validation_refs": []}}
      ]
    }}
  ],
  "keywords": ["行业或股票关键词"]
}}
sections必须且只能依次包含：core_judgement、market_context、focus、performance_risk、watch_points。
每个自然段至少引用一个输入中存在的evidence_id。entity_refs、risk_refs、validation_refs只能从公开事实的允许列表选择。
个股若无法同时写出风险、冲突或验证条件，就不要写该个股。标题不能夸张，不要使用宣传性词汇。

公开事实：
{public_json}

分析草稿：
{draft_json}"""
    document = _call_json(editor_prompt, EDITOR_SYSTEM, editor_config, post, max_tokens=12000)
    return _attach_ai_audit(document, editor_config) if isinstance(document, dict) else None


def revise_report_document(
    public_facts: dict,
    document: dict,
    errors: list[str],
    ai_config: dict | None = None,
    post: Callable | None = None,
) -> dict | None:
    """Repair a rejected document without changing its approved fact boundary."""
    config = _daily_report_stage_config(_resolve_config(ai_config), "editor")
    if not _valid_config(config):
        return None
    allowed_numbers = {
        evidence_id: [
            str(value)
            for value in (item.get("values") or [])
            if isinstance(value, (int, float))
        ]
        for evidence_id, item in (public_facts.get("evidence") or {}).items()
    }
    prompt = f"""The following market report failed deterministic validation.
Return a complete corrected JSON document with the same required structure.
Use only the supplied public facts and existing evidence ids.
Remove or rewrite every unsupported number instead of estimating, rounding, or inventing a replacement.
Do not add stocks, industries, events, conclusions, evidence ids, entity refs, risk refs, or validation refs.
Each paragraph may use a number only when that exact value belongs to one of that paragraph's evidence_ids.

Validation errors:
{json.dumps(errors, ensure_ascii=False)}

Allowed numeric values by evidence id:
{json.dumps(allowed_numbers, ensure_ascii=False, sort_keys=True)}

Public facts:
{json.dumps(public_facts, ensure_ascii=False, sort_keys=True)}

Rejected document:
{json.dumps(document, ensure_ascii=False, sort_keys=True)}
"""
    repaired = _call_json(prompt, EDITOR_SYSTEM, config, post, max_tokens=12000)
    return _attach_ai_audit(repaired, config) if isinstance(repaired, dict) else None


def build_deterministic_report_document(public_facts: dict) -> dict | None:
    """Compile an evidence-dense, number-safe report from approved public facts."""
    evidence = public_facts.get("evidence") or {}
    if not isinstance(evidence, dict) or not evidence:
        return None

    market = public_facts.get("market") or {}
    market_id = str(market.get("evidence_id") or "market:state")
    if market_id not in evidence:
        market_id = next(iter(evidence))
    sectors = [item for item in (public_facts.get("sectors") or []) if item.get("evidence_id") in evidence]
    healthy = [item for item in sectors if str(item.get("view") or "") != "风险观察"]
    risky = [item for item in sectors if str(item.get("view") or "") == "风险观察"]
    observations = list(public_facts.get("observations") or [])
    events = [item for item in (public_facts.get("events") or []) if item.get("evidence_id") in evidence]
    performance = public_facts.get("performance") or {}

    def paragraph(text, evidence_ids, entity_refs=None, risk_refs=None, validation_refs=None):
        return {
            "text": text,
            "evidence_ids": list(dict.fromkeys(value for value in evidence_ids if value in evidence)),
            "entity_refs": list(dict.fromkeys(entity_refs or [])),
            "risk_refs": list(dict.fromkeys(risk_refs or [])),
            "validation_refs": list(dict.fromkeys(validation_refs or [])),
        }

    trend = str(market.get("trend_environment") or "市场方向仍待确认")
    style = str(market.get("style") or "结构分化")
    sentiment = str(market.get("sentiment") or "情绪分化")
    core = [paragraph(
        f"市场处于{trend}，风格表现为{style}，情绪状态为{sentiment}。局部活跃与整体趋势并不等同，当前判断仍需结合行业扩散和成交承接。",
        [market_id],
    )]

    context = []
    stage_groups = {}
    for item in healthy[:6]:
        stage_groups.setdefault(str(item.get("stage") or "持续观察"), []).append(str(item.get("industry") or ""))
    if stage_groups:
        clauses = [f"{'、'.join(names)}处于{stage}" for stage, names in stage_groups.items() if any(names)]
        context.append(paragraph(
            "；".join(clauses) + "。这些方向具备行业层面的延续或启动特征，但仍需验证强度能否扩散。",
            [item.get("evidence_id") for item in healthy[:6]],
            [item.get("entity_ref") for item in healthy[:6] if item.get("entity_ref")],
        ))
    if events:
        selected_events = events[:3]
        context.append(paragraph(
            "公开事件线索包括" + "、".join(str(item.get("title") or "") for item in selected_events) + "，需要继续确认其行业映射与市场承接。",
            [item.get("evidence_id") for item in selected_events],
        ))
    else:
        context.append(paragraph(
            "当前主线缺少新增公开事件的交叉印证，行业趋势暂以市场表现验证为主，消息共振仍需等待。",
            [market_id],
        ))

    focus = []
    focus_groups = []
    for sector in healthy:
        industry = str(sector.get("industry") or "")
        group = [item for item in observations if str(item.get("industry") or "") == industry][:3]
        if group:
            focus_groups.append((sector, group))
        if len(focus_groups) >= 3:
            break
    for sector, group in focus_groups:
        names = "、".join(str(item.get("name") or "") for item in group)
        validation_refs = [
            str(entry.get("ref"))
            for item in group
            for entry in (item.get("validation") or [])[:1]
            if entry.get("ref")
        ]
        focus.append(paragraph(
            f"{sector.get('industry')}处于{sector.get('stage')}，代表性观察包括{names}。这些标的仅用于跟踪行业扩散和成交承接，不作为确定性结论。",
            [sector.get("evidence_id")] + [value for item in group for value in (item.get("evidence_ids") or [])],
            [sector.get("entity_ref")] + [item.get("entity_ref") for item in group if item.get("entity_ref")],
            validation_refs=validation_refs,
        ))
    if not focus:
        focus.append(paragraph(
            "当前没有形成证据完整的个股观察组合，行业方向仅保留跟踪，不扩展为个股结论。",
            [market_id],
        ))

    performance_risk = []
    short_cycle = performance.get("short_cycle") or {}
    short_id = short_cycle.get("evidence_id")
    if short_id in evidence:
        average_return = short_cycle.get("average_return")
        return_text = "平均收益仍为负" if isinstance(average_return, (int, float)) and average_return < 0 else "平均收益保持为正"
        performance_risk.append(paragraph(
            f"近期短周期样本{return_text}，上行机会与回撤同时存在，说明市场活跃度尚未稳定转化为兑现能力。",
            [short_id],
        ))
    if risky:
        performance_risk.append(paragraph(
            "、".join(str(item.get("industry") or "") for item in risky[:4]) + "处于退潮阶段，与活跃方向形成分化，需警惕风险继续扩散。",
            [item.get("evidence_id") for item in risky[:4]],
            [item.get("entity_ref") for item in risky[:4] if item.get("entity_ref")],
        ))
    if not performance_risk:
        performance_risk.append(paragraph(
            "历史兑现证据不足以支持确定性外推，当前仍应把分歧和回撤作为主要风险。",
            [market_id],
        ))

    watch = []
    for sector, group in focus_groups[:3]:
        watch.append(paragraph(
            f"{sector.get('industry')}后续重点观察行业扩散与成交承接能否延续，并确认活跃标的之间是否形成一致性。",
            [sector.get("evidence_id")] + [value for item in group for value in (item.get("evidence_ids") or [])],
            [sector.get("entity_ref")] + [item.get("entity_ref") for item in group if item.get("entity_ref")],
            validation_refs=[
                str(entry.get("ref"))
                for item in group
                for entry in (item.get("validation") or [])[:1]
                if entry.get("ref")
            ],
        ))
    if not watch:
        watch.append(paragraph("后续重点验证行业扩散、成交承接与风险信号是否收敛。", [market_id]))

    return {
        "title": "结构分化延续主线承接仍待进一步验证",
        "generation_mode": "data_fallback",
        "sections": [
            {"key": "core_judgement", "heading": "核心判断", "paragraphs": core},
            {"key": "market_context", "heading": "市场背景", "paragraphs": context},
            {"key": "focus", "heading": "关注方向", "paragraphs": focus},
            {"key": "performance_risk", "heading": "表现与风险", "paragraphs": performance_risk},
            {"key": "watch_points", "heading": "观察要点", "paragraphs": watch},
        ],
        "keywords": [],
    }


def _resolve_config(ai_config: dict | None) -> dict:
    if ai_config is not None:
        return dict(ai_config)
    try:
        import config as project_config

        return dict(getattr(project_config, "AI_CONFIG", {}) or {})
    except Exception:
        return {}


def _daily_report_stage_config(config: dict, stage: str) -> dict:
    """证据归纳使用快速模型，最终成稿和修订固定使用推理模型。"""
    resolved = dict(config or {})
    if stage == "analyst":
        resolved["model"] = str(resolved.get("fast_model") or resolved.get("model") or "").strip()
        resolved["thinking"] = {"type": "disabled"}
    else:
        resolved["model"] = str(resolved.get("reasoning_model") or resolved.get("model") or "").strip()
        resolved["thinking"] = {"type": "enabled", "reasoning_effort": "high"}
        resolved["timeout"] = max(int(resolved.get("timeout") or 60), 180)
    return resolved


def _attach_ai_audit(document: dict, config: dict) -> dict:
    """记录日报真实使用的模型与生成层级，便于线上审计。"""
    result = dict(document)
    result["ai_model"] = str(config.get("model") or "")
    result["ai_thinking"] = "high"
    result["ai_pipeline"] = "two_pass_reasoning"
    return result


def _valid_config(config: dict) -> bool:
    key = str(config.get("api_key") or "").strip()
    endpoint = str(config.get("base_url") or "").strip()
    model = str(config.get("model") or "").strip()
    return bool(key and endpoint and model and "你的" not in key)


def _call_json(
    prompt: str,
    system: str,
    config: dict,
    post: Callable | None,
    max_tokens: int,
) -> dict | None:
    requester = post
    if requester is None:
        try:
            import requests

            requester = requests.post
        except Exception:
            return None
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    thinking = config.get("thinking")
    if isinstance(thinking, dict):
        payload["thinking"] = dict(thinking)
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    endpoint = _endpoint(str(config["base_url"]))
    timeout = int(config.get("timeout") or 60)
    for _ in range(2):
        try:
            response = requester(endpoint, headers=headers, json=payload, timeout=timeout)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = _parse_json_object(content)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return None


def _endpoint(base_url: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    return clean + "/chat/completions"


def _parse_json_object(content) -> dict | None:
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(text[start : end + 1])
        return value if isinstance(value, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
