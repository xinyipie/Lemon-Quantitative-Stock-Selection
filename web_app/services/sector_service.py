#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""User-facing sector heat services for the Web dashboard."""

from __future__ import annotations

import json
from difflib import SequenceMatcher
import sqlite3
from pathlib import Path

from history_store import DEFAULT_HISTORY_DB_PATH
from sector_heat_diagnostics import (
    _latest_trade_date,
    calculate_sector_heat,
    load_history_frames,
    rank_sector_stocks,
)
from signal_store import DEFAULT_DB_PATH as DEFAULT_SIGNAL_DB_PATH


HEALTHY_STAGES = {"低位启动", "趋势延续", "弱修复"}
RISKY_STAGES = {"过热高潮", "退潮中"}
DEFAULT_CONCEPT_CACHE_DIR = Path("logs") / "cache"


def build_sector_radar(
    history_db: str | Path = DEFAULT_HISTORY_DB_PATH,
    end_date: str | None = None,
    top_sectors: int = 8,
    top_stocks: int = 3,
    min_stocks: int = 8,
) -> dict:
    """Build a concise market radar from industry heat data."""
    db_path = Path(history_db)
    if not db_path.exists():
        return _empty_radar(end_date=end_date, message="历史数据库不存在，无法生成行业热度。")
    try:
        actual_date = _latest_trade_date(db_path, end_date)
        frames = load_history_frames(db_path, actual_date, lookback_days=45)
        heat, stocks = calculate_sector_heat(
            frames["daily"],
            frames["stock_basic"],
            daily_basic=frames["daily_basic"],
            moneyflow=frames["moneyflow"],
            index_daily=frames["index_daily"],
            end_date=actual_date,
            min_stocks=min_stocks,
        )
    except Exception as exc:  # pragma: no cover - 页面兜底，细节由诊断脚本测试覆盖
        return _empty_radar(end_date=end_date, message=f"行业热度生成失败：{exc}")

    if heat.empty:
        return _empty_radar(end_date=actual_date, message="当前没有足够行业样本生成热度。")

    healthy = heat[heat["stage"].isin(HEALTHY_STAGES)].copy()
    risky = heat[heat["stage"].isin(RISKY_STAGES)].copy()
    candidate_sector_heat = healthy.head(top_sectors).copy()
    candidates = rank_sector_stocks(stocks, candidate_sector_heat, top_sectors=top_sectors, top_stocks=top_stocks)
    summary = _build_summary(heat, healthy, risky, actual_date)
    decorated_healthy = [_decorate_sector(item) for item in healthy.head(top_sectors).to_dict("records")]
    decorated_risky = [_decorate_sector(item) for item in risky.head(top_sectors).to_dict("records")]
    decorated_candidates = [_decorate_candidate(item) for item in candidates.to_dict("records")]
    summary["healthy_display_count"] = len(decorated_healthy)
    summary["risky_display_count"] = len(decorated_risky)
    return {
        "end_date": actual_date,
        "summary": summary,
        "healthy": decorated_healthy,
        "risky": decorated_risky,
        "candidates": decorated_candidates,
        "candidate_groups": _group_candidates_by_sector(decorated_candidates, decorated_healthy),
        "all_count": len(heat),
        "message": "",
    }


def build_concept_news_radar(
    signal_db: str | Path = DEFAULT_SIGNAL_DB_PATH,
    cache_dir: str | Path = DEFAULT_CONCEPT_CACHE_DIR,
    today: str | None = None,
    limit: int = 8,
) -> dict:
    """Build cached concept heat and news/concept impact summaries."""
    news_cache = _load_news_sector_cache(cache_dir=cache_dir, today=today, limit=limit)
    signal_news = _summarize_signal_news_impacts(signal_db=signal_db, limit=limit)
    news = news_cache if news_cache.get("positive") or news_cache.get("negative") else signal_news
    concepts = _load_concept_heat(cache_dir=cache_dir, today=today, limit=limit)
    if not concepts.get("items"):
        concepts = _concepts_from_news_impacts(news, limit=limit) or concepts
    return {
        "concepts": concepts,
        "news": news,
        "theme_filter": _load_theme_filter(cache_dir=cache_dir, today=today, limit=limit),
    }


