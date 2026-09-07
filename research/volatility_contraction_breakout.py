#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""预注册的波动收缩后温和突破研究。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.all_market_multi_engine_research import (  # noqa: E402
    _available_dates,
    _build_regimes,
    _load_stock_info,
    build_year_panel,
)
from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown  # noqa: E402
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio  # noqa: E402
from research.no_future_signal_pipeline import signal_eligible_mask  # noqa: E402
from research.two_stage_walkforward_research import _bootstrap_probability, _metrics, _period, _prepare, walk_forward  # noqa: E402


CACHE = ROOT / "data" / "cache"
PREREG = ROOT / "reports" / "research" / "prereg_volatility_contraction_breakout_20260808.json"
CANDIDATES = ROOT / "reports" / "research" / "volatility_contraction_breakout_candidates_20260808.csv"
REPORT = ROOT / "reports" / "research" / "volatility_contraction_breakout_validation_20260808.md"
FORBIDDEN_COLUMNS = {"ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d", "opportunity_score", "opportunity_rank"}
SCORE_COLUMNS = {
    "volatility_contraction_60", "industry_rs_20", "pct_chg", "drawdown_20",
    "volume_ratio", "ret_60", "turnover_rate",
}
FROZEN_CONFIG = {
    "topn": 2,
    "rank_ridge": 100.0,
    "gate_ridge": 100.0,
    "gate_window_years": 99,
    "gate_quantile": 0.8,
    "cost": 0.25,
    "regime_mode": "all",
}


def _rank(frame: pd.DataFrame, values: pd.Series, higher: bool) -> pd.Series:
    return values.groupby(frame["trade_date"]).rank(pct=True, ascending=higher, method="average") * 100


def build_candidates(panel: pd.DataFrame, topn: int = 60) -> pd.DataFrame:
    work = panel.copy().sort_values(["ts_code", "trade_date"])
    numeric_columns = (SCORE_COLUMNS - {"volatility_contraction_60"}) | {
        "history_count", "entry_gap_pct", "ret_20", "rsi_14", "ma_20", "ma_60", "close", "volatility_20"
    }
    for column in numeric_columns:
        work[column] = pd.to_numeric(work[column], errors="coerce")

    # 只使用截至T日的历史波动率中位数，衡量当前是否处于真实收缩阶段。
    historical_median = work.groupby("ts_code")["volatility_20"].transform(
        lambda values: values.rolling(60, min_periods=40).median()
    )
    work["volatility_contraction_60"] = work["volatility_20"] / historical_median.replace(0, pd.NA)
    mask = (
        signal_eligible_mask(work, min_history=140)
        & work["pct_chg"].between(1.0, 6.0)
        & work["turnover_rate"].between(0.8, 12.0)
        & work["volume_ratio"].between(1.0, 2.4)
        & work["ret_60"].between(8.0, 80.0)
        & work["ret_20"].between(-2.0, 25.0)
        & work["drawdown_20"].between(0.0, 4.0)
        & work["rsi_14"].between(50.0, 80.0)
        & work["industry_rs_20"].ge(0.0)
        & work["volatility_contraction_60"].le(0.85)
        & work["ma_20"].gt(work["ma_60"])
        & work["close"].ge(work["ma_20"])
    )
    work = work[mask].copy()
    if work.empty:
        return work
    volume_quality = -(work["volume_ratio"] - 1.4).abs()
    work["contraction_breakout_score"] = (
        _rank(work, work["volatility_contraction_60"], False) * 0.25
        + _rank(work, work["industry_rs_20"], True) * 0.15
        + _rank(work, work["pct_chg"], True) * 0.15
        + _rank(work, work["drawdown_20"], False) * 0.15
        + _rank(work, volume_quality, True) * 0.15
        + _rank(work, work["ret_60"], True) * 0.10
        + _rank(work, work["turnover_rate"], False) * 0.05
    ).round(4)
    selected = (
        work.sort_values(["trade_date", "contraction_breakout_score", "ts_code"], ascending=[True, False, True])
        .groupby("trade_date", group_keys=False)
        .head(topn)
        .drop_duplicates(["trade_date", "ts_code"])
        .copy()
    )
    selected["engine"] = "volatility_contraction_breakout"
    selected["engine_score"] = selected["contraction_breakout_score"]
    selected["engine_rank"] = selected.groupby("trade_date")["engine_score"].rank(ascending=False, method="first")
    return selected


