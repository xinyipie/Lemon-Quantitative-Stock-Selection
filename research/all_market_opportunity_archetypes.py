"""全市场短线机会画像研究。

只使用信号日及以前可见字段构造画像；未来收益仅用于标签和评价。
该脚本独立于正式选股策略，不修改线上评分或推荐结果。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import all_market_multi_engine_research as market_research


REPORT_DATE = "20260807"
REPORT_DIR = ROOT / "reports" / "research"
DEFAULT_REPORT = REPORT_DIR / f"all_market_opportunity_archetypes_{REPORT_DATE}.md"
DEFAULT_METRICS = REPORT_DIR / f"all_market_opportunity_archetypes_metrics_{REPORT_DATE}.csv"
DEFAULT_CANDIDATES = REPORT_DIR / f"all_market_opportunity_archetypes_candidates_{REPORT_DATE}.csv"

SPLITS = {
    "train": ("20160101", "20211231"),
    "validation": ("20220101", "20241231"),
    "sealed": ("20250101", "20260630"),
}

BIN_SPECS = {
    "ret_5": ([-np.inf, -10, -5, 0, 3, 7, np.inf], ["<=-10%", "-10~-5%", "-5~0%", "0~3%", "3~7%", ">7%"]),
    "ret_10": ([-np.inf, -15, -7, 0, 5, 12, np.inf], ["<=-15%", "-15~-7%", "-7~0%", "0~5%", "5~12%", ">12%"]),
    "ret_20": ([-np.inf, -20, -10, 0, 10, 25, np.inf], ["<=-20%", "-20~-10%", "-10~0%", "0~10%", "10~25%", ">25%"]),
    "ret_60": ([-np.inf, -30, -10, 0, 20, 50, np.inf], ["<=-30%", "-30~-10%", "-10~0%", "0~20%", "20~50%", ">50%"]),
    "drawdown_20": ([-np.inf, 2, 5, 10, 20, 35, np.inf], ["<=2%", "2~5%", "5~10%", "10~20%", "20~35%", ">35%"]),
    "pct_chg": ([-np.inf, -5, -2, 0, 2, 5, 7, np.inf], ["<=-5%", "-5~-2%", "-2~0%", "0~2%", "2~5%", "5~7%", ">7%"]),
    "rsi_14": ([-np.inf, 25, 35, 45, 55, 65, 75, np.inf], ["<=25", "25~35", "35~45", "45~55", "55~65", "65~75", ">75"]),
    "turnover_rate": ([-np.inf, 1, 3, 7, 12, 20, np.inf], ["<=1%", "1~3%", "3~7%", "7~12%", "12~20%", ">20%"]),
    "volume_ratio": ([-np.inf, 0.6, 0.9, 1.2, 1.8, 3, np.inf], ["<=0.6", "0.6~0.9", "0.9~1.2", "1.2~1.8", "1.8~3", ">3"]),
    "volatility_20": ([-np.inf, 2, 3, 4.5, 6.5, 9, np.inf], ["<=2", "2~3", "3~4.5", "4.5~6.5", "6.5~9", ">9"]),
    "industry_rs_20": ([-np.inf, -15, -5, 0, 5, 15, np.inf], ["<=-15%", "-15~-5%", "-5~0%", "0~5%", "5~15%", ">15%"]),
}

FEATURE_LABELS = {
    "regime_bin": "市场状态",
    "trend_bin": "趋势结构",
    "ret_5_bin": "近5日涨跌",
    "ret_10_bin": "近10日涨跌",
    "ret_20_bin": "近20日涨跌",
    "ret_60_bin": "近60日涨跌",
    "drawdown_20_bin": "距20日高点回撤",
    "pct_chg_bin": "当日涨跌",
    "rsi_14_bin": "RSI14",
    "turnover_rate_bin": "换手率",
    "volume_ratio_bin": "量比",
    "volatility_20_bin": "20日波动率",
    "industry_rs_20_bin": "行业相对强度",
}

METRIC_COLUMNS = [
    "support",
    "opportunities",
    "opportunity_rate",
    "baseline_rate",
    "lift",
    "coverage",
    "avg_ret_3d",
    "avg_ret_5d",
    "avg_ret_8d",
    "win_5d",
    "avg_mfe_8d",
    "avg_mae_8d",
    "active_days",
]


def _as_bin(values: pd.Series, edges: list[float], labels: list[str]) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.cut(numeric, bins=edges, labels=labels, include_lowest=True, right=True)
    return result.astype("string").fillna("缺失").astype(str)


def assign_feature_bins(panel: pd.DataFrame) -> pd.DataFrame:
    """把信号日前可见连续特征映射成固定、可解释的区间。"""
    result = panel.copy()
    result["regime_bin"] = result.get("regime", pd.Series("UNKNOWN", index=result.index)).fillna("UNKNOWN").astype(str)

    close = pd.to_numeric(result.get("synthetic_close", pd.Series(np.nan, index=result.index)), errors="coerce")
    ma20 = pd.to_numeric(result.get("ma_20", pd.Series(np.nan, index=result.index)), errors="coerce")
    ma60 = pd.to_numeric(result.get("ma_60", pd.Series(np.nan, index=result.index)), errors="coerce")
    conditions = [
        close.gt(ma20) & ma20.gt(ma60),
        close.le(ma20) & ma20.gt(ma60),
        close.gt(ma20) & ma20.le(ma60),
        close.le(ma20) & ma20.le(ma60),
    ]
    result["trend_bin"] = np.select(
        conditions,
        ["多头上方", "多头回调", "空头反弹", "空头下方"],
        default="缺失",
    )

    for column, (edges, labels) in BIN_SPECS.items():
        source = result[column] if column in result.columns else pd.Series(np.nan, index=result.index)
        result[f"{column}_bin"] = _as_bin(source, edges, labels)
    return result


def build_case_control_sample(panel: pd.DataFrame, controls_per_day: int = 80) -> pd.DataFrame:
    """保留全部机会，并按稳定哈希抽取同日对照股票。"""
    if panel.empty:
        return panel.copy()
    work = panel[market_research._signal_day_tradeable(panel)].copy()
    work["top20_opportunity"] = work["top20_opportunity"].fillna(False).astype(bool)
    cases = work[work["top20_opportunity"]].copy()
    controls = work[~work["top20_opportunity"]].copy()
    if controls.empty:
        cases["sample_weight"] = 1.0
        return cases

    controls["population_controls"] = controls.groupby("trade_date")["ts_code"].transform("size")
    keys = controls["trade_date"].astype(str) + "|" + controls["ts_code"].astype(str)
    controls["_stable_hash"] = pd.util.hash_pandas_object(keys, index=False).to_numpy()
    controls = controls.sort_values(["trade_date", "_stable_hash", "ts_code"])
    controls = controls.groupby("trade_date", group_keys=False).head(max(1, int(controls_per_day))).copy()
    controls["sampled_controls"] = controls.groupby("trade_date")["ts_code"].transform("size")
    controls["sample_weight"] = controls["population_controls"] / controls["sampled_controls"]
    controls = controls.drop(columns=["population_controls", "sampled_controls", "_stable_hash"])
    cases["sample_weight"] = 1.0
    return pd.concat([cases, controls], ignore_index=True, sort=False)


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return float("nan")
    return float(np.average(numeric[valid], weights=weights[valid]))


def evaluate_profile(sample: pd.DataFrame, mask: pd.Series) -> dict:
    """按案例/对照权重计算画像命中率、提升倍数和未来路径。"""
    if sample.empty:
        return {column: 0.0 for column in METRIC_COLUMNS}
    selected = sample.loc[mask.reindex(sample.index, fill_value=False)].copy()
    all_weights = pd.to_numeric(
        sample.get("sample_weight", pd.Series(1.0, index=sample.index)),
        errors="coerce",
    ).fillna(1.0)
    selected_weights = all_weights.reindex(selected.index)
    labels = sample["top20_opportunity"].fillna(False).astype(bool)
    selected_labels = labels.reindex(selected.index)
    total_opportunities = int(labels.sum())
    opportunities = int(selected_labels.sum())
    support = float(selected_weights.sum())
    total_support = float(all_weights.sum())
    baseline_rate = total_opportunities / total_support if total_support else 0.0
    opportunity_rate = opportunities / support if support else 0.0
    lift = opportunity_rate / baseline_rate if baseline_rate else 0.0

    metrics = {
        "support": round(support, 2),
        "opportunities": opportunities,
        "opportunity_rate": round(opportunity_rate, 8),
        "baseline_rate": round(baseline_rate, 8),
        "lift": round(lift, 4),
        "coverage": round(opportunities / total_opportunities, 8) if total_opportunities else 0.0,
        "active_days": int(selected["trade_date"].nunique()) if not selected.empty else 0,
    }
    for horizon in (3, 5, 8):
        column = f"ret_{horizon}d"
        metrics[f"avg_ret_{horizon}d"] = round(_weighted_mean(selected.get(column), selected_weights), 4) if not selected.empty else 0.0
    metrics["win_5d"] = round(
        _weighted_mean(pd.to_numeric(selected.get("ret_5d"), errors="coerce").gt(0).astype(float), selected_weights),
        4,
    ) if not selected.empty else 0.0
    metrics["avg_mfe_8d"] = round(_weighted_mean(selected.get("mfe_8d"), selected_weights), 4) if not selected.empty else 0.0
    metrics["avg_mae_8d"] = round(_weighted_mean(selected.get("mae_8d"), selected_weights), 4) if not selected.empty else 0.0
    return metrics


def _condition_text(conditions: list[tuple[str, str]]) -> str:
    return " 且 ".join(f"{FEATURE_LABELS.get(column, column)}={value}" for column, value in conditions)


def _profile_id(conditions: list[tuple[str, str]]) -> str:
    return "&".join(f"{column}={value}" for column, value in conditions)


def _profile_mask(sample: pd.DataFrame, conditions: list[tuple[str, str]]) -> pd.Series:
    mask = pd.Series(True, index=sample.index)
    for column, value in conditions:
        mask &= sample[column].astype(str).eq(str(value))
    return mask


def discover_profiles(train: pd.DataFrame, top_single_count: int = 20) -> list[dict]:
    """仅在训练期发现单维画像及最多两个条件的组合画像。"""
    singles = []
    bin_columns = [column for column in FEATURE_LABELS if column in train.columns]
    for column in bin_columns:
        for value in sorted(train[column].dropna().astype(str).unique()):
            if value in {"缺失", "UNKNOWN", "nan"}:
                continue
            conditions = [(column, value)]
            metrics = evaluate_profile(train, _profile_mask(train, conditions))
            row = {
                "profile_id": _profile_id(conditions),
                "profile_type": "single",
                "description": _condition_text(conditions),
                "conditions": conditions,
                **metrics,
            }
            row["discovery_score"] = metrics["lift"] * math.log1p(metrics["opportunities"]) * math.sqrt(max(metrics["coverage"], 0))
            singles.append(row)

    eligible_singles = [row for row in singles if row["opportunities"] >= 60 and row["lift"] > 1.0]
    eligible_singles.sort(key=lambda row: (row["discovery_score"], row["opportunities"]), reverse=True)
    top_singles = eligible_singles[:top_single_count]

    combined_profiles = []
    for left, right in combinations(top_singles, 2):
        left_condition = left["conditions"][0]
        right_condition = right["conditions"][0]
        if left_condition[0] == right_condition[0]:
            continue
        conditions = sorted([left_condition, right_condition])
        metrics = evaluate_profile(train, _profile_mask(train, conditions))
        if metrics["opportunities"] < 60 or metrics["lift"] <= 1.0:
            continue
        row = {
            "profile_id": _profile_id(conditions),
            "profile_type": "combined",
            "description": _condition_text(conditions),
            "conditions": conditions,
            **metrics,
        }
        row["discovery_score"] = metrics["lift"] * math.log1p(metrics["opportunities"]) * math.sqrt(max(metrics["coverage"], 0))
        combined_profiles.append(row)

    all_profiles = singles + combined_profiles
    all_profiles.sort(key=lambda row: (row["discovery_score"], row["opportunities"]), reverse=True)
    return all_profiles


def _split_label(trade_dates: pd.Series) -> pd.Series:
    dates = trade_dates.astype(str)
    return pd.Series(
        np.select(
            [dates.le(SPLITS["train"][1]), dates.le(SPLITS["validation"][1])],
            ["train", "validation"],
            default="sealed",
        ),
        index=trade_dates.index,
    )


def evaluate_across_splits(sample: pd.DataFrame, profiles: list[dict]) -> pd.DataFrame:
    """固定画像后，在训练、验证和封存期分别计算指标。"""
    rows = []
    for profile in profiles:
        for split in SPLITS:
            part = sample[sample["split"].eq(split)]
            metrics = evaluate_profile(part, _profile_mask(part, profile["conditions"]))
            rows.append(
                {
                    "profile_id": profile["profile_id"],
                    "profile_type": profile["profile_type"],
                    "description": profile["description"],
                    "conditions": json.dumps(profile["conditions"], ensure_ascii=False),
                    "discovery_score": round(float(profile["discovery_score"]), 6),
                    "split": split,
                    **metrics,
                }
            )
    return pd.DataFrame(rows)


def apply_acceptance(metrics: pd.DataFrame) -> pd.DataFrame:
    """把长表指标转换为每个画像一行，并执行三阶段硬验收。"""
    rows = []
    for profile_id, group in metrics.groupby("profile_id", sort=False):
        first = group.iloc[0]
        row = {
            "profile_id": profile_id,
            "profile_type": first.get("profile_type", "unknown"),
            "description": first.get("description", profile_id),
            "conditions": first.get("conditions", "[]"),
            "discovery_score": first.get("discovery_score", np.nan),
        }
        by_split = {str(item["split"]): item for _, item in group.iterrows()}
        for split in SPLITS:
            item = by_split.get(split, {})
            for column in METRIC_COLUMNS:
                row[f"{split}_{column}"] = item.get(column, 0.0)

        checks = {
            "train_support": row["train_support"] >= 500,
            "validation_support": row["validation_support"] >= 250,
            "sealed_support": row["sealed_support"] >= 120,
            "train_opportunities": row["train_opportunities"] >= 60,
            "validation_opportunities": row["validation_opportunities"] >= 30,
            "sealed_opportunities": row["sealed_opportunities"] >= 15,
            "train_lift": row["train_lift"] > 1.20,
            "validation_lift": row["validation_lift"] > 1.20,
            "sealed_lift": row["sealed_lift"] > 1.20,
            "validation_avg_ret_5d": row["validation_avg_ret_5d"] > 0,
            "sealed_avg_ret_5d": row["sealed_avg_ret_5d"] > 0,
            "sealed_coverage": row["sealed_coverage"] >= 0.003,
        }
        row.update({f"pass_{name}": bool(value) for name, value in checks.items()})
        row["research_pass"] = bool(all(checks.values()))
        row["failure_reasons"] = ",".join(name for name, value in checks.items() if not value)
        rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["research_pass", "sealed_lift", "validation_lift", "train_lift", "sealed_opportunities"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)


def _baseline_rows(sample: pd.DataFrame) -> list[dict]:
    rows = []
    for split in SPLITS:
        part = sample[sample["split"].eq(split)]
        metrics = evaluate_profile(part, pd.Series(True, index=part.index))
        rows.append(
            {
                "profile_id": "__baseline__",
                "profile_type": "baseline",
                "description": "同期全部可交易股票",
                "conditions": "[]",
                "discovery_score": 0.0,
                "split": split,
                **metrics,
            }
        )
    return rows


def run_research(start: str, end: str, cache_dir: Path, controls_per_day: int = 80) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按年度构造全市场面板，并压缩为案例/对照研究样本。"""
    all_dates = market_research._available_dates(cache_dir, "19900101", end)
    stock_info = market_research._load_stock_info(cache_dir)
    regimes = market_research._build_regimes(cache_dir, all_dates)
    samples = []
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
        compact = build_case_control_sample(panel, controls_per_day=controls_per_day)
        compact = assign_feature_bins(compact)
        samples.append(compact)
        del panel
    if not samples:
        return pd.DataFrame(), pd.DataFrame()

    sample = pd.concat(samples, ignore_index=True, sort=False)
    sample["split"] = _split_label(sample["trade_date"])
    train = sample[sample["split"].eq("train")]
    profiles = discover_profiles(train)
    metrics = pd.concat(
        [pd.DataFrame(_baseline_rows(sample)), evaluate_across_splits(sample, profiles)],
        ignore_index=True,
        sort=False,
    )
    candidates = apply_acceptance(metrics[~metrics["profile_id"].eq("__baseline__")])
    return metrics, candidates


