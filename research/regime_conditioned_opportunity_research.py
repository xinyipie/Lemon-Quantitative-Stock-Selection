"""按既有市场状态检验全市场短线机会信号的稳定性。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import all_market_multi_engine_research as market_research
from research.all_market_opportunity_archetypes import assign_feature_bins
from research.opportunity_archetype_ranking_research import (
    FROZEN_PROFILES,
    RANK_SPECS,
    select_ranked_candidates,
)


SPLITS = {
    "train": ("20160101", "20211231"),
    "validation": ("20220101", "20241231"),
    "observed": ("20250101", "20260630"),
}

REGIME_HOLDING_DAYS = {
    "BULL_TREND": 8,
    "BULL_PULLBACK": 5,
    "BEAR_BOUNCE": 3,
}

ALL_MARKET_PROFILE = {
    "profile_id": "all_market",
    "description": "全市场可交易股票",
    "conditions": [],
}
RESEARCH_PROFILES = [ALL_MARKET_PROFILE, *FROZEN_PROFILES]


def normalize_regime(values: pd.Series) -> pd.Series:
    """统一市场状态名称，未知值不得静默归入可交易状态。"""
    allowed = {*REGIME_HOLDING_DAYS, "BEAR_TREND"}
    normalized = values.fillna("UNKNOWN").astype(str).str.upper()
    return normalized.where(normalized.isin(allowed), "UNKNOWN")


def regime_holding_days(regime: str) -> int | None:
    """返回预先固定的持有期；熊市下跌和未知状态不交易。"""
    return REGIME_HOLDING_DAYS.get(str(regime).upper())


def _profit_factor(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(numeric[numeric > 0].sum())
    losses = abs(float(numeric[numeric < 0].sum()))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _split_label(values: pd.Series) -> pd.Series:
    dates = values.astype(str)
    return pd.Series(
        np.select(
            [dates.le(SPLITS["train"][1]), dates.le(SPLITS["validation"][1])],
            ["train", "validation"],
            default="observed",
        ),
        index=values.index,
    )


def summarize_regime_rankings(selected: pd.DataFrame, cost_pct: float = 0.30) -> pd.DataFrame:
    """按状态固定持有期汇总净收益，不在样本内挑选最优退出日。"""
    if selected.empty:
        return pd.DataFrame()
    work = selected.copy()
    work["regime"] = normalize_regime(work["regime"])
    work["holding_days"] = work["regime"].map(REGIME_HOLDING_DAYS)
    work = work[work["holding_days"].notna()].copy()
    if work.empty:
        return pd.DataFrame()
    work["holding_days"] = work["holding_days"].astype(int)
    work["net_pct"] = np.select(
        [work["holding_days"].eq(3), work["holding_days"].eq(5), work["holding_days"].eq(8)],
        [
            pd.to_numeric(work["ret_3d"], errors="coerce") - cost_pct,
            pd.to_numeric(work["ret_5d"], errors="coerce") - cost_pct,
            pd.to_numeric(work["ret_8d"], errors="coerce") - cost_pct,
        ],
        default=np.nan,
    )
    keys = [
        "profile_id",
        "profile_description",
        "regime",
        "rank_factor",
        "rank_label",
        "rank_direction",
        "rank_id",
        "top_n",
        "split",
        "holding_days",
    ]
    rows = []
    for group_values, group in work.groupby(keys, sort=False, dropna=False):
        values = dict(zip(keys, group_values))
        net = pd.to_numeric(group["net_pct"], errors="coerce").dropna()
        yearly = group.assign(net_pct=pd.to_numeric(group["net_pct"], errors="coerce")).groupby("year")["net_pct"].mean().dropna()
        rows.append(
            {
                **values,
                "trades": int(net.size),
                "active_days": int(group.loc[net.index, "trade_date"].astype(str).nunique()) if not net.empty else 0,
                "avg_net_pct": round(float(net.mean()), 4) if not net.empty else np.nan,
                "median_net_pct": round(float(net.median()), 4) if not net.empty else np.nan,
                "win_rate": round(float(net.gt(0).mean()), 4) if not net.empty else np.nan,
                "profit_factor": round(float(_profit_factor(net)), 4) if not net.empty else 0.0,
                "positive_year_ratio": round(float(yearly.gt(0).mean()), 4) if not yearly.empty else 0.0,
                "worst_year_avg_pct": round(float(yearly.min()), 4) if not yearly.empty else np.nan,
            }
        )
    return pd.DataFrame(rows)


def choose_training_directions(metrics: pd.DataFrame) -> pd.DataFrame:
    """每个画像、状态和因子只依据训练期选择一个排序方向。"""
    if metrics.empty:
        return pd.DataFrame()
    identity = ["profile_id", "regime", "rank_factor", "top_n", "holding_days"]
    train = metrics[metrics["split"].eq("train")].copy()
    if train.empty:
        return pd.DataFrame()
    train = train.sort_values(
        identity + ["avg_net_pct", "profit_factor", "rank_direction"],
        ascending=[True] * len(identity) + [False, False, True],
        kind="mergesort",
    )
    selected = train.groupby(identity, as_index=False, sort=False).head(1)
    direction_keys = selected[identity + ["rank_direction"]].drop_duplicates()
    return metrics.merge(direction_keys, on=identity + ["rank_direction"], how="inner", validate="many_to_one")


def _attach_training_stability(chosen: pd.DataFrame) -> pd.DataFrame:
    """把训练期稳定性指标固定到同一配置的所有分段行。"""
    required_keys = ["profile_id", "regime", "rank_factor", "rank_direction", "top_n", "holding_days"]
    if chosen.empty or not set(required_keys).issubset(chosen.columns):
        return chosen.copy()
    train = chosen[chosen["split"].eq("train")][
        required_keys + ["avg_net_pct", "profit_factor", "positive_year_ratio", "worst_year_avg_pct"]
    ].copy()
    train = train.rename(
        columns={
            "avg_net_pct": "train_avg_net_pct",
            "profit_factor": "train_profit_factor",
            "positive_year_ratio": "train_positive_year_ratio",
            "worst_year_avg_pct": "train_worst_year_avg_pct",
        }
    ).drop_duplicates(required_keys)
    return chosen.merge(train, on=required_keys, how="left", validate="many_to_one")


def apply_validation_gate(chosen: pd.DataFrame) -> pd.DataFrame:
    """应用独立验证门槛；近期观察结果不参与通过判定。"""
    result = chosen.copy()
    if result.empty:
        result["baseline_improvement_pct"] = pd.Series(dtype=float)
        result["research_pass"] = pd.Series(dtype=bool)
        return result
    if "train_avg_net_pct" not in result.columns:
        result = _attach_training_stability(result)
    for column in (
        "train_avg_net_pct",
        "train_profit_factor",
        "train_positive_year_ratio",
        "train_worst_year_avg_pct",
    ):
        if column not in result.columns:
            result[column] = np.nan
    result["baseline_improvement_pct"] = (
        pd.to_numeric(result["avg_net_pct"], errors="coerce")
        - pd.to_numeric(result["baseline_avg_net_pct"], errors="coerce")
    ).round(4)
    validation = result["split"].eq("validation")
    result["research_pass"] = (
        validation
        & pd.to_numeric(result["train_avg_net_pct"], errors="coerce").gt(0.10)
        & pd.to_numeric(result["train_profit_factor"], errors="coerce").gt(1.03)
        & pd.to_numeric(result["train_positive_year_ratio"], errors="coerce").ge(0.50)
        & pd.to_numeric(result["train_worst_year_avg_pct"], errors="coerce").gt(-0.75)
        & pd.to_numeric(result["trades"], errors="coerce").ge(150)
        & pd.to_numeric(result["active_days"], errors="coerce").ge(80)
        & pd.to_numeric(result["avg_net_pct"], errors="coerce").gt(0.30)
        & pd.to_numeric(result["profit_factor"], errors="coerce").gt(1.10)
        & pd.to_numeric(result["positive_year_ratio"], errors="coerce").ge(2 / 3)
        & pd.to_numeric(result["worst_year_avg_pct"], errors="coerce").gt(-0.75)
        & pd.to_numeric(result["baseline_improvement_pct"], errors="coerce").ge(0.20)
    )
    return result


def _summarize_unconditional(selected: pd.DataFrame, cost_pct: float = 0.30) -> pd.DataFrame:
    """为每个固定持有期计算不区分市场状态的对照基线。"""
    if selected.empty:
        return pd.DataFrame()
    keys = ["profile_id", "rank_factor", "rank_direction", "top_n", "split"]
    rows = []
    for holding_days in sorted(set(REGIME_HOLDING_DAYS.values())):
        work = selected.copy()
        work["net_pct"] = pd.to_numeric(work[f"ret_{holding_days}d"], errors="coerce") - cost_pct
        for group_values, group in work.groupby(keys, sort=False, dropna=False):
            net = group["net_pct"].dropna()
            rows.append(
                {
                    **dict(zip(keys, group_values)),
                    "holding_days": holding_days,
                    "baseline_avg_net_pct": round(float(net.mean()), 4) if not net.empty else np.nan,
                }
            )
    return pd.DataFrame(rows)


def _write_report(chosen: pd.DataFrame, coverage: pd.DataFrame, start: str, end: str) -> str:
    validation = chosen[chosen["split"].eq("validation")].copy()
    validation = validation.sort_values(
        ["research_pass", "avg_net_pct", "profit_factor"],
        ascending=[False, False, False],
    )
    passed = validation[validation["research_pass"]]
    lines = [
        "# 市场状态条件化机会研究",
        "",
        f"- 数据范围：{start} 至 {end}",
        "- 训练期：2016-2021；独立验证期：2022-2024；近期观察期：2025-2026H1。",
        "- 固定状态持有期：BULL_TREND 8日、BULL_PULLBACK 5日、BEAR_BOUNCE 3日；BEAR_TREND不交易。",
        "- T+1开盘买入，往返成本0.30%，每组每日Top3。",
        f"- 训练期固定配置：{int(chosen[chosen['split'].eq('train')].shape[0])} 组。",
        f"- 独立验证通过：{int(len(passed))} 组。",
        "",
        "## 结论",
        "",
    ]
    if passed.empty:
        lines.append("没有配置同时通过绝对收益、盈亏比、年度一致性、最差年份和相对无状态基线提升门槛；市场状态目前不能把既有单因子信号提升为可上线策略。")
    else:
        lines.append("以下配置通过独立验证，只能进入成本和参数扰动压力测试，尚不能直接上线。")
    lines.extend(["", "## 验证期前30名", ""])
    display_columns = [
        "profile_description",
        "regime",
        "rank_label",
        "rank_direction",
        "holding_days",
        "train_avg_net_pct",
        "train_profit_factor",
        "trades",
        "avg_net_pct",
        "profit_factor",
        "positive_year_ratio",
        "worst_year_avg_pct",
        "baseline_avg_net_pct",
        "baseline_improvement_pct",
        "research_pass",
    ]
    lines.append(validation[display_columns].head(30).to_markdown(index=False) if not validation.empty else "无可评估配置。")
    lines.extend(["", "## 状态覆盖审计", ""])
    lines.append(coverage.to_markdown(index=False) if not coverage.empty else "无覆盖数据。")
    return "\n".join(lines) + "\n"


def run_research(root: Path, start: str, end: str) -> dict[str, pd.DataFrame | Path]:
    cache_dir = root / "data" / "cache"
    # 多取一年历史，仅用于当日可见滚动指标和市场状态预热。
    history_start = f"{int(start[:4]) - 1}0101"
    all_dates = market_research._available_dates(cache_dir, history_start, end)
    stock_info = market_research._load_stock_info(cache_dir)
    regimes = market_research._build_regimes(cache_dir, all_dates)
    selected_frames = []
    coverage_rows = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        print(f"processing {year}", flush=True)
        panel = market_research.build_year_panel(cache_dir, stock_info, regimes, all_dates, year, start, end)
        if panel.empty:
            continue
        panel = assign_feature_bins(panel)
        panel["regime"] = normalize_regime(panel["regime"])
        panel["split"] = _split_label(panel["trade_date"])
        panel["year"] = panel["trade_date"].astype(str).str[:4].astype(int)
        coverage = panel.groupby("regime")["trade_date"].nunique()
        coverage_rows.extend(
            {"year": year, "regime": regime, "trading_days": int(days)}
            for regime, days in coverage.items()
        )
        investable = panel[pd.to_numeric(panel["amount"], errors="coerce").ge(100000)].copy()
        selected = select_ranked_candidates(
            investable,
            profiles=RESEARCH_PROFILES,
            rank_specs=RANK_SPECS,
            top_n=3,
        )
        if not selected.empty:
            selected["split"] = _split_label(selected["trade_date"])
            selected["year"] = selected["trade_date"].astype(str).str[:4].astype(int)
            selected_frames.append(selected)
    selected_all = pd.concat(selected_frames, ignore_index=True, sort=False) if selected_frames else pd.DataFrame()
    metrics = summarize_regime_rankings(selected_all)
    baseline = _summarize_unconditional(selected_all)
    chosen = choose_training_directions(metrics)
    merge_keys = ["profile_id", "rank_factor", "rank_direction", "top_n", "split", "holding_days"]
    if not chosen.empty:
        chosen = chosen.merge(baseline, on=merge_keys, how="left", validate="many_to_one")
    else:
        chosen["baseline_avg_net_pct"] = pd.Series(dtype=float)
    chosen = apply_validation_gate(chosen)
    coverage_df = pd.DataFrame(coverage_rows)

    output_dir = root / "reports" / "research"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = "20260807"
    report_path = output_dir / f"regime_conditioned_opportunity_{stamp}.md"
    metrics_path = output_dir / f"regime_conditioned_opportunity_metrics_{stamp}.csv"
    chosen_path = output_dir / f"regime_conditioned_opportunity_chosen_{stamp}.csv"
    coverage_path = output_dir / f"regime_conditioned_opportunity_coverage_{stamp}.csv"
    report_path.write_text(_write_report(chosen, coverage_df, start, end), encoding="utf-8")
    metrics.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    chosen.to_csv(chosen_path, index=False, encoding="utf-8-sig")
    coverage_df.to_csv(coverage_path, index=False, encoding="utf-8-sig")
    return {
        "metrics": metrics,
        "chosen": chosen,
        "coverage": coverage_df,
        "report_path": report_path,
        "metrics_path": metrics_path,
        "chosen_path": chosen_path,
        "coverage_path": coverage_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="市场状态条件化机会研究")
    parser.add_argument("--start", default="20160101")
    parser.add_argument("--end", default="20260630")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = run_research(root, args.start, args.end)
    chosen = result["chosen"]
    validation = chosen[chosen["split"].eq("validation")].sort_values(
        ["research_pass", "avg_net_pct"], ascending=[False, False]
    )
    print("\nVALIDATION TOP30")
    print(validation.head(30).to_string(index=False))
    print(f"metrics={len(result['metrics'])} chosen={len(chosen)} passed={int(validation['research_pass'].sum())}")
    print(f"report={result['report_path']}")


if __name__ == "__main__":
    main()
