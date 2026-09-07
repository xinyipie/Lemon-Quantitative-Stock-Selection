#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""干净的首次涨停与重复涨停事件家族研究。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.clean_archetype_family import _family_adjusted_p, _summary  # noqa: E402
from research.no_future_signal_pipeline import apply_next_open_execution, assert_no_future_features, lock_daily_topn  # noqa: E402


STORE = ROOT / "data" / "research" / "clean_all_market"
PREREG = ROOT / "reports" / "research" / "prereg_clean_limit_event_family_20260808.json"
REPORT = ROOT / "reports" / "research" / "clean_limit_event_family_training_20260808.md"
TRADES_PATH = ROOT / "reports" / "research" / "clean_limit_event_family_training_trades_20260808.csv"
EVENT_FEATURES = [
    "pct_chg", "prior_limit_count_20", "ret_20", "ret_60", "industry_rs_20", "volume_ratio",
    "turnover_rate", "volatility_20", "drawdown_20", "ma_20", "ma_60",
]


def limit_threshold(ts_code: str) -> float:
    code = str(ts_code).split(".")[0]
    if code.startswith(("300", "301", "688", "689")):
        return 18.5
    if code.startswith(("4", "8", "92")):
        return 28.0
    return 9.3


def add_limit_history(frame: pd.DataFrame, previous_tail: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    current = frame.copy()
    current["_current_year_row"] = True
    if previous_tail is not None and not previous_tail.empty:
        context = previous_tail.copy()
        context["_current_year_row"] = False
        work = pd.concat([context, current], ignore_index=True)
    else:
        work = current
    work = work.sort_values(["ts_code", "trade_date"]).copy()
    pct = pd.to_numeric(work["pct_chg"], errors="coerce")
    thresholds = work["ts_code"].map(limit_threshold)
    work["is_limit_event"] = pct.ge(thresholds)
    work["prior_limit_count_20"] = work.groupby("ts_code")["is_limit_event"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=1).sum()
    )
    result = work[work["_current_year_row"]].drop(columns=["_current_year_row"]).copy()
    tail = work.drop(columns=["_current_year_row"]).groupby("ts_code", group_keys=False).tail(20).copy()
    return result, tail


def _rank(frame: pd.DataFrame, values: pd.Series, higher: bool) -> pd.Series:
    return values.groupby(frame["trade_date"]).rank(pct=True, ascending=higher, method="average") * 100


