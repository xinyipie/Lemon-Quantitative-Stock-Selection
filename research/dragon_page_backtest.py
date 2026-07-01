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

from research.dragon_fast_money_experiment import (
    DragonFastMoneyConfig,
    apply_profit_rule_v4_labels,
    apply_profit_rule_v5_3d_labels,
    enrich_fast_money_events,
    load_aux_frames,
)
from research.dragon_reliability_backtest import (
    DragonReliabilityConfig,
    apply_profit_rule_v3_labels,
    build_factor_events,
)


CORE_RULES = {
    "three_day_prev_second",
    "three_day_space_lhb",
}
AGGRESSIVE_RULES = {
    "three_day_lhb_theme_buy",
    "three_day_space_base",
    "lhb_divergence_wash",
    "confirmed_hot_money",
    "lhb_confirmed",
    "crowd_confirmed",
    "sub_new_attack",
    "aggressive_base",
}
HIDDEN_RULES = {
    "three_day_gap_fail",
    "three_day_trap",
    "trap_low_turnover",
    "risk_high_board",
    "trap_avoid",
    "low_turnover_trap",
    "risk_limit_down_context",
}

RULE_PRIORITY = {
    "three_day_prev_second": 100,
    "three_day_space_lhb": 96,
    "three_day_lhb_theme_buy": 88,
    "lhb_divergence_wash": 82,
    "three_day_space_base": 78,
    "confirmed_hot_money": 76,
    "lhb_confirmed": 72,
    "crowd_confirmed": 68,
    "sub_new_attack": 64,
    "aggressive_base": 58,
    "three_day_observe": 30,
    "observe_v4": 20,
}


@dataclass
class DragonPageBacktestConfig:
    start_date: str | None = None
    end_date: str | None = None
    limit_dir: Path = Path("data_research/limit_pool")
    daily_dir: Path = Path("data/cache/daily")
    aux_dir: Path = Path("data_research/dragon_aux")
    output_dir: Path = Path("data_research/dragon_page_backtest")
    max_core: int = 3
    max_aggressive: int = 5
    max_watch: int = 8

    def __post_init__(self) -> None:
        self.limit_dir = Path(self.limit_dir)
        self.daily_dir = Path(self.daily_dir)
        self.aux_dir = Path(self.aux_dir)
        self.output_dir = Path(self.output_dir)


