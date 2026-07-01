"""龙头快钱实验：把龙虎榜、人气、风险池接入龙头事件。"""

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

from research.dragon_reliability_backtest import (
    DragonReliabilityConfig,
    apply_profit_rule_v3_labels,
    build_factor_events,
    render_markdown_report,
    summarize_events,
)


@dataclass
class DragonFastMoneyConfig:
    start_date: str | None = None
    end_date: str | None = None
    limit_dir: Path = Path("data_research/limit_pool")
    daily_dir: Path = Path("data/cache/daily")
    aux_dir: Path = Path("data_research/dragon_aux")
    output_dir: Path = Path("data_research/dragon_fast_money")
    min_group_samples: int = 20
    min_total_events: int = 100

    def __post_init__(self) -> None:
        self.limit_dir = Path(self.limit_dir)
        self.daily_dir = Path(self.daily_dir)
        self.aux_dir = Path(self.aux_dir)
        self.output_dir = Path(self.output_dir)


def run_fast_money_experiment(config: DragonFastMoneyConfig) -> dict:
    base = build_factor_events(
        DragonReliabilityConfig(
            limit_dir=config.limit_dir,
            daily_dir=config.daily_dir,
            start_date=config.start_date,
            end_date=config.end_date,
            min_group_samples=config.min_group_samples,
            min_total_events=config.min_total_events,
        )
    )
    base = apply_profit_rule_v3_labels(base)
    enriched = enrich_fast_money_events(
        base,
        lhb=load_aux_frames(config.aux_dir / "lhb_detail"),
        hot=load_aux_frames(config.aux_dir / "hot_rank"),
        dt_pool=load_aux_frames(config.aux_dir / "dt_pool"),
        sub_new_pool=load_aux_frames(config.aux_dir / "sub_new_pool"),
    )
    enriched = apply_profit_rule_v5_3d_labels(apply_profit_rule_v4_labels(enriched))
    summary, verdict = summarize_events(enriched, config.min_group_samples, config.min_total_events)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    events_path = config.output_dir / "dragon_fast_money_events.csv"
    summary_path = config.output_dir / "dragon_fast_money_summary.csv"
    report_path = config.output_dir / f"dragon_fast_money_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    enriched.to_csv(events_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    report_path.write_text(render_markdown_report(summary, verdict), encoding="utf-8")
    return {
        "events": enriched,
        "summary": summary,
        "verdict": verdict,
        "events_path": events_path,
        "summary_path": summary_path,
        "report_path": report_path,
    }


