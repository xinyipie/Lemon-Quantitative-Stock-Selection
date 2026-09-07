#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T日信号与T+1成交严格分离的研究工具。"""

from __future__ import annotations

import pandas as pd


FUTURE_ONLY_COLUMNS = {
    "entry_open",
    "entry_gap_pct",
    "tradeable",
    "ret_3d",
    "ret_5d",
    "ret_8d",
    "mfe_8d",
    "mae_8d",
    "relative_target",
    "rank_prediction",
    "gate_prediction",
    "net_ret",
}


def assert_no_future_features(feature_columns: list[str] | tuple[str, ...]) -> None:
    leaked = sorted(set(feature_columns) & FUTURE_ONLY_COLUMNS)
    if leaked:
        raise ValueError(f"信号特征包含未来字段: {leaked}")


def signal_eligible_mask(panel: pd.DataFrame, min_history: int = 120) -> pd.Series:
    """只使用T日收盘前可见信息判断信号资格。"""
    names = panel["name"].astype(str).str.upper()
    history = pd.to_numeric(panel["history_count"], errors="coerce")
    turnover = pd.to_numeric(panel["turnover_rate"], errors="coerce")
    close = pd.to_numeric(panel["close"], errors="coerce")
    return (
        ~names.str.contains("ST|退", regex=True, na=False)
        & history.ge(min_history)
        & turnover.notna()
        & close.gt(0)
    )


def lock_daily_topn(predictions: pd.DataFrame, score_column: str, topn: int = 2) -> pd.DataFrame:
    """先按T日分数锁定候选，不读取任何T+1字段。"""
    required = {"trade_date", "ts_code", score_column}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"候选缺少字段: {sorted(missing)}")
    locked = (
        predictions.sort_values(["trade_date", score_column, "ts_code"], ascending=[True, False, True])
        .groupby("trade_date", group_keys=False)
        .head(topn)
        .copy()
    )
    locked["signal_rank"] = locked.groupby("trade_date")[score_column].rank(ascending=False, method="first")
    return locked


def apply_next_open_execution(
    locked: pd.DataFrame,
    cost: float = 0.25,
    max_gap_pct: float = 9.5,
    outcome_column: str = "ret_5d",
) -> pd.DataFrame:
    """T+1开盘只决定锁定候选是否成交，不允许未成交后补位。"""
    work = locked.copy()
    entry_open = pd.to_numeric(work["entry_open"], errors="coerce")
    entry_gap = pd.to_numeric(work["entry_gap_pct"], errors="coerce")
    outcome = pd.to_numeric(work[outcome_column], errors="coerce")
    work["executed"] = entry_open.gt(0) & entry_gap.lt(max_gap_pct) & outcome.notna()
    work["execution_reason"] = "executed"
    work.loc[~entry_open.gt(0), "execution_reason"] = "no_next_open"
    work.loc[entry_open.gt(0) & ~entry_gap.lt(max_gap_pct), "execution_reason"] = "gap_limit"
    work.loc[entry_open.gt(0) & entry_gap.lt(max_gap_pct) & outcome.isna(), "execution_reason"] = "insufficient_path"
    work["net_ret"] = pd.NA
    work.loc[work["executed"], "net_ret"] = outcome[work["executed"]] - float(cost)
    return work
