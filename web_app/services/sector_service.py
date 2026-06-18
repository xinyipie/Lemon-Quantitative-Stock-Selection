#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""User-facing sector heat services for the Web dashboard."""

from __future__ import annotations

import json
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
    return {
        "concepts": _load_concept_heat(cache_dir=cache_dir, today=today, limit=limit),
        "news": news_cache if news_cache.get("positive") or news_cache.get("negative") else signal_news,
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
            "risky_count": 0,
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
                "message": "",
            }
    return {
        "items": [],
        "source_date": None,
        "source_name": "",
        "message": "概念热度缓存为空，当前只展示行业热度和已入库信号。",
    }


def _summarize_signal_news_impacts(signal_db: str | Path, limit: int = 8) -> dict:
    path = Path(signal_db)
    if not path.exists():
        return {"source_date": None, "positive": [], "negative": [], "message": "信号数据库不存在，暂无新闻板块归因。"}
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
            "message": "最近入库信号里暂无新闻/概念加分记录。",
        }
    source_date = max(str(item.get("trade_date") or "") for item in enriched)
    scoped = [item for item in enriched if str(item.get("trade_date") or "") == source_date]
    positive, negative = _group_news_impacts(scoped, limit=limit)
    return {
        "source_date": source_date,
        "source_name": "signal_pool",
        "positive": positive,
        "negative": negative,
        "message": "" if positive or negative else "最近入库信号有概念标记，但行业影响较弱。",
    }


def _load_news_sector_cache(cache_dir: str | Path, today: str | None = None, limit: int = 8) -> dict:
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return {"source_date": None, "source_name": "", "positive": [], "negative": [], "message": "暂无新闻板块缓存。"}
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
            return {
                "source_date": source_date,
                "source_name": path.name,
                "positive": positive,
                "negative": negative,
                "message": "",
            }
    return {"source_date": None, "source_name": "", "positive": [], "negative": [], "message": "新闻板块缓存为空。"}


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
            },
        )
        group["signal_count"] += 1
        group["news_boost"] += float(item.get("news_boost") or 0)
        group["concept_boost"] += float(item.get("concept_boost") or 0)
        group["impact_score"] += float(item.get("impact_score") or 0)
        group["top_stocks"].append(_decorate_impact_stock(item))

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
        "risky_count": risky_count,
        "top_sector": str(top_sector.get("industry") or "-"),
        "top_stage": str(top_sector.get("stage") or "-"),
        "top_score": float(top_sector.get("heat_score") or 0),
    }


def _decorate_sector(item: dict) -> dict:
    item = dict(item)
    item["heat_score_text"] = f"{float(item.get('heat_score') or 0):.1f}"
    item["avg_ret_5d_text"] = _pct_text(item.get("avg_ret_5d"))
    item["rel_ret_10d_text"] = _pct_text(item.get("rel_ret_10d"))
    item["above_ma20_text"] = _ratio_text(item.get("above_ma20_ratio"))
    item["volume_expansion_text"] = _ratio_text(item.get("volume_expansion_ratio"))
    item["action"] = _sector_action(item.get("stage"))
    item["tone"] = _stage_tone(item.get("stage"))
    item["heat_width"] = int(max(0, min(100, float(item.get("heat_score") or 0))))
    return item


def _decorate_candidate(item: dict) -> dict:
    item = dict(item)
    item["candidate_score_text"] = f"{float(item.get('candidate_score') or 0):.1f}"
    item["ret_5d_text"] = _pct_text(item.get("ret_5d"))
    item["ret_10d_text"] = _pct_text(item.get("ret_10d"))
    item["stock_vs_sector_10d_text"] = _pct_text(item.get("stock_vs_sector_10d"))
    item["action_tag"] = _candidate_action(item)
    item["tone"] = _candidate_tone(item["action_tag"])
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
                "sector": sector,
                "candidates": sorted(rows, key=lambda row: int(row.get("candidate_rank") or 999)),
            }
        )
    return sorted(groups, key=lambda group: float(group["sector"].get("heat_score") or 0), reverse=True)


def _sector_action(stage) -> str:
    return {
        "低位启动": "低吸观察",
        "趋势延续": "看承接",
        "弱修复": "谨慎观察",
        "过热高潮": "不追高",
        "退潮中": "回避",
    }.get(str(stage or ""), "只观察")


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
