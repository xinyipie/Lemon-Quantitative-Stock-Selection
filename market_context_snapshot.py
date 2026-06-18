#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate local market-context caches for the Web sector radar."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

import config
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

    old_enable_concepts = config.NEWS_ANALYSIS_CONFIG.get("enable_hot_concepts", False)
    try:
        config.NEWS_ANALYSIS_CONFIG["enable_hot_concepts"] = True
        hot_concepts = news_analyzer.get_hot_concepts(top_n=config.NEWS_ANALYSIS_CONFIG.get("concept_top_n", 10))
    finally:
        config.NEWS_ANALYSIS_CONFIG["enable_hot_concepts"] = old_enable_concepts
    _write_json(cache_path / f"hot_concepts_{date_text}.json", hot_concepts)

    news_df = news_analyzer.get_policy_news(days=3)
    titles = []
    if news_df is not None and not news_df.empty and "title" in news_df.columns:
        titles = [str(item) for item in news_df["title"].dropna().head(15).tolist()]
    ai_parser = call_ai_api_fn or call_ai_api
    ai_news = news_analyzer.ai_parse_news_to_sectors(titles, ai_parser) if titles else []
    sector_boosts = news_analyzer.build_sector_boosts(ai_news)
    sentiment = news_analyzer.analyze_news_sentiment(news_df, ai_news) if news_df is not None else {}
    news_payload = {
        "date": date_text,
        "titles": titles,
        "items": ai_news,
        "boosts": sector_boosts,
        "sentiment": sentiment,
    }
    _write_json(cache_path / f"news_sector_{date_text}.json", news_payload)
    return {
        "date": date_text,
        "concept_count": len(hot_concepts or []),
        "news_item_count": len(ai_news or []),
        "news_sector_count": len(sector_boosts or {}),
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
