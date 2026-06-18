#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate local market-context caches for the Web sector radar."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

import config
from concept_heat_provider import fetch_real_concept_heat
from news_source_provider import fetch_market_news
import news_analyzer


DEFAULT_CACHE_DIR = Path("logs") / "cache"


def write_market_context_snapshot(
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    snapshot_date: str | None = None,
    call_ai_api_fn: Callable | None = None,
) -> dict:
    date_text = normalize_date(snapshot_date or datetime.now().strftime("%Y%m%d"))
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    concept_top_n = config.NEWS_ANALYSIS_CONFIG.get("concept_top_n", 10)
    concept_cache_file = cache_path / f"hot_concepts_{date_text}.json"
    hot_concepts = _read_json(concept_cache_file)
    if not isinstance(hot_concepts, list) or not hot_concepts:
        hot_concepts = fetch_real_concept_heat(top_n=concept_top_n)
    if not hot_concepts:
        old_enable_concepts = config.NEWS_ANALYSIS_CONFIG.get("enable_hot_concepts", False)
        try:
            config.NEWS_ANALYSIS_CONFIG["enable_hot_concepts"] = True
            hot_concepts = news_analyzer.get_hot_concepts(top_n=concept_top_n)
        finally:
            config.NEWS_ANALYSIS_CONFIG["enable_hot_concepts"] = old_enable_concepts
    _write_json(concept_cache_file, hot_concepts)

    raw_news = fetch_market_news(days=3, limit=100)
    news_df = _raw_news_to_frame(raw_news)
    if not raw_news:
        news_df = news_analyzer.get_policy_news(days=3, prefer_rich=False)
        raw_news = _legacy_news_records(news_df)
    titles = [str(item.get("title") or "") for item in raw_news if item.get("title")]
    ai_titles = titles[:30]
    ai_parser = call_ai_api_fn or call_ai_api
    ai_news = news_analyzer.ai_parse_news_to_sectors(ai_titles, ai_parser, max_titles=30) if ai_titles else []
    sector_boosts = news_analyzer.build_sector_boosts(ai_news)
    sentiment = news_analyzer.analyze_news_sentiment(news_df, ai_news) if news_df is not None else {}
    news_payload = {
        "date": date_text,
        "titles": titles,
        "ai_titles": ai_titles,
        "raw_news_total": len(raw_news or []),
        "raw_news": raw_news,
        "items": ai_news,
        "boosts": sector_boosts,
        "sentiment": sentiment,
    }
    _write_json(cache_path / f"news_sector_{date_text}.json", news_payload)
    theme_filter = _get_or_create_theme_filter(
        cache_path=cache_path,
        date_text=date_text,
        hot_concepts=hot_concepts or [],
        ai_news=ai_news or [],
        call_ai_api_fn=ai_parser,
    )
    return {
        "date": date_text,
        "concept_count": len(hot_concepts or []),
        "news_item_count": len(ai_news or []),
        "news_sector_count": len(sector_boosts or {}),
        "theme_count": len(theme_filter.get("items") or []),
    }


