"""冻结机会画像的真实OHLC退出回测。

画像和阈值来自独立训练/验证/封存研究，本脚本不再搜索参数。
候选只按信号日成交额排序，未来行情仅用于成交与退出模拟。
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


REPORT_DATE = "20260807"
REPORT_DIR = ROOT / "reports" / "research"
DEFAULT_REPORT = REPORT_DIR / f"opportunity_archetype_exit_backtest_{REPORT_DATE}.md"
DEFAULT_TRADES = REPORT_DIR / f"opportunity_archetype_exit_trades_{REPORT_DATE}.csv"
DEFAULT_SUMMARY = REPORT_DIR / f"opportunity_archetype_exit_summary_{REPORT_DATE}.csv"

FROZEN_PROFILES = [
    {
        "profile_id": "volatility_6_5_9",
        "description": "20日波动率6.5~9",
        "conditions": [("volatility_20_bin", "6.5~9")],
    },
    {
        "profile_id": "daily_gain_gt7",
        "description": "当日涨幅>7%",
        "conditions": [("pct_chg_bin", ">7%")],
    },
    {
        "profile_id": "momentum20_gt25",
        "description": "近20日涨幅>25%",
        "conditions": [("ret_20_bin", ">25%")],
    },
    {
        "profile_id": "daily_gain_gt7_volatility",
        "description": "当日涨幅>7%且20日波动率6.5~9",
        "conditions": [("pct_chg_bin", ">7%"), ("volatility_20_bin", "6.5~9")],
    },
    {
        "profile_id": "momentum20_gt25_volatility",
        "description": "近20日涨幅>25%且20日波动率6.5~9",
        "conditions": [("ret_20_bin", ">25%"), ("volatility_20_bin", "6.5~9")],
    },
]

SPLITS = {
    "train": ("20160101", "20211231"),
    "validation": ("20220101", "20241231"),
    "sealed": ("20250101", "20260630"),
}


def _profile_mask(panel: pd.DataFrame, conditions: list[tuple[str, str]]) -> pd.Series:
    mask = pd.Series(True, index=panel.index)
    for column, value in conditions:
        if column not in panel.columns:
            return pd.Series(False, index=panel.index)
        mask &= panel[column].astype(str).eq(str(value))
    return mask


def select_profile_candidates(
    panel: pd.DataFrame,
    profiles: list[dict] = FROZEN_PROFILES,
    top_n: int = 3,
) -> pd.DataFrame:
    """按信号日成交额选择画像中流动性最好的候选，不使用未来收益排名。"""
    if panel.empty:
        return pd.DataFrame()
    names = panel.get("name", pd.Series("", index=panel.index)).fillna("").astype(str)
    eligible = (
        ~names.str.upper().str.contains("ST|退", regex=True)
        & pd.to_numeric(panel.get("history_count"), errors="coerce").ge(60)
        & pd.to_numeric(panel.get("turnover_rate"), errors="coerce").notna()
        & pd.to_numeric(panel.get("amount"), errors="coerce").gt(0)
    )
    # 仅要求未来五日行情完整，不用未来收益方向筛选候选。
    if "ret_5d" in panel.columns:
        eligible &= pd.to_numeric(panel["ret_5d"], errors="coerce").notna()

    selected = []
    for profile in profiles:
        work = panel[eligible & _profile_mask(panel, profile["conditions"])].copy()
        if work.empty:
            continue
        work = (
            work.sort_values(["trade_date", "amount", "ts_code"], ascending=[True, False, True])
            .groupby("trade_date", group_keys=False)
            .head(int(top_n))
            .copy()
        )
        work["profile_id"] = profile["profile_id"]
        work["profile_description"] = profile["description"]
        work["top_n"] = int(top_n)
        selected.append(work)
    return pd.concat(selected, ignore_index=True, sort=False) if selected else pd.DataFrame()


def simulate_five_day_exit(
    entry_price: float,
    bars: pd.DataFrame,
    stop_loss_pct: float = 7.0,
    take_profit_pct: float = 15.0,
    trailing_activate_pct: float = 3.0,
    trailing_drawdown_pct: float = 7.0,
    total_cost_pct: float = 0.30,
) -> dict:
    """使用未来五个交易日OHLC模拟固定止损、止盈和移动止损。"""
    if not np.isfinite(entry_price) or entry_price <= 0 or bars.empty:
        return {}
    work = bars.sort_values("trade_date").head(5).copy()
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

        # 跳空直接按开盘成交；盘中止损与止盈同时触发时按止损优先。
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
        elif day_number == 5:
            exit_price = day_close
            exit_reason = "max_hold"

        if exit_price is not None:
            exit_date = str(row.trade_date)
            break
        previous_peak = max(previous_peak, day_high)

    if exit_price is None:
        return {}

    gross_ret = (float(exit_price) / entry_price - 1) * 100
    net_ret = gross_ret - total_cost_pct
    return {
        "exit_date": exit_date,
        "exit_price": round(float(exit_price), 4),
        "exit_reason": exit_reason,
        "hold_days": int(hold_days),
        "gross_ret_pct": round(gross_ret, 4),
        "net_ret_pct": round(net_ret, 4),
        "mfe_pct": round((observed_high / entry_price - 1) * 100, 4),
        "mae_pct": round((observed_low / entry_price - 1) * 100, 4),
    }


def _future_dates(signal_date: str, all_dates: list[str], positions: dict[str, int]) -> list[str]:
    position = positions.get(str(signal_date))
    if position is None:
        return []
    return all_dates[position + 1 : position + 6]


def _load_bar_map(cache_dir: Path, dates: set[str], codes: set[str]) -> dict[tuple[str, str], dict]:
    result = {}
    columns = ["ts_code", "open", "high", "low", "close"]
    for date in sorted(dates):
        frame = market_research._read_parquet(cache_dir / "daily" / f"{date}.parquet", columns)
        if frame.empty or "ts_code" not in frame.columns:
            continue
        frame["ts_code"] = frame["ts_code"].astype(str)
        frame = frame[frame["ts_code"].isin(codes)]
        for row in frame.itertuples(index=False):
            result[(str(row.ts_code), str(date))] = {
                "trade_date": str(date),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
            }
    return result


def _split_label(date: str) -> str:
    if date <= SPLITS["train"][1]:
        return "train"
    if date <= SPLITS["validation"][1]:
        return "validation"
    return "sealed"


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
        needed_dates.update(_future_dates(date, all_dates, positions))
    codes = set(candidates["ts_code"].astype(str))
    bar_map = _load_bar_map(cache_dir, needed_dates, codes)
    simulation_cache = {}
    rows = []

    for candidate in candidates.itertuples(index=False):
        signal_date = str(candidate.trade_date)
        code = str(candidate.ts_code)
        dates = _future_dates(signal_date, all_dates, positions)
        if len(dates) < 5:
            continue
        bars = [bar_map.get((code, date)) for date in dates]
        if any(bar is None for bar in bars):
            continue
        entry_open = float(bars[0]["open"])
        signal_close = float(candidate.close)
        if entry_open <= 0 or signal_close <= 0:
            continue
        entry_gap_pct = (entry_open / signal_close - 1) * 100
        if entry_gap_pct >= 9.5:
            continue

        cache_key = (code, signal_date)
        if cache_key not in simulation_cache:
            simulation_cache[cache_key] = simulate_five_day_exit(entry_open, pd.DataFrame(bars))
        result = simulation_cache[cache_key]
        if not result:
            continue
        rows.append(
            {
                "profile_id": candidate.profile_id,
                "profile_description": candidate.profile_description,
                "top_n": int(candidate.top_n),
                "signal_date": signal_date,
                "entry_date": dates[0],
                "ts_code": code,
                "name": getattr(candidate, "name", ""),
                "industry": getattr(candidate, "industry", ""),
                "amount": float(candidate.amount),
                "entry_open": entry_open,
                "entry_gap_pct": round(entry_gap_pct, 4),
                "split": _split_label(signal_date),
                "year": signal_date[:4],
                **result,
            }
        )
    return pd.DataFrame(rows)


def _profit_factor(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    gains = values[values > 0].sum()
    losses = abs(values[values < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def summarize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if trades.empty:
        return pd.DataFrame()
    for keys, group in trades.groupby(["profile_id", "profile_description", "top_n", "split"], sort=False):
        profile_id, description, top_n, split = keys
        returns = pd.to_numeric(group["net_ret_pct"], errors="coerce").dropna()
        yearly = group.groupby("year")["net_ret_pct"].mean()
        rows.append(
            {
                "profile_id": profile_id,
                "profile_description": description,
                "top_n": int(top_n),
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
                "worst_year_avg_pct": round(float(yearly.min()), 4),
            }
        )
    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary

    accepted = []
    for (profile_id, top_n), group in summary.groupby(["profile_id", "top_n"], sort=False):
        by_split = {row.split: row for row in group.itertuples(index=False)}
        train = by_split.get("train")
        validation = by_split.get("validation")
        sealed = by_split.get("sealed")
        passed = bool(
            train and validation and sealed
            and train.trades >= 300
            and validation.trades >= 150
            and sealed.trades >= 75
            and validation.avg_net_ret_pct > 0.20
            and sealed.avg_net_ret_pct > 0.20
            and validation.profit_factor > 1.05
            and sealed.profit_factor > 1.05
            and validation.win_rate >= 0.48
            and sealed.win_rate >= 0.48
        )
        accepted.append((profile_id, int(top_n), passed))
    acceptance = pd.DataFrame(accepted, columns=["profile_id", "top_n", "research_pass"])
    return summary.merge(acceptance, on=["profile_id", "top_n"], how="left")


def run_backtest(start: str, end: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
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
        candidates = pd.concat(
            [
                select_profile_candidates(panel, FROZEN_PROFILES, top_n=3),
                select_profile_candidates(panel, FROZEN_PROFILES, top_n=10),
            ],
            ignore_index=True,
            sort=False,
        )
        trades = _simulate_candidates(candidates, cache_dir, all_dates, positions)
        if not trades.empty:
            trade_frames.append(trades)
        del panel, candidates

    all_trades = pd.concat(trade_frames, ignore_index=True, sort=False) if trade_frames else pd.DataFrame()
    return all_trades, summarize_trades(all_trades)


def _pct(value: float, ratio: bool = False) -> str:
    number = float(value) * 100 if ratio else float(value)
    return f"{number:+.2f}%"


def write_report(summary: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    passed = summary[summary["research_pass"]].drop_duplicates(["profile_id", "top_n"])
    lines = [
        "# 冻结机会画像真实退出回测",
        "",
        "## 固定口径",
        "",
        "- T日收盘筛选，画像阈值不再搜索；每天按成交额选择Top3或Top10。",
        "- T+1开盘买入；开盘涨幅不低于9.5%的候选跳过，不递补。",
        "- 最长持有5日，固定止损-7%，止盈+15%，盈利3%后启用7%移动回撤。",
        "- 同日止损和止盈都可能触发时按止损优先；每笔扣除0.30%交易摩擦。",
        "- 本研究不代表组合资金曲线，不修改正式策略。",
        "",
        "## 验收结果",
        "",
        f"- 画像/容量组合：`{summary[['profile_id', 'top_n']].drop_duplicates().shape[0]}`。",
        f"- 同时通过验证期和封存期真实退出门槛：`{len(passed)}`。",
        "",
        "| 画像 | 容量 | 阶段 | 交易 | 均收益 | 胜率 | 盈亏比 | MFE/MAE | 最差年度均收益 | 结论 |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    ordered = summary.sort_values(
        ["research_pass", "profile_id", "top_n", "split"],
        ascending=[False, True, True, True],
    )
    for row in ordered.itertuples(index=False):
        lines.append(
            f"| {row.profile_description} | Top{row.top_n} | {row.split} | {row.trades} | "
            f"{_pct(row.avg_net_ret_pct)} | {_pct(row.win_rate, ratio=True)} | {row.profit_factor:.2f} | "
            f"{_pct(row.avg_mfe_pct)} / {_pct(row.avg_mae_pct)} | {_pct(row.worst_year_avg_pct)} | "
            f"{'通过' if row.research_pass else '观察'} |"
        )
    lines.extend(["", "## 结论", ""])
    if passed.empty:
        lines.append("- 没有画像在真实退出、交易摩擦和封存期检验后达到接入标准。")
    else:
        for row in passed.itertuples(index=False):
            lines.append(f"- `{row.profile_description} / Top{row.top_n}`通过研究门槛，可进入20个交易日独立模拟观察。")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="冻结机会画像真实OHLC退出回测。")
    parser.add_argument("--start", default="20160101")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "cache")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trades, summary = run_backtest(args.start, args.end, args.cache_dir)
    if trades.empty:
        raise SystemExit("没有生成可评估交易")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    trades.to_csv(DEFAULT_TRADES, index=False, encoding="utf-8-sig")
    summary.to_csv(DEFAULT_SUMMARY, index=False, encoding="utf-8-sig")
    write_report(summary, DEFAULT_REPORT)
    print("\nSUMMARY")
    print(summary.to_string(index=False))
    print(f"trades={len(trades)} passed={summary[summary['research_pass']][['profile_id', 'top_n']].drop_duplicates().shape[0]}")
    print(f"report={DEFAULT_REPORT}")
    print(f"trades_csv={DEFAULT_TRADES}")
    print(f"summary_csv={DEFAULT_SUMMARY}")


if __name__ == "__main__":
    main()
