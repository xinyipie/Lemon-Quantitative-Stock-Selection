#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""干净全市场特征上的经典短线原型家族筛选。"""

from __future__ import annotations

import hashlib
import json
from math import ceil
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.no_future_signal_pipeline import apply_next_open_execution, assert_no_future_features, lock_daily_topn  # noqa: E402


STORE = ROOT / "data" / "research" / "clean_all_market"
PREREG = ROOT / "reports" / "research" / "prereg_clean_archetype_family_20260808.json"
REPORT = ROOT / "reports" / "research" / "clean_archetype_family_training_20260808.md"
TRADES_PATH = ROOT / "reports" / "research" / "clean_archetype_family_training_trades_20260808.csv"
LOCK_PATH = ROOT / "reports" / "research" / "clean_archetype_candidate_lock_20260808.json"
ARCHETYPE_FEATURES = {
    "low_vol_momentum": ["ret_60", "ret_20", "industry_rs_20", "volatility_20", "volume_ratio", "turnover_rate", "ma_20", "ma_60", "close", "rsi_14"],
    "confirmed_breakout": ["ret_60", "ret_20", "industry_rs_20", "volatility_20", "volume_ratio", "drawdown_20", "pct_chg", "ma_20", "ma_60", "rsi_14"],
    "trend_pullback": ["ret_60", "ret_20", "ret_5", "industry_rs_20", "volatility_20", "volume_ratio", "drawdown_20", "ma_20", "ma_60", "close", "rsi_14"],
    "short_reversal": ["ret_60", "ret_20", "ret_5", "industry_rs_20", "volatility_20", "volume_ratio", "drawdown_20", "pct_chg", "rsi_14"],
}


def _rank(frame: pd.DataFrame, values: pd.Series, higher: bool) -> pd.Series:
    return values.groupby(frame["trade_date"]).rank(pct=True, ascending=higher, method="average") * 100


def _numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    work = frame.copy()
    for column in columns:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    return work


def archetype_candidates(frame: pd.DataFrame, archetype: str) -> pd.DataFrame:
    assert_no_future_features(ARCHETYPE_FEATURES[archetype])
    work = _numeric(frame, ARCHETYPE_FEATURES[archetype])
    if archetype == "low_vol_momentum":
        mask = (
            work["ret_60"].between(10, 100) & work["ret_20"].between(0, 40)
            & work["industry_rs_20"].ge(-5) & work["volume_ratio"].between(0.4, 3.0)
            & work["turnover_rate"].between(0.5, 15) & work["rsi_14"].between(50, 80)
            & work["ma_20"].gt(work["ma_60"]) & work["close"].ge(work["ma_20"] * 0.98)
        )
        work = work[mask].copy()
        volume_quality = -(work["volume_ratio"] - 1.2).abs()
        work["score"] = (
            _rank(work, work["ret_60"], True) * 0.30 + _rank(work, work["industry_rs_20"], True) * 0.25
            + _rank(work, work["ret_20"], True) * 0.15 + _rank(work, work["volatility_20"], False) * 0.15
            + _rank(work, volume_quality, True) * 0.10 + _rank(work, work["turnover_rate"], False) * 0.05
        )
    elif archetype == "confirmed_breakout":
        mask = (
            work["ret_60"].between(5, 100) & work["ret_20"].between(0, 45)
            & work["drawdown_20"].between(0, 4) & work["pct_chg"].between(1, 7)
            & work["volume_ratio"].between(1, 3) & work["industry_rs_20"].ge(-5)
            & work["rsi_14"].between(50, 85) & work["ma_20"].gt(work["ma_60"])
        )
        work = work[mask].copy()
        volume_quality = -(work["volume_ratio"] - 1.5).abs()
        work["score"] = (
            _rank(work, work["drawdown_20"], False) * 0.20 + _rank(work, work["pct_chg"], True) * 0.20
            + _rank(work, work["industry_rs_20"], True) * 0.20 + _rank(work, work["ret_60"], True) * 0.15
            + _rank(work, volume_quality, True) * 0.15 + _rank(work, work["volatility_20"], False) * 0.10
        )
    elif archetype == "trend_pullback":
        mask = (
            work["ret_60"].between(8, 100) & work["ret_20"].between(-2, 35) & work["ret_5"].between(-10, 0)
            & work["drawdown_20"].between(4, 18) & work["industry_rs_20"].ge(-5)
            & work["volume_ratio"].between(0.3, 1.5) & work["rsi_14"].between(40, 70)
            & work["ma_20"].gt(work["ma_60"]) & work["close"].ge(work["ma_60"])
        )
        work = work[mask].copy()
        ret5_quality = -(work["ret_5"] + 3).abs()
        drawdown_quality = -(work["drawdown_20"] - 7).abs()
        work["score"] = (
            _rank(work, work["industry_rs_20"], True) * 0.25 + _rank(work, work["ret_60"], True) * 0.20
            + _rank(work, ret5_quality, True) * 0.20 + _rank(work, drawdown_quality, True) * 0.15
            + _rank(work, work["volatility_20"], False) * 0.10 + _rank(work, work["volume_ratio"], False) * 0.10
        )
    elif archetype == "short_reversal":
        mask = (
            work["ret_5"].between(-15, -3) & work["ret_20"].between(-30, 5) & work["pct_chg"].between(-9, 0)
            & work["rsi_14"].between(15, 50) & work["ret_60"].between(-20, 60)
            & work["drawdown_20"].between(5, 40) & work["volume_ratio"].between(0.5, 5)
            & work["industry_rs_20"].ge(-15)
        )
        work = work[mask].copy()
        volume_quality = -(work["volume_ratio"] - 1.2).abs()
        work["score"] = (
            _rank(work, work["ret_5"], False) * 0.25 + _rank(work, work["ret_20"], False) * 0.15
            + _rank(work, work["rsi_14"], False) * 0.15 + _rank(work, work["industry_rs_20"], True) * 0.20
            + _rank(work, work["volatility_20"], False) * 0.10 + _rank(work, volume_quality, True) * 0.10
            + _rank(work, work["drawdown_20"], False) * 0.05
        )
    else:
        raise ValueError(archetype)
    work["score"] = work["score"].round(4)
    return work


