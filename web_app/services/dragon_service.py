#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only dragon leader observation service for the Web dashboard."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


DEFAULT_LIMIT_POOL_CANDIDATES = (
    Path("data_research") / "limit_pool",
    Path("..") / "stock-strategy-research" / "data_research" / "limit_pool",
)

STUDY_METRICS = {
    "baseline_next_limit": "21.3%",
    "low_turnover_next_limit": "29.4%",
    "low_turnover_decapatated": "14.1%",
    "low_turnover_3d": "+4.08%",
    "low_turnover_hot_3d": "+4.27%",
    "real_board_early_next_limit": "42.6%",
}


def build_dragon_observation(limit_dir: str | Path | None = None, end_date: str | None = None) -> dict:
    data_dir = Path(limit_dir) if limit_dir else _default_limit_dir()
    frame = _load_latest_limit_pool(data_dir, end_date=end_date)
    if frame.empty:
        return _empty_observation(end_date=end_date)
    scored = _score_observation_candidates(frame)
    focus = scored[scored["bucket"] == "focus"].head(8)
    wait = scored[scored["bucket"] == "wait"].head(12)
    avoid = scored[scored["bucket"] == "avoid"].head(8)
    source_quality = "real" if scored["is_real_source"].any() else "derived"
    return {
        "trade_date": str(scored["trade_date"].iloc[0]),
        "summary": {
            "source_quality": source_quality,
            "focus_count": int(len(focus)),
            "wait_count": int(len(wait)),
            "avoid_count": int(len(avoid)),
            "headline": _headline(source_quality, len(focus)),
            "note": _source_note(source_quality),
        },
        "buckets": {
            "focus": [_decorate_item(row) for row in focus.to_dict("records")],
            "wait": [_decorate_item(row) for row in wait.to_dict("records")],
            "avoid": [_decorate_item(row) for row in avoid.to_dict("records")],
        },
        "study": STUDY_METRICS,
    }


def _default_limit_dir() -> Path:
    for candidate in DEFAULT_LIMIT_POOL_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_LIMIT_POOL_CANDIDATES[0]


def _load_latest_limit_pool(limit_dir: Path, end_date: str | None = None) -> pd.DataFrame:
    if not limit_dir.exists():
        return pd.DataFrame()
    normalized_end = str(end_date or "").replace("-", "")[:8]
    paths = []
    for path in sorted(limit_dir.glob("*.parquet")):
        if normalized_end and path.stem > normalized_end:
            continue
        paths.append(path)
    for path in reversed(paths):
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if frame.empty:
            continue
        frame = frame.copy()
        if "trade_date" not in frame.columns:
            frame["trade_date"] = path.stem
        frame["trade_date"] = frame["trade_date"].fillna(path.stem).astype(str)
        frame.loc[frame["trade_date"].isin(["", "None", "nan", "NaT"]), "trade_date"] = path.stem
        return frame
    return pd.DataFrame()