def event_candidates(frame: pd.DataFrame, event: str) -> pd.DataFrame:
    assert_no_future_features(EVENT_FEATURES)
    work = frame.copy()
    for column in EVENT_FEATURES:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    base = (
        work["is_limit_event"] & work["turnover_rate"].between(1, 25)
        & work["volume_ratio"].between(1, 6) & work["ret_60"].between(-10, 120)
    )
    if event == "first_limit_20d":
        mask = base & work["prior_limit_count_20"].eq(0) & work["industry_rs_20"].ge(-10)
    elif event == "trend_first_limit_20d":
        mask = (
            base & work["prior_limit_count_20"].eq(0) & work["ret_20"].ge(5) & work["ret_60"].ge(10)
            & work["industry_rs_20"].ge(0) & work["ma_20"].gt(work["ma_60"])
        )
    elif event == "repeat_limit_20d":
        mask = (
            base & work["prior_limit_count_20"].between(1, 3) & work["ret_20"].ge(5)
            & work["ret_60"].ge(10) & work["drawdown_20"].le(10) & work["industry_rs_20"].ge(-5)
        )
    else:
        raise ValueError(event)
    work = work[mask].copy()
    volume_quality = -(work["volume_ratio"] - 2.0).abs()
    if event == "first_limit_20d":
        work["score"] = (
            _rank(work, work["industry_rs_20"], True) * 0.25 + _rank(work, work["ret_20"], True) * 0.15
            + _rank(work, work["ret_60"], True) * 0.15 + _rank(work, volume_quality, True) * 0.15
            + _rank(work, work["volatility_20"], False) * 0.10 + _rank(work, work["turnover_rate"], False) * 0.10
            + _rank(work, work["drawdown_20"], False) * 0.10
        )
    elif event == "trend_first_limit_20d":
        work["score"] = (
            _rank(work, work["industry_rs_20"], True) * 0.30 + _rank(work, work["ret_60"], True) * 0.20
            + _rank(work, work["ret_20"], True) * 0.15 + _rank(work, work["drawdown_20"], False) * 0.15
            + _rank(work, volume_quality, True) * 0.10 + _rank(work, work["volatility_20"], False) * 0.10
        )
    else:
        work["score"] = (
            _rank(work, work["industry_rs_20"], True) * 0.30 + _rank(work, work["ret_20"], True) * 0.20
            + _rank(work, work["ret_60"], True) * 0.20 + _rank(work, work["prior_limit_count_20"], False) * 0.10
            + _rank(work, volume_quality, True) * 0.10 + _rank(work, work["volatility_20"], False) * 0.10
        )
    work["score"] = work["score"].round(4)
    return work


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    trades_list = []
    all_dates = []
    previous_tail = None
    for year in range(2016, 2022):
        raw = pd.read_parquet(STORE / f"{year}.parquet")
        frame, previous_tail = add_limit_history(raw, previous_tail)
        all_dates.extend(frame["trade_date"].astype(str).unique().tolist())
        for event in ("first_limit_20d", "trend_first_limit_20d", "repeat_limit_20d"):
            candidates = event_candidates(frame, event)
            print(f"year={year} event={event} candidates={len(candidates)}")
            for topn in (1, 2, 3):
                locked = lock_daily_topn(candidates, "score", topn=topn)
                for horizon in (3, 5, 8):
                    config = f"{event}_top{topn}_h{horizon}"
                    execution = apply_next_open_execution(locked, cost=0.25, outcome_column=f"ret_{horizon}d")
                    trades = execution[execution["executed"]].copy()
                    trades["net_ret"] = pd.to_numeric(trades["net_ret"], errors="coerce")
                    trades["raw_ret"] = pd.to_numeric(trades[f"ret_{horizon}d"], errors="coerce")
                    trades["config"] = config
                    trades_list.append(trades)
    trades = pd.concat(trades_list, ignore_index=True)
    trades.to_csv(TRADES_PATH, index=False, encoding="utf-8-sig")
    rows = []
    for config, group in trades.groupby("config"):
        row = {"config": config, **_summary(group)}
        row["base_pass"] = bool(
            row["trades"] >= 300 and row["positive_years"] >= 5
            and row["confirmation_positive_years"] == 3 and row["confirmation_pf"] >= 1.10
            and row["trimmed_avg"] > 0 and row["stress_avg"] > 0 and row["stress_pf"] >= 1.05
        )
        rows.append(row)
    summary = pd.DataFrame(rows)
    confirmation_dates = sorted(date for date in set(all_dates) if "2019" <= date[:4] <= "2021")
    confirmation = trades[trades["trade_date"].astype(str).str[:4].isin(["2019", "2020", "2021"])]
    matrix = pd.DataFrame(
        {config: group.groupby("trade_date")["net_ret"].mean().reindex(confirmation_dates, fill_value=0.0) for config, group in confirmation.groupby("config")},
        index=confirmation_dates,
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
        "# 干净涨停事件家族训练筛选", "", f"- 预注册 SHA256：`{prereg_hash}`。",
        f"- 基础门槛通过：`{len(passing)}/27`；候选：`{selected or '无'}`；家族校正 p=`{adjusted_p:.4f}`；允许验证：`{strict_pass}`。",
        "- 每日候选先按T日字段锁定，T+1涨停无法成交时不补位。", "",
        summary.to_markdown(index=False, floatfmt=".4f"), "", "- 未通过时不读取2022-2024收益。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    summary.to_csv(REPORT.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    print(summary.head(15).to_string(index=False))
    print(f"selected={selected} adjusted_p={adjusted_p:.4f} strict_pass={strict_pass}")


if __name__ == "__main__":
    run()
