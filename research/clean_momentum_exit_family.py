#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""干净低波动动量信号的因果退出规则家族。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import ceil
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


CACHE_DAILY = ROOT / "data" / "cache" / "daily"
SOURCE = ROOT / "reports" / "research" / "clean_archetype_family_training_trades_20260808.csv"
PREREG = ROOT / "reports" / "research" / "prereg_clean_momentum_exit_family_20260808.json"
REPORT = ROOT / "reports" / "research" / "clean_momentum_exit_family_training_20260808.md"
TRADES_PATH = ROOT / "reports" / "research" / "clean_momentum_exit_family_training_trades_20260808.csv"


@dataclass(frozen=True)
class ExitRule:
    name: str
    max_days: int = 8
    stop_pct: float | None = None
    take_pct: float | None = None
    trail_activate_pct: float | None = None
    trail_pct: float | None = None
    time_stop_day: int | None = None


EXIT_RULES = [
    ExitRule("fixed8"),
    ExitRule("stop5", stop_pct=5.0),
    ExitRule("stop7", stop_pct=7.0),
    ExitRule("stop5_take10", stop_pct=5.0, take_pct=10.0),
    ExitRule("stop6_trailing4", stop_pct=6.0, trail_activate_pct=4.0, trail_pct=4.0),
    ExitRule("stop7_trailing5", stop_pct=7.0, trail_activate_pct=5.0, trail_pct=5.0),
    ExitRule("stop6_time5", stop_pct=6.0, time_stop_day=5),
]


def simulate_exit(path: pd.DataFrame, rule: ExitRule) -> dict:
    entry = float(path.iloc[0]["open"])
    peak = entry
    for offset, row in enumerate(path.iloc[: rule.max_days].itertuples(index=False), 1):
        day_open = float(row.open)
        day_high = float(row.high)
        day_low = float(row.low)
        day_close = float(row.close)
        if rule.stop_pct is not None:
            stop_price = entry * (1.0 - rule.stop_pct / 100.0)
            if day_low <= stop_price:
                exit_price = min(day_open, stop_price)
                return {"gross_ret": (exit_price / entry - 1) * 100, "hold_days": offset, "exit_reason": "stop"}
        if rule.trail_activate_pct is not None and rule.trail_pct is not None and peak >= entry * (1.0 + rule.trail_activate_pct / 100.0):
            trail_price = peak * (1.0 - rule.trail_pct / 100.0)
            if day_low <= trail_price:
                exit_price = min(day_open, trail_price)
                return {"gross_ret": (exit_price / entry - 1) * 100, "hold_days": offset, "exit_reason": "trailing"}
        if rule.take_pct is not None:
            take_price = entry * (1.0 + rule.take_pct / 100.0)
            if day_high >= take_price:
                exit_price = max(day_open, take_price)
                return {"gross_ret": (exit_price / entry - 1) * 100, "hold_days": offset, "exit_reason": "take_profit"}
        peak = max(peak, day_high)
        if rule.time_stop_day is not None and offset == rule.time_stop_day and day_close <= entry:
            return {"gross_ret": (day_close / entry - 1) * 100, "hold_days": offset, "exit_reason": "time_stop"}
        if offset == min(rule.max_days, len(path)):
            return {"gross_ret": (day_close / entry - 1) * 100, "hold_days": offset, "exit_reason": "max_hold"}
    raise ValueError("没有可用退出日")


