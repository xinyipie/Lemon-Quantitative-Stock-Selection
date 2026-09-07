#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全市场逆向候选的独立压力审计，不修改正式策略。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.high_confidence_abstention_audit import (
    concentration_metrics,
    non_overlapping_sleeves,
    overlap_adjusted_portfolio,
)
from research.two_stage_walkforward_research import (
    _bootstrap_probability,
    _metrics,
    _period,
    _prepare,
    walk_forward,
)


INPUT = ROOT / "reports" / "research" / "full_market_contrarian_top50_20260808.csv"
OUTPUT = ROOT / "reports" / "research" / "contrarian_candidate_stress_20260808.md"
CACHE_DIR = ROOT / "data" / "cache"

BASE_CONFIG = {
    "topn": 2,
    "rank_ridge": 100.0,
    "gate_ridge": 100.0,
    "gate_window_years": 99,
    "gate_quantile": 0.8,
    "cost": 0.25,
    "regime_mode": "all",
}


def max_drawdown(returns: pd.Series) -> float:
    """按逐日复利净值计算最大回撤百分比。"""
    values = pd.to_numeric(returns, errors="coerce").dropna()
    if values.empty:
        return float("nan")
    equity = (1.0 + values / 100.0).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min() * 100.0)


def annual_path_metrics(path: pd.DataFrame) -> pd.DataFrame:
    """汇总真实重叠组合路径的逐年收益与年内最大回撤。"""
    if path.empty:
        return pd.DataFrame(columns=["year", "days", "return_pct", "max_drawdown_pct"])
    frame = path.copy()
    frame["trade_date"] = frame["trade_date"].astype(str).str[:8]
    frame["year"] = frame["trade_date"].str[:4].astype(int)
    rows = []
    for year, group in frame.groupby("year"):
        values = pd.to_numeric(group["net_ret"], errors="coerce").dropna()
        rows.append(
            {
                "year": int(year),
                "days": int(len(values)),
                "return_pct": float(((1.0 + values / 100.0).prod() - 1.0) * 100.0),
                "max_drawdown_pct": max_drawdown(values),
            }
        )
    return pd.DataFrame(rows)


def candidate_passes_period_gate(metrics: dict, minimum_trades: int) -> bool:
    """统一的分期门槛，禁止靠某一年补偿其他亏损年份。"""
    return bool(
        metrics.get("trades", 0) >= minimum_trades
        and metrics.get("avg_net", 0) > 0
        and metrics.get("profit_factor", 0) > 1.10
        and metrics.get("positive_years", 0) == metrics.get("years", 0)
    )


def config_name(config: dict, horizon: int = 5) -> str:
    return (
        f"h{horizon}_top{config['topn']}_gr{config['gate_ridge']:g}"
        f"_gw{config['gate_window_years']}_q{config['gate_quantile']:.2f}"
        f"_m{config['regime_mode']}_c{config['cost']:.2f}"
    )


def run_config(frame: pd.DataFrame, market: pd.DataFrame, config: dict, horizon: int = 5):
    candidate_frame = frame.copy()
    if horizon != 5:
        candidate_frame["ret_5d"] = pd.to_numeric(candidate_frame[f"ret_{horizon}d"], errors="coerce")
        candidate_frame["relative_target"] = candidate_frame["ret_5d"] - candidate_frame.groupby("trade_date")["ret_5d"].transform("mean")
    trades, days = walk_forward(candidate_frame, market, **config)
    return trades, days


def period_rows(name: str, trades: pd.DataFrame) -> list[dict]:
    periods = (("train", 2019, 2021), ("validation", 2022, 2024), ("recent", 2025, 2026))
    return [
        {"name": name, "period": label, **_metrics(_period(trades, start, end))}
        for label, start, end in periods
    ]


