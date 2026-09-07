#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T日信号、T+1确认、T+2开盘进入的干净两阶段研究。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.clean_archetype_family import _family_adjusted_p, _summary, archetype_candidates  # noqa: E402
from research.clean_momentum_exit_family import _load_daily, _normalized_path  # noqa: E402
from research.no_future_signal_pipeline import lock_daily_topn  # noqa: E402


STORE = ROOT / "data" / "research" / "clean_all_market"
PREREG = ROOT / "reports" / "research" / "prereg_clean_delayed_confirmation_20260808.json"
REPORT = ROOT / "reports" / "research" / "clean_delayed_confirmation_training_20260808.md"
TRADES_PATH = ROOT / "reports" / "research" / "clean_delayed_confirmation_training_trades_20260808.csv"


def confirmation_passes(row, confirmation: str) -> bool:
    pct = float(row["pct_chg"] if isinstance(row, dict) else row.pct_chg)
    day_open = float(row["open"] if isinstance(row, dict) else row.open)
    high = float(row["high"] if isinstance(row, dict) else row.high)
    low = float(row["low"] if isinstance(row, dict) else row.low)
    close = float(row["close"] if isinstance(row, dict) else row.close)
    intraday = (close / day_open - 1) * 100 if day_open > 0 else -999
    location = (close - low) / (high - low) if high > low else 0.5
    if confirmation == "positive_close":
        return 0 <= pct <= 5 and intraday > 0 and location >= 0.60
    if confirmation == "shallow_pullback":
        return -2.5 <= pct <= 0 and intraday > -1 and location >= 0.50
    if confirmation == "stable_acceptance":
        return -1.5 <= pct <= 3 and location >= 0.50
    raise ValueError(confirmation)


def _locked_signals() -> pd.DataFrame:
    rows = []
    for year in range(2016, 2022):
        frame = pd.read_parquet(STORE / f"{year}.parquet")
        candidates = archetype_candidates(frame, "low_vol_momentum")
        for topn in (1, 3):
            locked = lock_daily_topn(candidates, "score", topn=topn)
            locked["signal_config"] = f"low_vol_momentum_top{topn}"
            rows.append(locked)
    return pd.concat(rows, ignore_index=True)


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    signals = _locked_signals()
    daily_by_code = _load_daily(set(signals["ts_code"].astype(str)), "20160101", "20220331")
    rows = []
    for signal in signals.itertuples(index=False):
        code_daily = daily_by_code.get(str(signal.ts_code))
        if code_daily is None:
            continue
        future = code_daily[code_daily["trade_date"].astype(str) > str(signal.trade_date)].head(10).reset_index(drop=True)
        if len(future) < 9:
            continue
        confirmation_row = future.iloc[0]
        confirmation_date = str(confirmation_row["trade_date"])
        entry_open = float(future.iloc[1]["open"])
        prior_close = float(confirmation_row["close"])
        entry_gap = (entry_open / prior_close - 1) * 100 if prior_close > 0 else 999
        if entry_open <= 0 or entry_gap >= 9.5:
            continue
        path = _normalized_path(code_daily, confirmation_date, max_days=8)
        if path.empty:
            continue
        for confirmation in ("positive_close", "shallow_pullback", "stable_acceptance"):
            if not confirmation_passes(confirmation_row, confirmation):
                continue
            for horizon in (3, 5, 8):
                exit_close = float(path.iloc[horizon - 1]["close"])
                gross = (exit_close / float(path.iloc[0]["open"]) - 1) * 100
                config = f"{signal.signal_config}__{confirmation}__h{horizon}"
                rows.append(
                    {
                        "config": config, "signal_config": signal.signal_config, "confirmation": confirmation,
                        "trade_date": str(signal.trade_date), "confirmation_date": confirmation_date,
                        "entry_date": str(path.iloc[0]["trade_date"]), "ts_code": str(signal.ts_code),
                        "raw_ret": gross, "net_ret": gross - 0.25,
                    }
                )
    trades = pd.DataFrame(rows)
    trades.to_csv(TRADES_PATH, index=False, encoding="utf-8-sig")
    summary_rows = []
    for config, group in trades.groupby("config"):
        row = {"config": config, **_summary(group)}
        row["base_pass"] = bool(
            row["trades"] >= 500 and row["positive_years"] >= 5
            and row["confirmation_positive_years"] == 3 and row["confirmation_pf"] >= 1.10
            and row["trimmed_avg"] > 0 and row["stress_avg"] > 0 and row["stress_pf"] >= 1.05
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
    adjusted_p = _family_adjusted_p(matrix, selected) if selected else 1.0
    strict_pass = bool(selected and adjusted_p <= 0.10)
    summary["adjusted_p"] = np.where(summary["config"].eq(selected), adjusted_p, np.nan)
    summary = summary.sort_values(["base_pass", "confirmation_sharpe"], ascending=False)
    lines = [
        "# 干净T+1确认/T+2进入家族", "", f"- 预注册 SHA256：`{prereg_hash}`。",
        f"- 基础门槛通过：`{len(passing)}/18`；候选：`{selected or '无'}`；家族校正 p=`{adjusted_p:.4f}`；允许验证：`{strict_pass}`。",
        "- T+1数据只用于T+1收盘确认，实际进入为T+2开盘；T日未入选股票不能补位。", "",
        summary.to_markdown(index=False, floatfmt=".4f"), "", "- 未通过时不读取2022-2024收益。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    summary.to_csv(REPORT.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print(f"selected={selected} adjusted_p={adjusted_p:.4f} strict_pass={strict_pass}")


if __name__ == "__main__":
    run()
