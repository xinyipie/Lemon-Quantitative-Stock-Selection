#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""使用历史稳定配置共识而非单一最优参数的逆向策略研究。"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown  # noqa: E402
from research.contrarian_dynamic_selector import build_all_config_results  # noqa: E402
from research.high_confidence_abstention_audit import concentration_metrics, overlap_adjusted_portfolio  # noqa: E402
from research.two_stage_walkforward_research import (  # noqa: E402
    _bootstrap_probability,
    _metrics,
    _period,
    _prepare,
)


INPUT = ROOT / "reports" / "research" / "full_market_contrarian_top50_20260808.csv"
OUTPUT = ROOT / "reports" / "research" / "contrarian_consensus_selector_20260808.md"
CACHE_DIR = ROOT / "data" / "cache"


def eligible_names(annual: pd.DataFrame, target_year: int) -> list[str]:
    """只允许此前三年每年为正且样本充足的配置参与目标年投票。"""
    start = target_year - 3
    history = annual[annual["year"].between(start, target_year - 1)].copy()
    names = []
    for name, group in history.groupby("name"):
        if set(group["year"].astype(int)) != set(range(start, target_year)):
            continue
        if (pd.to_numeric(group["trades"], errors="coerce") < 15).any():
            continue
        if (pd.to_numeric(group["avg_net"], errors="coerce") <= 0).any():
            continue
        if (pd.to_numeric(group["profit_factor"], errors="coerce") <= 1.0).any():
            continue
        names.append(str(name))
    return sorted(names)


def build_consensus_for_year(
    rows: pd.DataFrame,
    *,
    vote_share: float = 0.5,
    min_votes: int = 3,
    topn: int = 2,
    cost: float = 0.25,
) -> pd.DataFrame:
    """在每个信号日按独立配置数投票，避免重复记录放大票数。"""
    if rows.empty:
        return rows.copy()
    frame = rows.drop_duplicates(["trade_date", "ts_code", "selected_config"]).copy()
    active = frame.groupby("trade_date")["selected_config"].nunique().rename("active_configs")
    votes = frame.groupby(["trade_date", "ts_code"]).agg(
        vote_count=("selected_config", "nunique"),
        mean_rank_prediction=("rank_prediction", "mean"),
    ).reset_index()
    votes = votes.merge(active, on="trade_date", how="left")
    votes["vote_share"] = votes["vote_count"] / votes["active_configs"].clip(lower=1)
    votes = votes[(votes["vote_count"] >= min_votes) & (votes["vote_share"] >= vote_share)].copy()
    votes = votes.sort_values(
        ["trade_date", "vote_count", "vote_share", "mean_rank_prediction", "ts_code"],
        ascending=[True, False, False, False, True],
    )
    votes = votes.groupby("trade_date", as_index=False).head(topn)
    representative = frame.sort_values(["trade_date", "ts_code", "selected_config"]).drop_duplicates(["trade_date", "ts_code"])
    selected = votes.merge(representative, on=["trade_date", "ts_code"], how="left")
    selected["net_ret"] = pd.to_numeric(selected["ret_5d"], errors="coerce") - cost
    return selected


def nested_consensus(trades_by_name: dict[str, pd.DataFrame], annual: pd.DataFrame, vote_share: float = 0.5):
    selected = []
    audit = []
    for target_year in range(2022, 2027):
        names = eligible_names(annual, target_year)
        target_rows = []
        for name in names:
            trades = trades_by_name[name]
            current = trades[trades["trade_date"].astype(str).str[:4].eq(str(target_year))].copy()
            if current.empty:
                continue
            current["selected_config"] = name
            target_rows.append(current)
        combined = pd.concat(target_rows, ignore_index=True) if target_rows else pd.DataFrame()
        consensus = build_consensus_for_year(combined, vote_share=vote_share, min_votes=3, topn=2, cost=0.25)
        if not consensus.empty:
            consensus["test_year"] = target_year
            selected.append(consensus)
        audit.append(
            {
                "target_year": target_year,
                "history_start": target_year - 3,
                "history_end": target_year - 1,
                "eligible_configs": len(names),
                "raw_votes": len(combined),
                "consensus_trades": len(consensus),
                "consensus_days": consensus["trade_date"].nunique() if not consensus.empty else 0,
            }
        )
    return (pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()), pd.DataFrame(audit)


def run(input_path: Path = INPUT, output: Path = OUTPUT) -> None:
    frame, market = _prepare(input_path)
    trades_by_name, annual = build_all_config_results(frame, market, cost=0.25)
    selected, audit = nested_consensus(trades_by_name, annual, vote_share=0.5)
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
    concentration = concentration_metrics(selected)
    validation_path = path_yearly[path_yearly["year"].between(2022, 2024)]
    historical_pass = bool(
        validation_metrics["trades"] >= 100
        and validation_metrics["avg_net"] > 0
        and validation_metrics["profit_factor"] > 1.10
        and validation_metrics["positive_years"] == validation_metrics["years"] == 3
        and recent_metrics["trades"] >= 40
        and recent_metrics["avg_net"] > 0
        and recent_metrics["profit_factor"] > 1.10
        and recent_metrics["positive_years"] == recent_metrics["years"] == 2
        and ci_low > 0
        and p_nonpositive < 0.05
        and len(validation_path) == 3
        and (validation_path["return_pct"] > 0).all()
        and path_drawdown > -20.0
        and concentration["largest_stock_positive_share"] < 0.10
        and concentration["largest_industry_positive_share"] < 0.25
    )
    ready_for_shadow = False

    output.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output.with_name(output.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    audit.to_csv(output.with_name(output.stem + "_audit.csv"), index=False, encoding="utf-8-sig")
    overlap.to_csv(output.with_name(output.stem + "_portfolio_path.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 全市场逆向策略历史稳定配置共识",
        "",
        "## 结论",
        "",
        f"- 无目标年泄漏的历史验收：{'通过' if historical_pass else '不通过'}。",
        f"- 可进入影子策略：{'是' if ready_for_shadow else '否'}。成本与投票阈值扰动通过前保持研究状态。",
        f"- 验证期 Bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于 0 的概率 {p_nonpositive:.2%}。",
        f"- 真实重叠持仓路径最大回撤：{path_drawdown:.2f}%。",
        f"- 最大个股/行业正贡献占比：{concentration['largest_stock_positive_share']:.2%} / {concentration['largest_industry_positive_share']:.2%}。",
        "",
        "## 逐年投票审计",
        "",
        audit.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 逐年结果",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 重叠持仓路径",
        "",
        path_yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 方法约束",
        "",
        "- 目标年只能由此前三年每年为正的配置参与投票。",
        "- 每个股票每个配置最多一票；至少三票且占当日活跃配置半数才保留。",
        "- 目标年收益不参与资格判断或投票阈值调整。",
        "- 本研究没有修改正式策略，也没有生成交易执行代码。",
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
