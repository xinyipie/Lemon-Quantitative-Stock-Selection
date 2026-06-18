#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""概念热度真实数据源适配层。

优先使用东方财富概念实时热度；如果当前网络或代理无法访问东方财富，
自动降级到同花顺近期概念事件 + 概念行情信息。调用方再决定是否继续
降级到新闻代理热度。
"""

from __future__ import annotations

import contextlib
import io
from typing import Any
import warnings

import pandas as pd


def fetch_real_concept_heat(top_n: int = 10, ths_probe_size: int = 16, ak_module: Any | None = None) -> list[dict]:
    """获取真实概念热度列表。

    返回字段统一为：concept/change/heat/source/reason。函数内部吞掉接口异常，
    保证一键更新不会因为某个外部接口不可用而中断。
    """
    try:
        ak = ak_module or _import_akshare()
    except Exception:
        return []

    items = _fetch_eastmoney_concepts(ak=ak, top_n=top_n)
    if items:
        return items[:top_n]

    return _fetch_ths_recent_concepts(ak=ak, top_n=top_n, probe_size=ths_probe_size)


def _import_akshare():
    import akshare as ak  # noqa: PLC0415

    return ak


def _fetch_eastmoney_concepts(ak: Any, top_n: int) -> list[dict]:
    frames = []
    for func_name in ("stock_board_concept_name_em", "stock_board_concept_spot_em"):
        func = getattr(ak, func_name, None)
        if func is None:
            continue
        try:
            df = _call_quietly(func)
        except Exception:
            continue
        if _valid_frame(df):
            frames.append(df)

    for df in frames:
        items = _normalize_eastmoney_frame(df)
        if items:
            return sorted(items, key=lambda item: (item.get("heat", 0), item.get("change", 0)), reverse=True)[:top_n]
    return []


def _normalize_eastmoney_frame(df: pd.DataFrame) -> list[dict]:
    concept_col = _pick_column(df, exact=("板块名称", "概念名称", "名称", "name"), contains=("名称", "概念"))
    change_col = _pick_column(df, exact=("涨跌幅", "涨幅", "板块涨幅", "change"), contains=("涨跌幅", "涨幅"))
    if concept_col is None or change_col is None:
        return []

    code_col = _pick_column(df, exact=("板块代码", "代码", "code"), contains=("代码",))
    turnover_col = _pick_column(df, exact=("换手率", "换手"), contains=("换手",))
    amount_col = _pick_column(df, exact=("成交额",), contains=("成交额",))

    rows = []
    for _, row in df.iterrows():
        concept = str(row.get(concept_col) or "").strip()
        change = _to_float(row.get(change_col))
        if not concept or change is None or change <= 0:
            continue
        turnover = _to_float(row.get(turnover_col)) if turnover_col else None
        rows.append(
            {
                "concept": concept,
                "code": str(row.get(code_col) or "").strip() if code_col else "",
                "change": round(change, 2),
                "turnover": round(turnover, 2) if turnover is not None else None,
                "amount": _to_float(row.get(amount_col)) if amount_col else None,
                "source": "eastmoney",
                "reason": "东方财富概念板块实时涨幅靠前",
            }
        )

    if not rows:
        return []

    max_change = max((item["change"] for item in rows), default=1) or 1
    max_turnover = max((item.get("turnover") or 0 for item in rows), default=0) or 0
    for item in rows:
        change_score = min(70.0, max(0.0, item["change"]) / max_change * 70.0)
        turnover_score = 0.0
        if max_turnover > 0 and item.get("turnover") is not None:
            turnover_score = min(30.0, max(0.0, item["turnover"]) / max_turnover * 30.0)
        item["heat"] = round(min(100.0, change_score + turnover_score), 1)
    return rows


def _fetch_ths_recent_concepts(ak: Any, top_n: int, probe_size: int) -> list[dict]:
    summary_func = getattr(ak, "stock_board_concept_summary_ths", None)
    info_func = getattr(ak, "stock_board_concept_info_ths", None)
    if summary_func is None or info_func is None:
        return []

    try:
        summary = _call_quietly(summary_func)
    except Exception:
        return []
    if not _valid_frame(summary):
        return []

    concept_col = _pick_column(summary, exact=("概念名称", "name"), contains=("概念", "名称"))
    reason_col = _pick_column(summary, exact=("驱动事件", "reason"), contains=("驱动", "事件"))
    date_col = _pick_column(summary, exact=("日期", "date"), contains=("日期",))
    if concept_col is None:
        return []

    items = []
    seen = set()
    for _, row in summary.head(max(probe_size, top_n)).iterrows():
        concept = str(row.get(concept_col) or "").strip()
        if not concept or concept in seen:
            continue
        seen.add(concept)
        info = _fetch_ths_info(info_func, concept)
        change = info.get("change")
        if change is None or change <= 0:
            continue
        rising_ratio = info.get("rising_ratio")
        heat = min(100.0, max(0.0, change) * 18.0 + (rising_ratio or 0) * 25.0)
        items.append(
            {
                "concept": concept,
                "change": round(change, 2),
                "heat": round(heat, 1),
                "source": "ths",
                "reason": str(row.get(reason_col) or "同花顺近期概念驱动事件") if reason_col else "同花顺近期概念驱动事件",
                "trade_date": str(row.get(date_col) or "") if date_col else "",
                "rising_falling": info.get("rising_falling", ""),
                "rank": info.get("rank", ""),
            }
        )

    return sorted(items, key=lambda item: (item.get("heat", 0), item.get("change", 0)), reverse=True)[:top_n]


def _fetch_ths_info(info_func: Any, concept: str) -> dict:
    try:
        info_df = _call_quietly(info_func, symbol=concept)
    except Exception:
        return {}
    if not _valid_frame(info_df):
        return {}

    key_col = _pick_column(info_df, exact=("项目", "item"), contains=("项目",))
    value_col = _pick_column(info_df, exact=("值", "value"), contains=("值",))
    if key_col is None or value_col is None:
        return {}

    values = {str(row.get(key_col) or "").strip(): str(row.get(value_col) or "").strip() for _, row in info_df.iterrows()}
    rising_falling = values.get("涨跌家数", "")
    return {
        "change": _to_float(values.get("板块涨幅")),
        "rising_falling": rising_falling,
        "rising_ratio": _parse_rising_ratio(rising_falling),
        "rank": values.get("涨幅排名", ""),
    }


def _pick_column(df: pd.DataFrame, exact: tuple[str, ...] = (), contains: tuple[str, ...] = ()) -> str | None:
    for name in exact:
        if name in df.columns:
            return name
    for col in df.columns:
        text = str(col)
        if any(token in text for token in contains):
            return col
    return None


def _valid_frame(df: Any) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty


def _call_quietly(func: Any, *args, **kwargs):
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore")
        return func(*args, **kwargs)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"-", "--", "None", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_rising_ratio(value: str) -> float | None:
    text = str(value or "").strip()
    if "/" not in text:
        return None
    left, right = text.split("/", 1)
    up = _to_float(left)
    down = _to_float(right)
    if up is None or down is None:
        return None
    total = up + down
    return up / total if total > 0 else None
