"""资金持续性、成交额加速度与行业扩散排序研究。

因子仅由信号日及历史行情构造；方向只由训练期决定。
统一采用T+1开盘至第3日收盘净收益，避免再次混入退出参数选择。
"""

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
from research.opportunity_archetype_exit_backtest import FROZEN_PROFILES
from research.opportunity_archetype_ranking_research import select_ranked_candidates


REPORT_DATE = "20260807"
REPORT_DIR = ROOT / "reports" / "research"
DEFAULT_REPORT = REPORT_DIR / f"flow_breadth_factor_research_{REPORT_DATE}.md"
DEFAULT_METRICS = REPORT_DIR / f"flow_breadth_factor_metrics_{REPORT_DATE}.csv"
DEFAULT_CHOSEN = REPORT_DIR / f"flow_breadth_factor_chosen_{REPORT_DATE}.csv"
DEFAULT_COVERAGE = REPORT_DIR / f"flow_breadth_factor_coverage_{REPORT_DATE}.csv"

ALL_MARKET_PROFILE = {
    "profile_id": "all_market",
    "description": "全市场可交易股票",
    "conditions": [],
}
RESEARCH_PROFILES = [ALL_MARKET_PROFILE, *FROZEN_PROFILES]

FLOW_RANK_SPECS = [
    {"factor": "mf_1_ratio", "label": "当日主力净流入占比", "column": "mf_1_ratio", "directions": ["high", "low"]},
    {"factor": "mf_3_ratio", "label": "3日主力净流入占比", "column": "mf_3_ratio", "directions": ["high", "low"]},
    {"factor": "mf_5_ratio", "label": "5日主力净流入占比", "column": "mf_5_ratio", "directions": ["high", "low"]},
    {"factor": "mf_positive_days_5", "label": "5日净流入天数", "column": "mf_positive_days_5", "directions": ["high", "low"]},
    {"factor": "amount_accel_5_20", "label": "成交额5/20日加速度", "column": "amount_accel_5_20", "directions": ["high", "low"]},
    {"factor": "industry_up_ratio", "label": "行业上涨宽度", "column": "industry_up_ratio", "directions": ["high", "low"]},
    {"factor": "industry_above_ma20_ratio", "label": "行业站上MA20比例", "column": "industry_above_ma20_ratio", "directions": ["high", "low"]},
    {"factor": "industry_flow_positive_ratio", "label": "行业资金流为正比例", "column": "industry_flow_positive_ratio", "directions": ["high", "low"]},
    {"factor": "industry_amount_accel", "label": "行业成交额加速度", "column": "industry_amount_accel", "directions": ["high", "low"]},
]

SPLITS = {
    "train": ("20160101", "20211231"),
    "validation": ("20220101", "20241231"),
    "observed": ("20250101", "20260630"),
}


def compute_stock_flow_features(frame: pd.DataFrame) -> pd.DataFrame:
    """按股票时间顺序计算资金流和成交额滚动特征。"""
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    work["ts_code"] = work["ts_code"].astype(str)
    work["trade_date"] = work["trade_date"].astype(str)
    work["amount"] = pd.to_numeric(work["amount"], errors="coerce")
    work["net_mf_amount"] = pd.to_numeric(work["net_mf_amount"], errors="coerce")
    work = work.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    # Tushare daily.amount 为千元，moneyflow.net_mf_amount 为万元，乘10后统一为千元。
    work["net_mf_thousand"] = work["net_mf_amount"] * 10.0
    work["mf_1_ratio"] = work["net_mf_thousand"] / work["amount"].replace(0, np.nan)
    work["mf_positive"] = work["net_mf_amount"].gt(0).astype(float)
    grouped = work.groupby("ts_code", sort=False)
    for window in (3, 5, 20):
        work[f"amount_sum_{window}"] = grouped["amount"].transform(
            lambda values, size=window: values.rolling(size, min_periods=size).sum()
        )
    for window in (3, 5):
        work[f"mf_sum_{window}"] = grouped["net_mf_thousand"].transform(
            lambda values, size=window: values.rolling(size, min_periods=size).sum()
        )
        work[f"mf_{window}_ratio"] = work[f"mf_sum_{window}"] / work[f"amount_sum_{window}"].replace(0, np.nan)
    work["mf_positive_days_5"] = grouped["mf_positive"].transform(
        lambda values: values.rolling(5, min_periods=5).sum()
    )
    work["amount_accel_5_20"] = (
        (work["amount_sum_5"] / 5.0) / (work["amount_sum_20"] / 20.0).replace(0, np.nan)
    )
    return work


