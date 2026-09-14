"""编排每日研究报告的事实、撰稿、质检与发布。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from daily_report.facts import build_daily_report_facts
from daily_report.publication import (
    build_public_facts,
    build_evidence_snapshot,
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
    freshness_checker=None,
    cache_dir: str | Path | None = None,
) -> dict:
    """校验初稿、一次修订与降级稿，仅发布符合事实边界的文章。"""
    if not begin_generation(signal_db, report_date, slot, retry_if_missing, force):
        return {
            "status": "skipped",
            "report_date": report_date,
            "reason": "already_published_or_running",
        }
    try:
        from market_data_clock import require_report_freshness

        if freshness_checker:
            freshness_result = freshness_checker(report_date, market_date, history_db)
        else:
            freshness_result = require_report_freshness(report_date, market_date, history_db, cache_dir=cache_dir)
        facts = facts_builder(report_date, market_date, signal_db, history_db)
        if not facts.get("completeness", {}).get("can_publish"):
            raise ReportGenerationError("critical facts incomplete")
        if not facts.get("input_hash"):
            facts["input_hash"] = hashlib.sha256(
                json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
        public_facts = build_public_facts(facts)
        try:
            document = writer(public_facts)
        except Exception:
            document = None
        errors = validate_report(document, facts, public_facts)
        if errors:
            try:
                document = reviser(public_facts, document, errors) if reviser else None
            except Exception:
                document = None
            errors = validate_report(document, facts, public_facts)
        if errors:
            document = fallback_builder(public_facts) if fallback_builder else None
            errors = validate_report(document, facts, public_facts)
        if errors:
            raise ReportGenerationError("report validation failed: " + "; ".join(errors))
        document.setdefault("generation_mode", "pro_reasoning")
        document["evidence_snapshot"] = build_evidence_snapshot(document, public_facts)
        if isinstance(freshness_result, dict):
            document['data_freshness'] = freshness_result
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