def run_page_backtest(config: DragonPageBacktestConfig) -> dict:
    events = build_page_candidate_events(config)
    displayed = build_page_display(events, config)
    summary = summarize_page_display(displayed)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    events_path = config.output_dir / "dragon_page_candidate_events.csv"
    display_path = config.output_dir / "dragon_page_display_events.csv"
    summary_path = config.output_dir / "dragon_page_display_summary.csv"
    report_path = config.output_dir / f"dragon_page_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    events.to_csv(events_path, index=False, encoding="utf-8-sig")
    displayed.to_csv(display_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    report_path.write_text(render_page_report(summary, displayed, config), encoding="utf-8")
    return {
        "events": events,
        "displayed": displayed,
        "summary": summary,
        "events_path": events_path,
        "display_path": display_path,
        "summary_path": summary_path,
        "report_path": report_path,
    }


def build_page_candidate_events(config: DragonPageBacktestConfig) -> pd.DataFrame:
    base = build_factor_events(
        DragonReliabilityConfig(
            limit_dir=config.limit_dir,
            daily_dir=config.daily_dir,
            start_date=config.start_date,
            end_date=config.end_date,
            min_group_samples=1,
            min_total_events=1,
        )
    )
    if base.empty:
        return base
    base = apply_profit_rule_v3_labels(base)
    fast_config = DragonFastMoneyConfig(
        start_date=config.start_date,
        end_date=config.end_date,
        limit_dir=config.limit_dir,
        daily_dir=config.daily_dir,
        aux_dir=config.aux_dir,
    )
    enriched = enrich_fast_money_events(
        base,
        lhb=load_aux_frames(fast_config.aux_dir / "lhb_detail"),
        hot=load_aux_frames(fast_config.aux_dir / "hot_rank"),
        dt_pool=load_aux_frames(fast_config.aux_dir / "dt_pool"),
        sub_new_pool=load_aux_frames(fast_config.aux_dir / "sub_new_pool"),
    )
    return apply_profit_rule_v5_3d_labels(apply_profit_rule_v4_labels(enriched))


def build_page_display(events: pd.DataFrame, config: DragonPageBacktestConfig) -> pd.DataFrame:
    if events is None or events.empty:
        return _empty_display()
    result = events.copy()
    result["page_rule"] = result.apply(_page_rule, axis=1)
    result = result[~result["page_rule"].isin(HIDDEN_RULES)].copy()
    result["display_group"] = result["page_rule"].map(_display_group)
    result = result[result["display_group"] != "hidden"].copy()
    if result.empty:
        return _empty_display()
    result["rule_priority"] = result["page_rule"].map(lambda value: RULE_PRIORITY.get(str(value), 0))
    result["display_score"] = result.apply(_display_score, axis=1)
    result = (
        result.sort_values(["trade_date", "ts_code", "rule_priority", "display_score"], ascending=[True, True, False, False])
        .drop_duplicates(["trade_date", "ts_code"], keep="first")
        .copy()
    )
    frames = []
    limits = {
        "core_attack": config.max_core,
        "aggressive": config.max_aggressive,
        "watch": config.max_watch,
    }
    for trade_date, day_frame in result.groupby("trade_date", sort=True):
        for group, limit in limits.items():
            selected = (
                day_frame[day_frame["display_group"] == group]
                .sort_values(["rule_priority", "display_score", "dragon_score", "ts_code"], ascending=[False, False, False, True])
                .head(limit)
                .copy()
            )
            if selected.empty:
                continue
            selected["display_rank"] = range(1, len(selected) + 1)
            frames.append(selected)
    if not frames:
        return _empty_display()
    displayed = pd.concat(frames, ignore_index=True)
    columns = [
        "trade_date",
        "buy_date",
        "display_group",
        "display_rank",
        "ts_code",
        "name",
        "page_rule",
        "profit_rule_v5_3d",
        "profit_rule_v4",
        "profit_rule_v3",
        "source",
        "limit_days",
        "turnover_rate",
        "open_count",
        "first_limit_time",
        "theme_name",
        "theme_state",
        "theme_score",
        "dragon_score",
        "lhb_net_buy",
        "lhb_turnover",
        "lhb_reason",
        "is_sub_new",
        "display_score",
        "ret_1d_pct",
        "ret_3d_pct",
        "ret_5d_pct",
        "mfe_5d_pct",
        "mae_5d_pct",
        "next_limit_up",
        "gap_fail",
    ]
    for column in columns:
        if column not in displayed.columns:
            displayed[column] = "" if column.endswith("reason") else 0
    return displayed[columns].sort_values(["trade_date", "display_group", "display_rank"]).reset_index(drop=True)


def summarize_page_display(displayed: pd.DataFrame) -> pd.DataFrame:
    if displayed is None or displayed.empty:
        return pd.DataFrame(
            columns=[
                "group_type",
                "group_value",
                "sample_count",
                "avg_ret_3d_pct",
                "median_ret_3d_pct",
                "win_3d_rate",
            ]
        )
    rows = [_summary_row("all", "页面展示全样本", displayed)]
    for column in ("display_group", "page_rule"):
        for value, frame in displayed.groupby(column, dropna=False):
            rows.append(_summary_row(column, str(value or "未分组"), frame))
    top1 = displayed[displayed["display_rank"] == 1]
    if not top1.empty:
        for value, frame in top1.groupby("display_group", dropna=False):
            rows.append(_summary_row("display_group_top1", str(value or "未分组"), frame))
    return pd.DataFrame(rows)


def render_page_report(summary: pd.DataFrame, displayed: pd.DataFrame, config: DragonPageBacktestConfig) -> str:
    lines = [
        "# 龙头页面展示回测",
        "",
        f"- 日期范围：{config.start_date or '全部'} ~ {config.end_date or '全部'}",
        f"- 页面展示样本：{len(displayed)}",
        "- 口径：T 日生成页面候选，T+1 开盘为买入基准，T+3 收盘计算 3 日收益。",
        "- 排序：只使用 T 日可见字段；`ret_*` 只用于事后评估。",
        "- 强制回避：高开回落、低换手首板陷阱、高位/跌停环境等风险票不进入展示。",
        "",
        "## 展示分组效果",
        "",
    ]
    if summary.empty:
        lines.append("暂无可评估的页面展示样本。")
        return "\n".join(lines) + "\n"
    columns = [
        "group_type",
        "group_value",
        "sample_count",
        "avg_ret_1d_pct",
        "avg_ret_3d_pct",
        "median_ret_3d_pct",
        "win_3d_rate",
        "avg_mfe_5d_pct",
        "avg_mae_5d_pct",
        "next_limit_rate",
        "gap_fail_rate",
    ]
    lines.append(summary[[column for column in columns if column in summary.columns]].to_markdown(index=False))
    return "\n".join(lines) + "\n"


def _page_rule(row: pd.Series) -> str:
    v5 = str(row.get("profit_rule_v5_3d") or "")
    v4 = str(row.get("profit_rule_v4") or "")
    v3 = str(row.get("profit_rule_v3") or "")
    if v5 in HIDDEN_RULES or v4 in HIDDEN_RULES or v3 in HIDDEN_RULES:
        return v5 if v5 in HIDDEN_RULES else v4 if v4 in HIDDEN_RULES else v3
    if v5 in CORE_RULES or v5 in AGGRESSIVE_RULES:
        return v5
    if v4 in AGGRESSIVE_RULES:
        return v4
    return v5 or v4 or v3 or "observe"


def _display_group(rule: object) -> str:
    value = str(rule or "")
    if value in HIDDEN_RULES:
        return "hidden"
    if value in CORE_RULES:
        return "core_attack"
    if value in AGGRESSIVE_RULES:
        return "aggressive"
    return "watch"


def _display_score(row: pd.Series) -> float:
    turnover = _safe_float(row.get("turnover_rate"))
    turnover_bonus = max(0.0, 20.0 - abs(turnover - 7.0) * 2.0)
    limit_days = _safe_float(row.get("limit_days"))
    limit_bonus = 12.0 if limit_days in (2.0, 3.0) else 0.0
    lhb_net_buy = _safe_float(row.get("lhb_net_buy"))
    lhb_bonus = min(max(lhb_net_buy / 5_000_000, -5.0), 8.0)
    return round(
        _safe_float(row.get("theme_score"))
        + _safe_float(row.get("dragon_score")) * 0.2
        + turnover_bonus
        + limit_bonus
        + lhb_bonus
        - _safe_float(row.get("open_count")) * 1.5,
        4,
    )


def _summary_row(group_type: str, group_value: str, frame: pd.DataFrame) -> dict:
    return {
        "group_type": group_type,
        "group_value": group_value,
        "sample_count": int(len(frame)),
        "avg_ret_1d_pct": _mean(frame, "ret_1d_pct"),
        "avg_ret_3d_pct": _mean(frame, "ret_3d_pct"),
        "median_ret_3d_pct": _median(frame, "ret_3d_pct"),
        "win_3d_rate": _rate(frame, "ret_3d_pct", lambda value: value > 0),
        "avg_mfe_5d_pct": _mean(frame, "mfe_5d_pct"),
        "avg_mae_5d_pct": _mean(frame, "mae_5d_pct"),
        "next_limit_rate": _bool_rate(frame, "next_limit_up"),
        "gap_fail_rate": _bool_rate(frame, "gap_fail"),
    }


def _mean(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return round(float(values.mean()), 4) if not values.empty else None


def _median(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return round(float(values.median()), 4) if not values.empty else None


def _rate(frame: pd.DataFrame, column: str, predicate) -> float | None:
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return round(float(values.map(predicate).mean()), 4) if not values.empty else None


def _bool_rate(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns or frame.empty:
        return None
    return round(float(frame[column].astype(bool).mean()), 4)


def _safe_float(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _empty_display() -> pd.DataFrame:
    return pd.DataFrame()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回测龙头页面当日展示清单的 3 日赚钱能力。")
    parser.add_argument("--start", dest="start_date")
    parser.add_argument("--end", dest="end_date")
    parser.add_argument("--limit-dir", default="data_research/limit_pool")
    parser.add_argument("--daily-dir", default="data/cache/daily")
    parser.add_argument("--aux-dir", default="data_research/dragon_aux")
    parser.add_argument("--output-dir", default="data_research/dragon_page_backtest")
    parser.add_argument("--max-core", type=int, default=3)
    parser.add_argument("--max-aggressive", type=int, default=5)
    parser.add_argument("--max-watch", type=int, default=8)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_page_backtest(
        DragonPageBacktestConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            limit_dir=Path(args.limit_dir),
            daily_dir=Path(args.daily_dir),
            aux_dir=Path(args.aux_dir),
            output_dir=Path(args.output_dir),
            max_core=args.max_core,
            max_aggressive=args.max_aggressive,
            max_watch=args.max_watch,
        )
    )
    print(f"candidate events: {len(result['events'])} -> {result['events_path']}")
    print(f"display events: {len(result['displayed'])} -> {result['display_path']}")
    print(f"summary: {len(result['summary'])} -> {result['summary_path']}")
    print(f"report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