def add_industry_breadth(frame: pd.DataFrame) -> pd.DataFrame:
    """由个股状态聚合同日行业扩散，不依赖申万指数成分接口。"""
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    work["industry"] = work.get("industry", pd.Series("未知行业", index=work.index)).fillna("未知行业").astype(str)
    work["_up"] = pd.to_numeric(work["pct_chg"], errors="coerce").gt(0).astype(float)
    work["_above_ma20"] = (
        pd.to_numeric(work["synthetic_close"], errors="coerce")
        .gt(pd.to_numeric(work["ma_20"], errors="coerce"))
        .astype(float)
    )
    work["_flow_positive"] = pd.to_numeric(work["mf_1_ratio"], errors="coerce").gt(0).astype(float)
    groups = work.groupby(["trade_date", "industry"], sort=False)
    work["industry_up_ratio"] = groups["_up"].transform("mean")
    work["industry_above_ma20_ratio"] = groups["_above_ma20"].transform("mean")
    work["industry_flow_positive_ratio"] = groups["_flow_positive"].transform("mean")
    work["industry_amount_accel"] = groups["amount_accel_5_20"].transform("median")
    return work.drop(columns=["_up", "_above_ma20", "_flow_positive"])


def _load_flow_history(cache_dir: Path, dates: list[str]) -> pd.DataFrame:
    frames = []
    for date in dates:
        daily = market_research._read_parquet(
            cache_dir / "daily" / f"{date}.parquet",
            ["ts_code", "amount"],
        )
        moneyflow = market_research._read_parquet(
            cache_dir / "moneyflow" / f"{date}.parquet",
            ["ts_code", "net_mf_amount"],
        )
        if daily.empty or "ts_code" not in daily.columns:
            continue
        daily = daily.copy()
        daily["ts_code"] = daily["ts_code"].astype(str)
        daily["trade_date"] = str(date)
        if moneyflow.empty or "ts_code" not in moneyflow.columns:
            daily["net_mf_amount"] = np.nan
        else:
            moneyflow = moneyflow.copy()
            moneyflow["ts_code"] = moneyflow["ts_code"].astype(str)
            daily = daily.merge(moneyflow[["ts_code", "net_mf_amount"]], on="ts_code", how="left")
        frames.append(daily[["ts_code", "trade_date", "amount", "net_mf_amount"]])
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def _year_flow_features(
    cache_dir: Path,
    all_dates: list[str],
    target_dates: list[str],
) -> pd.DataFrame:
    if not target_dates:
        return pd.DataFrame()
    first_position = all_dates.index(target_dates[0])
    last_position = all_dates.index(target_dates[-1])
    history_dates = all_dates[max(0, first_position - 19) : last_position + 1]
    history = _load_flow_history(cache_dir, history_dates)
    if history.empty:
        return history
    features = compute_stock_flow_features(history)
    columns = [
        "ts_code",
        "trade_date",
        "mf_1_ratio",
        "mf_3_ratio",
        "mf_5_ratio",
        "mf_positive_days_5",
        "amount_accel_5_20",
    ]
    return features[features["trade_date"].isin(target_dates)][columns].copy()