def call_ai_api(prompt: str, system: str = "") -> str | None:
    if not prompt:
        return None
    api_key = config.AI_CONFIG.get("api_key")
    if not api_key:
        return None
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": config.AI_CONFIG["model"],
        "messages": messages,
        "temperature": config.AI_CONFIG["temperature"],
        "max_tokens": config.AI_CONFIG["max_tokens"],
    }
    try:
        response = requests.post(
            url=config.AI_CONFIG["base_url"],
            headers={"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=config.AI_CONFIG["timeout"],
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def normalize_date(value: str) -> str:
    text = str(value or "").replace("-", "")[:8]
    return text if len(text) == 8 and text.isdigit() else datetime.now().strftime("%Y%m%d")


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _raw_news_to_frame(raw_news: list[dict]):
    try:
        import pandas as pd
    except Exception:  # pragma: no cover - pandas 是项目基础依赖，这里只是兜底
        return None
    rows = []
    for item in raw_news or []:
        rows.append(
            {
                "title": item.get("title") or "",
                "date": item.get("publish_time") or "",
                "source": item.get("source") or item.get("provider") or "",
                "content": item.get("content_excerpt") or item.get("title") or "",
            }
        )
    return pd.DataFrame(rows)


def _legacy_news_records(news_df) -> list[dict]:
    if news_df is None or getattr(news_df, "empty", True):
        return []
    records = []
    for _, row in news_df.head(30).iterrows():
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        records.append(
            {
                "title": title,
                "source": str(row.get("source") or row.get("来源") or "东方财富").strip(),
                "provider": "legacy_policy_news",
                "providers": ["legacy_policy_news"],
                "sources": [str(row.get("source") or row.get("来源") or "东方财富").strip()],
                "source_count": 1,
                "publish_time": str(row.get("date") or row.get("time") or row.get("发布时间") or "").strip(),
                "url": str(row.get("url") or row.get("链接") or "").strip(),
                "content_excerpt": str(row.get("content") or row.get("内容") or title).strip()[:180],
            }
        )
    return records


def _get_or_create_theme_filter(
    cache_path: Path,
    date_text: str,
    hot_concepts: list[dict],
    ai_news: list[dict],
    call_ai_api_fn: Callable,
) -> dict:
    target = cache_path / f"theme_filter_{date_text}.json"
    cached = _read_json(target)
    if isinstance(cached, dict) and isinstance(cached.get("items"), list):
        return cached

    candidates = _theme_candidates(hot_concepts, ai_news)
    if not candidates:
        payload = {"date": date_text, "items": [], "message": "暂无可供AI筛选的概念或新闻题材。"}
        _write_json(target, payload)
        return payload

    prompt = _build_theme_filter_prompt(candidates)
    raw = call_ai_api_fn(prompt=prompt, system="你是A股题材研究员，只做题材归因和风险分级，不给交易指令。")
    items = _parse_theme_filter(raw)
    payload = {
        "date": date_text,
        "items": items,
        "message": "" if items else "AI未返回有效题材分级，保留原始概念热度供人工观察。",
    }
    _write_json(target, payload)
    return payload


def _theme_candidates(hot_concepts: list[dict], ai_news: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for item in hot_concepts[:8]:
        if not isinstance(item, dict):
            continue
        candidates.append(
            {
                "theme": item.get("concept") or item.get("name") or "",
                "change": item.get("change"),
                "heat": item.get("heat"),
                "reason": item.get("reason") or "",
                "source": item.get("source") or "concept",
            }
        )
    for item in ai_news[:8]:
        if not isinstance(item, dict):
            continue
        sectors = item.get("sectors") or []
        if isinstance(sectors, str):
            sectors = [sectors]
        for sector in sectors[:3]:
            candidates.append(
                {
                    "theme": sector,
                    "change": None,
                    "heat": item.get("strength"),
                    "reason": item.get("reason") or item.get("news") or "",
                    "source": "news",
                }
            )
    seen = set()
    unique = []
    for item in candidates:
        theme = str(item.get("theme") or "").strip()
        if not theme or theme in seen:
            continue
        seen.add(theme)
        item["theme"] = theme
        unique.append(item)
    return unique[:12]


def _build_theme_filter_prompt(candidates: list[dict]) -> str:
    lines = []
    for idx, item in enumerate(candidates, start=1):
        lines.append(
            f"{idx}. 题材={item.get('theme')} 来源={item.get('source')} "
            f"涨幅={item.get('change')} 热度={item.get('heat')} 原因={item.get('reason')}"
        )
    return (
        "请从下面A股题材/新闻候选中筛掉噪音，只输出JSON数组。"
        "每项字段必须为 theme、level、horizon、verdict、reason。"
        "level只能取 strong/watch/noise/risk；horizon只能取 intraday/short/swing/unknown。"
        "verdict用10字以内中文，例如强催化、观察、噪音、过热风险。不要输出交易指令。\n"
        + "\n".join(lines)
    )


def _parse_theme_filter(raw: str | None) -> list[dict]:
    if not raw:
        return []
    match = re.search(r"\[[\s\S]*\]", str(raw))
    if not match:
        return []
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    valid = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        theme = str(item.get("theme") or item.get("concept") or "").strip()
        if not theme:
            continue
        level = str(item.get("level") or "watch").strip().lower()
        if level not in {"strong", "watch", "noise", "risk"}:
            level = "watch"
        horizon = str(item.get("horizon") or "unknown").strip().lower()
        if horizon not in {"intraday", "short", "swing", "unknown"}:
            horizon = "unknown"
        valid.append(
            {
                "theme": theme,
                "level": level,
                "horizon": horizon,
                "verdict": str(item.get("verdict") or "").strip()[:20],
                "reason": str(item.get("reason") or "").strip()[:120],
            }
        )
    return valid[:8]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成市场雷达的概念热度和新闻板块缓存")
    parser.add_argument("--date", default=None, help="快照日期 YYYYMMDD，默认今天")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = write_market_context_snapshot(cache_dir=args.cache_dir, snapshot_date=args.date)
    print(
        "市场上下文快照完成："
        f"date={result['date']} concepts={result['concept_count']} "
        f"news_items={result['news_item_count']} news_sectors={result['news_sector_count']}"
    )


if __name__ == "__main__":
    main()
