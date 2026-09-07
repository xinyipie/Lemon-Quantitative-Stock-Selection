"""冻结机会画像的退出规则归因研究。

同一批候选同时运行固定3/5/8日、当前风控和机械式波动率自适应退出。
退出选择只看训练期，验证期用于准入，已反复观察的2025至2026数据仅标记为observed。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import all_market_multi_engine_research as market_research
from research.all_market_opportunity_archetypes import assign_feature_bins
from research.opportunity_archetype_exit_backtest import (
    FROZEN_PROFILES,
    _load_bar_map,
    simulate_five_day_exit,
)
from research.opportunity_archetype_ranking_research import select_ranked_candidates


REPORT_DATE = "20260807"
REPORT_DIR = ROOT / "reports" / "research"
DEFAULT_REPORT = REPORT_DIR / f"opportunity_exit_attribution_{REPORT_DATE}.md"
DEFAULT_TRADES = REPORT_DIR / f"opportunity_exit_attribution_trades_{REPORT_DATE}.csv"
DEFAULT_METRICS = REPORT_DIR / f"opportunity_exit_attribution_metrics_{REPORT_DATE}.csv"
DEFAULT_CHOSEN = REPORT_DIR / f"opportunity_exit_attribution_chosen_{REPORT_DATE}.csv"

SPLITS = {
    "train": ("20160101", "20211231"),
    "validation": ("20220101", "20241231"),
    "observed": ("20250101", "20260630"),
}

AMOUNT_RANK = [{"factor": "amount", "label": "成交额", "column": "amount", "directions": ["high"]}]


def simulate_fixed_holding(
    entry_price: float,
    bars: pd.DataFrame,
    hold_days: int,
    total_cost_pct: float = 0.30,
) -> dict:
    """按指定交易日收盘退出，完整记录持有期高低点。"""
    if entry_price <= 0 or len(bars) < hold_days:
        return {}
    work = bars.sort_values("trade_date").head(hold_days).copy()
    for column in ("open", "high", "low", "close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    if work[["open", "high", "low", "close"]].isna().any().any():
        return {}
    exit_row = work.iloc[-1]
    exit_price = float(exit_row["close"])
    gross_ret = (exit_price / entry_price - 1) * 100
    return {
        "exit_date": str(exit_row["trade_date"]),
        "exit_price": round(exit_price, 4),
        "exit_reason": f"fixed_{hold_days}d",
        "hold_days": int(hold_days),
        "gross_ret_pct": round(gross_ret, 4),
        "net_ret_pct": round(gross_ret - total_cost_pct, 4),
        "mfe_pct": round((float(work["high"].max()) / entry_price - 1) * 100, 4),
        "mae_pct": round((float(work["low"].min()) / entry_price - 1) * 100, 4),
    }


def adaptive_exit_parameters(volatility_20: float) -> dict:
    """从已知20日波动率机械生成退出参数，不搜索历史最优值。"""
    volatility = float(volatility_20) if np.isfinite(volatility_20) else 5.0
    stop = float(np.clip(volatility * 1.5, 7.0, 14.0))
    return {
        "stop_loss_pct": round(stop, 4),
        "take_profit_pct": round(min(25.0, stop * 2), 4),
        "trailing_activate_pct": round(max(3.0, stop / 2), 4),
        "trailing_drawdown_pct": round(stop, 4),
        "max_hold_days": 8,
    }


def simulate_risk_exit(
    entry_price: float,
    bars: pd.DataFrame,
    stop_loss_pct: float,
    take_profit_pct: float,
    trailing_activate_pct: float,
    trailing_drawdown_pct: float,
    max_hold_days: int,
    total_cost_pct: float = 0.30,
) -> dict:
    """使用保守盘中顺序模拟可配置风控退出。"""
    if entry_price <= 0 or len(bars) < max_hold_days:
        return {}
    work = bars.sort_values("trade_date").head(max_hold_days).copy()
    for column in ("open", "high", "low", "close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    if work[["open", "high", "low", "close"]].isna().any().any():
        return {}

    fixed_stop = entry_price * (1 - stop_loss_pct / 100)
    take_profit = entry_price * (1 + take_profit_pct / 100)
    previous_peak = entry_price
    observed_high = entry_price
    observed_low = entry_price
    exit_price = None
    exit_date = None
    exit_reason = None
    hold_days = 0

    for day_number, row in enumerate(work.itertuples(index=False), start=1):
        day_open = float(row.open)
        day_high = float(row.high)
        day_low = float(row.low)
        day_close = float(row.close)
        hold_days = day_number
        observed_high = max(observed_high, day_high)
        observed_low = min(observed_low, day_low)
        trailing_active = previous_peak >= entry_price * (1 + trailing_activate_pct / 100)
        trailing_stop = previous_peak * (1 - trailing_drawdown_pct / 100) if trailing_active else -np.inf
        effective_stop = max(fixed_stop, trailing_stop)

        if day_open <= effective_stop:
            exit_price = day_open
            exit_reason = "trailing_stop" if trailing_stop >= fixed_stop else "fixed_stop"
        elif day_open >= take_profit:
            exit_price = day_open
            exit_reason = "take_profit"
        elif day_low <= effective_stop:
            exit_price = effective_stop
            exit_reason = "trailing_stop" if trailing_stop >= fixed_stop else "fixed_stop"
        elif day_high >= take_profit:
            exit_price = take_profit
            exit_reason = "take_profit"
        elif day_number == max_hold_days:
            exit_price = day_close
            exit_reason = "max_hold"

        if exit_price is not None:
            exit_date = str(row.trade_date)
            break
        previous_peak = max(previous_peak, day_high)

    gross_ret = (float(exit_price) / entry_price - 1) * 100
    return {
        "exit_date": exit_date,
        "exit_price": round(float(exit_price), 4),
        "exit_reason": exit_reason,
        "hold_days": int(hold_days),
        "gross_ret_pct": round(gross_ret, 4),
        "net_ret_pct": round(gross_ret - total_cost_pct, 4),
        "mfe_pct": round((observed_high / entry_price - 1) * 100, 4),
        "mae_pct": round((observed_low / entry_price - 1) * 100, 4),
    }


def _future_dates(signal_date: str, all_dates: list[str], positions: dict[str, int], count: int = 8) -> list[str]:
    position = positions.get(str(signal_date))
    if position is None:
        return []
    return all_dates[position + 1 : position + 1 + count]


def _split_label(date: str) -> str:
    if date <= SPLITS["train"][1]:
        return "train"
    if date <= SPLITS["validation"][1]:
        return "validation"
    return "observed"


def _simulate_candidates(
    candidates: pd.DataFrame,
    cache_dir: Path,
    all_dates: list[str],
    positions: dict[str, int],
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    needed_dates = set()
    for date in candidates["trade_date"].astype(str).unique():
        needed_dates.update(_future_dates(date, all_dates, positions, 8))
    codes = set(candidates["ts_code"].astype(str))
    bar_map = _load_bar_map(cache_dir, needed_dates, codes)
    path_cache = {}
    rows = []

    for candidate in candidates.itertuples(index=False):
        signal_date = str(candidate.trade_date)
        code = str(candidate.ts_code)
        dates = _future_dates(signal_date, all_dates, positions, 8)
        if len(dates) < 8:
            continue
        bars_data = [bar_map.get((code, date)) for date in dates]
        if any(item is None for item in bars_data):
            continue
        bars = pd.DataFrame(bars_data)
        entry_price = float(bars.iloc[0]["open"])
        volatility = float(candidate.volatility_20)
        cache_key = (code, signal_date, round(volatility, 6))
        if cache_key not in path_cache:
            adaptive = adaptive_exit_parameters(volatility)
            path_cache[cache_key] = {
                "fixed_3d": simulate_fixed_holding(entry_price, bars, 3),
                "fixed_5d": simulate_fixed_holding(entry_price, bars, 5),
                "fixed_8d": simulate_fixed_holding(entry_price, bars, 8),
                "current_risk": simulate_five_day_exit(entry_price, bars.head(5)),
                "adaptive": simulate_risk_exit(entry_price, bars, **adaptive),
            }
        for exit_id, result in path_cache[cache_key].items():
            if not result:
                continue
            rows.append(
                {
                    "profile_id": candidate.profile_id,
                    "profile_description": candidate.profile_description,
                    "signal_date": signal_date,
                    "entry_date": dates[0],
                    "ts_code": code,
                    "name": getattr(candidate, "name", ""),
                    "industry": getattr(candidate, "industry", ""),
                    "volatility_20": volatility,
                    "exit_id": exit_id,
                    "split": _split_label(signal_date),
                    "year": signal_date[:4],
                    **result,
                }
            )
    return pd.DataFrame(rows)


def _profit_factor(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    gains = numeric[numeric > 0].sum()
    losses = abs(numeric[numeric < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def summarize_exits(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in trades.groupby(["profile_id", "profile_description", "exit_id", "split"], sort=False):
        profile_id, description, exit_id, split = keys
        returns = pd.to_numeric(group["net_ret_pct"], errors="coerce").dropna()
        yearly = group.groupby("year")["net_ret_pct"].mean()
        rows.append(
            {
                "profile_id": profile_id,
                "profile_description": description,
                "exit_id": exit_id,
                "split": split,
                "trades": int(len(group)),
                "active_days": int(group["signal_date"].nunique()),
                "avg_net_ret_pct": round(float(returns.mean()), 4),
                "median_net_ret_pct": round(float(returns.median()), 4),
                "win_rate": round(float((returns > 0).mean()), 4),
                "profit_factor": round(_profit_factor(returns), 4),
                "avg_mfe_pct": round(float(group["mfe_pct"].mean()), 4),
                "avg_mae_pct": round(float(group["mae_pct"].mean()), 4),
                "avg_hold_days": round(float(group["hold_days"].mean()), 2),
                "stop_rate": round(float(group["exit_reason"].isin(["fixed_stop", "trailing_stop"]).mean()), 4),
                "take_profit_rate": round(float(group["exit_reason"].eq("take_profit").mean()), 4),
                "positive_year_ratio": round(float((yearly > 0).mean()), 4),
                "worst_year_avg_pct": round(float(yearly.min()), 4),
            }
        )
    return pd.DataFrame(rows)


def choose_training_exit(metrics: pd.DataFrame) -> pd.DataFrame:
    """每个画像只按训练期平均净收益和盈亏比确定一个退出方式。"""
    if metrics.empty:
        return metrics.copy()
    train = metrics[metrics["split"].eq("train")].sort_values(
        ["profile_id", "avg_net_ret_pct", "profit_factor", "exit_id"],
        ascending=[True, False, False, True],
    )
    choices = train.groupby("profile_id", group_keys=False).head(1)
    keys = set(zip(choices["profile_id"], choices["exit_id"]))
    chosen = metrics[
        metrics.apply(lambda row: (row["profile_id"], row["exit_id"]) in keys, axis=1)
    ].copy()

    pass_map = {}
    for profile_id, group in chosen.groupby("profile_id", sort=False):
        by_split = {row.split: row for row in group.itertuples(index=False)}
        train_row = by_split.get("train")
        validation = by_split.get("validation")

        def value(row, name, default=0):
            return getattr(row, name, default) if row is not None else default

        pass_map[profile_id] = bool(
            train_row and validation
            and value(train_row, "trades") >= 300
            and value(validation, "trades") >= 150
            and value(validation, "avg_net_ret_pct") > 0.20
            and value(validation, "profit_factor") > 1.05
            and value(validation, "positive_year_ratio") >= 2 / 3
            and value(validation, "worst_year_avg_pct") > -1.0
        )
    chosen["research_pass"] = chosen["profile_id"].map(pass_map).fillna(False).astype(bool)
    return chosen


def run_research(start: str, end: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_dates = market_research._available_dates(cache_dir, "19900101", end)
    positions = {date: index for index, date in enumerate(all_dates)}
    stock_info = market_research._load_stock_info(cache_dir)
    regimes = market_research._build_regimes(cache_dir, all_dates)
    trade_frames = []

    for year in range(int(start[:4]), int(end[:4]) + 1):
        print(f"processing {year}", flush=True)
        panel = market_research.build_year_panel(
            cache_dir,
            stock_info,
            regimes,
            all_dates,
            year,
            start,
            end,
        )
        if panel.empty:
            continue
        panel = assign_feature_bins(panel)
        candidates = select_ranked_candidates(panel, FROZEN_PROFILES, AMOUNT_RANK, top_n=3)
        candidates = candidates[pd.to_numeric(candidates.get("ret_8d"), errors="coerce").notna()]
        trades = _simulate_candidates(candidates, cache_dir, all_dates, positions)
        if not trades.empty:
            trade_frames.append(trades)
        del panel, candidates

    all_trades = pd.concat(trade_frames, ignore_index=True, sort=False) if trade_frames else pd.DataFrame()
    metrics = summarize_exits(all_trades)
    chosen = choose_training_exit(metrics)
    return all_trades, metrics, chosen


def _pct(value: float, ratio: bool = False) -> str:
    number = float(value) * 100 if ratio else float(value)
    return f"{number:+.2f}%"


def write_report(metrics: pd.DataFrame, chosen: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    passed = chosen[chosen["research_pass"]]["profile_id"].nunique() if not chosen.empty else 0
    lines = [
        "# 冻结机会画像退出规则归因",
        "",
        "## 边界",
        "",
        "- 同一候选同时运行固定3/5/8日、当前风控与机械式波动率自适应退出。",
        "- 每笔扣除0.30%交易摩擦；盘中止损和止盈同时可能触发时按止损优先。",
        "- 退出方式只由2016至2021训练期选择，2022至2024验证。",
        "- 2025至2026已被反复观察，只作observed展示，不参与准入。",
        "",
        "## 训练期选择结果",
        "",
        f"- 画像数：`{chosen['profile_id'].nunique() if not chosen.empty else 0}`。",
        f"- 通过验证期退出门槛：`{passed}`。",
        "",
        "| 画像 | 训练期选定退出 | 阶段 | 交易 | 均收益 | 胜率 | 盈亏比 | 持有日 | 止损率 | 最差年度 | 结论 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in chosen.sort_values(["research_pass", "profile_id", "split"], ascending=[False, True, True]).itertuples(index=False):
        lines.append(
            f"| {row.profile_description} | {row.exit_id} | {row.split} | {row.trades} | "
            f"{_pct(row.avg_net_ret_pct)} | {_pct(row.win_rate, ratio=True)} | {row.profit_factor:.2f} | "
            f"{row.avg_hold_days:.2f} | {_pct(row.stop_rate, ratio=True)} | {_pct(row.worst_year_avg_pct)} | "
            f"{'通过' if row.research_pass else '观察'} |"
        )
    lines.extend(["", "## 全退出方式验证期对照", ""])
    validation = metrics[metrics["split"].eq("validation")].sort_values(
        ["profile_id", "avg_net_ret_pct"], ascending=[True, False]
    )
    for profile_id, group in validation.groupby("profile_id", sort=False):
        description = group.iloc[0]["profile_description"]
        lines.append(f"- `{description}`：" + "；".join(
            f"{row.exit_id} {_pct(row.avg_net_ret_pct)} / PF {row.profit_factor:.2f}"
            for row in group.itertuples(index=False)
        ))
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="冻结机会画像退出规则归因研究。")
    parser.add_argument("--start", default="20160101")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "cache")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trades, metrics, chosen = run_research(args.start, args.end, args.cache_dir)
    if trades.empty:
        raise SystemExit("没有生成退出归因交易")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    trades.to_csv(DEFAULT_TRADES, index=False, encoding="utf-8-sig")
    metrics.to_csv(DEFAULT_METRICS, index=False, encoding="utf-8-sig")
    chosen.to_csv(DEFAULT_CHOSEN, index=False, encoding="utf-8-sig")
    write_report(metrics, chosen, DEFAULT_REPORT)
    print("\nCHOSEN")
    print(chosen.to_string(index=False))
    print(f"trades={len(trades)} passed={chosen[chosen['research_pass']]['profile_id'].nunique()}")
    print(f"report={DEFAULT_REPORT}")
    print(f"metrics_csv={DEFAULT_METRICS}")
    print(f"chosen_csv={DEFAULT_CHOSEN}")


if __name__ == "__main__":
    main()