def _profit_factor(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    gains = numeric[numeric > 0].sum()
    losses = abs(numeric[numeric < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def _split_label(dates: pd.Series) -> pd.Series:
    values = dates.astype(str)
    return pd.Series(
        np.select(
            [values.le(SPLITS["train"][1]), values.le(SPLITS["validation"][1])],
            ["train", "validation"],
            default="observed",
        ),
        index=dates.index,
    )


def summarize_factors(selected: pd.DataFrame, total_cost_pct: float = 0.30) -> pd.DataFrame:
    if selected.empty:
        return pd.DataFrame()
    work = selected.copy()
    work["net_3d_pct"] = pd.to_numeric(work["ret_3d"], errors="coerce") - total_cost_pct
    rows = []
    keys = [
        "profile_id",
        "profile_description",
        "rank_factor",
        "rank_label",
        "rank_direction",
        "rank_id",
        "top_n",
        "split",
    ]
    for group_keys, group in work.groupby(keys, sort=False):
        values = dict(zip(keys, group_keys))
        returns = group["net_3d_pct"].dropna()
        yearly = group.groupby("year")["net_3d_pct"].mean()
        rows.append(
            {
                **values,
                "trades": int(len(group)),
                "active_days": int(group["trade_date"].nunique()),
                "avg_net_3d_pct": round(float(returns.mean()), 4),
                "median_net_3d_pct": round(float(returns.median()), 4),
                "win_rate_3d": round(float((returns > 0).mean()), 4),
                "profit_factor_3d": round(_profit_factor(returns), 4),
                "avg_mfe_8d_pct": round(float(group["mfe_8d"].mean()), 4),
                "avg_mae_8d_pct": round(float(group["mae_8d"].mean()), 4),
                "positive_year_ratio": round(float((yearly > 0).mean()), 4),
                "worst_year_avg_3d_pct": round(float(yearly.min()), 4),
            }
        )
    return pd.DataFrame(rows)


def choose_training_directions(metrics: pd.DataFrame) -> pd.DataFrame:
    """按训练期3日净收益为每个画像/因子确定唯一方向。"""
    if metrics.empty:
        return metrics.copy()
    train = metrics[metrics["split"].eq("train")].sort_values(
        ["profile_id", "rank_factor", "avg_net_3d_pct", "profit_factor_3d", "rank_id"],
        ascending=[True, True, False, False, True],
    )
    choices = train.groupby(["profile_id", "rank_factor", "top_n"], group_keys=False).head(1)
    keys = set(zip(choices["profile_id"], choices["rank_id"], choices["top_n"]))
    chosen = metrics[
        metrics.apply(lambda row: (row["profile_id"], row["rank_id"], row["top_n"]) in keys, axis=1)
    ].copy()

    pass_map = {}
    for keys, group in chosen.groupby(["profile_id", "rank_id", "top_n"], sort=False):
        by_split = {row.split: row for row in group.itertuples(index=False)}
        train_row = by_split.get("train")
        validation = by_split.get("validation")
        pass_map[keys] = bool(
            train_row and validation
            and train_row.trades >= 300
            and validation.trades >= 150
            and validation.avg_net_3d_pct > 0.20
            and validation.profit_factor_3d > 1.05
            and validation.positive_year_ratio >= 2 / 3
            and validation.worst_year_avg_3d_pct > -1.0
        )
    chosen["research_pass"] = [
        pass_map[(row.profile_id, row.rank_id, row.top_n)] for row in chosen.itertuples(index=False)
    ]
    return chosen


def run_research(start: str, end: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_dates = market_research._available_dates(cache_dir, "19900101", end)
    stock_info = market_research._load_stock_info(cache_dir)
    regimes = market_research._build_regimes(cache_dir, all_dates)
    selected_frames = []
    coverage_rows = []
    keep = [
        "profile_id",
        "profile_description",
        "rank_factor",
        "rank_label",
        "rank_direction",
        "rank_id",
        "top_n",
        "trade_date",
        "ts_code",
        "ret_3d",
        "mfe_8d",
        "mae_8d",
    ]

    for year in range(int(start[:4]), int(end[:4]) + 1):
        print(f"processing {year}", flush=True)
        panel = market_research.build_year_panel(
            cache_dir,
            stock_info,
            regimes,
            all_dates,
            year,
            start,
            end,
        )
        if panel.empty:
            continue
        panel = assign_feature_bins(panel)
        target_dates = sorted(panel["trade_date"].astype(str).unique())
        flow = _year_flow_features(cache_dir, all_dates, target_dates)
        panel = panel.merge(flow, on=["ts_code", "trade_date"], how="left")
        panel = add_industry_breadth(panel)
        coverage_rows.append(
            {
                "year": year,
                "rows": int(len(panel)),
                "moneyflow_coverage": round(float(panel["mf_1_ratio"].notna().mean()), 6),
                "rolling5_coverage": round(float(panel["mf_5_ratio"].notna().mean()), 6),
                "rolling20_coverage": round(float(panel["amount_accel_5_20"].notna().mean()), 6),
            }
        )
        # 固定最低日成交额1亿元，避免净流入比例被极小成交额放大。
        investable = panel[pd.to_numeric(panel["amount"], errors="coerce").ge(100000)].copy()
        selected = select_ranked_candidates(
            investable,
            RESEARCH_PROFILES,
            FLOW_RANK_SPECS,
            top_n=3,
        )
        if not selected.empty:
            selected_frames.append(selected[keep].copy())
        del panel, flow, investable, selected

    if not selected_frames:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(coverage_rows)
    selected = pd.concat(selected_frames, ignore_index=True, sort=False)
    selected["split"] = _split_label(selected["trade_date"])
    selected["year"] = selected["trade_date"].astype(str).str[:4]
    metrics = summarize_factors(selected)
    chosen = choose_training_directions(metrics)
    return metrics, chosen, pd.DataFrame(coverage_rows)


def _pct(value: float, ratio: bool = False) -> str:
    number = float(value) * 100 if ratio else float(value)
    return f"{number:+.2f}%"


def write_report(metrics: pd.DataFrame, chosen: pd.DataFrame, coverage: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    passed = chosen[chosen["research_pass"]][["profile_id", "rank_id"]].drop_duplicates()
    lines = [
        "# 资金持续性与行业扩散因子研究",
        "",
        "## 研究边界",
        "",
        "- T日收盘观察，T+1开盘成交，固定持有3日，每笔扣除0.30%交易摩擦。",
        "- 股票最低日成交额1亿元；方向只由2016至2021训练期决定。",
        "- 2022至2024用于验证；2025至2026仅作observed展示。",
        "- 资金流、成交额和行业宽度全部由本地历史数据计算，不使用AI。",
        "",
        "## 数据覆盖",
        "",
        f"- 年度平均当日资金流覆盖率：`{_pct(coverage['moneyflow_coverage'].mean(), ratio=True)}`。",
        f"- 年度平均5日资金流覆盖率：`{_pct(coverage['rolling5_coverage'].mean(), ratio=True)}`。",
        f"- 年度平均20日成交额加速度覆盖率：`{_pct(coverage['rolling20_coverage'].mean(), ratio=True)}`。",
        "",
        "## 验收结果",
        "",
        f"- 训练期确定方向后的画像/因子：`{chosen[['profile_id', 'rank_id']].drop_duplicates().shape[0]}`。",
        f"- 通过验证期门槛：`{len(passed)}`。",
        "",
        "| 画像 | 因子方向 | 阶段 | 交易 | 3日净收益 | 胜率 | 盈亏比 | 最差年度 | 结论 |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    validation_order = chosen[chosen["split"].eq("validation")].sort_values(
        ["research_pass", "avg_net_3d_pct", "profit_factor_3d"], ascending=[False, False, False]
    )
    top_keys = set(zip(validation_order.head(20)["profile_id"], validation_order.head(20)["rank_id"]))
    display = chosen[
        chosen.apply(lambda row: (row["profile_id"], row["rank_id"]) in top_keys, axis=1)
    ].sort_values(["research_pass", "profile_id", "rank_factor", "split"], ascending=[False, True, True, True])
    for row in display.itertuples(index=False):
        direction = "高到低" if row.rank_direction == "high" else "低到高"
        lines.append(
            f"| {row.profile_description} | {row.rank_label}（{direction}） | {row.split} | {row.trades} | "
            f"{_pct(row.avg_net_3d_pct)} | {_pct(row.win_rate_3d, ratio=True)} | {row.profit_factor_3d:.2f} | "
            f"{_pct(row.worst_year_avg_3d_pct)} | {'通过' if row.research_pass else '观察'} |"
        )
    lines.extend(["", "## 结论", ""])
    if passed.empty:
        lines.append("- 新增资金与行业扩散单因子仍未形成跨阶段稳定优势，不应接入正式策略。")
    else:
        lines.append("- 通过项只进入多因子正交组合与真实OHLC复核，不直接上线。")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="资金持续性与行业扩散因子研究。")
    parser.add_argument("--start", default="20160101")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "cache")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics, chosen, coverage = run_research(args.start, args.end, args.cache_dir)
    if metrics.empty:
        raise SystemExit("没有生成资金与行业宽度研究样本")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(DEFAULT_METRICS, index=False, encoding="utf-8-sig")
    chosen.to_csv(DEFAULT_CHOSEN, index=False, encoding="utf-8-sig")
    coverage.to_csv(DEFAULT_COVERAGE, index=False, encoding="utf-8-sig")
    write_report(metrics, chosen, coverage, DEFAULT_REPORT)
    validation = chosen[chosen["split"].eq("validation")].sort_values(
        ["research_pass", "avg_net_3d_pct", "profit_factor_3d"], ascending=[False, False, False]
    )
    print("\nVALIDATION TOP30")
    print(validation.head(30).to_string(index=False))
    passed = chosen[chosen["research_pass"]][["profile_id", "rank_id"]].drop_duplicates()
    print(f"metrics={len(metrics)} chosen={chosen[['profile_id', 'rank_id']].drop_duplicates().shape[0]} passed={len(passed)}")
    print(f"coverage_mean={coverage[['moneyflow_coverage', 'rolling5_coverage', 'rolling20_coverage']].mean().to_dict()}")
    print(f"report={DEFAULT_REPORT}")
    print(f"metrics_csv={DEFAULT_METRICS}")
    print(f"chosen_csv={DEFAULT_CHOSEN}")


if __name__ == "__main__":
    main()
