from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path

import pandas as pd

from delayed_entry_path_audit import load_daily_subset, load_samples


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
SOURCE = REPORTS / "stage3_candidate_consensus_topn_selected.csv"


@dataclass(frozen=True)
class TimingRule:
    bucket: str
    wait_days: int


TIMING_RULES = [
    TimingRule("T1", 0),
    TimingRule("T3", 2),
    TimingRule("T5", 4),
    TimingRule("T7", 6),
]


@dataclass(frozen=True)
class SearchRule:
    entry_bucket: str
    max_best_rank: float | None = None
    max_avg_rank: float | None = None
    min_pattern: float | None = None
    max_limit_down: float | None = None
    min_pre_low: float | None = None
    min_pre_close: float | None = None

    @property
    def name(self) -> str:
        parts = [self.entry_bucket]
        if self.max_best_rank is not None:
            parts.append(f"best_rank<={self.max_best_rank:g}")
        if self.max_avg_rank is not None:
            parts.append(f"avg_rank<={self.max_avg_rank:g}")
        if self.min_pattern is not None:
            parts.append(f"pattern>={self.min_pattern:g}")
        if self.max_limit_down is not None:
            parts.append(f"limit_down<={self.max_limit_down:g}")
        if self.min_pre_low is not None:
            parts.append(f"pre_low>{self.min_pre_low:g}")
        if self.min_pre_close is not None:
            parts.append(f"pre_close>{self.min_pre_close:g}")
        return "|".join(parts)


FACTOR_COLUMNS = [
    "n_versions",
    "best_rank",
    "avg_rank",
    "avg_score",
    "max_score",
    "factor_sector",
    "factor_pattern",
    "factor_wyckoff",
    "factor_inflow",
    "factor_volume_ratio",
    "factor_drawdown",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "market_index_change",
    "sector_ma10_ratio",
    "limit_up_count",
    "limit_down_count",
    "consensus_score",
    "recent_factor_score",
    "hybrid_score",
]


PATH_COLUMNS = [
    "pre_T3_low_pct",
    "pre_T3_close_min_pct",
    "pre_T5_low_pct",
    "pre_T5_close_min_pct",
    "pre_T7_low_pct",
    "pre_T7_close_min_pct",
    "pre_T7_high_pct",
]