def _pf(returns: pd.Series) -> float:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    return gains / losses if losses > 0 else float("inf")


def _summary(trades: pd.DataFrame) -> dict:
    returns = pd.to_numeric(trades["net_ret"], errors="coerce").dropna()
    yearly = trades.assign(year=trades["trade_date"].astype(str).str[:4]).groupby("year")["net_ret"].mean()
    trim_count = ceil(len(returns) * 0.05)
    trimmed = returns.sort_values().iloc[:-trim_count] if trim_count and len(returns) > trim_count else returns
    stress = pd.to_numeric(trades["raw_ret"], errors="coerce") - 0.50
    confirmation = trades[trades["trade_date"].astype(str).str[:4].isin(["2019", "2020", "2021"])]
    confirmation_returns = pd.to_numeric(confirmation["net_ret"], errors="coerce").dropna()
    confirmation_yearly = confirmation.assign(year=confirmation["trade_date"].astype(str).str[:4]).groupby("year")["net_ret"].mean()
    return {
        "trades": int(len(returns)), "avg_net": float(returns.mean()), "profit_factor": _pf(returns),
        "positive_years": int((yearly > 0).sum()), "years": int(len(yearly)),
        "confirmation_trades": int(len(confirmation_returns)), "confirmation_avg": float(confirmation_returns.mean()),
        "confirmation_pf": _pf(confirmation_returns), "confirmation_positive_years": int((confirmation_yearly > 0).sum()),
        "trimmed_avg": float(trimmed.mean()), "stress_avg": float(stress.mean()), "stress_pf": _pf(stress),
    }


