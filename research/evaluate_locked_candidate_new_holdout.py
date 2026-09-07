#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""使用新增未见时间样本评估已经锁定的逆向候选。"""

from __future__ import annotations

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
from research.contrarian_candidate_stress import max_drawdown  # noqa: E402
from research.contrarian_incremental_alpha import load_csi300_holding_returns  # noqa: E402
from research.full_market_contrarian_candidates import build_candidates  # noqa: E402
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio  # noqa: E402
from research.two_stage_walkforward_research import _metrics, _prepare, walk_forward  # noqa: E402


CACHE = ROOT / "data" / "cache"
HISTORICAL = ROOT / "reports" / "research" / "full_market_contrarian_top50_20260808.csv"
NEW_CANDIDATES = ROOT / "reports" / "research" / "contrarian_new_holdout_candidates_20260807.csv"
COMBINED = ROOT / "reports" / "research" / "contrarian_candidates_through_20260807.csv"
OUTPUT = ROOT / "reports" / "research" / "contrarian_locked_new_holdout_20260807.md"
FROZEN_CONFIG = {
    "topn": 2,
    "rank_ridge": 100.0,
    "gate_ridge": 100.0,
    "gate_window_years": 99,
    "gate_quantile": 0.8,
    "cost": 0.25,
    "regime_mode": "all",
}


def completed_holdout(frame: pd.DataFrame, start_date: str = "20260701") -> pd.DataFrame:
    result = frame.copy()
    result["trade_date"] = result["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    return result[(result["trade_date"] >= start_date) & pd.to_numeric(result["ret_5d"], errors="coerce").notna()].copy()


def run() -> None:
    dates = _available_dates(CACHE, "20160101", "20260807")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    panel = build_year_panel(CACHE, stock_info, regimes, dates, 2026, "20260701", "20260807")
    new_candidates = build_candidates(panel)
    NEW_CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    new_candidates.to_csv(NEW_CANDIDATES, index=False, encoding="utf-8-sig")

    historical = pd.read_csv(HISTORICAL, encoding="utf-8-sig", low_memory=False)
    combined = pd.concat([historical, new_candidates], ignore_index=True)
    combined["trade_date"] = combined["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    combined = combined.sort_values(["trade_date", "ts_code"]).drop_duplicates(["trade_date", "ts_code", "engine"], keep="last")
    combined.to_csv(COMBINED, index=False, encoding="utf-8-sig")

    frame, market = _prepare(COMBINED)
    trades, _ = walk_forward(frame, market, **FROZEN_CONFIG)
    holdout = completed_holdout(trades)
    metrics = _metrics(holdout)
    days = holdout.groupby("trade_date", as_index=False)["net_ret"].mean() if not holdout.empty else pd.DataFrame(columns=["trade_date", "net_ret"])
    portfolio_path = overlap_adjusted_portfolio(holdout, CACHE, cost=0.25) if not holdout.empty else pd.DataFrame()
    compounded = float(((1.0 + portfolio_path["net_ret"] / 100.0).prod() - 1.0) * 100.0) if not portfolio_path.empty else 0.0
    drawdown = max_drawdown(portfolio_path["net_ret"]) if not portfolio_path.empty else float("nan")

    benchmark = load_csi300_holding_returns(days["trade_date"].tolist()) if not days.empty else pd.DataFrame()
    if not benchmark.empty:
        alpha = days.merge(benchmark[["trade_date", "benchmark_ret"]], on="trade_date", how="inner")
        alpha["alpha_ret"] = alpha["net_ret"] - alpha["benchmark_ret"]
        alpha_mean = float(alpha["alpha_ret"].mean())
    else:
        alpha = pd.DataFrame()
        alpha_mean = float("nan")
    positive = holdout[pd.to_numeric(holdout["net_ret"], errors="coerce") > 0]
    remove_count = int(len(positive) * 0.05 + 0.999999)
    trimmed = holdout.drop(index=positive.nlargest(remove_count, "net_ret").index) if remove_count else holdout.copy()
    trimmed_metrics = _metrics(trimmed)
    month_count = holdout["trade_date"].astype(str).str[:6].nunique() if not holdout.empty else 0
    minimum_evidence = bool(
        metrics["trades"] >= 60
        and month_count >= 6
        and metrics["avg_net"] > 0
        and metrics["profit_factor"] > 1.10
        and trimmed_metrics["avg_net"] > 0
        and drawdown > -20.0
    )

    holdout.to_csv(OUTPUT.with_name(OUTPUT.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    days.to_csv(OUTPUT.with_name(OUTPUT.stem + "_days.csv"), index=False, encoding="utf-8-sig")
    portfolio_path.to_csv(OUTPUT.with_name(OUTPUT.stem + "_portfolio_path.csv"), index=False, encoding="utf-8-sig")
    alpha.to_csv(OUTPUT.with_name(OUTPUT.stem + "_alpha.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 锁定逆向候选新增未见时间样本",
        "",
        "- 样本区间：2026-07-01 至 2026-08-07；只纳入已经走满5个交易日的信号。",
        "- 参数完全读取锁定版本，未重新搜索或调参。",
        f"- 最低新增证据门槛：{'通过' if minimum_evidence else '不通过/样本不足'}。",
        f"- 交易 {int(metrics['trades'])} 笔、覆盖 {month_count} 个月，平均净收益 {metrics['avg_net']:+.4f}%，胜率 {metrics['win_rate']:.2%}，盈亏比 {metrics['profit_factor']:.4f}。",
        f"- 移除最大5%赢家后平均净收益 {trimmed_metrics['avg_net']:+.4f}%，盈亏比 {trimmed_metrics['profit_factor']:.4f}。",
        f"- 五袖套重叠持仓复利收益 {compounded:+.4f}%，最大回撤 {drawdown:.4f}%。",
        f"- 相对沪深300同期平均超额 {alpha_mean:+.4f}%。",
        "",
        "## 信号明细",
        "",
        holdout[[column for column in ["trade_date", "ts_code", "name", "industry", "ret_5d", "net_ret", "rank_prediction", "gate_prediction"] if column in holdout.columns]].to_markdown(index=False, floatfmt=".4f") if not holdout.empty else "无已完成信号。",
        "",
        "- 这是研究过程中首次读取的新增时间段，但不是锁定之后自然流逝产生的实盘前瞻样本，因此只能增强或削弱历史证据，不能替代6个月影子观察。",
        "- 本研究未修改正式策略，也不生成交易执行代码。",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"panel={len(panel)} new_candidates={len(new_candidates)} completed_trades={len(holdout)}")
    print(f"minimum_evidence={minimum_evidence} metrics={metrics} trimmed_metrics={trimmed_metrics} months={month_count}")
    print(f"compounded={compounded:.4f} drawdown={drawdown:.4f} alpha_mean={alpha_mean:.4f}")
    if not holdout.empty:
        print(holdout[[column for column in ["trade_date", "ts_code", "name", "industry", "net_ret"] if column in holdout.columns]].to_string(index=False))
    print(f"wrote={OUTPUT}")


if __name__ == "__main__":
    run()
