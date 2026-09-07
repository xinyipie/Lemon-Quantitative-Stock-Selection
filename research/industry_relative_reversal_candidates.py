#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""预注册的行业内相对超跌修复候选生成与首次独立验证。"""

from __future__ import annotations

import hashlib
import json
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
from research.two_stage_walkforward_research import (  # noqa: E402
    _bootstrap_probability,
    _metrics,
    _period,
    _prepare,
    walk_forward,
)


CACHE = ROOT / "data" / "cache"
PREREG = ROOT / "reports" / "research" / "prereg_industry_relative_reversal_20260808.json"
OUTPUT = ROOT / "reports" / "research" / "industry_relative_reversal_candidates_20260808.csv"
REPORT = ROOT / "reports" / "research" / "industry_relative_reversal_validation_20260808.md"
FORBIDDEN_COLUMNS = {"ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d", "opportunity_score", "opportunity_rank"}
SCORE_COLUMNS = {
    "drawdown_20",
    "ret_5",
    "ret_10",
    "ret_20",
    "volatility_20",
    "turnover_rate",
    "volume_ratio",
    "rsi_14",
    "industry_rs_20",
}


def _industry_rank(frame: pd.DataFrame, column: str, higher: bool) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    groups = [frame["trade_date"], frame["industry_bucket"]]
    return values.groupby(groups).rank(pct=True, ascending=higher, method="average") * 100


def _daily_rank(frame: pd.DataFrame, column: str, higher: bool) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    return values.groupby(frame["trade_date"]).rank(pct=True, ascending=higher, method="average") * 100


def build_candidates(panel: pd.DataFrame, topn: int = 60, per_industry: int = 2) -> pd.DataFrame:
    work = panel.copy()
    for column in SCORE_COLUMNS | {"pct_chg", "entry_gap_pct", "history_count", "ret_60"}:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work["industry_bucket"] = work.get("industry", pd.Series(index=work.index, dtype=object)).fillna("未知行业").astype(str)
    mask = (
        work["tradeable"].astype(str).str.lower().isin(["true", "1"])
        & (work["history_count"] >= 120)
        & work["pct_chg"].between(-3.5, 4.5)
        & work["turnover_rate"].between(0.6, 12.0)
        & work["volume_ratio"].between(0.4, 1.8)
        & work["entry_gap_pct"].between(-3.0, 4.0)
        & work["drawdown_20"].between(4.0, 25.0)
        & work["ret_60"].between(-15.0, 35.0)
        & work["rsi_14"].between(25.0, 60.0)
        & work["industry_bucket"].ne("未知行业")
    )
    work = work[mask].copy()
    if work.empty:
        return work
    industry_size = work.groupby(["trade_date", "industry_bucket"])["ts_code"].transform("count")
    work = work[industry_size >= 4].copy()
    if work.empty:
        return work
    work["industry_relative_score"] = (
        _industry_rank(work, "drawdown_20", True) * 0.20
        + _industry_rank(work, "ret_5", False) * 0.15
        + _industry_rank(work, "ret_10", False) * 0.10
        + _industry_rank(work, "ret_20", False) * 0.10
        + _industry_rank(work, "volatility_20", False) * 0.10
        + _industry_rank(work, "turnover_rate", False) * 0.05
        + _industry_rank(work, "volume_ratio", False) * 0.05
        + _industry_rank(work, "rsi_14", False) * 0.10
        + _daily_rank(work, "industry_rs_20", True) * 0.15
    ).round(4)
    diversified = (
        work.sort_values(
            ["trade_date", "industry_bucket", "industry_relative_score", "ts_code"],
            ascending=[True, True, False, True],
        )
        .groupby(["trade_date", "industry_bucket"], group_keys=False)
        .head(per_industry)
    )
    selected = (
        diversified.sort_values(["trade_date", "industry_relative_score", "ts_code"], ascending=[True, False, True])
        .groupby("trade_date", group_keys=False)
        .head(topn)
        .drop_duplicates(["trade_date", "ts_code"])
        .copy()
    )
    selected["engine"] = "industry_relative_reversal"
    selected["engine_score"] = selected["industry_relative_score"]
    selected["engine_rank"] = selected.groupby("trade_date")["engine_score"].rank(ascending=False, method="first")
    return selected


def _prereg_hash() -> str:
    return hashlib.sha256(PREREG.read_bytes()).hexdigest()


def evaluate(candidates_path: Path = OUTPUT, report_path: Path = REPORT) -> None:
    frame, market = _prepare(candidates_path)
    trades, _ = walk_forward(
        frame,
        market,
        topn=2,
        rank_ridge=100.0,
        gate_ridge=100.0,
        gate_window_years=99,
        gate_quantile=0.8,
        cost=0.25,
        regime_mode="all",
    )
    train = _metrics(_period(trades, 2019, 2021))
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
    report_path.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(report_path.with_name(report_path.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    overlap.to_csv(report_path.with_name(report_path.stem + "_portfolio_path.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 预注册行业内相对超跌修复首次验证",
        "",
        f"- 预注册 SHA256：`{_prereg_hash()}`。",
        f"- 严格首次验证：{'通过' if strict_pass else '不通过'}。",
        f"- 验证期 Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于0概率 {p_nonpositive:.2%}。",
        f"- 真实重叠持仓最大回撤：{path_drawdown:.2f}%。",
        "",
        "## 分期结果",
        "",
        pd.DataFrame([{"period": "train", **train}, {"period": "validation", **validation}, {"period": "recent", **recent}]).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 逐年结果",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 重叠持仓路径",
        "",
        path_yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "- 本次运行后不得修改 v1 规则；失败结果原样保留。",
        "- 本研究未修改正式策略，也不生成交易执行代码。",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"prereg_sha256={_prereg_hash()}")
    print(f"strict_pass={strict_pass}")
    print(pd.DataFrame([{"period": "train", **train}, {"period": "validation", **validation}, {"period": "recent", **recent}]).to_string(index=False))
    print(yearly.to_string(index=False))
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f} path_drawdown={path_drawdown:.2f}")
    print(f"wrote={report_path}")


def run() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("registered_before_validation"):
        raise RuntimeError("预注册文件无效")
    dates = _available_dates(CACHE, "20160101", "20260630")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    frames = []
    for year in range(2016, 2027):
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", "20260630" if year == 2026 else f"{year}1231")
        candidates = build_candidates(panel)
        frames.append(candidates)
        print(f"year={year} panel={len(panel)} candidates={len(candidates)}")
    result = pd.concat(frames, ignore_index=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"rows={len(result)} dates={result['trade_date'].nunique()} wrote={OUTPUT}")
    evaluate(OUTPUT, REPORT)


if __name__ == "__main__":
    run()