def _family_adjusted_p(daily_matrix: pd.DataFrame, candidate: str, repetitions: int = 5000, block: int = 20) -> float:
    values = daily_matrix.to_numpy(dtype=float)
    observed = float(daily_matrix[candidate].mean())
    centered = values - values.mean(axis=0, keepdims=True)
    rng = np.random.default_rng(20260808)
    n = len(centered)
    maxima = np.empty(repetitions)
    offsets = np.arange(block)
    for index in range(repetitions):
        starts = rng.integers(0, n, size=ceil(n / block))
        sampled = np.concatenate([(start + offsets) % n for start in starts])[:n]
        maxima[index] = centered[sampled].mean(axis=0).max()
    return float((np.count_nonzero(maxima >= observed) + 1) / (repetitions + 1))


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    all_trades = []
    all_dates = []
    for year in range(2016, 2022):
        frame = pd.read_parquet(STORE / f"{year}.parquet")
        all_dates.extend(frame["trade_date"].astype(str).unique().tolist())
        for archetype in ARCHETYPE_FEATURES:
            candidates = archetype_candidates(frame, archetype)
            print(f"year={year} archetype={archetype} candidates={len(candidates)}")
            for topn in (1, 2, 3):
                locked = lock_daily_topn(candidates, "score", topn=topn)
                for horizon in (3, 5, 8):
                    config = f"{archetype}_top{topn}_h{horizon}"
                    execution = apply_next_open_execution(locked, cost=0.25, outcome_column=f"ret_{horizon}d")
                    trades = execution[execution["executed"]].copy()
                    trades["net_ret"] = pd.to_numeric(trades["net_ret"], errors="coerce")
                    trades["raw_ret"] = pd.to_numeric(trades[f"ret_{horizon}d"], errors="coerce")
                    trades["config"] = config
                    all_trades.append(trades)
    trades = pd.concat(all_trades, ignore_index=True)
    trades.to_csv(TRADES_PATH, index=False, encoding="utf-8-sig")
    rows = []
    for config, group in trades.groupby("config"):
        row = {"config": config, **_summary(group)}
        row["base_pass"] = bool(
            row["trades"] >= 1000 and row["positive_years"] >= 5
            and row["confirmation_positive_years"] == 3 and row["confirmation_avg"] > 0
            and row["confirmation_pf"] >= 1.10 and row["trimmed_avg"] > 0
            and row["stress_avg"] > 0 and row["stress_pf"] >= 1.05
        )
        rows.append(row)
    summary = pd.DataFrame(rows)
    confirmation_dates = sorted(date for date in set(all_dates) if "2019" <= date[:4] <= "2021")
    daily_columns = {}
    for config, group in trades[trades["trade_date"].astype(str).str[:4].isin(["2019", "2020", "2021"])].groupby("config"):
        daily_columns[config] = group.groupby("trade_date")["net_ret"].mean().reindex(confirmation_dates, fill_value=0.0)
    daily_matrix = pd.DataFrame(daily_columns, index=confirmation_dates)
    means = daily_matrix.mean()
    stds = daily_matrix.std(ddof=1).replace(0, np.nan)
    sharpes = means / stds * np.sqrt(252)
    summary["confirmation_daily_mean"] = summary["config"].map(means)
    summary["confirmation_sharpe"] = summary["config"].map(sharpes)
    passing = summary[summary["base_pass"]].sort_values(["confirmation_sharpe", "confirmation_avg"], ascending=False)
    selected = None
    adjusted_p = 1.0
    if not passing.empty:
        selected = str(passing.iloc[0]["config"])
        adjusted_p = _family_adjusted_p(daily_matrix, selected)
    summary["family_adjusted_p"] = np.where(summary["config"].eq(selected), adjusted_p, np.nan)
    summary = summary.sort_values(["base_pass", "confirmation_sharpe", "confirmation_avg"], ascending=[False, False, False])
    strict_pass = bool(selected is not None and adjusted_p <= 0.10)
    if strict_pass:
        lock = {
            "prereg_sha256": prereg_hash,
            "selected_config": selected,
            "family_adjusted_p": adjusted_p,
            "frozen": True,
            "validation_not_yet_read": True,
        }
        LOCK_PATH.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 干净经典短线原型家族训练筛选", "", f"- 预注册 SHA256：`{prereg_hash}`。",
        "- 信号资格与排名不使用T+1开盘、跳空、tradeable或未来收益；未成交不补位。",
        f"- 基础门槛通过配置：`{len(passing)}/36`。",
        f"- 训练期候选：`{selected or '无'}`；家族校正 p 值：`{adjusted_p:.4f}`；是否允许进入验证：`{strict_pass}`。", "",
        summary.to_markdown(index=False, floatfmt=".4f"), "",
        "- 未通过家族校正时不得读取2022-2024候选收益。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    summary.to_csv(REPORT.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    print(summary.head(12).to_string(index=False))
    print(f"selected={selected} adjusted_p={adjusted_p:.4f} strict_pass={strict_pass}")


if __name__ == "__main__":
    run()