def _load_daily(codes: set[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    frames = []
    for path in sorted(CACHE_DAILY.glob("*.parquet")):
        date = path.stem
        if date < start or date > end:
            continue
        frame = pd.read_parquet(path, columns=["ts_code", "trade_date", "open", "high", "low", "close", "pct_chg"])
        frame = frame[frame["ts_code"].astype(str).isin(codes)]
        if not frame.empty:
            frames.append(frame)
    daily = pd.concat(frames, ignore_index=True).sort_values(["ts_code", "trade_date"])
    return {code: group.reset_index(drop=True) for code, group in daily.groupby("ts_code")}


def _normalized_path(code_daily: pd.DataFrame, signal_date: str, max_days: int = 8) -> pd.DataFrame:
    future = code_daily[code_daily["trade_date"].astype(str) > str(signal_date)].head(max_days).copy()
    if len(future) < max_days:
        return pd.DataFrame()
    rows = []
    previous_close = None
    for offset, row in enumerate(future.itertuples(index=False)):
        raw_close = float(row.close)
        if offset == 0:
            scale = 1.0
            synthetic_close = raw_close
        else:
            synthetic_close = previous_close * (1.0 + float(row.pct_chg) / 100.0)
            scale = synthetic_close / raw_close if raw_close > 0 else np.nan
        rows.append(
            {
                "trade_date": str(row.trade_date),
                "open": float(row.open) * scale,
                "high": float(row.high) * scale,
                "low": float(row.low) * scale,
                "close": synthetic_close,
            }
        )
        previous_close = synthetic_close
    return pd.DataFrame(rows)


def _pf(values: pd.Series) -> float:
    returns = pd.to_numeric(values, errors="coerce").dropna()
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")


def _metrics(frame: pd.DataFrame) -> dict:
    returns = pd.to_numeric(frame["net_ret"], errors="coerce").dropna()
    yearly = frame.assign(year=frame["trade_date"].astype(str).str[:4]).groupby("year")["net_ret"].mean()
    confirmation = frame[frame["trade_date"].astype(str).str[:4].isin(["2019", "2020", "2021"])]
    conf_ret = pd.to_numeric(confirmation["net_ret"], errors="coerce").dropna()
    conf_yearly = confirmation.assign(year=confirmation["trade_date"].astype(str).str[:4]).groupby("year")["net_ret"].mean()
    trim_count = ceil(len(returns) * 0.05)
    trimmed = returns.sort_values().iloc[:-trim_count] if trim_count and len(returns) > trim_count else returns
    stress = pd.to_numeric(frame["gross_ret"], errors="coerce") - 0.50
    path_frame = frame.copy()
    path_frame["daily_equivalent_ret"] = pd.to_numeric(path_frame["net_ret"], errors="coerce") / pd.to_numeric(path_frame["hold_days"], errors="coerce").clip(lower=1)
    daily = path_frame.groupby("trade_date")["daily_equivalent_ret"].mean().sort_index()
    cumulative = daily.cumsum()
    drawdown = (cumulative - cumulative.cummax()).min()
    return {
        "trades": len(returns), "avg_net": returns.mean(), "pf": _pf(returns),
        "positive_years": int((yearly > 0).sum()), "years": len(yearly),
        "confirmation_avg": conf_ret.mean(), "confirmation_pf": _pf(conf_ret),
        "confirmation_positive_years": int((conf_yearly > 0).sum()),
        "trimmed_avg": trimmed.mean(), "stress_avg": stress.mean(), "stress_pf": _pf(stress),
        "signal_date_drawdown": float(drawdown),
    }


def _adjusted_p(matrix: pd.DataFrame, candidate: str, repetitions: int = 5000, block: int = 20) -> float:
    values = matrix.to_numpy(float)
    observed = float(matrix[candidate].mean())
    centered = values - values.mean(axis=0, keepdims=True)
    rng = np.random.default_rng(20260808)
    maxima = np.empty(repetitions)
    offsets = np.arange(block)
    for index in range(repetitions):
        starts = rng.integers(0, len(values), size=ceil(len(values) / block))
        sampled = np.concatenate([(start + offsets) % len(values) for start in starts])[: len(values)]
        maxima[index] = centered[sampled].mean(axis=0).max()
    return float((np.count_nonzero(maxima >= observed) + 1) / (repetitions + 1))


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    source = pd.read_csv(SOURCE, encoding="utf-8-sig")
    source = source[source["config"].isin(["low_vol_momentum_top1_h8", "low_vol_momentum_top3_h8"])].copy()
    source = source.drop_duplicates(["config", "trade_date", "ts_code"])
    daily_by_code = _load_daily(set(source["ts_code"].astype(str)), "20160101", "20220228")
    rows = []
    for signal in source.itertuples(index=False):
        code_daily = daily_by_code.get(str(signal.ts_code))
        if code_daily is None:
            continue
        path = _normalized_path(code_daily, str(signal.trade_date), max_days=8)
        if path.empty:
            continue
        for rule in EXIT_RULES:
            result = simulate_exit(path, rule)
            rows.append(
                {
                    "signal_config": signal.config, "exit_rule": rule.name,
                    "config": f"{signal.config}__{rule.name}", "trade_date": str(signal.trade_date),
                    "ts_code": str(signal.ts_code), "gross_ret": result["gross_ret"],
                    "net_ret": result["gross_ret"] - 0.25, "hold_days": result["hold_days"],
                    "exit_reason": result["exit_reason"],
                }
            )
    trades = pd.DataFrame(rows)
    trades.to_csv(TRADES_PATH, index=False, encoding="utf-8-sig")
    summary_rows = []
    for config, group in trades.groupby("config"):
        row = {"config": config, **_metrics(group)}
        row["base_pass"] = bool(
            row["trades"] >= 1000 and row["positive_years"] >= 5
            and row["confirmation_positive_years"] == 3 and row["confirmation_pf"] >= 1.10
            and row["trimmed_avg"] > 0 and row["stress_avg"] > 0 and row["stress_pf"] >= 1.05
            and row["signal_date_drawdown"] > -20.0
        )
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows)
    confirmation = trades[trades["trade_date"].astype(str).str[:4].isin(["2019", "2020", "2021"])]
    dates = sorted(confirmation["trade_date"].astype(str).unique())
    matrix = pd.DataFrame(
        {config: group.groupby("trade_date")["net_ret"].mean().reindex(dates, fill_value=0.0) for config, group in confirmation.groupby("config")},
        index=dates,
    )
    means = matrix.mean()
    sharpes = means / matrix.std(ddof=1).replace(0, np.nan) * np.sqrt(252)
    summary["confirmation_daily_mean"] = summary["config"].map(means)
    summary["confirmation_sharpe"] = summary["config"].map(sharpes)
    passing = summary[summary["base_pass"]].sort_values("confirmation_sharpe", ascending=False)
    selected = str(passing.iloc[0]["config"]) if not passing.empty else None
    adjusted_p = _adjusted_p(matrix, selected) if selected else 1.0
    strict_pass = bool(selected and adjusted_p <= 0.10)
    summary["adjusted_p"] = np.where(summary["config"].eq(selected), adjusted_p, np.nan)
    summary = summary.sort_values(["base_pass", "confirmation_sharpe"], ascending=False)
    lines = [
        "# 干净低波动动量因果退出家族", "", f"- 预注册 SHA256：`{prereg_hash}`。",
        f"- 基础门槛通过：`{len(passing)}/14`；候选：`{selected or '无'}`；家族校正 p=`{adjusted_p:.4f}`；允许验证：`{strict_pass}`。",
        "- 路径按pct_chg链接复权，移动止损只使用此前已经形成的峰值，同日止损与止盈冲突时保守按止损。", "",
        summary.to_markdown(index=False, floatfmt=".4f"), "", "- 未通过时不读取2022-2024收益。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    summary.to_csv(REPORT.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print(f"selected={selected} adjusted_p={adjusted_p:.4f} strict_pass={strict_pass}")


if __name__ == "__main__":
    run()