def build_market_radar_decision(radar: dict, concept_news: dict) -> dict:
    """Turn raw sector/news context into one trader-facing market stance."""
    healthy = list(radar.get("healthy") or [])
    risky = list(radar.get("risky") or [])
    news = concept_news.get("news") or {}
    positive = list(news.get("positive") or [])
    negative = list(news.get("negative") or [])

    healthy_names = [str(item.get("industry") or "") for item in healthy if item.get("industry")]
    positive_names = [str(item.get("industry") or "") for item in positive if item.get("industry")]
    negative_names = [str(item.get("industry") or "") for item in negative if item.get("industry")]
    aligned = [name for name in healthy_names if name in set(positive_names)]

    if aligned:
        alignment = "主线共振"
        confidence = "高"
        tone = "ok"
        focus_industries = aligned[:3]
        primary_action = f"优先观察 {'、'.join(focus_industries)} 的策略信号，等待承接，不追高。"
        explanation = "趋势主线和消息面指向同一批行业，适合作为今日重点观察区。"
    elif healthy_names and positive_names:
        alignment = "主线分裂"
        confidence = "中"
        tone = "watch"
        focus_industries = healthy_names[:3]
        primary_action = f"先看趋势更扎实的 {'、'.join(focus_industries)}，消息面题材只作辅助验证。"
        explanation = "趋势热度和新闻热度不在同一方向，容易出现题材热闹但承接不足。"
    elif healthy_names:
        alignment = "趋势主线"
        confidence = "中"
        tone = "watch"
        focus_industries = healthy_names[:3]
        primary_action = f"重点观察 {'、'.join(focus_industries)}，但需要个股信号确认。"
        explanation = "行业趋势有扩散，但缺少明确消息面共振。"
    elif positive_names:
        alignment = "消息主线"
        confidence = "低"
        tone = "warn"
        focus_industries = positive_names[:3]
        primary_action = "只把消息热度当线索，暂不单独作为买入依据。"
        explanation = "新闻/概念有热度，但行业趋势没有同步确认。"
    else:
        alignment = "无清晰主线"
        confidence = "低"
        tone = "neutral"
        focus_industries = []
        primary_action = "没有清晰主线时，市场雷达的价值是提醒少做或不做。"
        explanation = "趋势和消息面都没有给出稳定方向。"

    avoid_industries = _unique(
        [str(item.get("industry") or "") for item in risky[:3] if item.get("industry")]
        + negative_names[:3]
    )
    if avoid_industries:
        avoid_text = f"回避或只复盘 {'、'.join(avoid_industries[:4])}。"
    else:
        avoid_text = "暂无明确风险板块，但仍需控制追高。"

    return {
        "alignment": alignment,
        "confidence": confidence,
        "tone": tone,
        "focus_industries": focus_industries,
        "avoid_industries": avoid_industries[:5],
        "primary_action": primary_action,
        "avoid_action": avoid_text,
        "explanation": explanation,
        "source_note": "以本地行业热度、入库信号新闻/概念因子和概念缓存综合判断；外部概念接口缺失时不参与决策。",
    }


def build_strategy_overlap(
    signal_db: str | Path,
    radar: dict,
    concept_news: dict,
    limit: int = 8,
) -> dict:
    """Find real strategy signals that overlap with healthy sectors or news-positive sectors."""
    path = Path(signal_db)
    if not path.exists():
        return {"items": [], "source_date": None, "message": "信号数据库不存在，暂无策略共振候选。"}

    healthy_by_industry = _industry_map(radar.get("healthy") or [])
    positive_by_industry = _industry_map((concept_news.get("news") or {}).get("positive") or [])
    qualified_industries = set(healthy_by_industry) | set(positive_by_industry)
    if not qualified_industries:
        return {"items": [], "source_date": None, "message": "当前没有健康主线或正向消息行业，暂不生成共振候选。"}

    radar_date = str(radar.get("end_date") or "").replace("-", "")[:8]
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if radar_date:
            source_row = conn.execute(
                """
                select max(p.trade_date) as trade_date
                from signal_pool p
                where p.trade_date <= ?
                  and p.score is not null
                """,
                (radar_date,),
            ).fetchone()
        else:
            source_row = conn.execute(
                "select max(trade_date) as trade_date from signal_pool where score is not null"
            ).fetchone()
        source_date = str(source_row["trade_date"] or "") if source_row else ""
        if not source_date:
            return {"items": [], "source_date": None, "message": "暂无可用于共振判断的策略信号。"}
        rows = conn.execute(
            """
            select p.trade_date, p.mode, p.profile, p.ts_code, p.name, p.industry,
                   p.rank, p.score, p.pool_type, p.reason, p.factor_json,
                   r.source, r.label
            from signal_pool p
            left join signal_runs r on r.run_id = p.run_id
            where p.trade_date = ?
              and p.score is not null
            order by p.score desc, p.rank asc, p.id desc
            limit 300
            """,
            (source_date,),
        ).fetchall()
    finally:
        conn.close()

    items = []
    seen_codes = set()
    for row in rows:
        item = dict(row)
        industry = str(item.get("industry") or "")
        if industry not in qualified_industries:
            continue
        code = str(item.get("ts_code") or "")
        if code in seen_codes:
            continue
        seen_codes.add(code)
        items.append(_decorate_strategy_overlap(item, healthy_by_industry, positive_by_industry))

    items.sort(key=lambda item: item["overlap_score"], reverse=True)
    return {
        "items": items[:limit],
        "source_date": source_date,
        "message": "" if items else "最近策略信号没有落在健康主线或正向消息行业里。",
    }


def _empty_radar(end_date: str | None = None, message: str = "") -> dict:
    return {
        "end_date": end_date,
        "summary": {
            "market_line": "无数据",
            "headline": "行业热度暂不可用",
            "stance": message or "请先更新历史数据库。",
            "tone": "warn",
            "healthy_count": 0,
            "healthy_display_count": 0,
            "risky_count": 0,
            "risky_display_count": 0,
            "top_sector": "-",
        },
        "healthy": [],
        "risky": [],
        "candidates": [],
        "candidate_groups": [],
        "all_count": 0,
        "message": message,
    }


