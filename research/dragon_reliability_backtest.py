"""龙头情绪观察池可靠性研究脚本。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from web_app.services.dragon_service import _build_theme_radar, _score_observation_candidates


@dataclass
class DragonReliabilityConfig:
    limit_dir: Path = Path("data_research/limit_pool")
    daily_dir: Path = Path("data/cache/daily")
    output_dir: Path = Path("data_research/dragon_reliability")
    start_date: str | None = None
    end_date: str | None = None
    horizons: tuple[int, ...] = (1, 3, 5)
    max_mfe_days: int = 5
    min_group_samples: int = 30
    min_total_events: int = 200

    def __post_init__(self) -> None:
        self.limit_dir = Path(self.limit_dir)
        self.daily_dir = Path(self.daily_dir)
        self.output_dir = Path(self.output_dir)
        self.start_date = _normalize_date(self.start_date)
        self.end_date = _normalize_date(self.end_date)


def build_factor_events(config: DragonReliabilityConfig) -> pd.DataFrame:
    signals = load_limit_events(config)
    if signals.empty:
        return _empty_events()
    dates = _available_daily_dates(config.daily_dir)
    if not dates:
        return _empty_events()
    date_pos = {date: idx for idx, date in enumerate(dates)}
    daily_cache: dict[str, pd.DataFrame] = {}
    rows = []
    for signal in signals.to_dict("records"):
        trade_date = str(signal.get("trade_date") or "")
        if trade_date not in date_pos:
            continue
        signal_pos = date_pos[trade_date]
        buy_pos = signal_pos + 1
        if buy_pos >= len(dates):
            continue
        ts_code = str(signal.get("ts_code") or "")
        buy_date = dates[buy_pos]
        buy_row = _daily_row(daily_cache, config.daily_dir, buy_date, ts_code)
        signal_row = _daily_row(daily_cache, config.daily_dir, trade_date, ts_code)
        if buy_row is None:
            continue
        buy_open = _safe_float(buy_row.get("open"))
        if buy_open <= 0:
            continue
        event = {
            "trade_date": trade_date,
            "buy_date": buy_date,
            "ts_code": ts_code,
            "name": signal.get("name", ""),
            "industry": signal.get("industry", ""),
            "source": signal.get("source", ""),
            "bucket": signal.get("bucket", ""),
            "lifecycle": signal.get("lifecycle", ""),
            "theme_name": signal.get("theme_name", ""),
            "theme_state": signal.get("theme_state", ""),
            "theme_score": _safe_float(signal.get("theme_score")),
            "dragon_score": _safe_float(signal.get("score")),
            "limit_days": _safe_float(signal.get("limit_days")),
            "turnover_rate": _safe_float(signal.get("turnover_rate")),
            "open_count": _safe_float(signal.get("open_count")),
            "first_limit_time": signal.get("first_limit_time", ""),
            "buy_open": buy_open,
            "next_limit_up": _safe_float(buy_row.get("pct_chg")) >= 9.7,
            "gap_fail": _is_gap_fail(signal_row, buy_row),
        }
        for horizon in config.horizons:
            target_pos = signal_pos + horizon
            target_date = dates[target_pos] if target_pos < len(dates) else ""
            target_row = _daily_row(daily_cache, config.daily_dir, target_date, ts_code) if target_date else None
            event[f"ret_{horizon}d_pct"] = _return_from_open(buy_open, target_row)
        highs = []
        lows = []
        for hold_pos in range(buy_pos, min(signal_pos + config.max_mfe_days, len(dates) - 1) + 1):
            hold_row = _daily_row(daily_cache, config.daily_dir, dates[hold_pos], ts_code)
            if hold_row is None:
                continue
            highs.append(_safe_float(hold_row.get("high")))
            lows.append(_safe_float(hold_row.get("low")))
        event["mfe_5d_pct"] = ((max(highs) / buy_open - 1) * 100) if highs else None
        event["mae_5d_pct"] = ((min(lows) / buy_open - 1) * 100) if lows else None
        rows.append(event)
    if not rows:
        return _empty_events()
    return pd.DataFrame(rows).sort_values(["trade_date", "bucket", "dragon_score"], ascending=[True, True, False]).reset_index(drop=True)


def load_limit_events(config: DragonReliabilityConfig) -> pd.DataFrame:
    if not config.limit_dir.exists():
        return pd.DataFrame()
    frames = []
    for path in sorted(config.limit_dir.glob("*.parquet")):
        trade_date = _normalize_date(path.stem)
        if not _date_in_range(trade_date, config.start_date, config.end_date):
            continue
        try:
            raw = pd.read_parquet(path)
        except Exception:
            continue
        if raw.empty:
            continue
        raw = raw.copy()
        if "trade_date" not in raw.columns:
            raw["trade_date"] = trade_date
        raw["trade_date"] = raw["trade_date"].fillna(trade_date).astype(str)
        scored = _score_observation_candidates(raw)
        if scored.empty:
            continue
        themes = _build_theme_radar(scored)
        theme_meta = {
            str(item.get("theme_name") or ""): {
                "theme_state": item.get("theme_state", ""),
                "theme_score": item.get("theme_score", 0),
            }
            for item in themes
        }
        scored = scored.copy()
        scored["theme_state"] = scored["theme_name"].map(lambda value: theme_meta.get(str(value), {}).get("theme_state", ""))
        scored["theme_score"] = scored["theme_name"].map(lambda value: theme_meta.get(str(value), {}).get("theme_score", 0))
        frames.append(scored)
    if not frames:
        return pd.DataFrame()
    columns = [
        "trade_date",
        "ts_code",
        "name",
        "industry",
        "source",
        "bucket",
        "lifecycle",
        "theme_name",
        "theme_state",
        "theme_score",
        "score",
        "limit_days",
        "turnover_rate",
        "open_count",
        "first_limit_time",
    ]
    result = pd.concat(frames, ignore_index=True)
    for column in columns:
        if column not in result.columns:
            result[column] = ""
    return result[columns].reset_index(drop=True)


def summarize_events(
    events: pd.DataFrame,
    min_group_samples: int = 30,
    min_total_events: int = 200,
    signal_count: int | None = None,
) -> tuple[pd.DataFrame, dict]:
    if events.empty:
        reason = "没有可评估的龙头事件；需要先补采历史涨停池。"
        if signal_count:
            reason = f"已生成 {signal_count} 条龙头信号，但缺少 T+1 之后行情，暂时无法评估未来收益。"
        verdict = {
            "rating": "样本不足",
            "reason": reason,
            "event_count": 0,
            "signal_count": int(signal_count or 0),
        }
        return pd.DataFrame(), verdict
    rows = []
    group_specs = [("all", None)]
    for column in ("bucket", "lifecycle", "theme_state"):
        if column in events.columns:
            group_specs.append((column, column))
    for column in ("profit_rule", "profit_rule_v2", "profit_rule_v3", "profit_rule_v4", "profit_rule_v5_3d"):
        if column in events.columns:
            group_specs.append((column, column))
    for group_type, column in group_specs:
        groups = [("全样本", events)] if column is None else events.groupby(column, dropna=False)
        for group_value, frame in groups:
            rows.append(_summary_row(group_type, str(group_value or "未分组"), frame, min_group_samples))
    summary = pd.DataFrame(rows)
    verdict = _build_verdict(summary, events, min_total_events)
    verdict["signal_count"] = int(signal_count if signal_count is not None else len(events))
    return summary, verdict


def render_markdown_report(summary: pd.DataFrame, verdict: dict) -> str:
    lines = [
        "# 龙头情绪观察池可靠性回测",
        "",
        f"- 结论：{verdict.get('rating', '未知')}",
        f"- 样本数：{verdict.get('event_count', 0)}",
        f"- 说明：{verdict.get('reason', '')}",
        "",
        "## 分组摘要",
        "",
    ]
    if summary.empty:
        lines.append("暂无分组结果。")
        return "\n".join(lines) + "\n"
    display_columns = [
        "group_type",
        "group_value",
        "sample_count",
        "avg_ret_1d_pct",
        "avg_ret_3d_pct",
        "avg_ret_5d_pct",
        "median_ret_3d_pct",
        "win_3d_rate",
        "avg_mfe_5d_pct",
        "avg_mae_5d_pct",
        "next_limit_rate",
        "gap_fail_rate",
        "sample_note",
    ]
    available = [column for column in display_columns if column in summary.columns]
    lines.append(summary[available].to_markdown(index=False))
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- `ret_1d/3d/5d` 使用信号日后一个交易日开盘价作为买入基准，只做研究评估。",
            "- `MFE/MAE` 观察未来 5 个交易日内最大有利/不利波动。",
            "- 样本不足的分组只作观察，不作为规则优劣结论。",
        ]
    )
    return "\n".join(lines) + "\n"


def run_reliability_backtest(config: DragonReliabilityConfig) -> dict:
    signals = load_limit_events(config)
    events = apply_profit_rule_v3_labels(apply_profit_rule_v2_labels(apply_profit_rule_labels(build_factor_events(config))))
    summary, verdict = summarize_events(events, config.min_group_samples, config.min_total_events, signal_count=len(signals))
    config.output_dir.mkdir(parents=True, exist_ok=True)
    events_path = config.output_dir / "dragon_factor_events.csv"
    summary_path = config.output_dir / "dragon_factor_summary.csv"
    report_path = config.output_dir / f"dragon_reliability_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    events.to_csv(events_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    report_path.write_text(render_markdown_report(summary, verdict), encoding="utf-8")
    return {
        "events": events,
        "signals": signals,
        "summary": summary,
        "verdict": verdict,
        "events_path": events_path,
        "summary_path": summary_path,
        "report_path": report_path,
    }


def apply_profit_rule_labels(events: pd.DataFrame) -> pd.DataFrame:
    """给龙头事件打上以未来收益验证为目标的实验标签。"""
    if events is None or events.empty:
        return events
    result = events.copy()
    result["profit_rule"] = result.apply(_profit_rule_label, axis=1)
    return result


def apply_profit_rule_v2_labels(events: pd.DataFrame) -> pd.DataFrame:
    """按已验证收益方向打第二版实验标签。"""
    if events is None or events.empty:
        return events
    result = events.copy()
    result["profit_rule_v2"] = result.apply(_profit_rule_v2_label, axis=1)
    return result


def apply_profit_rule_v3_labels(events: pd.DataFrame) -> pd.DataFrame:
    """更激进的赚钱优先实验标签，样本更少但攻击性更强。"""
    if events is None or events.empty:
        return events
    result = events.copy()
    result["profit_rule_v3"] = result.apply(_profit_rule_v3_label, axis=1)
    return result


def _profit_rule_label(row: pd.Series) -> str:
    limit_days = _safe_float(row.get("limit_days"))
    open_count = _safe_float(row.get("open_count"))
    turnover = _safe_float(row.get("turnover_rate"))
    first_time = _time_value(row.get("first_limit_time"))
    theme_state = str(row.get("theme_state") or "")
    theme_score = _safe_float(row.get("theme_score"))
    source = str(row.get("source") or "")

    if theme_score < 30 and first_time >= 1400 and (open_count >= 5 or turnover >= 20):
        return "retreat_avoid"
    if theme_state in {"轮动补涨", "退潮回避"} and theme_score < 25 and open_count >= 4:
        return "retreat_avoid"
    if 2 <= limit_days <= 4 and theme_score >= 55 and theme_state in {"主线确认", "发酵观察", "分歧中"} and open_count <= 3:
        return "core_watch"
    if limit_days >= 2 and theme_score >= 35 and 1 <= open_count <= 6 and first_time <= 1457:
        return "divergence_confirm"
    if limit_days == 1 and theme_score >= 35 and first_time <= 1000 and open_count <= 1:
        return "early_probe"
    if source == "strong_pool" and theme_score >= 35:
        return "supplement_watch"
    if first_time >= 1400 and open_count >= 4:
        return "late_risk"
    return "observe"


def _profit_rule_v2_label(row: pd.Series) -> str:
    source = str(row.get("source") or "")
    limit_days = _safe_float(row.get("limit_days"))
    turnover = _safe_float(row.get("turnover_rate"))
    open_count = _safe_float(row.get("open_count"))
    first_time = _time_value(row.get("first_limit_time"))

    if limit_days >= 4:
        return "high_board_avoid"
    if source == "strong_pool" and 3 <= turnover <= 15 and limit_days <= 3:
        return "strong_momentum"
    if source == "zt_pool" and limit_days == 1 and turnover <= 3 and first_time <= 1000:
        return "low_turnover_trap"
    if source == "zt_pool" and 2 <= limit_days <= 3 and 8 <= turnover <= 20 and open_count >= 3:
        return "zt_divergence_watch"
    if source == "zt_pool" and 8 <= turnover <= 15 and limit_days <= 3:
        return "zt_mid_turnover_watch"
    return "observe_v2"


def _profit_rule_v3_label(row: pd.Series) -> str:
    source = str(row.get("source") or "")
    limit_days = _safe_float(row.get("limit_days"))
    turnover = _safe_float(row.get("turnover_rate"))
    open_count = _safe_float(row.get("open_count"))
    theme_score = _safe_float(row.get("theme_score"))
    gap_fail = bool(row.get("gap_fail"))

    if limit_days >= 4:
        return "risk_high_board"
    if source == "zt_pool" and limit_days == 1 and turnover <= 3:
        return "trap_low_turnover"
    if source == "previous_pool" and limit_days == 2 and theme_score >= 35 and not gap_fail:
        return "aggressive_prev_second"
    if source == "zt_pool" and limit_days == 3 and theme_score >= 35:
        return "aggressive_zt_third"
    if source == "zt_pool" and limit_days == 1 and 3 <= turnover <= 8 and open_count >= 3 and not gap_fail:
        return "aggressive_first_divergence"
    if source == "strong_pool" and 8 <= turnover <= 15 and limit_days <= 3:
        return "aggressive_strong_mid_turnover"
    return "observe_v3"


def _summary_row(group_type: str, group_value: str, frame: pd.DataFrame, min_group_samples: int) -> dict:
    sample_count = int(len(frame))
    return {
        "group_type": group_type,
        "group_value": group_value,
        "sample_count": sample_count,
        "avg_ret_1d_pct": _mean(frame, "ret_1d_pct"),
        "avg_ret_3d_pct": _mean(frame, "ret_3d_pct"),
        "avg_ret_5d_pct": _mean(frame, "ret_5d_pct"),
        "median_ret_3d_pct": _median(frame, "ret_3d_pct"),
        "median_ret_5d_pct": _median(frame, "ret_5d_pct"),
        "win_1d_rate": _rate(frame, "ret_1d_pct", lambda value: value > 0),
        "win_3d_rate": _rate(frame, "ret_3d_pct", lambda value: value > 0),
        "win_5d_rate": _rate(frame, "ret_5d_pct", lambda value: value > 0),
        "avg_mfe_5d_pct": _mean(frame, "mfe_5d_pct"),
        "avg_mae_5d_pct": _mean(frame, "mae_5d_pct"),
        "next_limit_rate": _bool_rate(frame, "next_limit_up"),
        "gap_fail_rate": _bool_rate(frame, "gap_fail"),
        "sample_note": "样本不足" if sample_count < min_group_samples else "可参考",
    }


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "trade_date",
            "buy_date",
            "ts_code",
            "name",
            "industry",
            "source",
            "bucket",
            "lifecycle",
            "theme_name",
            "theme_state",
            "ret_1d_pct",
            "ret_3d_pct",
            "ret_5d_pct",
            "mfe_5d_pct",
            "mae_5d_pct",
            "next_limit_up",
            "gap_fail",
        ]
    )


def _build_verdict(summary: pd.DataFrame, events: pd.DataFrame, min_total_events: int) -> dict:
    event_count = int(len(events))
    if event_count < min_total_events:
        return {
            "rating": "样本不足",
            "reason": f"当前只有 {event_count} 条事件，低于 {min_total_events} 条最低验证门槛。",
            "event_count": event_count,
        }
    v2 = summary[summary["group_type"] == "profit_rule_v2"].set_index("group_value")
    v3 = summary[summary["group_type"] == "profit_rule_v3"].set_index("group_value")
    v3_best = max(
        value
        for value in (
            _lookup(v3, "aggressive_prev_second", "avg_ret_5d_pct"),
            _lookup(v3, "aggressive_zt_third", "avg_ret_5d_pct"),
            _lookup(v3, "aggressive_first_divergence", "avg_ret_5d_pct"),
            _lookup(v3, "aggressive_strong_mid_turnover", "avg_ret_5d_pct"),
        )
        if pd.notna(value)
    ) if not v3.empty and any(
        pd.notna(value)
        for value in (
            _lookup(v3, "aggressive_prev_second", "avg_ret_5d_pct"),
            _lookup(v3, "aggressive_zt_third", "avg_ret_5d_pct"),
            _lookup(v3, "aggressive_first_divergence", "avg_ret_5d_pct"),
            _lookup(v3, "aggressive_strong_mid_turnover", "avg_ret_5d_pct"),
        )
    ) else float("nan")
    v3_trap = min(
        value
        for value in (
            _lookup(v3, "trap_low_turnover", "avg_ret_5d_pct"),
            _lookup(v3, "risk_high_board", "avg_ret_5d_pct"),
        )
        if pd.notna(value)
    ) if not v3.empty and any(
        pd.notna(value)
        for value in (
            _lookup(v3, "trap_low_turnover", "avg_ret_5d_pct"),
            _lookup(v3, "risk_high_board", "avg_ret_5d_pct"),
        )
    ) else float("nan")
    if pd.notna(v3_best) and pd.notna(v3_trap) and v3_best - v3_trap >= 5:
        return {
            "rating": "激进新规则有效",
            "reason": "profit_rule_v3 找到更高收益的攻击型结构，同时识别出低换手/高位陷阱。",
            "event_count": event_count,
        }
    strong_5d = _lookup(v2, "strong_momentum", "avg_ret_5d_pct")
    divergence_5d = _lookup(v2, "zt_divergence_watch", "avg_ret_5d_pct")
    trap_5d = _lookup(v2, "low_turnover_trap", "avg_ret_5d_pct")
    high_board_5d = _lookup(v2, "high_board_avoid", "avg_ret_5d_pct")
    best_watch = max(value for value in (strong_5d, divergence_5d) if pd.notna(value)) if any(pd.notna(value) for value in (strong_5d, divergence_5d)) else float("nan")
    worst_risk = min(value for value in (trap_5d, high_board_5d) if pd.notna(value)) if any(pd.notna(value) for value in (trap_5d, high_board_5d)) else float("nan")
    if pd.notna(best_watch) and pd.notna(worst_risk) and best_watch - worst_risk >= 3:
        return {
            "rating": "新规则初步有效",
            "reason": "profit_rule_v2 已把赚钱候选与低收益陷阱分开，可继续做实盘排序前的研究验证。",
            "event_count": event_count,
        }
    bucket = summary[summary["group_type"] == "bucket"].set_index("group_value")
    focus_5d = _lookup(bucket, "focus", "avg_ret_5d_pct")
    avoid_5d = _lookup(bucket, "avoid", "avg_ret_5d_pct")
    focus_mae = _lookup(bucket, "focus", "avg_mae_5d_pct")
    avoid_mae = _lookup(bucket, "avoid", "avg_mae_5d_pct")
    if pd.notna(focus_5d) and pd.notna(avoid_5d) and focus_5d - avoid_5d >= 2 and avoid_mae < focus_mae:
        return {
            "rating": "可靠偏正面",
            "reason": "focus 组相对 avoid 组有收益优势，且 avoid 组不利波动更大。",
            "event_count": event_count,
        }
    if pd.notna(focus_5d) and pd.notna(avoid_5d) and focus_5d <= avoid_5d:
        return {
            "rating": "暂不可靠",
            "reason": "focus 组未来收益没有跑赢 avoid 组，当前龙头标签不宜加大权重。",
            "event_count": event_count,
        }
    return {
        "rating": "有待观察",
        "reason": "总体样本达标，但强弱分组差异还不够清晰。",
        "event_count": event_count,
    }


def _available_daily_dates(daily_dir: Path) -> list[str]:
    if not daily_dir.exists():
        return []
    return sorted(_normalize_date(path.stem) for path in daily_dir.glob("*.parquet") if _normalize_date(path.stem))


def _daily_row(cache: dict[str, pd.DataFrame], daily_dir: Path, trade_date: str, ts_code: str) -> pd.Series | None:
    if not trade_date:
        return None
    if trade_date not in cache:
        path = daily_dir / f"{trade_date}.parquet"
        if not path.exists():
            cache[trade_date] = pd.DataFrame()
        else:
            try:
                frame = pd.read_parquet(path)
            except Exception:
                frame = pd.DataFrame()
            if not frame.empty and "ts_code" in frame.columns:
                frame = frame.set_index(frame["ts_code"].astype(str), drop=False)
            cache[trade_date] = frame
    frame = cache[trade_date]
    if frame.empty or ts_code not in frame.index:
        return None
    row = frame.loc[ts_code]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    return row


def _return_from_open(buy_open: float, target_row: pd.Series | None) -> float | None:
    if target_row is None:
        return None
    close = _safe_float(target_row.get("close"))
    if buy_open <= 0 or close <= 0:
        return None
    return round((close / buy_open - 1) * 100, 4)


def _is_gap_fail(signal_row: pd.Series | None, buy_row: pd.Series) -> bool:
    prev_close = _safe_float(signal_row.get("close") if signal_row is not None else 0)
    buy_open = _safe_float(buy_row.get("open"))
    buy_close = _safe_float(buy_row.get("close"))
    if prev_close <= 0 or buy_open <= 0 or buy_close <= 0:
        return False
    return buy_open / prev_close - 1 >= 0.03 and buy_close < buy_open


def _mean(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    return round(float(series.mean()), 4) if not series.empty else None


def _median(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    return round(float(series.median()), 4) if not series.empty else None


def _rate(frame: pd.DataFrame, column: str, predicate) -> float | None:
    if column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    return round(float(series.map(predicate).mean()), 4) if not series.empty else None


def _bool_rate(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns or frame.empty:
        return None
    return round(float(frame[column].fillna(False).astype(bool).mean()), 4)


def _lookup(frame: pd.DataFrame, index_value: str, column: str) -> float:
    if frame.empty or index_value not in frame.index or column not in frame.columns:
        return float("nan")
    return _safe_float(frame.loc[index_value, column])


def _safe_float(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _time_value(value: object) -> int:
    text = str(value or "").strip().replace(":", "")
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else 9999


def _normalize_date(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).replace("-", "").strip()
    return text[:8] if len(text) >= 8 and text[:8].isdigit() else None


def _date_in_range(date: str | None, start_date: str | None, end_date: str | None) -> bool:
    if not date:
        return False
    if start_date and date < start_date:
        return False
    if end_date and date > end_date:
        return False
    return True


def _parse_horizons(value: str) -> tuple[int, ...]:
    return tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回测龙头情绪观察池标签的未来收益可靠性")
    parser.add_argument("--limit-dir", default="data_research/limit_pool")
    parser.add_argument("--daily-dir", default="data/cache/daily")
    parser.add_argument("--output-dir", default="data_research/dragon_reliability")
    parser.add_argument("--start", dest="start_date")
    parser.add_argument("--end", dest="end_date")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--min-group-samples", type=int, default=30)
    parser.add_argument("--min-total-events", type=int, default=200)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    config = DragonReliabilityConfig(
        limit_dir=Path(args.limit_dir),
        daily_dir=Path(args.daily_dir),
        output_dir=Path(args.output_dir),
        start_date=args.start_date,
        end_date=args.end_date,
        horizons=_parse_horizons(args.horizons),
        min_group_samples=args.min_group_samples,
        min_total_events=args.min_total_events,
    )
    result = run_reliability_backtest(config)
    print(f"events: {len(result['events'])} -> {result['events_path']}")
    print(f"summary: {len(result['summary'])} -> {result['summary_path']}")
    print(f"report: {result['report_path']}")
    print(f"verdict: {result['verdict'].get('rating')} - {result['verdict'].get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
