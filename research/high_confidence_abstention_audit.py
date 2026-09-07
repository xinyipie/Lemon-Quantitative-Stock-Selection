from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research.two_stage_walkforward_research import (
    DEFAULT_INPUT,
    _bootstrap_probability,
    _metrics,
    _period,
    _prepare,
    walk_forward,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports" / "research" / "high_confidence_abstention_audit_20260807.md"
PRIMARY = {
    "topn": 4,
    "rank_ridge": 100.0,
    "gate_ridge": 100.0,
    "gate_window_years": 99,
    "gate_quantile": 0.85,
    "cost": 0.25,
    "regime_mode": "risk_on",
    "target_clip": 0.0,
    "target_mode": "raw",
}


def non_overlapping_sleeves(days: pd.DataFrame, spacing: int = 5) -> dict[int, pd.DataFrame]:
    ordered = days.sort_values("trade_date").reset_index(drop=True)
    return {offset: ordered.iloc[offset::spacing].copy() for offset in range(spacing)}


def concentration_metrics(trades: pd.DataFrame) -> dict[str, float]:
    positive = trades[pd.to_numeric(trades["net_ret"], errors="coerce") > 0].copy()
    total = float(positive["net_ret"].sum())
    if total <= 0:
        return {"largest_stock_positive_share": np.nan, "largest_industry_positive_share": np.nan}
    stock = positive.groupby("ts_code")["net_ret"].sum()
    industry = positive.groupby(positive.get("industry", pd.Series("未知", index=positive.index)).fillna("未知"))["net_ret"].sum()
    return {
        "largest_stock_positive_share": float(stock.max() / total),
        "largest_industry_positive_share": float(industry.max() / total),
    }


def _daily(trades: pd.DataFrame) -> pd.DataFrame:
    return trades.groupby("trade_date", as_index=False)["net_ret"].mean()


def _max_drawdown(values: pd.Series) -> float:
    equity = (1 + pd.to_numeric(values, errors="coerce").fillna(0) / 100).cumprod()
    drawdown = equity / equity.cummax() - 1
    return float(drawdown.min() * 100) if len(drawdown) else np.nan


def overlap_adjusted_portfolio(trades: pd.DataFrame, cache_dir: Path, cost: float = 0.25) -> pd.DataFrame:
    daily_dir = cache_dir / "daily"
    calendar = sorted(path.stem for path in daily_dir.glob("*.parquet"))
    position = {date: index for index, date in enumerate(calendar)}
    contributions: dict[str, float] = {}
    frame_cache: dict[str, pd.Series] = {}

    for signal_date, cohort in trades.groupby("trade_date"):
        signal_date = str(signal_date)
        start = position.get(signal_date)
        if start is None:
            continue
        holding_dates = calendar[start + 1 : start + 6]
        if len(holding_dates) < 5:
            continue
        cohort = cohort.drop_duplicates("ts_code")
        cohort_size = len(cohort)
        if cohort_size == 0:
            continue
        previous = {
            str(row.ts_code): float(row.entry_open)
            for row in cohort.itertuples(index=False)
            if pd.notna(row.entry_open) and float(row.entry_open) > 0
        }
        for day_index, date in enumerate(holding_dates):
            if date not in frame_cache:
                try:
                    daily = pd.read_parquet(daily_dir / f"{date}.parquet", columns=["ts_code", "close"])
                    frame_cache[date] = daily.set_index("ts_code")["close"]
                except Exception:
                    frame_cache[date] = pd.Series(dtype=float)
            close_map = frame_cache[date]
            stock_returns = []
            for code, prior_close in list(previous.items()):
                close = pd.to_numeric(pd.Series([close_map.get(code)]), errors="coerce").iloc[0]
                if pd.isna(close) or prior_close <= 0:
                    continue
                daily_return = (float(close) / prior_close - 1) * 100
                # 总成本在建仓和退出各扣一半，仅用于组合级压力评估。
                if day_index in (0, 4):
                    daily_return -= cost / 2
                stock_returns.append(daily_return)
                previous[code] = float(close)
            if stock_returns:
                contributions[date] = contributions.get(date, 0.0) + float(np.mean(stock_returns)) / 5.0
    result = pd.DataFrame(sorted(contributions.items()), columns=["trade_date", "net_ret"])
    if not result.empty:
        result["year"] = result["trade_date"].str[:4]
    return result


def _config_name(config: dict) -> str:
    return (
        f"top{config['topn']}_gr{config['gate_ridge']:g}_gw{config['gate_window_years']}_"
        f"q{config['gate_quantile']:.2f}_m{config.get('regime_mode', 'all')}_tm{config.get('target_mode', 'raw')}_"
        f"tc{config.get('target_clip', 0):g}_c{config['cost']:.2f}"
    )


def run() -> None:
    frame, market = _prepare(DEFAULT_INPUT)
    configs: list[dict] = []
    for topn in (2, 3, 4, 5):
        for gate_ridge in (10.0, 100.0):
            for window in (3, 99):
                for quantile in (0.75, 0.80, 0.85, 0.90):
                    for regime_mode in ("risk_on", "all"):
                        configs.append(
                            {
                                "topn": topn,
                                "rank_ridge": 100.0,
                                "gate_ridge": gate_ridge,
                                "gate_window_years": window,
                                "gate_quantile": quantile,
                                "cost": 0.25,
                                "regime_mode": regime_mode,
                                "target_clip": 0.0,
                                "target_mode": "raw",
                            }
                        )
    # 局部目标截尾扰动只围绕正式候选区域运行，真实收益评估不截尾。
    for target_mode, target_clip in (("raw", 0.0), ("raw", 8.0), ("raw", 10.0), ("raw", 12.0)):
        for topn in (3, 4, 5):
            for gate_ridge in (10.0, 100.0):
                for quantile in (0.75, 0.80, 0.85):
                    configs.append(
                        {
                            **PRIMARY,
                            "topn": topn,
                            "gate_ridge": gate_ridge,
                            "gate_quantile": quantile,
                            "target_clip": target_clip,
                            "target_mode": target_mode,
                        }
                    )
    for cost in (0.15, 0.35, 0.50):
        configs.append({**PRIMARY, "cost": cost})

    rows = []
    primary_trades = pd.DataFrame()
    for config in configs:
        trades, _ = walk_forward(frame, market, **config)
        name = _config_name(config)
        if config == PRIMARY:
            primary_trades = trades.copy()
        rows.append(
            {
                "name": name,
                **{f"train_{key}": value for key, value in _metrics(_period(trades, 2019, 2021)).items()},
                **{f"validation_{key}": value for key, value in _metrics(_period(trades, 2022, 2024)).items()},
                **{f"recent_{key}": value for key, value in _metrics(_period(trades, 2025, 2026)).items()},
            }
        )
    stress = pd.DataFrame(rows).drop_duplicates("name")
    primary_days = _daily(primary_trades)
    validation_days = _period(primary_days, 2022, 2024)
    ci_low, ci_high, probability = _bootstrap_probability(validation_days)
    yearly = primary_trades.assign(year=primary_trades["trade_date"].str[:4]).groupby("year").apply(
        lambda group: pd.Series(_metrics(group)), include_groups=False
    ).reset_index()
    sleeves = []
    for offset, sleeve in non_overlapping_sleeves(primary_days).items():
        metrics = _metrics(sleeve)
        sleeves.append({"sleeve": offset + 1, **metrics, "max_drawdown": _max_drawdown(sleeve["net_ret"])})
    sleeve_frame = pd.DataFrame(sleeves)
    concentration = concentration_metrics(primary_trades)
    portfolio = overlap_adjusted_portfolio(primary_trades, ROOT / "data" / "cache", cost=PRIMARY["cost"])
    portfolio_drawdown = _max_drawdown(portfolio["net_ret"]) if not portfolio.empty else np.nan
    portfolio_yearly = (
        portfolio.groupby("year")["net_ret"].apply(lambda values: (np.prod(1 + values / 100) - 1) * 100).reset_index(name="compounded_ret")
        if not portfolio.empty
        else pd.DataFrame()
    )

    neighbor = stress[
        stress["name"].str.match(r"top[345]_gr(10|100)_gw99_q0\.(80|85|90)_mrisk_on_tmraw_tc0_c0\.25")
    ]
    neighbor_pass = (
        (neighbor["validation_avg_net"] > 0)
        & (neighbor["validation_profit_factor"] > 1.05)
        & (neighbor["validation_positive_years"] == 3)
    )
    cost50 = stress[stress["name"].eq(_config_name({**PRIMARY, "cost": 0.50}))].iloc[0]
    primary_row = stress[stress["name"].eq(_config_name(PRIMARY))].iloc[0]
    strict_pass = bool(
        primary_row["train_positive_years"] == 3
        and primary_row["validation_positive_years"] == 3
        and primary_row["recent_positive_years"] == 2
        and primary_row["validation_profit_factor"] > 1.15
        and probability < 0.10
        and neighbor_pass.mean() >= 0.60
        and (sleeve_frame["avg_net"] > 0).sum() == 5
        and sleeve_frame["max_drawdown"].min() >= -45
        and portfolio_drawdown >= -20
        and cost50["validation_avg_net"] > 0
        and concentration["largest_stock_positive_share"] < 0.10
        and concentration["largest_industry_positive_share"] < 0.30
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    stress.to_csv(OUTPUT.with_name(OUTPUT.stem + "_stress.csv"), index=False, encoding="utf-8-sig")
    primary_trades.to_csv(OUTPUT.with_name(OUTPUT.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 高置信度稀疏出手候选审计",
        "",
        "## 结论",
        "",
        f"- 严格验收：{'通过' if strict_pass else '不通过'}。",
        "- 主方案固定为 `Top4 + 排除BEAR_TREND + 全历史择时窗口 + 预测最强15%日期 + 原始相对收益目标 + 0.25%成本`。",
        f"- 相邻参数通过率：{neighbor_pass.mean():.2%}；验证期 bootstrap 均值不大于0概率：{probability:.2%}。",
        f"- 验证期 bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%。",
        f"- 单只股票占正收益最大比例：{concentration['largest_stock_positive_share']:.2%}；单一行业最大比例：{concentration['largest_industry_positive_share']:.2%}。",
        f"- 按真实逐日路径重建的五批次交叠观察净值最大回撤：{portfolio_drawdown:.2f}%。",
        "",
        "## 主方案逐年",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 五组不重叠持仓序列",
        "",
        sleeve_frame.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 交叠观察净值逐年",
        "",
        portfolio_yearly.to_markdown(index=False, floatfmt=".4f") if not portfolio_yearly.empty else "无可用路径",
        "",
        "## 参数与成本压力",
        "",
        stress.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 限制",
        "",
        "- 该候选是在多轮研究后识别出的高置信度子区域，仍存在研究者自由度偏差。",
        "- 即使通过历史验收，也应先以影子策略记录未来信号，不应直接替换正式策略。",
        "- 本研究只定义选股与观察，不包含自动交易或仓位执行。",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"strict_pass={strict_pass}")
    print(f"neighbor_pass={neighbor_pass.mean():.4f}")
    print(f"bootstrap=({ci_low:.4f},{ci_high:.4f}) p={probability:.4f}")
    print(f"concentration={concentration}")
    print(yearly.to_string(index=False))
    print(sleeve_frame.to_string(index=False))
    print(f"wrote={OUTPUT}")


if __name__ == "__main__":
    run()