def _load_concept_heat(cache_dir: str | Path, today: str | None = None, limit: int = 8) -> dict:
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return {
            "items": [],
            "source_date": None,
            "source_name": "",
            "source_kind": "empty",
            "message": "暂无概念热度缓存，运行 main.py 并开启概念热度后可生成。",
        }
    candidates = []
    if today:
        text = str(today).replace("-", "")[:8]
        candidates.append(cache_path / f"hot_concepts_{text}.json")
    candidates.extend(sorted(cache_path.glob("hot_concepts_*.json"), key=lambda path: path.name, reverse=True))
    seen = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = raw if isinstance(raw, list) else []
        decorated = [_decorate_concept(item) for item in items[:limit] if isinstance(item, dict)]
        if decorated:
            source_date = path.stem.replace("hot_concepts_", "")
            return {
                "items": decorated,
                "source_date": source_date,
                "source_name": path.name,
                "source_kind": "cache",
                "message": "",
            }
    return {
        "items": [],
        "source_date": None,
        "source_name": "",
        "source_kind": "empty",
        "message": "概念热度缓存为空，当前只展示行业热度和已入库信号。",
    }


def _concepts_from_news_impacts(news: dict, limit: int = 8) -> dict | None:
    groups = list(news.get("positive") or []) + list(news.get("negative") or [])
    if not groups:
        return None
    items = []
    for group in sorted(groups, key=lambda item: abs(float(item.get("impact_score") or 0)), reverse=True)[:limit]:
        impact = float(group.get("impact_score") or 0)
        heat = min(100.0, abs(impact) * 4)
        items.append(
            {
                "concept": f"消息面：{group.get('industry') or '-'}",
                "change": impact,
                "heat": heat,
                "change_text": f"影响 {impact:+.1f}",
                "heat_text": f"{heat:.1f}",
                "heat_width": int(max(0, min(100, heat))),
                "tone": "ok" if impact > 0 else "bad" if impact < 0 else "neutral",
            }
        )
    return {
        "items": items,
        "source_date": news.get("source_date"),
        "source_name": news.get("source_name") or "news_sector_proxy",
        "source_kind": "news_proxy",
        "message": "真实概念热度为空，当前用新闻板块影响生成代理热度。",
    }


def _load_theme_filter(cache_dir: str | Path, today: str | None = None, limit: int = 8) -> dict:
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return {"items": [], "source_date": None, "message": "暂无AI题材筛选缓存。"}
    candidates = []
    if today:
        text = str(today).replace("-", "")[:8]
        candidates.append(cache_path / f"theme_filter_{text}.json")
    candidates.extend(sorted(cache_path.glob("theme_filter_*.json"), key=lambda path: path.name, reverse=True))
    seen = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = payload.get("items") if isinstance(payload, dict) else []
        if isinstance(items, list) and items:
            return {
                "items": [_decorate_theme_filter(item) for item in items[:limit] if isinstance(item, dict)],
                "source_date": str(payload.get("date") or path.stem.replace("theme_filter_", "")),
                "source_name": path.name,
                "message": str(payload.get("message") or ""),
            }
    return {"items": [], "source_date": None, "message": "暂无AI题材筛选结果。"}


def _decorate_theme_filter(item: dict) -> dict:
    level = str(item.get("level") or "watch").lower()
    labels = {
        "strong": "强催化",
        "watch": "观察",
        "noise": "噪音",
        "risk": "过热风险",
    }
    tones = {
        "strong": "ok",
        "watch": "warn",
        "noise": "neutral",
        "risk": "bad",
    }
    return {
        "theme": str(item.get("theme") or "-"),
        "level": level,
        "level_text": labels.get(level, "观察"),
        "tone": tones.get(level, "warn"),
        "horizon": str(item.get("horizon") or "unknown"),
        "verdict": str(item.get("verdict") or labels.get(level, "观察")),
        "reason": str(item.get("reason") or ""),
    }


