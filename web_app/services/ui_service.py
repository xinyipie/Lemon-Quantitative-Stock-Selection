#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Web 页面共享的展示与分页辅助函数。"""

from __future__ import annotations

import math
from typing import Any


DISPLAY_LABELS = {
    "fallback": "规则解释",
    "fallback_preview": "规则摘要",
    "cache": "缓存解释",
    "ai": "AI 解释",
    "not_found": "未找到记录",
    "short_v9_final": "v9 底层评分",
    "profile_v9_sector_quality_guard": "v9 底层评分",
    "profile_v39_consensus_top1": "v39 强推荐层",
}


def paginate_items(items: list[dict] | None, page: int | str, page_size: int = 50) -> tuple[list[dict], dict]:
    """对已限定上限的页面数据分页，并把非法页码收敛到有效范围。"""
    values = list(items or [])
    safe_size = max(int(page_size or 1), 1)
    total = len(values)
    total_pages = max(1, (total + safe_size - 1) // safe_size)
    try:
        current = int(page)
    except (TypeError, ValueError):
        current = 1
    current = min(max(current, 1), total_pages)
    start = (current - 1) * safe_size
    selected = values[start : start + safe_size]
    return selected, {
        "page": current,
        "page_size": safe_size,
        "total": total,
        "total_pages": total_pages,
        "start_index": start + 1 if selected else 0,
        "end_index": start + len(selected),
    }


def normalize_date_input(value: str | None) -> str:
    """把网页日期输入统一为数据库使用的 YYYYMMDD。"""
    return str(value or "").strip().replace("-", "").replace("/", "")[:8]


def format_date_input(value: str | None) -> str:
    """把内部日期转换成 HTML date 控件需要的 YYYY-MM-DD。"""
    text = normalize_date_input(value)
    if len(text) != 8 or not text.isdigit():
        return ""
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def display_source_label(value: Any) -> str:
    """隐藏内部枚举名，返回用户可读标签。"""
    text = str(value or "").strip()
    return DISPLAY_LABELS.get(text, text or "-")


def format_optional(value: Any, decimals: int = 2, suffix: str = "") -> str:
    """区分缺失值与真实零值，避免页面把两者混为一谈。"""
    if value is None or value == "":
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "-"
    return f"{number:.{max(int(decimals), 0)}f}{suffix}"
