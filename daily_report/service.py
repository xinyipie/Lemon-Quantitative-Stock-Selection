"""编排每日研究报告的事实、撰稿、质检与发布。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from daily_report.facts import build_daily_report_facts
from daily_report.publication import (
    build_public_facts,
    extract_search_keywords,
    report_to_plain_text,
    validate_report,
)
from daily_report.store import begin_generation, finish_generation, publish_report
from daily_report.writer import (
    build_deterministic_report_document,
    generate_report_document,
    revise_report_document,
)


class ReportGenerationError(RuntimeError):
    """表示本次生成不满足发布条件。"""


def generate_daily_report(
    report_date: str,
    market_date: str,
    signal_db: str | Path,
    history_db: str | Path,
    slot: str = "manual",
    retry_if_missing: bool = False,
    force: bool = False,
    facts_builder=build_daily_report_facts,
    writer=generate_report_document,
    reviser=revise_report_document,
    fallback_builder=build_deterministic_report_document,
) -> dict:
    """优先发布可解析的 AI 稿件；仅在 AI 无法成稿时使用确定性降级稿。"""
    if not begin_generation(signal_db, report_date, slot, retry_if_missing, force):
        return {
            "status": "skipped",
            "report_date": report_date,
            "reason": "already_published_or_running",
        }
    try:
        facts = facts_builder(report_date, market_date, signal_db, history_db)
        if not facts.get("completeness", {}).get("can_publish"):
            raise ReportGenerationError("critical facts incomplete")
        if not facts.get("input_hash"):
            facts["input_hash"] = hashlib.sha256(
                json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
        public_facts = build_public_facts(facts)
        document = writer(public_facts)
        ai_document_ready = (
            isinstance(document, dict)
            and bool(str(document.get("title") or "").strip())
            and isinstance(document.get("sections"), list)
        )
        if ai_document_ready:
            document.setdefault("generation_mode", "pro_reasoning")
        else:
            document = fallback_builder(public_facts) if fallback_builder else None
            fallback_ready = (
                isinstance(document, dict)
                and bool(str(document.get("title") or "").strip())
                and isinstance(document.get("sections"), list)
            )
            if not fallback_ready:
                raise ReportGenerationError(
                    "AI returned no renderable document and deterministic fallback also failed"
                )
        body_text = report_to_plain_text(document)
        keywords = extract_search_keywords(document, public_facts)
        version_id = publish_report(
            signal_db,
            report_date=report_date,
            market_date=market_date,
            title=document["title"],
            document=document,
            body_text=body_text,
            keywords=keywords,
            input_hash=facts["input_hash"],
            data_cutoff=facts["cutoffs"]["data"],
            news_cutoff=facts["cutoffs"]["news"],
        )
        finish_generation(signal_db, report_date, "published", "")
        return {
            "status": "published",
            "report_date": report_date,
            "version_id": version_id,
        }
    except Exception as exc:
        finish_generation(signal_db, report_date, "failed", str(exc)[:500])
        return {
            "status": "failed",
            "report_date": report_date,
            "reason": str(exc)[:200],
        }