def evaluate(path: Path, validation_allowed: bool) -> tuple[bool, pd.DataFrame]:
    frame, market = _prepare(path)
    trades, _ = walk_forward(frame, market, **FROZEN_CONFIG)
    train = _metrics(_period(trades, 2019, 2021))
    train_pass = bool(
        train["trades"] >= 100
        and train["avg_net"] > 0
        and train["profit_factor"] > 1.10
        and train["positive_years"] == train["years"] == 3
    )
    print(f"training_gate={train_pass} train={train}")
    if not validation_allowed or not train_pass:
        return train_pass, trades

    validation = _metrics(_period(trades, 2022, 2024))
    recent = _metrics(_period(trades, 2025, 2026))
    yearly = trades.assign(year=trades["trade_date"].astype(str).str[:4].astype(int)).groupby("year").apply(
        lambda group: pd.Series(_metrics(group)), include_groups=False
    ).reset_index()
    validation_days = _period(trades.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024)
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(validation_days, block=20, repetitions=10000)
    overlap = overlap_adjusted_portfolio(trades, CACHE, cost=0.25)
    path_yearly = annual_path_metrics(overlap)
    path_drawdown = max_drawdown(overlap["net_ret"]) if not overlap.empty else float("nan")
    validation_path = path_yearly[path_yearly["year"].between(2022, 2024)]
    strict_pass = bool(
        validation["trades"] >= 100
        and validation["avg_net"] > 0
        and validation["profit_factor"] > 1.10
        and validation["positive_years"] == validation["years"] == 3
        and recent["trades"] >= 40
        and recent["avg_net"] > 0
        and recent["profit_factor"] > 1.10
        and recent["positive_years"] == recent["years"] == 2
        and ci_low > 0
        and p_nonpositive < 0.05
        and len(validation_path) == 3
        and (validation_path["return_pct"] > 0).all()
        and path_drawdown > -20.0
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(REPORT.with_name(REPORT.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    summary = pd.DataFrame([
        {"period": "train_oos", **train},
        {"period": "validation", **validation},
        {"period": "recent", **recent},
    ])
    lines = [
        "# 预注册波动收缩后温和突破首次验证",
        "",
        f"- 预注册 SHA256：`{hashlib.sha256(PREREG.read_bytes()).hexdigest()}`。",
        f"- 训练门槛：通过。严格首次验证：{'通过' if strict_pass else '不通过'}。",
        f"- 验证期 Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于0概率 {p_nonpositive:.2%}。",
        f"- 真实重叠持仓最大回撤：{path_drawdown:.2f}%。",
        "",
        summary.to_markdown(index=False, floatfmt=".4f"),
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        path_yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "- v1首次验证后不得改参，失败结果原样保留。",
        "- 本研究未修改正式策略，也不生成交易执行代码。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"strict_pass={strict_pass} validation={validation} recent={recent}")
    print(yearly.to_string(index=False))
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f} path_drawdown={path_drawdown:.2f}")
    return strict_pass, trades


def run() -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    print(f"prereg_sha256={prereg_hash}")
    dates = _available_dates(CACHE, "20160101", "20260807")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    frames = []
    for year in range(2016, 2022):
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", f"{year}1231")
        frames.append(build_candidates(panel))
        print(f"training_year={year} panel={len(panel)} candidates={len(frames[-1])}")
    training_candidates = pd.concat(frames, ignore_index=True)
    training_path = CANDIDATES.with_name(CANDIDATES.stem + "_training_only.csv")
    training_candidates.to_csv(training_path, index=False, encoding="utf-8-sig")
    train_pass, _ = evaluate(training_path, validation_allowed=False)
    if not train_pass:
        REPORT.write_text(
            f"# 波动收缩后温和突破\n\n- 预注册 SHA256：`{prereg_hash}`。\n"
            "- 训练期内部OOS门槛未通过，按预注册规则未读取2022-2026验证收益。\n",
            encoding="utf-8",
        )
        print(f"training_failed wrote={REPORT}")
        return
    for year in range(2022, 2027):
        end_date = "20260807" if year == 2026 else f"{year}1231"
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", end_date)
        frames.append(build_candidates(panel))
        print(f"validation_year={year} panel={len(panel)} candidates={len(frames[-1])}")
    all_candidates = pd.concat(frames, ignore_index=True)
    all_candidates.to_csv(CANDIDATES, index=False, encoding="utf-8-sig")
    evaluate(CANDIDATES, validation_allowed=True)


if __name__ == "__main__":
    run()