def _summarize_signal_news_impacts(signal_db: str | Path, limit: int = 8) -> dict:
    path = Path(signal_db)
    if not path.exists():
        return {
            "source_date": None,
            "positive": [],
            "negative": [],
            "items": [],
            "selection": _empty_news_selection(),
            "message": "信号数据库不存在，暂无新闻板块归因。",
        }
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select p.trade_date, p.ts_code, p.name, p.industry, p.score, p.factor_json
            from signal_pool p
            join signal_runs r on r.run_id = p.run_id
            where p.factor_json is not null
            order by p.trade_date desc, p.id desc
            limit 800
            """
        ).fetchall()
    finally:
        conn.close()

    enriched = []
    for row in rows:
        item = dict(row)
        factors = _json_dict(item.get("factor_json"))
        news_boost = _num(factors.get("news_boost")) or 0.0
        concept_boost = _num(factors.get("concept_boost")) or 0.0
        hot_concept_match = bool(factors.get("hot_concept_match"))
        if news_boost == 0 and concept_boost == 0 and not hot_concept_match:
            continue
        item["news_boost"] = news_boost
        item["concept_boost"] = concept_boost
        item["hot_concept_match"] = hot_concept_match
        item["impact_score"] = news_boost + concept_boost
        enriched.append(item)

    if not enriched:
        return {
            "source_date": None,
            "positive": [],
            "negative": [],
            "items": [],
            "selection": _empty_news_selection(),
            "message": "最近入库信号里暂无新闻/概念加分记录。",
        }
    source_date = max(str(item.get("trade_date") or "") for item in enriched)
    scoped = [item for item in enriched if str(item.get("trade_date") or "") == source_date]
    positive, negative = _group_news_impacts(scoped, limit=limit)
    selection = _build_signal_news_selection_summary(scoped, positive, negative)
    return {
        "source_date": source_date,
        "source_name": "signal_pool",
        "positive": positive,
        "negative": negative,
        "items": [],
        "selection": selection,
        "message": "" if positive or negative else "最近入库信号有概念标记，但行业影响较弱。",
    }


def _load_news_sector_cache(cache_dir: str | Path, today: str | None = None, limit: int = 8) -> dict:
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return {
            "source_date": None,
            "source_name": "",
            "positive": [],
            "negative": [],
            "items": [],
            "selection": _empty_news_selection(),
            "message": "暂无新闻板块缓存。",
        }
    candidates = []
    if today:
        text = str(today).replace("-", "")[:8]
        candidates.append(cache_path / f"news_sector_{text}.json")
    candidates.extend(sorted(cache_path.glob("news_sector_*.json"), key=lambda path: path.name, reverse=True))
    seen = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        positive, negative = _news_payload_to_groups(payload, limit=limit)
        if positive or negative:
            source_date = str(payload.get("date") or path.stem.replace("news_sector_", ""))
            items = _decorate_news_items(payload, limit=limit)
            selection = _build_news_selection_summary(payload, positive, negative, items)
            return {
                "source_date": source_date,
                "source_name": path.name,
                "positive": positive,
                "negative": negative,
                "items": items,
                "selection": selection,
                "message": "",
            }
    return {
        "source_date": None,
        "source_name": "",
        "positive": [],
        "negative": [],
        "items": [],
        "selection": _empty_news_selection(),
        "message": "新闻板块缓存为空。",
    }


def _news_payload_to_groups(payload: dict, limit: int = 8) -> tuple[list[dict], list[dict]]:
    boosts = payload.get("boosts") if isinstance(payload.get("boosts"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    groups: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        sectors = item.get("sectors") or []
        if isinstance(sectors, str):
            sectors = [sectors]
        impact = str(item.get("impact") or "neutral")
        strength = _num(item.get("strength")) or 0
        for sector in sectors:
            industry = str(sector or "").strip()
            if not industry:
                continue
            score = _num(boosts.get(industry))
            if score is None:
                score = strength * 3 if impact == "positive" else -strength * 2 if impact == "negative" else 0
            group = groups.setdefault(
                industry,
                {
                    "industry": industry,
                    "signal_count": 0,
                    "news_boost": 0.0,
                    "concept_boost": 0.0,
                    "impact_score": 0.0,
                    "top_stocks": [],
                    "reasons": [],
                },
            )
            group["signal_count"] += 1
            group["news_boost"] += float(score or 0)
            group["impact_score"] += float(score or 0)
            reason = str(item.get("reason") or item.get("news") or "")
            if reason and len(group["reasons"]) < 2:
                group["reasons"].append(reason)
    decorated = []
    for group in groups.values():
        group["impact_text"] = f"{group['impact_score']:+.1f}"
        group["news_boost_text"] = f"{group['news_boost']:+.1f}"
        group["concept_boost_text"] = f"{group['concept_boost']:+.1f}"
        group["tone"] = "ok" if group["impact_score"] > 0 else "bad" if group["impact_score"] < 0 else "neutral"
        group["top_stocks"] = []
        decorated.append(group)
    positive = [item for item in decorated if item["impact_score"] > 0]
    negative = [item for item in decorated if item["impact_score"] < 0]
    positive.sort(key=lambda item: item["impact_score"], reverse=True)
    negative.sort(key=lambda item: item["impact_score"])
    return positive[:limit], negative[:limit]


def _decorate_news_items(payload: dict, limit: int = 8) -> list[dict]:
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    boosts = payload.get("boosts") if isinstance(payload.get("boosts"), dict) else {}
    raw_news_index = _raw_news_index(payload)
    merged: dict[str, dict] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        sectors = item.get("sectors") or []
        if isinstance(sectors, str):
            sectors = [sectors]
        sectors = [str(sector).strip() for sector in sectors if str(sector).strip()]
        strength = int(_num(item.get("strength")) or 0)
        impact = str(item.get("impact") or "neutral")
        if strength < 1 or not sectors or impact not in {"positive", "negative"}:
            continue
        title = str(item.get("news") or item.get("title") or "").strip()[:80]
        if not title:
            continue
        quality = str(item.get("type") or "未分类")
        key = _normalize_news_title(title)
        current = merged.get(key)
        if current is None:
            current = {
                "title": title,
                "quality": quality,
                "impact": impact,
                "strength": strength,
                "duration": str(item.get("duration") or "未知"),
                "sectors": [],
                "reasons": [],
                "raw_sources": [],
                "source_count": 0,
            }
            merged[key] = current
        raw_source = _find_raw_news_source(title, raw_news_index)
        if raw_source and raw_source not in current["raw_sources"]:
            current["raw_sources"].append(raw_source)
        if strength > current["strength"]:
            current["strength"] = strength
            current["quality"] = quality
            current["duration"] = str(item.get("duration") or current["duration"] or "未知")
            current["impact"] = impact
        for sector in sectors:
            if sector not in current["sectors"]:
                current["sectors"].append(sector)
        reason = str(item.get("reason") or "").strip()
        if reason and reason not in current["reasons"]:
            current["reasons"].append(reason[:120])
        current["source_count"] += 1

    decorated = []
    for item in merged.values():
        sectors = item["sectors"]
        quality = item["quality"]
        impact = item["impact"]
        strength = item["strength"]
        grade = _news_grade(strength, quality, impact)
        boost_total = sum(float(boosts.get(sector) or 0) for sector in sectors)
        sectors_text = "、".join(sectors)
        reason = item["reasons"][0] if item["reasons"] else ""
        raw_source = _primary_raw_news(item["raw_sources"], item["title"])
        decorated.append(
            {
                "title": item["title"],
                "quality": quality,
                "impact": impact,
                "impact_text": "利好" if impact == "positive" else "利空",
                "tone": "ok" if impact == "positive" else "bad",
                "strength": strength,
                "strength_text": f"{strength}/10",
                "duration": item["duration"],
                "sectors": sectors,
                "sectors_text": sectors_text,
                "reason": reason,
                "grade": grade,
                "boost_total": boost_total,
                "boost_text": f"{boost_total:+.1f}",
                "impact_path": f"{quality} → {sectors_text}",
                "trading_hint": _news_trading_hint(impact),
                "verification_points": _news_verification_points(impact),
                "risk_note": _news_risk_note(impact),
                "why_selected": _news_selected_reason(quality, strength, sectors, item["source_count"]),
                "source_title": raw_source.get("title") or item["title"],
                "source": raw_source.get("source") or "",
                "source_url": raw_source.get("url") or "",
                "source_time": raw_source.get("publish_time") or "",
                "source_excerpt": raw_source.get("content_excerpt") or "",
                "source_providers_text": _source_providers_text(raw_source),
                "raw_source_count": int(raw_source.get("source_count") or len(item["raw_sources"]) or 1),
                "news_value_score": raw_source.get("news_value_score"),
                "news_value_score_text": _value_score_text(raw_source.get("news_value_score")),
                "value_reason_text": raw_source.get("value_reason_text") or "",
            }
        )
    decorated.sort(key=lambda item: (_news_grade_rank(item["grade"]), item["strength"], abs(item["boost_total"])), reverse=True)
    return decorated[:limit]


def _normalize_news_title(title: str) -> str:
    return "".join(str(title or "").split()).lower()


def _raw_news_index(payload: dict) -> dict[str, dict]:
    raw_news = payload.get("raw_news") if isinstance(payload.get("raw_news"), list) else []
    result: dict[str, dict] = {}
    for item in raw_news:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        key = _normalize_news_title(title)
        if not key or key in result:
            continue
        result[key] = item
    return result


def _find_raw_news_source(title: str, raw_news_index: dict[str, dict]) -> dict | None:
    key = _normalize_news_title(title)
    if key in raw_news_index:
        return raw_news_index[key]
    if len(key) < 6:
        return None
    for raw_key, raw_item in raw_news_index.items():
        if key in raw_key or raw_key in key:
            return raw_item
    best_item = None
    best_score = 0.0
    for raw_key, raw_item in raw_news_index.items():
        score = SequenceMatcher(None, key, raw_key).ratio()
        if score > best_score:
            best_score = score
            best_item = raw_item
    if best_score >= 0.38:
        return best_item
    return None


def _primary_raw_news(raw_sources: list[dict], fallback_title: str) -> dict:
    if raw_sources:
        return sorted(
            raw_sources,
            key=lambda item: (
                float(item.get("news_value_score") or 0),
                bool(item.get("url")),
                bool(item.get("content_excerpt")),
                str(item.get("publish_time") or ""),
            ),
            reverse=True,
        )[0]
    return {"title": fallback_title}


def _source_providers_text(raw_source: dict) -> str:
    providers = raw_source.get("sources") or raw_source.get("providers") or []
    if isinstance(providers, str):
        providers = [providers]
    text = " / ".join(str(item) for item in providers if item)
    return text or str(raw_source.get("source") or raw_source.get("provider") or "")


def _value_score_text(value) -> str:
    number = _num(value)
    return f"{number:.1f}" if number is not None else "-"


def _news_selected_reason(quality: str, strength: int, sectors: list[str], source_count: int = 1) -> str:
    extra = f"，合并{source_count}条同源消息" if source_count > 1 else ""
    return f"入选依据：消息类型明确为{quality}，强度{strength}/10，映射到{'、'.join(sectors)}{extra}。"


def _news_trading_hint(impact: str) -> str:
    if impact == "positive":
        return "交易含义：这是短期催化线索，不单独构成买入理由；优先等待板块承接和策略信号共振。"
    return "交易含义：这是风险提示线索，不单独构成卖出理由；重点观察行业是否继续退潮。"


def _news_verification_points(impact: str) -> list[str]:
    direction = "走强" if impact == "positive" else "转弱"
    return [
        f"板块热度、扩散和相对大盘是否同步{direction}",
        "相关个股是否进入短线或长线策略池",
        "成交量、资金流和盘中承接是否确认消息方向",
    ]


def _news_risk_note(impact: str) -> str:
    if impact == "positive":
        return "风险提示：持续性不足或消息已被提前反映时，容易冲高回落。"
    return "风险提示：利空若没有形成价格破位，可能只是短期扰动，需结合趋势确认。"


def _build_news_selection_summary(payload: dict, positive: list[dict], negative: list[dict], items: list[dict]) -> dict:
    titles = payload.get("titles") if isinstance(payload.get("titles"), list) else []
    ai_titles = payload.get("ai_titles") if isinstance(payload.get("ai_titles"), list) else titles
    raw_news = payload.get("raw_news") if isinstance(payload.get("raw_news"), list) else []
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    raw_title_count = int(payload.get("raw_news_total") or len(raw_news) or len(titles))
    ai_title_count = len(ai_titles)
    ai_item_count = len([item for item in raw_items if isinstance(item, dict)])
    displayed_sector_count = len(positive) + len(negative)
    filtered_count = max(0, ai_title_count - ai_item_count)
    if items:
        top_grade = items[0]["grade"]
        strongest = max(item["strength"] for item in items)
        quality_text = f"{top_grade}，最高强度 {strongest}/10"
    else:
        quality_text = "暂无有效消息"
    return {
        "raw_title_count": raw_title_count,
        "ai_item_count": ai_item_count,
        "displayed_sector_count": displayed_sector_count,
        "filtered_count": filtered_count,
        "quality_text": quality_text,
        "path_text": f"{raw_title_count}条候选新闻 → 价值排序取{ai_title_count}条给AI → AI保留{ai_item_count}条 → 映射{displayed_sector_count}个行业",
        "rule_text": "先按来源可信度、事件类型、行业映射、原文可追溯和时效性排序；AI只保留能映射行业、正负面明确、强度大于0的消息。",
    }


def _build_signal_news_selection_summary(scoped: list[dict], positive: list[dict], negative: list[dict]) -> dict:
    signal_count = len(scoped)
    displayed_sector_count = len(positive) + len(negative)
    strong_count = len([item for item in scoped if abs(float(item.get("impact_score") or 0)) >= 10])
    if signal_count:
        quality_text = f"信号归因，强影响 {strong_count}/{signal_count} 个"
    else:
        quality_text = "暂无有效消息"
    return {
        "raw_title_count": 0,
        "ai_item_count": signal_count,
        "displayed_sector_count": displayed_sector_count,
        "filtered_count": 0,
        "quality_text": quality_text,
        "path_text": f"无独立新闻缓存 → 读取最新信号{signal_count}条 → 汇总{displayed_sector_count}个行业",
        "rule_text": "这是降级口径：只解释已入库信号中的 news_boost / concept_boost，不代表全市场新闻扫描。",
    }


def _empty_news_selection() -> dict:
    return {
        "raw_title_count": 0,
        "ai_item_count": 0,
        "displayed_sector_count": 0,
        "filtered_count": 0,
        "quality_text": "暂无有效消息",
        "path_text": "暂无新闻筛选链路",
        "rule_text": "新闻缓存为空时，消息面不参与市场判断。",
    }


def _news_grade(strength: int, quality: str, impact: str) -> str:
    text = str(quality or "")
    if strength >= 8 and any(key in text for key in ["政策", "产业", "订单", "业绩"]):
        return "A级"
    if strength >= 6:
        return "B级"
    if strength >= 3:
        return "C级"
    return "D级"


def _news_grade_rank(grade: str) -> int:
    return {"A级": 4, "B级": 3, "C级": 2, "D级": 1}.get(str(grade), 0)


def _decorate_concept(item: dict) -> dict:
    concept = str(item.get("concept") or item.get("name") or "-")
    change = _num(item.get("change"))
    heat = _num(item.get("heat")) or 0.0
    return {
        "concept": concept,
        "change": change,
        "heat": heat,
        "change_text": _pct_text(change),
        "heat_text": f"{heat:.1f}",
        "heat_width": int(max(0, min(100, heat))),
        "tone": "ok" if (change or 0) > 0 else "bad" if (change or 0) < 0 else "neutral",
    }


def _group_news_impacts(rows: list[dict], limit: int = 8) -> tuple[list[dict], list[dict]]:
    groups: dict[str, dict] = {}
    for item in rows:
        industry = str(item.get("industry") or "未分类")
        group = groups.setdefault(
            industry,
            {
                "industry": industry,
                "signal_count": 0,
                "news_boost": 0.0,
                "concept_boost": 0.0,
                "impact_score": 0.0,
                "top_stocks": [],
                "reasons": [],
            },
        )
        group["signal_count"] += 1
        group["news_boost"] += float(item.get("news_boost") or 0)
        group["concept_boost"] += float(item.get("concept_boost") or 0)
        group["impact_score"] += float(item.get("impact_score") or 0)
        group["top_stocks"].append(_decorate_impact_stock(item))
        if len(group["reasons"]) < 2:
            group["reasons"].append(f"{item.get('name') or item.get('ts_code')} 消息/概念因子 {float(item.get('impact_score') or 0):+.1f}")

    decorated = []
    for group in groups.values():
        group["top_stocks"] = sorted(
            group["top_stocks"],
            key=lambda stock: (abs(float(stock["impact_score"])), float(stock["score"] or 0)),
            reverse=True,
        )[:3]
        group["impact_text"] = f"{group['impact_score']:+.1f}"
        group["news_boost_text"] = f"{group['news_boost']:+.1f}"
        group["concept_boost_text"] = f"{group['concept_boost']:+.1f}"
        group["tone"] = "ok" if group["impact_score"] > 0 else "bad" if group["impact_score"] < 0 else "neutral"
        decorated.append(group)
    positive = [item for item in decorated if item["impact_score"] > 0]
    negative = [item for item in decorated if item["impact_score"] < 0]
    positive.sort(key=lambda item: item["impact_score"], reverse=True)
    negative.sort(key=lambda item: item["impact_score"])
    return positive[:limit], negative[:limit]


def _decorate_impact_stock(item: dict) -> dict:
    score = _num(item.get("score"))
    impact_score = float(item.get("impact_score") or 0)
    return {
        "ts_code": item.get("ts_code"),
        "name": item.get("name") or item.get("ts_code"),
        "score": score,
        "score_text": f"{score:.1f}" if score is not None else "-",
        "impact_score": impact_score,
        "impact_text": f"{impact_score:+.1f}",
        "hot_concept_match": bool(item.get("hot_concept_match")),
    }


def _decorate_strategy_overlap(item: dict, healthy_by_industry: dict[str, dict], positive_by_industry: dict[str, dict]) -> dict:
    industry = str(item.get("industry") or "")
    signal_score = _num(item.get("score")) or 0.0
    healthy = healthy_by_industry.get(industry)
    positive = positive_by_industry.get(industry)
    heat_score = _num((healthy or {}).get("heat_score")) or 0.0
    news_score = _num((positive or {}).get("impact_score")) or 0.0
    overlap_score = signal_score + heat_score * 0.2 + max(news_score, 0.0) * 0.5
    if healthy and positive:
        overlap_score += 5.0

    parts = ["策略信号"]
    if healthy:
        parts.append(f"{healthy.get('stage') or '健康主线'}，热度 {float(heat_score):.1f}")
    if positive:
        parts.append(f"消息面 {float(news_score):+.1f}")
    reason = " / ".join(parts)
    mode = str(item.get("mode") or "")
    mode_text = "短线" if mode == "short" else "长线" if mode == "longterm" else mode or "-"
    return {
        "trade_date": item.get("trade_date"),
        "mode": mode,
        "mode_text": mode_text,
        "profile": item.get("profile") or "",
        "source": item.get("source") or "",
        "label": item.get("label") or "",
        "ts_code": item.get("ts_code"),
        "name": item.get("name") or item.get("ts_code"),
        "industry": industry,
        "rank": item.get("rank"),
        "score": signal_score,
        "score_text": f"{signal_score:.1f}",
        "heat_score": heat_score,
        "heat_score_text": f"{heat_score:.1f}" if healthy else "-",
        "news_score": news_score,
        "news_score_text": f"{news_score:+.1f}" if positive else "-",
        "overlap_score": overlap_score,
        "overlap_score_text": f"{overlap_score:.1f}",
        "reason": reason,
        "action": _overlap_action(signal_score, heat_score, news_score, bool(healthy), bool(positive)),
    }


def _overlap_action(signal_score: float, heat_score: float, news_score: float, has_healthy: bool, has_news: bool) -> str:
    if has_healthy and has_news and signal_score >= 55:
        return "重点体检"
    if has_healthy and signal_score >= 50:
        return "跟踪承接"
    if has_news and not has_healthy:
        return "只看催化"
    if heat_score >= 70 or news_score >= 18:
        return "观察确认"
    return "轻量观察"


def _build_summary(heat, healthy, risky, end_date: str) -> dict:
    healthy_count = len(healthy)
    risky_count = len(risky)
    top_sector = healthy.iloc[0] if healthy_count else heat.iloc[0]
    strong_healthy_count = int((healthy["heat_score"] >= 65).sum()) if healthy_count else 0
    if healthy_count >= 3 or strong_healthy_count >= 1:
        market_line = "有主线"
        stance = "先看健康主线里的承接，不追过热板块。"
        tone = "ok"
    elif healthy_count >= 1:
        market_line = "弱主线"
        stance = "有局部机会，但更适合小范围观察和单股体检。"
        tone = "watch"
    else:
        market_line = "无主线"
        stance = "行业扩散不足，系统价值是提醒别硬追。"
        tone = "neutral"
    return {
        "market_line": market_line,
        "headline": f"{end_date} 行业热度：{market_line}",
        "stance": stance,
        "tone": tone,
        "healthy_count": healthy_count,
        "healthy_display_count": healthy_count,
        "risky_count": risky_count,
        "risky_display_count": risky_count,
        "top_sector": str(top_sector.get("industry") or "-"),
        "top_stage": str(top_sector.get("stage") or "-"),
        "top_score": float(top_sector.get("heat_score") or 0),
    }


def _industry_map(items: list[dict]) -> dict[str, dict]:
    result = {}
    for item in items:
        industry = str(item.get("industry") or "").strip()
        if industry and industry not in result:
            result[industry] = item
    return result


def _unique(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _decorate_sector(item: dict) -> dict:
    item = dict(item)
    item["heat_score_text"] = f"{float(item.get('heat_score') or 0):.1f}"
    item["avg_ret_5d_text"] = _pct_text(item.get("avg_ret_5d"))
    item["rel_ret_10d_text"] = _pct_text(item.get("rel_ret_10d"))
    item["above_ma20_text"] = _ratio_text(item.get("above_ma20_ratio"))
    item["volume_expansion_text"] = _ratio_text(item.get("volume_expansion_ratio"))
    item["action"] = _sector_action(item)
    item["tone"] = _stage_tone(item.get("stage"))
    item["heat_width"] = int(max(0, min(100, float(item.get("heat_score") or 0))))
    item["anchor_id"] = _sector_anchor(item.get("industry"))
    return item


def _decorate_candidate(item: dict) -> dict:
    item = dict(item)
    item["candidate_score_text"] = f"{float(item.get('candidate_score') or 0):.1f}"
    item["ret_5d_text"] = _pct_text(item.get("ret_5d"))
    item["ret_10d_text"] = _pct_text(item.get("ret_10d"))
    item["stock_vs_sector_10d_text"] = _pct_text(item.get("stock_vs_sector_10d"))
    item["action_tag"] = _candidate_action(item)
    item["tone"] = _candidate_tone(item["action_tag"])
    item["anchor_id"] = _sector_anchor(item.get("industry"))
    return item


def _group_candidates_by_sector(candidates: list[dict], sectors: list[dict]) -> list[dict]:
    sector_map = {str(item.get("industry") or ""): item for item in sectors}
    by_industry: dict[str, list[dict]] = {}
    for item in candidates:
        by_industry.setdefault(str(item.get("industry") or ""), []).append(item)

    groups = []
    for industry, rows in by_industry.items():
        sector = sector_map.get(
            industry,
            {"industry": industry, "stage": "-", "action": "-", "heat_score": 0, "heat_score_text": "-", "summary": ""},
        )
        groups.append(
            {
                "industry": industry,
                "anchor_id": _sector_anchor(industry),
                "sector": sector,
                "candidates": sorted(rows, key=lambda row: int(row.get("candidate_rank") or 999)),
            }
        )
    return sorted(groups, key=lambda group: float(group["sector"].get("heat_score") or 0), reverse=True)


def _sector_action(item) -> str:
    if isinstance(item, dict):
        stage = str(item.get("stage") or "")
        avg_ret_5d = _num(item.get("avg_ret_5d")) or 0
        rel_ret_10d = _num(item.get("rel_ret_10d")) or 0
        above_ma20 = _num(item.get("above_ma20_ratio")) or 0
    else:
        stage = str(item or "")
        avg_ret_5d = rel_ret_10d = above_ma20 = 0
    if stage == "过热高潮":
        return "停止追涨"
    if stage == "退潮中":
        if avg_ret_5d <= -4 or rel_ret_10d <= -5 or above_ma20 <= 0.25:
            return "暂不参与"
        if avg_ret_5d > -3 and rel_ret_10d > -3 and above_ma20 >= 0.4:
            return "等待企稳"
        return "只复盘"
    return {
        "低位启动": "低吸观察",
        "趋势延续": "看承接",
        "弱修复": "谨慎观察",
    }.get(stage, "只观察")


def _sector_anchor(industry) -> str:
    text = str(industry or "unknown").strip() or "unknown"
    for char in " #./\\?&=%":
        text = text.replace(char, "-")
    return f"sector-{text}"


def _stage_tone(stage) -> str:
    return {
        "低位启动": "ok",
        "趋势延续": "ok",
        "弱修复": "watch",
        "过热高潮": "warn",
        "退潮中": "bad",
    }.get(str(stage or ""), "neutral")


def _candidate_action(item: dict) -> str:
    note = str(item.get("risk_note") or "")
    if "不追高" in note:
        return "等分歧"
    if "退潮" in note:
        return "仅复盘"
    score = float(item.get("candidate_score") or 0)
    if score >= 70:
        return "可跟踪"
    return "继续观察"


def _candidate_tone(action: str) -> str:
    return {
        "可跟踪": "ok",
        "继续观察": "watch",
        "等分歧": "warn",
        "仅复盘": "bad",
    }.get(action, "neutral")


def _pct_text(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:+.2f}%"


def _ratio_text(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number * 100:.0f}%"


def _json_dict(raw) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _num(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