def run(input_path: Path = INPUT, output: Path = OUTPUT) -> None:
    frame, market = _prepare(input_path)
    scenarios: list[tuple[str, dict, int]] = []
    for cost in (0.15, 0.25, 0.35, 0.50):
        config = {**BASE_CONFIG, "cost": cost}
        scenarios.append((config_name(config), config, 5))
    for topn in (3, 5):
        config = {**BASE_CONFIG, "topn": topn}
        scenarios.append((config_name(config), config, 5))
    for quantile in (0.65, 0.75):
        config = {**BASE_CONFIG, "gate_quantile": quantile}
        scenarios.append((config_name(config), config, 5))
    for window in (2, 3):
        config = {**BASE_CONFIG, "gate_window_years": window}
        scenarios.append((config_name(config), config, 5))
    for ridge in (10.0, 300.0):
        config = {**BASE_CONFIG, "gate_ridge": ridge}
        scenarios.append((config_name(config), config, 5))
    risk_on = {**BASE_CONFIG, "regime_mode": "risk_on"}
    scenarios.append((config_name(risk_on), risk_on, 5))
    for horizon in (3, 8):
        scenarios.append((config_name(BASE_CONFIG, horizon), BASE_CONFIG.copy(), horizon))

    metric_rows: list[dict] = []
    scenario_trades: dict[str, pd.DataFrame] = {}
    for name, config, horizon in scenarios:
        trades, _ = run_config(frame, market, config, horizon)
        scenario_trades[name] = trades
        metric_rows.extend(period_rows(name, trades))
    metrics = pd.DataFrame(metric_rows)

    base_name = config_name(BASE_CONFIG)
    base_trades = scenario_trades[base_name]
    base_days = base_trades.groupby("trade_date", as_index=False)["net_ret"].mean()
    validation_days = _period(base_days, 2022, 2024)
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(validation_days, block=20, repetitions=10000)

    sleeve_rows = []
    for offset, sleeve in non_overlapping_sleeves(validation_days, spacing=5).items():
        values = pd.to_numeric(sleeve["net_ret"], errors="coerce").dropna()
        sleeve_rows.append(
            {
                "sleeve": offset,
                "days": len(values),
                "avg_net": float(values.mean()) if len(values) else np.nan,
                "profit_factor": float(values[values > 0].sum() / abs(values[values < 0].sum())) if (values < 0).any() else np.inf,
                "total_return": float(((1.0 + values / 100.0).prod() - 1.0) * 100.0) if len(values) else np.nan,
            }
        )
    sleeves = pd.DataFrame(sleeve_rows)

    overlap_path = overlap_adjusted_portfolio(base_trades, CACHE_DIR, cost=BASE_CONFIG["cost"])
    path_yearly = annual_path_metrics(overlap_path)
    path_total_return = float(((1.0 + overlap_path["net_ret"] / 100.0).prod() - 1.0) * 100.0) if not overlap_path.empty else np.nan
    path_drawdown = max_drawdown(overlap_path["net_ret"]) if not overlap_path.empty else np.nan
    concentration = concentration_metrics(base_trades)

    yearly = base_trades.assign(year=base_trades["trade_date"].astype(str).str[:4].astype(int)).groupby("year").apply(
        lambda group: pd.Series(_metrics(group)), include_groups=False
    ).reset_index()

    base_periods = metrics[metrics["name"].eq(base_name)].set_index("period")
    period_gate = all(
        candidate_passes_period_gate(base_periods.loc[label].to_dict(), minimum)
        for label, minimum in (("train", 150), ("validation", 150), ("recent", 60))
    )
    cost_gate = all(
        candidate_passes_period_gate(
            metrics[(metrics["name"].eq(config_name({**BASE_CONFIG, "cost": cost}))) & metrics["period"].eq("validation")].iloc[0].to_dict(),
            150,
        )
        for cost in (0.35, 0.50)
    )
    neighbor_names = [
        name for name, _, horizon in scenarios
        if horizon == 5 and name not in {config_name({**BASE_CONFIG, "cost": cost}) for cost in (0.15, 0.25, 0.35, 0.50)}
    ]
    neighbor_validation = metrics[metrics["name"].isin(neighbor_names) & metrics["period"].eq("validation")]
    neighbor_pass_count = int(sum(candidate_passes_period_gate(row._asdict(), 120) for row in neighbor_validation.itertuples(index=False)))
    sleeve_gate = bool((sleeves["avg_net"] > 0).sum() >= 4 and (sleeves["profit_factor"] > 1.0).sum() >= 4)
    path_gate = bool(
        not path_yearly.empty
        and (path_yearly[path_yearly["year"].between(2022, 2024)]["return_pct"] > 0).all()
        and path_drawdown > -20.0
    )
    concentration_gate = bool(
        concentration["largest_stock_positive_share"] < 0.10
        and concentration["largest_industry_positive_share"] < 0.25
    )
    statistical_gate = bool(ci_low > 0 and p_nonpositive < 0.05)
    # 该参数是在查看验证期搜索面后锁定，因此即使数值门槛全过，也只能进入前瞻影子观察。
    numeric_pass = bool(period_gate and cost_gate and neighbor_pass_count >= 5 and sleeve_gate and path_gate and concentration_gate and statistical_gate)
    formal_pass = False

    output.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output.with_name(output.stem + "_scenarios.csv"), index=False, encoding="utf-8-sig")
    yearly.to_csv(output.with_name(output.stem + "_yearly.csv"), index=False, encoding="utf-8-sig")
    sleeves.to_csv(output.with_name(output.stem + "_sleeves.csv"), index=False, encoding="utf-8-sig")
    overlap_path.to_csv(output.with_name(output.stem + "_portfolio_path.csv"), index=False, encoding="utf-8-sig")
    base_trades.to_csv(output.with_name(output.stem + "_trades.csv"), index=False, encoding="utf-8-sig")

    lines = [
        "# 全市场逆向候选压力审计",
        "",
        "## 结论",
        "",
        f"- 数值压力门槛：{'通过' if numeric_pass else '不通过'}。",
        f"- 正式策略接入门槛：{'通过' if formal_pass else '不通过'}。该参数是在查看 2022-2024 验证结果后发现，验证集已被污染，只允许继续研究或前瞻影子观察。",
        f"- Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于 0 的概率 {p_nonpositive:.2%}。",
        f"- 邻域通过数：{neighbor_pass_count}/{len(neighbor_validation)}；五个不重叠袖套通过：{'是' if sleeve_gate else '否'}。",
        f"- 重叠持仓路径总收益：{path_total_return:+.2f}%，最大回撤：{path_drawdown:.2f}%；路径门槛：{'通过' if path_gate else '不通过'}。",
        f"- 最大个股正贡献占比：{concentration['largest_stock_positive_share']:.2%}；最大行业正贡献占比：{concentration['largest_industry_positive_share']:.2%}。",
        "",
        "## 基准候选逐年结果",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 参数、成本与持有期扰动",
        "",
        metrics.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 五个互不重叠交易袖套（独立验证期）",
        "",
        sleeves.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 真实重叠持仓路径逐年结果",
        "",
        path_yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 研究约束",
        "",
        "- 所有股票排序和择时模型均按逐年走步，只读取测试年度之前的数据。",
        "- 收益从 T+1 开盘开始计算，基准结果扣除双边合计 0.25% 成本。",
        "- 参数后验发现造成的验证污染不会用更多漂亮指标掩盖；下一步必须改用训练期可定义的动态选择规则或新增前瞻样本。",
        "- 本研究没有修改正式策略，也不生成任何交易执行代码。",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"numeric_pass={numeric_pass}")
    print(f"formal_pass={formal_pass}")
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f}")
    print(f"neighbor_pass={neighbor_pass_count}/{len(neighbor_validation)}")
    print(f"path_return={path_total_return:.2f} path_drawdown={path_drawdown:.2f}")
    print(yearly.to_string(index=False))
    print(f"wrote={output}")


if __name__ == "__main__":
    run()
