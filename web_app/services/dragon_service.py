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
    "page_sample_count": "178",
    "page_avg_3d": "+3.41%",
    "priority_avg_3d": "+10.18%",
    "priority_win_3d": "83.33%",
    "priority_top1_avg_3d": "+10.77%",
    "baseline_next_limit": "21.3%",
    "low_turnover_next_limit": "29.4%",
    "low_turnover_decapatated": "14.1%",
    "low_turnover_3d": "+4.08%",
    "low_turnover_hot_3d": "+4.27%",
    "real_board_early_next_limit": "42.6%",
}

DISPLAY_LIMITS = {
    "priority": 3,
    "caution": 5,
    "research": 8,
}

RULE_PRIORITY = {
    "second_board_confirm": 100,
    "third_board_space": 96,
    "theme_money_confirm": 84,
    "divergence_repair": 78,
    "strong_theme_watch": 62,
    "research_sample": 20,
}


def build_dragon_observation(limit_dir: str | Path | None = None, end_date: str | None = None) -> dict:
    data_dir = Path(limit_dir) if limit_dir else _default_limit_dir()
    frame = _load_latest_limit_pool(data_dir, end_date=end_date)
    if frame.empty:
        return _empty_observation(end_date=end_date)
    scored = _score_observation_candidates(frame)
    if scored.empty:
        return _empty_observation(end_date=end_date)

    source_quality = "real" if scored["is_real_source"].any() else "derived"
    themes = _build_theme_radar(scored)
    scored = _attach_theme_meta(scored, themes)
    scored = _apply_page_display_rules(scored)

    display_groups = _build_display_groups(scored)
    legacy_buckets = _build_legacy_buckets(scored)
    emotion_snapshot = _build_emotion_snapshot(scored, themes)
    lifecycle_groups = _build_lifecycle_groups(scored)
    summary = _build_summary(scored, display_groups, source_quality)

    return {
        "trade_date": str(scored["trade_date"].iloc[0]),
        "summary": summary,
        "emotion_snapshot": emotion_snapshot,
        "themes": themes,
        "lifecycle_groups": lifecycle_groups,
        "display_groups": display_groups,
        "display_group_meta": _display_group_meta(),
        "buckets": legacy_buckets,
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
    for column in ["trade_date", "ts_code", "name", "industry", "limit_up_reason", "first_limit_time"]:
        if column not in work.columns:
            work[column] = ""
        work[column] = work[column].fillna("").astype(str)
    if "concept" not in work.columns:
        work["concept"] = ""
    work["concept"] = work["concept"].fillna("").astype(str)
    work = work[work["pct_chg"] >= 7].copy()
    if work.empty:
        return work
    work["theme_name"] = work.apply(_theme_key, axis=1)
    work["theme_heat_count"] = work.groupby([work["trade_date"].astype(str), work["theme_name"]])["ts_code"].transform("count").fillna(1)
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
    work["lifecycle"] = work.apply(_lifecycle_label, axis=1)
    return work.sort_values(["bucket", "score", "amount"], ascending=[True, False, False]).reset_index(drop=True)


def _attach_theme_meta(work: pd.DataFrame, themes: list[dict]) -> pd.DataFrame:
    result = work.copy()
    by_name = {
        str(theme.get("theme_name") or ""): {
            "theme_state": str(theme.get("theme_state") or ""),
            "theme_score": float(theme.get("theme_score") or 0),
        }
        for theme in themes
    }
    result["theme_state"] = result["theme_name"].map(lambda value: by_name.get(str(value), {}).get("theme_state", ""))
    result["theme_score"] = result["theme_name"].map(lambda value: by_name.get(str(value), {}).get("theme_score", 0.0))
    return result


def _apply_page_display_rules(work: pd.DataFrame) -> pd.DataFrame:
    result = work.copy()
    result["display_rule"] = result.apply(_display_rule, axis=1)
    result["display_group"] = result["display_rule"].map(_display_group)
    result["rule_priority"] = result["display_rule"].map(lambda value: RULE_PRIORITY.get(str(value), 0))
    result["display_score"] = result.apply(_display_score, axis=1)
    result["action"] = result.apply(_display_action_text, axis=1)
    result = (
        result.sort_values(["trade_date", "ts_code", "rule_priority", "display_score"], ascending=[True, True, False, False])
        .drop_duplicates(["trade_date", "ts_code"], keep="first")
        .copy()
    )
    return result


def _build_display_groups(work: pd.DataFrame) -> dict:
    groups = {key: [] for key in DISPLAY_LIMITS}
    visible = work[work["display_group"].isin(DISPLAY_LIMITS)].copy()
    for group, limit in DISPLAY_LIMITS.items():
        selected = (
            visible[visible["display_group"] == group]
            .sort_values(["rule_priority", "display_score", "score", "amount", "ts_code"], ascending=[False, False, False, False, True])
            .head(limit)
        )
        groups[group] = [_decorate_item(row) for row in selected.to_dict("records")]
    return groups


def _build_legacy_buckets(work: pd.DataFrame) -> dict:
    focus = work[work["display_group"] == "priority"].head(8)
    wait = work[work["display_group"].isin(["caution", "research"])].head(12)
    avoid = work[work["display_group"] == "hidden"].head(8)
    return {
        "focus": [_decorate_item(row) for row in focus.to_dict("records")],
        "wait": [_decorate_item(row) for row in wait.to_dict("records")],
        "avoid": [_decorate_item(row) for row in avoid.to_dict("records")],
    }


def _build_summary(work: pd.DataFrame, display_groups: dict, source_quality: str) -> dict:
    priority_count = len(display_groups.get("priority") or [])
    caution_count = len(display_groups.get("caution") or [])
    research_count = len(display_groups.get("research") or [])
    hidden_count = int((work["display_group"] == "hidden").sum()) if "display_group" in work.columns else 0
    return {
        "source_quality": source_quality,
        "priority_count": priority_count,
        "caution_count": caution_count,
        "research_count": research_count,
        "hidden_count": hidden_count,
        "focus_count": priority_count,
        "wait_count": caution_count + research_count,
        "avoid_count": hidden_count,
        "headline": _headline(source_quality, priority_count),
        "note": _source_note(source_quality),
    }


def _display_rule(row: pd.Series) -> str:
    source = str(row.get("source") or "")
    limit_days = _safe_float(row.get("limit_days"))
    turnover = _safe_float(row.get("turnover_rate"))
    open_count = _safe_float(row.get("open_count"))
    theme_score = _safe_float(row.get("theme_score"))
    if row.get("late_or_fragile") or limit_days >= 4:
        return "hidden_risk"
    if source == "zt_pool" and limit_days == 1 and turnover <= 3:
        return "hidden_low_turnover_first"
    if source in {"previous_pool", "zt_pool"} and limit_days == 2 and theme_score >= 35:
        return "second_board_confirm"
    if source == "zt_pool" and limit_days == 3 and theme_score >= 35:
        return "third_board_space"
    if source == "zt_pool" and 3 <= turnover <= 8 and theme_score >= 55 and open_count >= 1:
        return "theme_money_confirm"
    if source == "zt_pool" and 8 <= turnover <= 18 and theme_score >= 45 and open_count >= 2:
        return "divergence_repair"
    if source == "strong_pool" and theme_score >= 35:
        return "strong_theme_watch"
    return "research_sample"


def _display_group(rule: object) -> str:
    value = str(rule or "")
    if value in {"hidden_risk", "hidden_low_turnover_first"}:
        return "hidden"
    if value in {"second_board_confirm", "third_board_space"}:
        return "priority"
    if value in {"theme_money_confirm", "divergence_repair", "strong_theme_watch"}:
        return "caution"
    return "research"


def _display_score(row: pd.Series) -> float:
    turnover = _safe_float(row.get("turnover_rate"))
    turnover_bonus = max(0.0, 20.0 - abs(turnover - 7.0) * 2.0)
    limit_days = _safe_float(row.get("limit_days"))
    limit_bonus = 12.0 if limit_days in (2.0, 3.0) else 0.0
    return round(
        _safe_float(row.get("theme_score"))
        + _safe_float(row.get("score")) * 0.35
        + turnover_bonus
        + limit_bonus
        - _safe_float(row.get("open_count")) * 1.5,
        4,
    )


def _display_action_text(row: pd.Series) -> str:
    rule = str(row.get("display_rule") or "")
    if rule == "second_board_confirm":
        return "二板确认且题材有合力，优先观察次日承接是否继续强。"
    if rule == "third_board_space":
        return "三板打开高度，主要看是否带动同题材扩散。"
    if rule == "theme_money_confirm":
        return "题材热度和换手较均衡，适合观察分歧后的承接。"
    if rule == "divergence_repair":
        return "已有分歧换手，先看回封质量和题材是否继续发酵。"
    if rule == "strong_theme_watch":
        return "强势股辅助观察，等待更明确的涨停确认。"
    if rule.startswith("hidden"):
        return "风险样本已从页面展示中隐藏。"
    return "只作研究样本，等待题材或梯队进一步确认。"


def _display_group_meta() -> dict:
    return {
        "priority": {
            "title": "优先关注",
            "hint": "历史验证较强的二板确认/三板打开高度结构，页面只做观察提示。",
            "metric": f"3日均值 {STUDY_METRICS['priority_avg_3d']} / 胜率 {STUDY_METRICS['priority_win_3d']}",
        },
        "caution": {
            "title": "谨慎观察",
            "hint": "题材、换手或资金结构有亮点，但历史收益不如优先关注稳定。",
            "metric": "等待分歧承接确认",
        },
        "research": {
            "title": "研究样本",
            "hint": "保留市场温度和题材扩散线索，不作为页面主推。",
            "metric": "辅助观察",
        },
    }


def _theme_key(row: pd.Series) -> str:
    for key in ("concept", "limit_up_reason", "industry"):
        text = str(row.get(key) or "").strip()
        if text:
            for sep in ("，", ",", ";", "；", " "):
                if sep in text:
                    text = text.split(sep)[0]
                    break
            return text or "未分组"
    return "未分组"


def _build_theme_radar(work: pd.DataFrame) -> list[dict]:
    if work.empty or "theme_name" not in work.columns:
        return []
    rows = []
    for theme_name, grp in work.groupby("theme_name"):
        limit_up = grp[grp["source"].astype(str).str.contains("zt_pool|previous_pool", na=False)]
        strong = grp[grp["source"].astype(str).str.contains("strong_pool", na=False)]
        fragile = grp[grp["late_or_fragile"]]
        board_2 = int((grp["limit_days"] == 2).sum())
        board_3_plus = int((grp["limit_days"] >= 3).sum())
        early = int(grp["early_seal"].sum())
        low_turnover = int(grp["low_turnover"].sum())
        leader_rows = grp.sort_values(["limit_days", "score", "amount"], ascending=[False, False, False]).head(3)
        heat = min(len(limit_up) * 12 + len(strong) * 5, 40)
        ladder = min(board_2 * 12 + board_3_plus * 18 + (10 if len(limit_up) >= 3 else 0), 30)
        leader = min(early * 4 + low_turnover * 5 + board_3_plus * 8, 20)
        fragility = min(len(fragile) * 8, 25)
        theme_score = max(0, min(100, heat + ladder + leader - fragility))
        rows.append(
            {
                "theme_name": str(theme_name),
                "primary_industry": _mode_text(grp["industry"] if "industry" in grp.columns else None),
                "stock_count": int(len(grp)),
                "limit_up_count": int(len(limit_up)),
                "strong_count": int(len(strong)),
                "board_2_count": board_2,
                "board_3_plus_count": board_3_plus,
                "early_seal_count": early,
                "low_turnover_count": low_turnover,
                "fragile_count": int(len(fragile)),
                "theme_score": round(float(theme_score), 1),
                "theme_state": _theme_state(theme_score, len(limit_up), board_2, board_3_plus, len(fragile)),
                "leader_codes": [_decorate_item(row) for row in leader_rows.to_dict("records")],
                "risk_notes": _theme_risk_notes(len(fragile), board_3_plus, theme_score),
            }
        )
    return sorted(rows, key=lambda item: item["theme_score"], reverse=True)


def _mode_text(series: pd.Series | None) -> str:
    if series is None:
        return "-"
    values = series.fillna("").astype(str).str.strip()
    values = values[values.ne("")]
    if values.empty:
        return "-"
    return str(values.mode().iloc[0])


def _theme_state(score: float, limit_up_count: int, board_2: int, board_3_plus: int, fragile_count: int) -> str:
    if fragile_count >= max(limit_up_count, 1) and score < 35:
        return "退潮回避"
    if board_3_plus > 0 and fragile_count > 0:
        return "分歧中"
    if score >= 55 and (board_2 > 0 or board_3_plus > 0):
        return "主线确认"
    if score >= 35:
        return "发酵观察"
    return "轮动补涨"


def _theme_risk_notes(fragile_count: int, board_3_plus: int, score: float) -> list[str]:
    notes = []
    if fragile_count:
        notes.append(f"{fragile_count}只脆弱/开板样本，追高需降权")
    if board_3_plus >= 2:
        notes.append("高位梯队拥挤，更多用于观察情绪")
    if score < 30:
        notes.append("题材合力不足，按轮动处理")
    return notes


def _build_emotion_snapshot(work: pd.DataFrame, themes: list[dict]) -> dict:
    limit_up_count = int(work["source"].astype(str).str.contains("zt_pool|previous_pool", na=False).sum())
    board_2_plus = int((work["limit_days"] >= 2).sum())
    board_3_plus = int((work["limit_days"] >= 3).sum())
    fragile_count = int(work["late_or_fragile"].sum())
    top_theme = themes[0] if themes else {}
    top_score = float(top_theme.get("theme_score") or 0)
    if fragile_count >= max(limit_up_count // 2, 3):
        phase = "退潮"
    elif fragile_count >= 2 and board_3_plus:
        phase = "分歧"
    elif board_3_plus >= 2 and top_score >= 65:
        phase = "高潮"
    elif board_2_plus >= 2 or top_score >= 55:
        phase = "发酵"
    elif limit_up_count > 0:
        phase = "启动"
    else:
        phase = "修复"
    if top_score >= 55:
        mainline_state = "强主线"
    elif len(themes) >= 3 and top_score >= 30:
        mainline_state = "多题材轮动"
    else:
        mainline_state = "无主线"
    if phase == "退潮":
        risk_state = "退潮"
        next_day_bias = "降低短线出手"
    elif fragile_count >= 3:
        risk_state = "高位拥挤"
        next_day_bias = "等分歧"
    elif mainline_state == "强主线":
        risk_state = "正常"
        next_day_bias = "看优先关注，找低位扩散"
    else:
        risk_state = "正常"
        next_day_bias = "只看低位"
    theme_name = str(top_theme.get("theme_name") or "暂无明确题材")
    summary = f"{theme_name}处于{mainline_state}状态，情绪阶段为{phase}，明日偏向：{next_day_bias}。"
    return {
        "emotion_phase": phase,
        "mainline_state": mainline_state,
        "risk_state": risk_state,
        "next_day_bias": next_day_bias,
        "summary_text": summary,
    }


def _lifecycle_label(row: pd.Series) -> str:
    limit_days = int(row.get("limit_days") or 1)
    source = str(row.get("source") or "")
    if row.get("late_or_fragile"):
        return "退潮风险" if limit_days >= 3 else "分歧回封"
    if limit_days >= 3:
        return "空间确认"
    if limit_days == 2:
        return "二板确认"
    if source == "strong_pool":
        return "主线补涨"
    if row.get("low_turnover") and row.get("early_seal"):
        return "首板高质量"
    if row.get("open_count", 0) > 0 and not row.get("late_or_fragile"):
        return "换手龙苗"
    return "首板试错"


def _build_lifecycle_groups(work: pd.DataFrame) -> dict:
    groups = {
        "early_opportunity": [],
        "emotion_anchor": [],
        "risk_sample": [],
    }
    if work.empty:
        return groups
    for row in work.sort_values(["score", "amount"], ascending=[False, False]).to_dict("records"):
        label = str(row.get("lifecycle") or "")
        item = _decorate_item(row)
        if label in {"首板高质量", "二板确认", "换手龙苗", "主线补涨", "首板试错"}:
            groups["early_opportunity"].append(item)
        elif label in {"空间确认", "高位加速"}:
            groups["emotion_anchor"].append(item)
        else:
            groups["risk_sample"].append(item)
    return {key: value[:12] for key, value in groups.items()}


def enrich_short_pool_with_dragon_sentiment(pool: pd.DataFrame, observation: dict | None) -> pd.DataFrame:
    """Attach low-weight dragon sentiment fields to a short signal pool."""
    if pool is None or pool.empty or not observation:
        return pool
    themes = observation.get("themes") or []
    if not themes:
        return pool
    theme_by_industry = {}
    for theme in themes:
        industry = str(theme.get("primary_industry") or "").strip()
        if industry and industry != "-" and industry not in theme_by_industry:
            theme_by_industry[industry] = theme
    result = pool.copy()
    adjustments = []
    states = []
    reasons = []
    risks = []
    theme_names = []
    theme_scores = []
    for _, row in result.iterrows():
        industry = str(row.get("industry") or "").strip()
        theme = theme_by_industry.get(industry)
        adjustment, reason, risk = _short_dragon_adjustment(theme)
        adjustments.append(adjustment)
        states.append(str(theme.get("theme_state") or "") if theme else "")
        reasons.append(reason)
        risks.append(risk)
        theme_names.append(str(theme.get("theme_name") or "") if theme else "")
        theme_scores.append(float(theme.get("theme_score") or 0.0) if theme else 0.0)
    result["dragon_adjustment"] = adjustments
    result["dragon_theme_state"] = states
    result["dragon_theme_name"] = theme_names
    result["dragon_theme_score"] = theme_scores
    result["dragon_reason"] = reasons
    result["dragon_risk"] = risks
    result["score"] = (pd.to_numeric(result["score"], errors="coerce").fillna(0) + result["dragon_adjustment"]).round(2)
    return result


def _short_dragon_adjustment(theme: dict | None) -> tuple[float, str, str]:
    if not theme:
        return 0.0, "龙头情绪：无题材映射", ""
    state = str(theme.get("theme_state") or "")
    score = float(theme.get("theme_score") or 0.0)
    risk = "；".join(str(note) for note in (theme.get("risk_notes") or []) if note)
    if state == "退潮回避":
        return -8.0, "龙头情绪：退潮题材降权", risk
    if state == "分歧中":
        return -3.0, "龙头情绪：题材分歧，非核心降权", risk
    if state == "主线确认":
        boost = 6.0 if score >= 75 else 4.0
        return boost, f"龙头情绪：主线共振 +{boost:g}", risk
    if state == "发酵观察":
        return 3.0, "龙头情绪：题材发酵 +3", risk
    if state == "轮动补涨":
        return 2.0, "龙头情绪：轮动补涨 +2", risk
    return 0.0, "龙头情绪：观察", risk


def _decorate_item(row: dict) -> dict:
    badges = []
    if row.get("low_turnover"):
        badges.append("低换手")
    if row.get("hot_theme"):
        badges.append("题材有热度")
    if row.get("early_seal"):
        badges.append("封板较早")
    if row.get("limit_days", 0) and float(row.get("limit_days") or 0) >= 2:
        badges.append("连板")
    if row.get("display_group") == "priority":
        badges.append("优先关注")
    if row.get("display_group") == "hidden":
        badges.append("已隐藏风险")
    return {
        "trade_date": str(row.get("trade_date") or ""),
        "ts_code": str(row.get("ts_code") or ""),
        "name": str(row.get("name") or row.get("ts_code") or ""),
        "industry": str(row.get("industry") or "-"),
        "score": round(float(row.get("display_score", row.get("score") or 0) or 0), 1),
        "raw_score": round(float(row.get("score") or 0), 1),
        "turnover_rate": _fmt_pct(row.get("turnover_rate")),
        "theme_heat_count": int(row.get("theme_heat_count") or 0),
        "theme_name": str(row.get("theme_name") or "-"),
        "theme_state": str(row.get("theme_state") or "-"),
        "theme_score": round(float(row.get("theme_score") or 0), 1),
        "first_limit_time": str(row.get("first_limit_time") or "-"),
        "open_count": int(row.get("open_count") or 0),
        "limit_days": int(row.get("limit_days") or 0),
        "lifecycle": str(row.get("lifecycle") or ""),
        "action": str(row.get("action") or ""),
        "display_rule": str(row.get("display_rule") or ""),
        "display_group": str(row.get("display_group") or ""),
        "badges": badges,
    }


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


def _safe_float(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _headline(source_quality: str, priority_count: int) -> str:
    if priority_count:
        return "龙头观察：已有优先关注样本"
    if source_quality == "real":
        return "龙头观察：今日先等更清晰的承接"
    return "龙头观察：历史衍生源，仅做辅助筛查"


def _source_note(source_quality: str) -> str:
    if source_quality == "real":
        return "真实涨停池含首封、开板、封单等字段；页面只做研究观察，不生成交易执行指令。"
    return "当前只读到历史衍生涨停池，缺少真实封板质量字段。"


def _empty_observation(end_date: str | None = None) -> dict:
    return {
        "trade_date": str(end_date or ""),
        "summary": {
            "source_quality": "missing",
            "priority_count": 0,
            "caution_count": 0,
            "research_count": 0,
            "hidden_count": 0,
            "focus_count": 0,
            "wait_count": 0,
            "avoid_count": 0,
            "headline": "暂无龙头观察数据",
            "note": "未找到涨停池数据，请先运行研究数据采集。",
        },
        "emotion_snapshot": {
            "emotion_phase": "修复",
            "mainline_state": "无主线",
            "risk_state": "正常",
            "next_day_bias": "等待数据",
            "summary_text": "暂无龙头观察数据，请先刷新涨停池。",
        },
        "themes": [],
        "lifecycle_groups": {"early_opportunity": [], "emotion_anchor": [], "risk_sample": []},
        "display_groups": {"priority": [], "caution": [], "research": []},
        "display_group_meta": _display_group_meta(),
        "buckets": {"focus": [], "wait": [], "avoid": []},
        "study": STUDY_METRICS,
    }