def _pct(value: float, ratio: bool = False) -> str:
    if pd.isna(value):
        return "NA"
    number = float(value) * 100 if ratio else float(value)
    return f"{number:+.2f}%"


def write_report(metrics: pd.DataFrame, candidates: pd.DataFrame, output: Path) -> None:
    """写入可人工审阅的画像稳定性报告。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    baseline = metrics[metrics["profile_id"].eq("__baseline__")].set_index("split")
    passed_count = int(candidates["research_pass"].sum()) if not candidates.empty else 0
    lines = [
        "# 全市场短线机会画像研究",
        "",
        "## 结论边界",
        "",
        "- T日收盘观察，T+1开盘成交；画像只使用T日及以前数据。",
        "- 训练期发现画像，验证期与封存期只做评价。",
        "- 对照组按固定哈希抽样，并用样本权重还原全市场分母。",
        "- 本报告不修改正式策略，不包含自动交易逻辑。",
        "",
        "## 同期基准",
        "",
        "| 阶段 | 全市场样本权重 | Top20机会 | 基础机会率 | 5日均收益 | 5日胜率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for split in SPLITS:
        row = baseline.loc[split] if split in baseline.index else pd.Series(dtype=object)
        lines.append(
            f"| {split} | {float(row.get('support', 0)):,.0f} | {int(row.get('opportunities', 0)):,} | "
            f"{_pct(row.get('baseline_rate', 0), ratio=True)} | {_pct(row.get('avg_ret_5d', 0))} | "
            f"{_pct(row.get('win_5d', 0), ratio=True)} |"
        )

    lines.extend(
        [
            "",
            "## 验收结果",
            "",
            f"- 进入评价的画像数：`{len(candidates)}`。",
            f"- 同时通过训练、验证、封存硬门槛：`{passed_count}`。",
            "- 未通过的画像仅用于解释历史机会，不得接入正式策略。",
            "",
            "## 最稳定画像 Top20",
            "",
            "| 画像 | 训练Lift/命中 | 验证Lift/5日收益 | 封存Lift/5日收益/覆盖 | 结论 |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for _, row in candidates.head(20).iterrows():
        verdict = "通过" if bool(row.get("research_pass")) else f"未通过：{row.get('failure_reasons', '')}"
        lines.append(
            f"| {row.get('description')} | {row.get('train_lift', 0):.2f} / {int(row.get('train_opportunities', 0))} | "
            f"{row.get('validation_lift', 0):.2f} / {_pct(row.get('validation_avg_ret_5d', 0))} | "
            f"{row.get('sealed_lift', 0):.2f} / {_pct(row.get('sealed_avg_ret_5d', 0))} / "
            f"{_pct(row.get('sealed_coverage', 0), ratio=True)} | {verdict} |"
        )

    lines.extend(["", "## 下一步", ""])
    if passed_count:
        lines.append("- 通过画像进入独立模拟观察层，连续跟踪20个交易日后再讨论是否接入正式推荐。")
    else:
        lines.append("- 暂无可接入正式策略的画像；下一轮只针对封存期最稳定但单项未达标的画像研究资金持续性，不调整正式策略。")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全市场短线Top20机会画像研究，不修改正式策略。")
    parser.add_argument("--start", default="20160101")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "cache")
    parser.add_argument("--controls-per-day", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics, candidates = run_research(args.start, args.end, args.cache_dir, args.controls_per_day)
    if metrics.empty:
        raise SystemExit("没有可用研究样本")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(DEFAULT_METRICS, index=False, encoding="utf-8-sig")
    candidates.to_csv(DEFAULT_CANDIDATES, index=False, encoding="utf-8-sig")
    write_report(metrics, candidates, DEFAULT_REPORT)
    passed = int(candidates["research_pass"].sum()) if not candidates.empty else 0
    print("\nSUMMARY")
    print(candidates.head(20)[[
        "description",
        "train_lift",
        "validation_lift",
        "sealed_lift",
        "validation_avg_ret_5d",
        "sealed_avg_ret_5d",
        "sealed_coverage",
        "research_pass",
        "failure_reasons",
    ]].to_string(index=False) if not candidates.empty else "no profiles")
    print(f"profiles={len(candidates)} passed={passed}")
    print(f"report={DEFAULT_REPORT}")
    print(f"metrics={DEFAULT_METRICS}")
    print(f"candidates={DEFAULT_CANDIDATES}")


if __name__ == "__main__":
    main()