def enrich_fast_money_events(
    events: pd.DataFrame,
    lhb: pd.DataFrame | None = None,
    hot: pd.DataFrame | None = None,
    dt_pool: pd.DataFrame | None = None,
    sub_new_pool: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if events is None or events.empty:
        return events
    result = events.copy()
    for column in ("trade_date", "ts_code"):
        result[column] = result[column].astype(str)
    result = _merge_lhb(result, lhb)
    result = _merge_hot(result, hot)
    result["is_dt_pool"] = _membership(result, dt_pool)
    result["is_sub_new"] = _membership(result, sub_new_pool)
    for column, default in {
        "lhb_net_buy": 0.0,
        "lhb_buy_amount": 0.0,
        "lhb_sell_amount": 0.0,
        "lhb_turnover": 0.0,
        "hot_rank": 9999.0,
        "new_fans_ratio": 0.0,
        "loyal_fans_ratio": 0.0,
    }.items():
        if column not in result.columns:
            result[column] = default
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(default)
    if "lhb_reason" not in result.columns:
        result["lhb_reason"] = ""
    result["has_lhb"] = result["lhb_turnover"] > 0
    result["lhb_net_buy_ratio"] = result["lhb_net_buy"] / result["lhb_turnover"].replace(0, pd.NA)
    result["lhb_net_buy_ratio"] = pd.to_numeric(result["lhb_net_buy_ratio"], errors="coerce").fillna(0)
    return result


def apply_profit_rule_v4_labels(events: pd.DataFrame) -> pd.DataFrame:
    if events is None or events.empty:
        return events
    result = events.copy()
    result["profit_rule_v4"] = result.apply(_profit_rule_v4_label, axis=1)
    return result


def apply_profit_rule_v5_3d_labels(events: pd.DataFrame) -> pd.DataFrame:
    if events is None or events.empty:
        return events
    result = events.copy()
    result["profit_rule_v5_3d"] = result.apply(_profit_rule_v5_3d_label, axis=1)
    return result


def load_aux_frames(directory: str | Path) -> pd.DataFrame:
    path = Path(directory)
    if not path.exists():
        return pd.DataFrame()
    frames = []
    for file in sorted(path.glob("*.parquet")):
        try:
            frame = pd.read_parquet(file)
        except Exception:
            continue
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _merge_lhb(events: pd.DataFrame, lhb: pd.DataFrame | None) -> pd.DataFrame:
    if lhb is None or lhb.empty:
        return events
    keys = ["trade_date", "ts_code"]
    keep = keys + [column for column in ["lhb_net_buy", "lhb_buy_amount", "lhb_sell_amount", "lhb_turnover", "lhb_reason"] if column in lhb.columns]
    lhb_work = lhb[keep].copy()
    lhb_work["trade_date"] = lhb_work["trade_date"].astype(str)
    lhb_work["ts_code"] = lhb_work["ts_code"].astype(str)
    lhb_work = lhb_work.sort_values("lhb_net_buy", ascending=False).drop_duplicates(keys)
    return events.merge(lhb_work, on=keys, how="left")


def _merge_hot(events: pd.DataFrame, hot: pd.DataFrame | None) -> pd.DataFrame:
    if hot is None or hot.empty:
        return events
    keys = ["trade_date", "ts_code"]
    keep = keys + [column for column in ["hot_rank", "new_fans_ratio", "loyal_fans_ratio"] if column in hot.columns]
    hot_work = hot[keep].copy()
    hot_work["trade_date"] = hot_work["trade_date"].astype(str)
    hot_work["ts_code"] = hot_work["ts_code"].astype(str)
    hot_work = hot_work.sort_values("hot_rank").drop_duplicates(keys)
    return events.merge(hot_work, on=keys, how="left")


def _membership(events: pd.DataFrame, frame: pd.DataFrame | None) -> pd.Series:
    if frame is None or frame.empty or "trade_date" not in frame.columns or "ts_code" not in frame.columns:
        return pd.Series([False] * len(events), index=events.index)
    pairs = set(zip(frame["trade_date"].astype(str), frame["ts_code"].astype(str)))
    return events.apply(lambda row: (str(row["trade_date"]), str(row["ts_code"])) in pairs, axis=1)


def _profit_rule_v4_label(row: pd.Series) -> str:
    v3 = str(row.get("profit_rule_v3") or "")
    lhb_net_buy = _safe_float(row.get("lhb_net_buy"))
    hot_rank = _safe_float(row.get("hot_rank"))
    is_dt_pool = bool(row.get("is_dt_pool"))
    is_sub_new = bool(row.get("is_sub_new"))
    aggressive = {
        "aggressive_prev_second",
        "aggressive_zt_third",
        "aggressive_first_divergence",
        "aggressive_strong_mid_turnover",
    }
    if is_dt_pool:
        return "risk_limit_down_context"
    if v3 in {"trap_low_turnover", "risk_high_board"}:
        return "trap_avoid"
    if v3 in aggressive and lhb_net_buy < 0:
        return "lhb_divergence_wash"
    if v3 in aggressive and lhb_net_buy >= 5_000_000 and hot_rank <= 300:
        return "confirmed_hot_money"
    if v3 in aggressive and hot_rank <= 200:
        return "crowd_confirmed"
    if v3 in aggressive and lhb_net_buy >= 5_000_000:
        return "lhb_confirmed"
    if v3 in aggressive and is_sub_new:
        return "sub_new_attack"
    if v3 in aggressive:
        return "aggressive_base"
    return "observe_v4"


def _profit_rule_v5_3d_label(row: pd.Series) -> str:
    source = str(row.get("source") or "")
    limit_days = _safe_float(row.get("limit_days"))
    theme_score = _safe_float(row.get("theme_score"))
    turnover = _safe_float(row.get("turnover_rate"))
    lhb_turnover = _safe_float(row.get("lhb_turnover"))
    lhb_net_buy = _safe_float(row.get("lhb_net_buy"))
    gap_fail = bool(row.get("gap_fail"))
    if gap_fail:
        return "three_day_gap_fail"
    if source == "zt_pool" and limit_days == 1 and turnover <= 3:
        return "three_day_trap"
    if source == "zt_pool" and limit_days == 3 and theme_score >= 35 and lhb_turnover > 0:
        return "three_day_space_lhb"
    if source == "previous_pool" and limit_days == 2 and theme_score >= 35:
        return "three_day_prev_second"
    if 3 <= turnover <= 8 and theme_score >= 55 and lhb_net_buy >= 5_000_000:
        return "three_day_lhb_theme_buy"
    if source == "zt_pool" and limit_days == 3 and theme_score >= 35:
        return "three_day_space_base"
    return "three_day_observe"


def _safe_float(value: object) -> float:
    try:
        if pd.isna(value):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行龙头快钱 v4 实验。")
    parser.add_argument("--start", dest="start_date")
    parser.add_argument("--end", dest="end_date")
    parser.add_argument("--limit-dir", default="data_research/limit_pool")
    parser.add_argument("--daily-dir", default="data/cache/daily")
    parser.add_argument("--aux-dir", default="data_research/dragon_aux")
    parser.add_argument("--output-dir", default="data_research/dragon_fast_money")
    parser.add_argument("--min-group-samples", type=int, default=20)
    parser.add_argument("--min-total-events", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_fast_money_experiment(
        DragonFastMoneyConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            limit_dir=Path(args.limit_dir),
            daily_dir=Path(args.daily_dir),
            aux_dir=Path(args.aux_dir),
            output_dir=Path(args.output_dir),
            min_group_samples=args.min_group_samples,
            min_total_events=args.min_total_events,
        )
    )
    print(f"events: {len(result['events'])} -> {result['events_path']}")
    print(f"summary: {len(result['summary'])} -> {result['summary_path']}")
    print(f"report: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
