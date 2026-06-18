#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only history database services for Web pages."""

from __future__ import annotations

from pathlib import Path

from history_db_check import check_history_db
from history_store import DEFAULT_HISTORY_DB_PATH
from signal_store import DEFAULT_DB_PATH as DEFAULT_SIGNAL_DB_PATH
from stock_history_query import query_stock_history


def get_db_status(history_db: str | Path = DEFAULT_HISTORY_DB_PATH) -> dict:
    return check_history_db(history_db)


def get_stock_detail(
    code: str,
    history_db: str | Path = DEFAULT_HISTORY_DB_PATH,
    signal_db: str | Path | None = DEFAULT_SIGNAL_DB_PATH,
) -> dict:
    detail = query_stock_history(code, history_db=history_db, signal_db=signal_db)
    detail["verdict"] = build_stock_verdict(detail)
    return detail


def build_stock_verdict(detail: dict) -> dict:
    returns = detail.get("returns") or {}
    basic = detail.get("latest_basic") or {}
    moneyflow = detail.get("latest_moneyflow") or {}
    finance = detail.get("latest_finance") or {}
    signal = detail.get("signal_state") or {}

    score = 0
    reasons = []
    risks = []

    ret40 = _num(returns.get("40d"))
    ret80 = _num(returns.get("80d"))
    if ret40 is not None and ret40 > 5:
        score += 1
        reasons.append("近40日走势偏强")
    elif ret40 is not None and ret40 < -8:
        risks.append("近40日明显走弱")

    if ret80 is not None and ret80 > 8:
        score += 1
        reasons.append("近80日趋势有延续")
    elif ret80 is not None and ret80 < -10:
        risks.append("近80日表现较弱")

    pe = _num(basic.get("pe_ttm"))
    pb = _num(basic.get("pb"))
    if pe is not None and 0 < pe < 35:
        score += 1
        reasons.append("估值未明显过热")
    if pb is not None and pb > 6:
        risks.append("PB偏高")

    inflow = _num(moneyflow.get("net_mf_amount"))
    if inflow is not None and inflow > 0:
        score += 1
        reasons.append("最新主力资金净流入")
    elif inflow is not None and inflow < -10000:
        risks.append("最新主力资金净流出较多")

    roe = _num(finance.get("roe"))
    yoy = _num(finance.get("netprofit_yoy"))
    if roe is not None and roe > 8:
        score += 1
        reasons.append("ROE质量较好")
    if yoy is not None and yoy < -20:
        risks.append("净利润同比承压")

    if signal:
        score += 1
        reasons.append("当前在信号库有状态记录")

    if score >= 5:
        level = "可重点关注"
    elif score >= 3:
        level = "继续观察"
    elif risks:
        level = "风险偏高"
    else:
        level = "数据不足"

    return {
        "level": level,
        "score": score,
        "reasons": reasons[:4],
        "risks": risks[:4],
    }


def _num(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
