#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全市场逆向策略的嵌套逐年参数选择研究。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.high_confidence_abstention_audit import overlap_adjusted_portfolio  # noqa: E402
from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown  # noqa: E402
from research.two_stage_walkforward_research import (  # noqa: E402
    _bootstrap_probability,
    _metrics,
    _period,
    _prepare,
    walk_forward,
)


INPUT = ROOT / "reports" / "research" / "full_market_contrarian_top50_20260808.csv"
OUTPUT = ROOT / "reports" / "research" / "contrarian_dynamic_selector_20260808.md"
CACHE_DIR = ROOT / "data" / "cache"


def config_name(config: dict) -> str:
    return (
        f"top{config['topn']}_gr{config['gate_ridge']:g}_gw{config['gate_window_years']}"
        f"_q{config['gate_quantile']:.2f}_m{config['regime_mode']}"
    )


def config_grid(cost: float = 0.25) -> list[dict]:
    """使用研究开始前已存在的离散网格，不为目标年份新增特例。"""
    rows = []
    for topn in (2, 3, 5):
        for gate_ridge in (10.0, 100.0):
            for gate_window_years in (2, 3, 99):
                for gate_quantile in (0.50, 0.65, 0.80):
                    for regime_mode in ("all", "risk_on", "bull_only"):
                        rows.append(
                            {
                                "topn": topn,
                                "rank_ridge": 100.0,
                                "gate_ridge": gate_ridge,
                                "gate_window_years": gate_window_years,
                                "gate_quantile": gate_quantile,
                                "cost": cost,
                                "regime_mode": regime_mode,
                            }
                        )
    return rows


def choose_config(annual: pd.DataFrame, target_year: int) -> tuple[str | None, dict]:
    """按此前三年最差年度优先选择配置，目标年不得进入裁决。"""
    start = target_year - 3
    history = annual[annual["year"].between(start, target_year - 1)].copy()
    rows = []
    for name, group in history.groupby("name"):
        if set(group["year"].astype(int)) != set(range(start, target_year)):
            continue
        if (pd.to_numeric(group["trades"], errors="coerce") < 15).any():
            continue
        if (pd.to_numeric(group["avg_net"], errors="coerce") <= 0).any():
            continue
        if (pd.to_numeric(group["profit_factor"], errors="coerce") <= 1.0).any():
            continue
        rows.append(
            {
                "name": name,
                "worst_year_avg": float(group["avg_net"].min()),
                "mean_year_avg": float(group["avg_net"].mean()),
                "worst_year_pf": float(group["profit_factor"].min()),
                "history_trades": int(group["trades"].sum()),
            }
        )
    audit = {"target_year": target_year, "history_start": start, "history_end": target_year - 1, "eligible": len(rows)}
    if not rows:
        return None, audit
    ranked = pd.DataFrame(rows).sort_values(
        ["worst_year_avg", "worst_year_pf", "mean_year_avg", "history_trades", "name"],
        ascending=[False, False, False, False, True],
    )
    chosen = ranked.iloc[0]
    audit.update(chosen.to_dict())
    return str(chosen["name"]), audit


def build_all_config_results(frame: pd.DataFrame, market: pd.DataFrame, cost: float = 0.25):
    trades_by_name: dict[str, pd.DataFrame] = {}
    annual_rows = []
    for config in config_grid(cost):
        name = config_name(config)
        trades, _ = walk_forward(frame, market, **config)
        trades_by_name[name] = trades
        for year in range(2019, 2027):
            year_trades = trades[trades["trade_date"].astype(str).str[:4].eq(str(year))]
            annual_rows.append({"name": name, "year": year, **_metrics(year_trades)})
    return trades_by_name, pd.DataFrame(annual_rows)


def nested_select(trades_by_name: dict[str, pd.DataFrame], annual: pd.DataFrame):
    selected = []
    audits = []
    for target_year in range(2022, 2027):
        name, audit = choose_config(annual, target_year)
        audits.append(audit)
        if name is None:
            continue
        source = trades_by_name[name]
        target = source[source["trade_date"].astype(str).str[:4].eq(str(target_year))].copy()
        target["selected_config"] = name
        selected.append(target)
    return (pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()), pd.DataFrame(audits)