def _score_observation_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    if "source" not in work.columns:
        work["source"] = ""
    source = work["source"].fillna("").astype(str)
    work = work[source.str.contains("zt_pool|strong_pool|previous_pool", na=False)].copy()
    if work.empty:
        return work
    for column, default in {
        "pct_chg": 0,
        "turnover_rate": 99,
        "amount": 0,
        "seal_amount": 0,
        "open_count": 0,
        "limit_days": 1,
    }.items():
        work[column] = pd.to_numeric(work[column] if column in work.columns else default, errors="coerce").fillna(default)
    for column in ["name", "industry", "limit_up_reason", "first_limit_time"]:
        if column not in work.columns:
            work[column] = ""
        work[column] = work[column].fillna("").astype(str)
    work = work[work["pct_chg"] >= 7].copy()
    if work.empty:
        return work
    theme_key = work["industry"].where(work["industry"].str.strip().ne(""), work["limit_up_reason"])
    work["theme_heat_count"] = work.groupby([work["trade_date"].astype(str), theme_key])["ts_code"].transform("count").fillna(1)
    turnover = work["turnover_rate"]
    work["turnover_q20"] = turnover.quantile(0.2)
    work["turnover_q80"] = turnover.quantile(0.8)
    work["low_turnover"] = work["turnover_rate"] <= work["turnover_q20"]
    work["hot_theme"] = work["theme_heat_count"] >= 5
    work["is_real_source"] = work["source"].fillna("").astype(str).isin(["zt_pool", "strong_pool", "previous_pool"])
    work["seal_time_value"] = work["first_limit_time"].map(_time_value)
    work["early_seal"] = work["seal_time_value"] <= 1000
    work["late_or_fragile"] = (work["seal_time_value"] > 1400) | (work["open_count"] > 4) | (work["turnover_rate"] >= work["turnover_q80"])
    work["score"] = (
        40
        + work["low_turnover"].astype(int) * 20
        + work["hot_theme"].astype(int) * 16
        + work["early_seal"].astype(int) * 10
        + work["limit_days"].clip(1, 4) * 4
        - work["late_or_fragile"].astype(int) * 28
        - work["open_count"].clip(0, 8) * 2
    ).round(1)
    work["bucket"] = "wait"
    work.loc[work["late_or_fragile"], "bucket"] = "avoid"
    work.loc[work["low_turnover"] & work["hot_theme"] & ~work["late_or_fragile"], "bucket"] = "focus"
    work["action"] = work.apply(_action_text, axis=1)
    return work.sort_values(["bucket", "score", "amount"], ascending=[True, False, False]).reset_index(drop=True)


def _decorate_item(row: dict) -> dict:
    badges = []
    if row.get("low_turnover"):
        badges.append("low turnover")
    if row.get("hot_theme"):
        badges.append("hot theme")
    if row.get("early_seal"):
        badges.append("early seal")
    if row.get("limit_days", 0) and float(row.get("limit_days") or 0) >= 2:
        badges.append("multi-board")
    if row.get("late_or_fragile"):
        badges.append("fragile")
    return {
        "trade_date": str(row.get("trade_date") or ""),
        "ts_code": str(row.get("ts_code") or ""),
        "name": str(row.get("name") or row.get("ts_code") or ""),
        "industry": str(row.get("industry") or "-"),
        "score": round(float(row.get("score") or 0), 1),
        "turnover_rate": _fmt_pct(row.get("turnover_rate")),
        "theme_heat_count": int(row.get("theme_heat_count") or 0),
        "first_limit_time": str(row.get("first_limit_time") or "-"),
        "open_count": int(row.get("open_count") or 0),
        "limit_days": int(row.get("limit_days") or 0),
        "action": str(row.get("action") or ""),
        "badges": badges,
    }


def _action_text(row: pd.Series) -> str:
    if row.get("bucket") == "focus":
        return "small gap / 平开小高开放量可看；高开过多不追"
    if row.get("bucket") == "avoid":
        return "禁止追高；等下一轮更干净的板"
    return "等分歧确认；承接强或回封再看"


def _time_value(value: object) -> int:
    text = str(value or "").strip().replace(":", "")
    if len(text) < 4 or not text[:4].isdigit():
        return 9999
    return int(text[:4])


def _fmt_pct(value: object) -> str:
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "-"


def _headline(source_quality: str, focus_count: int) -> str:
    if focus_count:
        return "研究版观察榜：已有可重点跟踪候选"
    if source_quality == "real":
        return "研究版观察榜：今日先等分歧确认"
    return "研究版观察榜：历史衍生源，仅做辅助筛查"


def _source_note(source_quality: str) -> str:
    if source_quality == "real":
        return "真实涨停池含首封、开板、封单等字段；仍是研究版，不作为正式买入指令。"
    return "当前只读到历史衍生涨停池，缺少真实封板质量字段。"


def _empty_observation(end_date: str | None = None) -> dict:
    return {
        "trade_date": str(end_date or ""),
        "summary": {
            "source_quality": "missing",
            "focus_count": 0,
            "wait_count": 0,
            "avoid_count": 0,
            "headline": "暂无龙头观察数据",
            "note": "未找到涨停池数据，请先运行研究数据采集。",
        },
        "buckets": {"focus": [], "wait": [], "avoid": []},
        "study": STUDY_METRICS,
    }
