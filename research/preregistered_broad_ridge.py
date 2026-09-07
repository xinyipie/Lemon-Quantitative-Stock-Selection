#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""预注册宽流动性候选池双层 Ridge 首次验证。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown  # noqa: E402
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio  # noqa: E402
from research.two_stage_walkforward_research import (  # noqa: E402
    _bootstrap_probability,
    _metrics,
    _period,
    _prepare,
    walk_forward,
)


INPUT = ROOT / "reports" / "research" / "nonlinear_broad_candidates_20260808.csv"
PREREG = ROOT / "reports" / "research" / "prereg_broad_ridge_walkforward_20260808.json"
OUTPUT = ROOT / "reports" / "research" / "broad_ridge_walkforward_validation_20260808.md"
CACHE = ROOT / "data" / "cache"
FROZEN_CONFIG = {
    "topn": 2,
    "rank_ridge": 100.0,
    "gate_ridge": 100.0,
    "gate_window_years": 99,
    "gate_quantile": 0.8,
    "cost": 0.25,
    "regime_mode": "all",
}


def run(input_path: Path = INPUT, output: Path = OUTPUT) -> None:
    prereg_hash = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    source = pd.read_csv(input_path, encoding="utf-8-sig", low_memory=False)
    source["engine"] = "broad_liquid"
    source["engine_score"] = pd.to_numeric(source["amount"], errors="coerce")
    source["engine_rank"] = source.groupby("trade_date")["engine_score"].rank(ascending=False, method="first")
    prepared_path = output.with_name(output.stem + "_prepared_candidates.csv")
    source.to_csv(prepared_path, index=False, encoding="utf-8-sig")
    frame, market = _prepare(prepared_path)
    trades, _ = walk_forward(frame, market, **FROZEN_CONFIG)
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
    output.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(output.with_name(output.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    overlap.to_csv(output.with_name(output.stem + "_portfolio_path.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 预注册宽候选池双层 Ridge 首次验证",
        "",
        f"- 预注册 SHA256：`{prereg_hash}`。",
        f"- 严格首次验证：{'通过' if strict_pass else '不通过'}。",
        f"- 验证期 Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于0概率 {p_nonpositive:.2%}。",
        f"- 真实重叠持仓最大回撤：{path_drawdown:.2f}%。",
        "",
        pd.DataFrame([{"period": "train_oos", **train}, {"period": "validation", **validation}, {"period": "recent", **recent}]).to_markdown(index=False, floatfmt=".4f"),
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        path_yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "- v1首次验证后不得改参，失败结果原样保留。",
        "- 本研究未修改正式策略，也不生成交易执行代码。",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"prereg_sha256={prereg_hash} strict_pass={strict_pass}")
    print(pd.DataFrame([{"period": "train_oos", **train}, {"period": "validation", **validation}, {"period": "recent", **recent}]).to_string(index=False))
    print(yearly.to_string(index=False))
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f} path_drawdown={path_drawdown:.2f}")
    print(f"wrote={output}")


if __name__ == "__main__":
    run()