def run(input_path: Path = INPUT, output: Path = OUTPUT) -> None:
    frame, market = _prepare(input_path)
    trades_by_name, annual = build_all_config_results(frame, market, cost=0.25)
    selected, audit = nested_select(trades_by_name, annual)
    validation = _period(selected, 2022, 2024)
    recent = _period(selected, 2025, 2026)
    validation_metrics = _metrics(validation)
    recent_metrics = _metrics(recent)
    yearly = selected.assign(year=selected["trade_date"].astype(str).str[:4].astype(int)).groupby("year").apply(
        lambda group: pd.Series(_metrics(group)), include_groups=False
    ).reset_index()

    validation_days = validation.groupby("trade_date", as_index=False)["net_ret"].mean()
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(validation_days, block=20, repetitions=10000)
    overlap = overlap_adjusted_portfolio(selected, CACHE_DIR, cost=0.25)
    path_yearly = annual_path_metrics(overlap)
    path_drawdown = max_drawdown(overlap["net_ret"]) if not overlap.empty else np.nan

    validation_path = path_yearly[path_yearly["year"].between(2022, 2024)]
    validation_pass = bool(
        validation_metrics["trades"] >= 150
        and validation_metrics["avg_net"] > 0
        and validation_metrics["profit_factor"] > 1.10
        and validation_metrics["positive_years"] == validation_metrics["years"] == 3
        and ci_low > 0
        and p_nonpositive < 0.05
    )
    recent_pass = bool(
        recent_metrics["trades"] >= 50
        and recent_metrics["avg_net"] > 0
        and recent_metrics["profit_factor"] > 1.10
        and recent_metrics["positive_years"] == recent_metrics["years"] == 2
    )
    path_pass = bool(
        len(validation_path) == 3
        and (validation_path["return_pct"] > 0).all()
        and path_drawdown > -20.0
    )
    historical_pass = bool(validation_pass and recent_pass and path_pass)
    # 选择规则是在本轮研究中新增，仍需成本和规则扰动压力测试后才能成为影子策略候选。
    ready_for_shadow = False

    output.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(output.with_name(output.stem + "_config_yearly.csv"), index=False, encoding="utf-8-sig")
    audit.to_csv(output.with_name(output.stem + "_selection_audit.csv"), index=False, encoding="utf-8-sig")
    selected.to_csv(output.with_name(output.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    overlap.to_csv(output.with_name(output.stem + "_portfolio_path.csv"), index=False, encoding="utf-8-sig")

    lines = [
        "# 全市场逆向策略嵌套逐年选择",
        "",
        "## 结论",
        "",
        f"- 无目标年泄漏的历史验收：{'通过' if historical_pass else '不通过'}。",
        f"- 可进入影子策略：{'是' if ready_for_shadow else '否'}。完成成本与选择规则扰动前不得接入正式策略。",
        f"- 验证期 Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于 0 的概率 {p_nonpositive:.2%}。",
        f"- 真实重叠持仓路径最大回撤：{path_drawdown:.2f}%。",
        "",
        "## 每年事前配置选择",
        "",
        audit.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 逐年样本外结果",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 真实重叠持仓路径",
        "",
        path_yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 方法约束",
        "",
        "- 每个目标年只使用此前三年已经产生的逐年样本外结果选择配置。",
        "- 选择目标是最大化此前三年中最差年度的日均净收益，并要求此前三年均为正。",
        "- 目标年度的收益、胜率或盈亏比不参与该年度配置选择。",
        "- 当前仍是研究结果，没有修改正式策略，也没有生成交易执行代码。",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"historical_pass={historical_pass}")
    print(f"ready_for_shadow={ready_for_shadow}")
    print(audit.to_string(index=False))
    print(yearly.to_string(index=False))
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f}")
    print(f"path_drawdown={path_drawdown:.2f}")
    print(f"wrote={output}")


if __name__ == "__main__":
    run()