def _date(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace("-", "")[:8]


def _year_bucket(date: str) -> str:
    if str(date).startswith("2026"):
        return "2026H1"
    return str(date)[:4]


def load_stage3_samples() -> pd.DataFrame:
    source = pd.read_csv(SOURCE, encoding="utf-8-sig")
    source["sample"] = "stage3_candidates"
    source["select_date"] = source["select_date"].map(_date)
    source["ts_code"] = source["ts_code"].astype(str)
    for col in FACTOR_COLUMNS:
        if col in source.columns:
            source[col] = pd.to_numeric(source[col], errors="coerce")

    helper = load_samples()
    helper = helper[helper["sample"].eq("stage3_candidates")][["sample", "select_date", "buy_date", "ts_code"]]
    source = source.merge(helper, on=["sample", "select_date", "ts_code"], how="inner")
    return source.drop_duplicates(["select_date", "ts_code"]).reset_index(drop=True)


def _future_path(code_df: pd.DataFrame, buy_date: str, max_len: int = 14) -> pd.DataFrame:
    idx = code_df.index[code_df["trade_date"] >= buy_date]
    if len(idx) == 0:
        return pd.DataFrame()
    pos = code_df.index.get_loc(idx[0])
    return code_df.iloc[pos : pos + max_len].reset_index(drop=True)


def _path_feature(path: pd.DataFrame, base_open: float, end_exclusive: int, kind: str) -> float | None:
    if end_exclusive <= 0 or len(path) < end_exclusive:
        return None
    scoped = path.iloc[:end_exclusive]
    if kind == "low":
        return (float(scoped["low"].min()) / base_open - 1) * 100
    if kind == "close_min":
        return (float(scoped["close"].min()) / base_open - 1) * 100
    if kind == "high":
        return (float(scoped["high"].max()) / base_open - 1) * 100
    return None


def _simulate_entry(path: pd.DataFrame, rule: TimingRule, hold_days: int = 5) -> dict | None:
    if len(path) <= rule.wait_days:
        return None
    entry_idx = rule.wait_days
    exit_idx = min(entry_idx + hold_days - 1, len(path) - 1)
    if exit_idx <= entry_idx:
        return None
    entry = path.iloc[entry_idx]
    after_entry = path.iloc[entry_idx : exit_idx + 1]
    entry_price = float(entry["open"])
    if entry_price <= 0:
        return None
    ret = (float(path.iloc[exit_idx]["close"]) / entry_price - 1) * 100
    mfe = (float(after_entry["high"].max()) / entry_price - 1) * 100
    mae = (float(after_entry["low"].min()) / entry_price - 1) * 100
    return {
        "entry_bucket": rule.bucket,
        "entry_date": entry["trade_date"],
        "entry_price": entry_price,
        "exit_date": path.iloc[exit_idx]["trade_date"],
        "ret_5d_from_entry": ret,
        "mfe_from_entry": mfe,
        "mae_from_entry": mae,
        "win": ret > 0,
        "hit3": mfe >= 3.0,
    }


def build_entry_outcomes(samples: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_by_code = {code: part.reset_index(drop=True) for code, part in daily.groupby("ts_code")}
    outcome_rows = []
    path_rows = []

    for row in samples.itertuples(index=False):
        code_df = daily_by_code.get(str(row.ts_code))
        if code_df is None:
            continue
        path = _future_path(code_df, str(row.buy_date))
        if len(path) < 8:
            continue
        base_open = float(path.iloc[0]["open"])
        base = row._asdict()
        path_features = {
            "pre_T3_low_pct": _path_feature(path, base_open, 2, "low"),
            "pre_T3_close_min_pct": _path_feature(path, base_open, 2, "close_min"),
            "pre_T5_low_pct": _path_feature(path, base_open, 4, "low"),
            "pre_T5_close_min_pct": _path_feature(path, base_open, 4, "close_min"),
            "pre_T7_low_pct": _path_feature(path, base_open, 6, "low"),
            "pre_T7_close_min_pct": _path_feature(path, base_open, 6, "close_min"),
            "pre_T7_high_pct": _path_feature(path, base_open, 6, "high"),
        }
        path_rows.append({**base, **path_features, "year": _year_bucket(str(row.buy_date))})
        for rule in TIMING_RULES:
            result = _simulate_entry(path, rule)
            if result is not None:
                outcome_rows.append({**base, **path_features, **result, "year": _year_bucket(result["entry_date"])})

    return pd.DataFrame(outcome_rows), pd.DataFrame(path_rows)


def classify_tickets(outcomes: pd.DataFrame) -> pd.DataFrame:
    keys = ["select_date", "buy_date", "ts_code"]
    rows = []
    for _, group in outcomes.groupby(keys, sort=False):
        work = group.copy()
        viable = work[
            (work["ret_5d_from_entry"] > 0)
            & (work["mfe_from_entry"] >= 3.0)
            & (work["mae_from_entry"] > -5.0)
        ].copy()
        if viable.empty:
            best = work.sort_values(["ret_5d_from_entry", "mfe_from_entry"], ascending=[False, False]).iloc[0]
            label = "NO_BUY"
        else:
            viable["quality_score"] = (
                viable["ret_5d_from_entry"] * 1.0
                + viable["mfe_from_entry"] * 0.25
                + viable["mae_from_entry"] * 0.35
            )
            best = viable.sort_values(["quality_score", "ret_5d_from_entry"], ascending=[False, False]).iloc[0]
            label = str(best["entry_bucket"])
        row = best.to_dict()
        row["recommended_bucket"] = label
        row["best_ret"] = float(best["ret_5d_from_entry"])
        row["best_mfe"] = float(best["mfe_from_entry"])
        row["best_mae"] = float(best["mae_from_entry"])
        rows.append(row)
    return pd.DataFrame(rows)


def summarise_bucket(outcomes: pd.DataFrame, classified: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    entry_summary = (
        outcomes.groupby("entry_bucket")
        .agg(
            trades=("ts_code", "count"),
            win_rate=("win", "mean"),
            avg_ret=("ret_5d_from_entry", "mean"),
            total_ret=("ret_5d_from_entry", "sum"),
            hit3_rate=("hit3", "mean"),
            avg_mfe=("mfe_from_entry", "mean"),
            avg_mae=("mae_from_entry", "mean"),
        )
        .reset_index()
    )
    for col in ["win_rate", "hit3_rate"]:
        entry_summary[col] = entry_summary[col] * 100

    bucket_summary = (
        classified.groupby("recommended_bucket")
        .agg(
            tickets=("ts_code", "count"),
            avg_best_ret=("best_ret", "mean"),
            win_rate=("win", "mean"),
            avg_best_mfe=("best_mfe", "mean"),
            avg_best_mae=("best_mae", "mean"),
        )
        .reset_index()
    )
    bucket_summary["win_rate"] = bucket_summary["win_rate"] * 100

    yearly = (
        classified.groupby(["recommended_bucket", "year"])
        .agg(
            tickets=("ts_code", "count"),
            avg_best_ret=("best_ret", "mean"),
            total_best_ret=("best_ret", "sum"),
            win_rate=("win", "mean"),
        )
        .reset_index()
        .sort_values(["recommended_bucket", "year"])
    )
    yearly["win_rate"] = yearly["win_rate"] * 100
    return entry_summary, bucket_summary, yearly


def factor_profiles(classified: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in FACTOR_COLUMNS + PATH_COLUMNS if c in classified.columns]
    rows = []
    for bucket, group in classified.groupby("recommended_bucket"):
        row = {"recommended_bucket": bucket, "tickets": len(group)}
        for col in cols:
            row[f"{col}_mean"] = pd.to_numeric(group[col], errors="coerce").mean()
        rows.append(row)
    return pd.DataFrame(rows)


def contrast_profiles(classified: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in FACTOR_COLUMNS + PATH_COLUMNS if c in classified.columns]
    rows = []
    no_buy = classified[classified["recommended_bucket"].eq("NO_BUY")]
    for bucket, group in classified.groupby("recommended_bucket"):
        if bucket == "NO_BUY" or group.empty or no_buy.empty:
            continue
        row = {"recommended_bucket": bucket, "tickets": len(group)}
        for col in cols:
            bucket_mean = pd.to_numeric(group[col], errors="coerce").mean()
            no_buy_mean = pd.to_numeric(no_buy[col], errors="coerce").mean()
            row[f"{col}_edge_vs_no_buy"] = bucket_mean - no_buy_mean
        rows.append(row)
    return pd.DataFrame(rows)


def _pre_cols_for_bucket(bucket: str) -> tuple[str | None, str | None]:
    if bucket == "T3":
        return "pre_T3_low_pct", "pre_T3_close_min_pct"
    if bucket == "T5":
        return "pre_T5_low_pct", "pre_T5_close_min_pct"
    if bucket == "T7":
        return "pre_T7_low_pct", "pre_T7_close_min_pct"
    return None, None


def _apply_search_rule(df: pd.DataFrame, rule: SearchRule) -> pd.DataFrame:
    work = df[df["entry_bucket"].eq(rule.entry_bucket)].copy()
    if rule.max_best_rank is not None:
        work = work[pd.to_numeric(work["best_rank"], errors="coerce") <= rule.max_best_rank]
    if rule.max_avg_rank is not None:
        work = work[pd.to_numeric(work["avg_rank"], errors="coerce") <= rule.max_avg_rank]
    if rule.min_pattern is not None:
        work = work[pd.to_numeric(work["factor_pattern"], errors="coerce") >= rule.min_pattern]
    if rule.max_limit_down is not None:
        work = work[pd.to_numeric(work["limit_down_count"], errors="coerce") <= rule.max_limit_down]
    pre_low_col, pre_close_col = _pre_cols_for_bucket(rule.entry_bucket)
    if rule.min_pre_low is not None and pre_low_col is not None:
        work = work[pd.to_numeric(work[pre_low_col], errors="coerce") > rule.min_pre_low]
    if rule.min_pre_close is not None and pre_close_col is not None:
        work = work[pd.to_numeric(work[pre_close_col], errors="coerce") > rule.min_pre_close]
    return work


def _search_rules_for_bucket(bucket: str) -> list[SearchRule]:
    rank_grid = [None, 1.5, 2.0]
    avg_rank_grid = [None, 2.0, 2.5, 3.0]
    pattern_grid = [None, 50.0, 60.0]
    limit_down_grid = [None, 8.0, 12.0]
    if bucket == "T1":
        pre_low_grid = [None]
        pre_close_grid = [None]
    else:
        pre_low_grid = [None, -2.0, -3.0, -4.0]
        pre_close_grid = [None, -1.0, -2.0, -3.0]

    rules = []
    for values in product(rank_grid, avg_rank_grid, pattern_grid, limit_down_grid, pre_low_grid, pre_close_grid):
        max_best_rank, max_avg_rank, min_pattern, max_limit_down, min_pre_low, min_pre_close = values
        if max_best_rank is None and max_avg_rank is None and min_pattern is None and max_limit_down is None and min_pre_low is None:
            continue
        rules.append(
            SearchRule(
                entry_bucket=bucket,
                max_best_rank=max_best_rank,
                max_avg_rank=max_avg_rank,
                min_pattern=min_pattern,
                max_limit_down=max_limit_down,
                min_pre_low=min_pre_low,
                min_pre_close=min_pre_close,
            )
        )
    return rules


def search_entry_rules(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for bucket in ["T1", "T3", "T5", "T7"]:
        min_trades = 25 if bucket == "T1" else 35
        for rule in _search_rules_for_bucket(bucket):
            selected = _apply_search_rule(outcomes, rule)
            if len(selected) < min_trades:
                continue
            yearly = selected.groupby("year")["ret_5d_from_entry"].sum()
            recent = selected[selected["year"].isin(["2025", "2026H1"])]
            win_rate = float(selected["win"].mean() * 100)
            hit3_rate = float(selected["hit3"].mean() * 100)
            total_ret = float(selected["ret_5d_from_entry"].sum())
            recent_win = float(recent["win"].mean() * 100) if len(recent) else 0.0
            loss_years = int((yearly <= 0).sum())
            score = (
                win_rate * 0.9
                + hit3_rate * 0.25
                + min(total_ret, 250.0) * 0.1
                + recent_win * 0.4
                + min(len(selected), 120) * 0.1
                - loss_years * 7.0
                - abs(min(float(yearly.min()), 0.0)) * 1.2
            )
            rows.append(
                {
                    "rule": rule.name,
                    "entry_bucket": bucket,
                    "trades": int(len(selected)),
                    "win_rate": win_rate,
                    "hit3_rate": hit3_rate,
                    "total_ret": total_ret,
                    "avg_ret": float(selected["ret_5d_from_entry"].mean()),
                    "avg_mae": float(selected["mae_from_entry"].mean()),
                    "recent_trades": int(len(recent)),
                    "recent_win_rate": recent_win,
                    "positive_years": int((yearly > 0).sum()),
                    "loss_years": loss_years,
                    "worst_year": float(yearly.min()),
                    "score": score,
                }
            )
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows)
    return result.sort_values(
        ["score", "win_rate", "total_ret", "trades"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def _write_doc(
    entry_summary: pd.DataFrame,
    bucket_summary: pd.DataFrame,
    yearly: pd.DataFrame,
    profiles: pd.DataFrame,
    contrast: pd.DataFrame,
    rule_search: pd.DataFrame,
    output: Path,
) -> None:
    key_cols = [
        "recommended_bucket",
        "tickets",
        "best_rank_mean",
        "avg_rank_mean",
        "factor_pattern_mean",
        "factor_inflow_mean",
        "sector_ma10_ratio_mean",
        "limit_down_count_mean",
        "pre_T3_low_pct_mean",
        "pre_T5_low_pct_mean",
        "pre_T7_low_pct_mean",
    ]
    profile_view = profiles[[c for c in key_cols if c in profiles.columns]].copy()
    contrast_cols = [
        "recommended_bucket",
        "tickets",
        "best_rank_edge_vs_no_buy",
        "avg_rank_edge_vs_no_buy",
        "factor_pattern_edge_vs_no_buy",
        "factor_inflow_edge_vs_no_buy",
        "sector_ma10_ratio_edge_vs_no_buy",
        "limit_down_count_edge_vs_no_buy",
        "pre_T3_low_pct_edge_vs_no_buy",
        "pre_T5_low_pct_edge_vs_no_buy",
        "pre_T7_low_pct_edge_vs_no_buy",
    ]
    contrast_view = contrast[[c for c in contrast_cols if c in contrast.columns]].copy()

    lines = [
        "# T1/T3/T5/T7 入场时点分桶研究（2026-07-06）",
        "",
        "## 研究口径",
        "",
        "对 stage3 历史候选票逐一模拟 T1/T3/T5/T7 开盘买入，并统一看入场后 5 个交易日收益、MFE、MAE。若某个入场点满足 `ret>0`、`MFE>=3%`、`MAE>-5%`，则按质量分选择最佳入场桶；若所有入场点都不满足，则标为 `NO_BUY`。",
        "",
        "## 四个入场点整体表现",
        "",
        entry_summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 最佳分桶分布",
        "",
        bucket_summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 年度拆分",
        "",
        yearly.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 分桶共性均值",
        "",
        profile_view.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 相对不买桶的差异",
        "",
        contrast_view.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 当时可用规则搜索 Top20",
        "",
        rule_search.head(20).to_markdown(index=False, floatfmt=".2f") if not rule_search.empty else "无",
        "",
        "## 初步读法",
        "",
        "- `T1` 桶若排名更强、形态更高、早期回撤更浅，说明强势票不应等待。",
        "- `T3/T5/T7` 桶若早期低点更深但未破坏结构，说明它们更像确认买点。",
        "- `NO_BUY` 桶的共性会作为下一轮过滤器候选，而不是直接上线。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    samples = load_stage3_samples()
    daily = load_daily_subset(samples[["sample", "select_date", "buy_date", "ts_code"]])
    outcomes, paths = build_entry_outcomes(samples, daily)
    classified = classify_tickets(outcomes)
    entry_summary, bucket_summary, yearly = summarise_bucket(outcomes, classified)
    profiles = factor_profiles(classified)
    contrast = contrast_profiles(classified)
    rule_search = search_entry_rules(outcomes)

    outcomes.to_csv(REPORTS / "entry_timing_outcomes_T1_T3_T5_T7_20260706.csv", index=False, encoding="utf-8-sig")
    classified.to_csv(REPORTS / "entry_timing_classified_T1_T3_T5_T7_20260706.csv", index=False, encoding="utf-8-sig")
    entry_summary.to_csv(REPORTS / "entry_timing_entry_summary_20260706.csv", index=False, encoding="utf-8-sig")
    bucket_summary.to_csv(REPORTS / "entry_timing_bucket_summary_20260706.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(REPORTS / "entry_timing_yearly_20260706.csv", index=False, encoding="utf-8-sig")
    profiles.to_csv(REPORTS / "entry_timing_factor_profiles_20260706.csv", index=False, encoding="utf-8-sig")
    contrast.to_csv(REPORTS / "entry_timing_factor_contrast_20260706.csv", index=False, encoding="utf-8-sig")
    rule_search.to_csv(REPORTS / "entry_timing_rule_search_20260706.csv", index=False, encoding="utf-8-sig")
    _write_doc(
        entry_summary,
        bucket_summary,
        yearly,
        profiles,
        contrast,
        rule_search,
        DOCS / "ENTRY_TIMING_BUCKET_RESEARCH_20260706.md",
    )

    print(entry_summary.to_string(index=False))
    print()
    print(bucket_summary.to_string(index=False))
    print()
    key_cols = [
        "recommended_bucket",
        "tickets",
        "best_rank_mean",
        "avg_rank_mean",
        "factor_pattern_mean",
        "factor_inflow_mean",
        "sector_ma10_ratio_mean",
        "limit_down_count_mean",
        "pre_T3_low_pct_mean",
        "pre_T5_low_pct_mean",
        "pre_T7_low_pct_mean",
    ]
    print(profiles[[c for c in key_cols if c in profiles.columns]].to_string(index=False))
    print()
    print(rule_search.head(30).to_string(index=False) if not rule_search.empty else "no rule candidates")


if __name__ == "__main__":
    main()
