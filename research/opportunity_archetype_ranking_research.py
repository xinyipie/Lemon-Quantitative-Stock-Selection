"""冻结机会画像内部的个股排序研究。

方向只由训练期决定；验证期和封存期不参与排序方向选择。
统一使用T+1开盘至第5日收盘收益并扣除交易摩擦，先隔离选股能力。
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


REPORT_DATE = "20260807"
REPORT_DIR = ROOT / "reports" / "research"
DEFAULT_REPORT = REPORT_DIR / f"opportunity_archetype_ranking_{REPORT_DATE}.md"
DEFAULT_METRICS = REPORT_DIR / f"opportunity_archetype_ranking_metrics_{REPORT_DATE}.csv"
DEFAULT_CHOSEN = REPORT_DIR / f"opportunity_archetype_ranking_chosen_{REPORT_DATE}.csv"

RANK_SPECS = [
    {"factor": "amount", "label": "成交额", "column": "amount", "directions": ["high"]},
    {"factor": "ret_5", "label": "近5日涨跌", "column": "ret_5", "directions": ["high", "low"]},
    {"factor": "ret_20", "label": "近20日涨跌", "column": "ret_20", "directions": ["high", "low"]},
    {"factor": "industry_rs_20", "label": "行业相对强度", "column": "industry_rs_20", "directions": ["high", "low"]},
    {"factor": "volume_ratio", "label": "量比", "column": "volume_ratio", "directions": ["high", "low"]},
    {"factor": "turnover_rate", "label": "换手率", "column": "turnover_rate", "directions": ["high", "low"]},
    {"factor": "rsi_14", "label": "RSI14", "column": "rsi_14", "directions": ["high", "low"]},
    {"factor": "drawdown_20", "label": "距20日高点回撤", "column": "drawdown_20", "directions": ["high", "low"]},
    {"factor": "pct_chg", "label": "当日涨跌", "column": "pct_chg", "directions": ["high", "low"]},
]

SPLITS = {
    "train": ("20160101", "20211231"),
    "validation": ("20220101", "20241231"),
    "sealed": ("20250101", "20260630"),
}


def _profile_mask(panel: pd.DataFrame, conditions: list[tuple[str, str]]) -> pd.Series:
    mask = pd.Series(True, index=panel.index)
    for column, value in conditions:
        if column not in panel.columns:
            return pd.Series(False, index=panel.index)
        mask &= panel[column].astype(str).eq(str(value))
    return mask


def select_ranked_candidates(
    panel: pd.DataFrame,
    profiles: list[dict] = FROZEN_PROFILES,
    rank_specs: list[dict] = RANK_SPECS,
    top_n: int = 3,
) -> pd.DataFrame:
    """对每个画像按单一信号日因子排序，成交后不递补。"""
    if panel.empty:
        return pd.DataFrame()
    names = panel.get("name", pd.Series("", index=panel.index)).fillna("").astype(str)
    eligible = (
        ~names.str.upper().str.contains("ST|退", regex=True)
        & pd.to_numeric(panel.get("history_count"), errors="coerce").ge(60)
        & pd.to_numeric(panel.get("turnover_rate"), errors="coerce").notna()
        & pd.to_numeric(panel.get("amount"), errors="coerce").gt(0)
        & pd.to_numeric(panel.get("ret_5d"), errors="coerce").notna()
    )
    selected = []
    for profile in profiles:
        profile_rows = panel[eligible & _profile_mask(panel, profile["conditions"])]
        if profile_rows.empty:
            continue
        for spec in rank_specs:
            column = spec["column"]
            if column not in profile_rows.columns:
                continue
            valid = profile_rows[pd.to_numeric(profile_rows[column], errors="coerce").notna()]
            for direction in spec["directions"]:
                ascending = direction == "low"
                work = (
                    valid.sort_values(
                        ["trade_date", column, "amount", "ts_code"],
                        ascending=[True, ascending, False, True],
                    )
                    .groupby("trade_date", group_keys=False)
                    .head(int(top_n))
                    .copy()
                )
                # 排名发生在T日；T+1无法成交的候选直接跳过，不拿下一名递补。
                work = work[
                    pd.to_numeric(work.get("entry_open"), errors="coerce").gt(0)
                    & pd.to_numeric(work.get("entry_gap_pct"), errors="coerce").lt(9.5)
                ]
                if work.empty:
                    continue
                work["profile_id"] = profile["profile_id"]
                work["profile_description"] = profile["description"]
                work["rank_factor"] = spec["factor"]
                work["rank_label"] = spec.get("label", spec["factor"])
                work["rank_direction"] = direction
                work["rank_id"] = f"{spec['factor']}_{direction}"
                work["top_n"] = int(top_n)
                selected.append(work)
    return pd.concat(selected, ignore_index=True, sort=False) if selected else pd.DataFrame()


def _profit_factor(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    gains = numeric[numeric > 0].sum()
    losses = abs(numeric[numeric < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def summarize_rankings(selected: pd.DataFrame, total_cost_pct: float = 0.30) -> pd.DataFrame:
    """计算固定3/5/8日持有的净收益，避免退出规则干扰排序判断。"""
    if selected.empty:
        return pd.DataFrame()
    work = selected.copy()
    if "rank_label" not in work.columns:
        work["rank_label"] = work["rank_factor"]
    if "top_n" not in work.columns:
        work["top_n"] = 3
    for horizon in (3, 5, 8):
        work[f"net_{horizon}d_pct"] = pd.to_numeric(work[f"ret_{horizon}d"], errors="coerce") - total_cost_pct
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
        net5 = group["net_5d_pct"].dropna()
        yearly = group.groupby("year")["net_5d_pct"].mean()
        rows.append(
            {
                **values,
                "trades": int(len(group)),
                "active_days": int(group["trade_date"].nunique()),
                "avg_net_3d_pct": round(float(group["net_3d_pct"].mean()), 4),
                "avg_net_5d_pct": round(float(net5.mean()), 4),
                "avg_net_8d_pct": round(float(group["net_8d_pct"].mean()), 4),
                "median_net_5d_pct": round(float(net5.median()), 4),
                "win_rate_5d": round(float((net5 > 0).mean()), 4),
                "profit_factor_5d": round(_profit_factor(net5), 4),
                "avg_mfe_8d_pct": round(float(group["mfe_8d"].mean()), 4),
                "avg_mae_8d_pct": round(float(group["mae_8d"].mean()), 4),
                "worst_year_avg_5d_pct": round(float(yearly.min()), 4),
            }
        )
    return pd.DataFrame(rows)


def choose_train_directions(metrics: pd.DataFrame) -> pd.DataFrame:
    """每个画像/因子的高低方向只按训练期5日净收益决定。"""
    if metrics.empty:
        return metrics.copy()
    metrics = metrics.copy()
    if "top_n" not in metrics.columns:
        metrics["top_n"] = 3
    train = metrics[metrics["split"].eq("train")].copy()
    train = train.sort_values(
        ["profile_id", "rank_factor", "top_n", "avg_net_5d_pct", "profit_factor_5d", "rank_id"],
        ascending=[True, True, True, False, False, True],
    )
    choices = train.groupby(["profile_id", "rank_factor", "top_n"], group_keys=False).head(1)
    keys = set(zip(choices["profile_id"], choices["rank_id"], choices["top_n"]))
    chosen = metrics[
        metrics.apply(lambda row: (row["profile_id"], row["rank_id"], row["top_n"]) in keys, axis=1)
    ].copy()
    return _apply_acceptance(chosen)


def _apply_acceptance(chosen: pd.DataFrame) -> pd.DataFrame:
    if chosen.empty:
        return chosen
    pass_map = {}
    for keys, group in chosen.groupby(["profile_id", "rank_id", "top_n"], sort=False):
        by_split = {row.split: row for row in group.itertuples(index=False)}
        train = by_split.get("train")
        validation = by_split.get("validation")
        sealed = by_split.get("sealed")
        def value(row, name, default=0):
            return getattr(row, name, default) if row is not None else default

        passed = bool(
            train and validation and sealed
            and value(train, "trades") >= 300
            and value(validation, "trades") >= 150
            and value(sealed, "trades") >= 75
            and value(validation, "avg_net_5d_pct") > 0.20
            and value(sealed, "avg_net_5d_pct") > 0.20
            and value(validation, "profit_factor_5d") > 1.05
            and value(sealed, "profit_factor_5d") > 1.05
            and value(validation, "win_rate_5d") >= 0.48
            and value(sealed, "win_rate_5d") >= 0.48
        )
        pass_map[keys] = passed
    chosen["research_pass"] = [
        pass_map[(row.profile_id, row.rank_id, row.top_n)] for row in chosen.itertuples(index=False)
    ]
    return chosen


def _split_label(dates: pd.Series) -> pd.Series:
    values = dates.astype(str)
    return pd.Series(
        np.select(
            [values.le(SPLITS["train"][1]), values.le(SPLITS["validation"][1])],
            ["train", "validation"],
            default="sealed",
        ),
        index=dates.index,
    )


def run_research(start: str, end: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_dates = market_research._available_dates(cache_dir, "19900101", end)
    stock_info = market_research._load_stock_info(cache_dir)
    regimes = market_research._build_regimes(cache_dir, all_dates)
    frames = []
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
        "ret_5d",
        "ret_8d",
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
        selected = select_ranked_candidates(panel, FROZEN_PROFILES, RANK_SPECS, top_n=3)
        if not selected.empty:
            frames.append(selected[keep].copy())
        del panel, selected
    if not frames:
        return pd.DataFrame(), pd.DataFrame()
    selected = pd.concat(frames, ignore_index=True, sort=False)
    selected["split"] = _split_label(selected["trade_date"])
    selected["year"] = selected["trade_date"].astype(str).str[:4]
    metrics = summarize_rankings(selected)
    chosen = choose_train_directions(metrics)
    return metrics, chosen


def _pct(value: float, ratio: bool = False) -> str:
    number = float(value) * 100 if ratio else float(value)
    return f"{number:+.2f}%"


def write_report(metrics: pd.DataFrame, chosen: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    passed_keys = chosen[chosen["research_pass"]][["profile_id", "rank_id", "top_n"]].drop_duplicates()
    lines = [
        "# 冻结机会画像内部排序研究",
        "",
        "## 研究口径",
        "",
        "- 每个画像每天最多选择Top3，因子方向只由2016至2021训练期决定。",
        "- T+1开盘成交，固定持有至第3/5/8日收盘，每笔扣除0.30%交易摩擦。",
        "- 验证期和封存期不参与方向选择；本研究不修改正式策略。",
        "",
        "## 结果",
        "",
        f"- 原始排序方向/阶段记录：`{len(metrics)}`。",
        f"- 训练期确定方向后的画像/因子：`{chosen[['profile_id', 'rank_id']].drop_duplicates().shape[0]}`。",
        f"- 同时通过验证与封存门槛：`{len(passed_keys)}`。",
        "",
        "| 画像 | 排序 | 阶段 | 交易 | 5日净收益 | 胜率 | 盈亏比 | 3日/8日净收益 | 最差年度 | 结论 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    sealed_order = chosen[chosen["split"].eq("sealed")].sort_values(
        ["research_pass", "avg_net_5d_pct", "profit_factor_5d"],
        ascending=[False, False, False],
    )
    top_keys = set(zip(sealed_order.head(20)["profile_id"], sealed_order.head(20)["rank_id"]))
    display = chosen[
        chosen.apply(lambda row: (row["profile_id"], row["rank_id"]) in top_keys, axis=1)
    ].sort_values(["research_pass", "profile_id", "rank_factor", "split"], ascending=[False, True, True, True])
    for row in display.itertuples(index=False):
        direction = "高到低" if row.rank_direction == "high" else "低到高"
        lines.append(
            f"| {row.profile_description} | {row.rank_label}（{direction}） | {row.split} | {row.trades} | "
            f"{_pct(row.avg_net_5d_pct)} | {_pct(row.win_rate_5d, ratio=True)} | {row.profit_factor_5d:.2f} | "
            f"{_pct(row.avg_net_3d_pct)} / {_pct(row.avg_net_8d_pct)} | {_pct(row.worst_year_avg_5d_pct)} | "
            f"{'通过' if row.research_pass else '观察'} |"
        )
    lines.extend(["", "## 结论", ""])
    if passed_keys.empty:
        lines.append("- 单因子排序仍无法稳定识别画像内部赢家，下一步不应继续堆叠阈值。")
    else:
        lines.append("- 通过项只进入真实OHLC退出复核，不直接接入正式推荐。")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="冻结机会画像内部个股排序研究。")
    parser.add_argument("--start", default="20160101")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "cache")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics, chosen = run_research(args.start, args.end, args.cache_dir)
    if metrics.empty:
        raise SystemExit("没有生成排序研究样本")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(DEFAULT_METRICS, index=False, encoding="utf-8-sig")
    chosen.to_csv(DEFAULT_CHOSEN, index=False, encoding="utf-8-sig")
    write_report(metrics, chosen, DEFAULT_REPORT)
    sealed = chosen[chosen["split"].eq("sealed")].sort_values(
        ["research_pass", "avg_net_5d_pct", "profit_factor_5d"],
        ascending=[False, False, False],
    )
    print("\nSEALED TOP30")
    print(sealed.head(30).to_string(index=False))
    passed = chosen[chosen["research_pass"]][["profile_id", "rank_id", "top_n"]].drop_duplicates()
    print(f"metrics={len(metrics)} chosen={chosen[['profile_id', 'rank_id']].drop_duplicates().shape[0]} passed={len(passed)}")
    print(f"report={DEFAULT_REPORT}")
    print(f"metrics_csv={DEFAULT_METRICS}")
    print(f"chosen_csv={DEFAULT_CHOSEN}")


if __name__ == "__main__":
    main()
