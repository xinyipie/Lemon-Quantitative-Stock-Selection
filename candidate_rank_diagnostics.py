"""Diagnose Top3 ranking misses from ic_short_*.csv candidate pools.

Usage:
  python candidate_rank_diagnostics.py
  python candidate_rank_diagnostics.py --candidates backtest_results/ic_short_20260603_172342.csv
  python candidate_rank_diagnostics.py --candidates backtest_results/ic_short_a.csv backtest_results/ic_short_b.csv
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from trade_diagnostics import factor_label


FACTOR_COLUMNS = [
    "score",
    "original_score",
    "score_base",
    "factor_pattern",
    "factor_inflow",
    "factor_sector",
    "factor_drawdown",
    "factor_wyckoff",
    "factor_volume_ratio",
    "factor_turnover",
    "factor_counter_trend",
    "factor_accel",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
    "change",
]
TARGET_COLUMNS = ["mfe_pct", "window_end_pct", "best_close_pct", "ret_5d", "ret_10d", "ret_20d", "mae_pct"]
IDENTITY_COLUMNS = ["select_date", "buy_date", "ts_code", "industry", "market_style", "macro_mode", "score"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Top3 vs rank 4-10 missed candidates from ic_short_*.csv files.")
    parser.add_argument("--candidates", nargs="*", default=None, help="One or more ic_short_*.csv files. Defaults to latest.")
    parser.add_argument("--results-dir", default="backtest_results", help="Directory containing ic_short_*.csv files.")
    parser.add_argument("--output", default=None, help="Markdown report path. Defaults to reports/candidate_rank_diagnostics_*.md.")
    parser.add_argument("--top-n", type=int, default=3, help="Selected rank cutoff. Defaults to 3.")
    parser.add_argument("--compare-max-rank", type=int, default=10, help="Lowest candidate rank to compare. Defaults to 10.")
    parser.add_argument("--top", type=int, default=20, help="Rows to show in report tables.")
    return parser.parse_args()


def find_latest_candidates(results_dir: str | Path = "backtest_results") -> Path:
    files = sorted(Path(results_dir).glob("ic_short_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No ic_short_*.csv files found under {results_dir}")
    return files[-1]


def load_candidates(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["source_file"] = Path(path).name
    return normalize_frame(df)


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    for col in set(FACTOR_COLUMNS + TARGET_COLUMNS):
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    for col in ["select_date", "buy_date", "ts_code", "industry", "market_style", "macro_mode", "source_file"]:
        if col in data.columns:
            data[col] = data[col].fillna("NA").astype(str)
    return data


def rank_candidates(df: pd.DataFrame, top_n: int = 3, compare_max_rank: int = 10, score_col: str = "score") -> pd.DataFrame:
    data = normalize_frame(df)
    required = {"select_date", score_col}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    data = data.sort_values(["select_date", score_col], ascending=[True, False]).copy()
    data["candidate_rank"] = data.groupby("select_date")[score_col].rank(method="first", ascending=False).astype(int)
    data["is_top_n"] = data["candidate_rank"] <= top_n
    data["rank_bucket"] = "rank_gt_compare"
    data.loc[data["is_top_n"], "rank_bucket"] = f"top_{top_n}"
    data.loc[
        (data["candidate_rank"] > top_n) & (data["candidate_rank"] <= compare_max_rank),
        "rank_bucket",
    ] = f"rank_{top_n + 1}_{compare_max_rank}"
    return data.reset_index(drop=True)


def find_missed_good_candidates(
    df: pd.DataFrame,
    top_n: int = 3,
    compare_max_rank: int = 10,
    score_col: str = "score",
) -> pd.DataFrame:
    ranked = df.copy() if "candidate_rank" in df.columns else rank_candidates(df, top_n, compare_max_rank, score_col)
    ranked = normalize_frame(ranked)
    top = ranked[ranked["candidate_rank"] <= top_n]
    if top.empty:
        return ranked.iloc[0:0].copy()

    baselines = top.groupby("select_date").agg(
        top_mfe_median=("mfe_pct", "median") if "mfe_pct" in top.columns else ("score", "median"),
        top_window_end_median=("window_end_pct", "median") if "window_end_pct" in top.columns else ("score", "median"),
    )
    compare = ranked[(ranked["candidate_rank"] > top_n) & (ranked["candidate_rank"] <= compare_max_rank)].copy()
    if compare.empty:
        return compare

    compare = compare.merge(baselines, left_on="select_date", right_index=True, how="left")
    mfe_better = compare["mfe_pct"] > compare["top_mfe_median"] if "mfe_pct" in compare.columns else False
    end_better = (
        compare["window_end_pct"] > compare["top_window_end_median"] if "window_end_pct" in compare.columns else False
    )
    missed = compare[mfe_better | end_better].copy()
    if missed.empty:
        return missed

    missed["miss_reason"] = ""
    missed.loc[mfe_better.loc[missed.index], "miss_reason"] += "MFE优于当日Top3中位数"
    both = mfe_better.loc[missed.index] & end_better.loc[missed.index]
    missed.loc[both, "miss_reason"] += "；"
    missed.loc[end_better.loc[missed.index], "miss_reason"] += "窗口期末优于当日Top3中位数"
    return missed.reset_index(drop=True)


def compare_top3_vs_missed(
    ranked: pd.DataFrame,
    missed: pd.DataFrame,
    factors: list[str] | None = None,
) -> pd.DataFrame:
    data = ranked.copy() if "candidate_rank" in ranked.columns else rank_candidates(ranked)
    factors = [col for col in (factors or FACTOR_COLUMNS) if col in data.columns]
    top3 = data[data["is_top_n"]]
    rows = []
    for factor in factors:
        top_avg = top3[factor].mean()
        missed_avg = missed[factor].mean() if factor in missed.columns else pd.NA
        if pd.isna(top_avg) or pd.isna(missed_avg):
            continue
        rows.append(
            {
                "factor": factor,
                "meaning": factor_label(factor),
                "top3_avg": round(float(top_avg), 2),
                "missed_avg": round(float(missed_avg), 2),
                "missed_minus_top3": round(float(missed_avg - top_avg), 2),
                "top3_count": int(top3[factor].notna().sum()),
                "missed_count": int(missed[factor].notna().sum()),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["factor", "meaning", "top3_avg", "missed_avg", "missed_minus_top3", "top3_count", "missed_count"])
    result = pd.DataFrame(rows)
    return result.sort_values("missed_minus_top3", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def summarize_rank_buckets(ranked: pd.DataFrame) -> pd.DataFrame:
    targets = [col for col in ["mfe_pct", "window_end_pct", "ret_5d", "mae_pct"] if col in ranked.columns]
    rows = []
    for bucket, part in ranked.groupby("rank_bucket", dropna=False):
        row = {"rank_bucket": bucket, "count": int(len(part))}
        for target in targets:
            row[f"avg_{target}"] = round(float(part[target].mean()), 2)
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_groups(ranked: pd.DataFrame, missed: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if group_col not in ranked.columns:
        return pd.DataFrame()
    top = ranked[ranked["is_top_n"]]
    top_counts = top.groupby(group_col).size().rename("top3_count")
    missed_counts = missed.groupby(group_col).size().rename("missed_count") if not missed.empty else pd.Series(dtype="int64")
    result = pd.concat([top_counts, missed_counts], axis=1).fillna(0).astype(int).reset_index()
    result["missed_per_top3"] = result.apply(
        lambda row: round(row["missed_count"] / row["top3_count"], 2) if row["top3_count"] else 0.0,
        axis=1,
    )
    return result.sort_values(["missed_count", "top3_count"], ascending=[False, False]).reset_index(drop=True)


def build_plain_chinese_summary(ranked: pd.DataFrame, missed: pd.DataFrame, diff: pd.DataFrame) -> str:
    total_top = int(ranked["is_top_n"].sum()) if "is_top_n" in ranked.columns else 0
    total_compare = int(((ranked["candidate_rank"] > 3) & (ranked["candidate_rank"] <= 10)).sum()) if "candidate_rank" in ranked.columns else 0
    missed_count = int(len(missed))
    lines = [
        f"- 共分析 `{ranked['select_date'].nunique()}` 个选股日，Top3 样本 `{total_top}` 个，第4-10名样本 `{total_compare}` 个。",
        f"- 发现 `{missed_count}` 个第4-10名错过好票：它们的 MFE 或窗口期末收益优于当日 Top3 中位数。",
    ]
    if not diff.empty:
        strongest = diff.head(5)
        names = [
            f"{row.meaning}（`{row.factor}`，错过组比Top3 {row.missed_minus_top3:+.2f}）"
            for row in strongest.itertuples()
        ]
        lines.append("- 错过好票最突出的因子差异：" + "、".join(names) + "。")
    if missed_count:
        lines.append("- 这些差异更适合先作为下一轮排序归因线索，不建议直接一次性改多项权重。")
    else:
        lines.append("- 当前文件没有发现明显 Top3 排名错过样本，说明这个区间后排候选没有提供清晰增量。")
    return "\n".join(lines)


def build_markdown_report(
    df: pd.DataFrame,
    source: str = "",
    top_n: int = 3,
    compare_max_rank: int = 10,
    top: int = 20,
) -> str:
    ranked = rank_candidates(df, top_n=top_n, compare_max_rank=compare_max_rank)
    missed = find_missed_good_candidates(ranked, top_n=top_n, compare_max_rank=compare_max_rank)
    diff = compare_top3_vs_missed(ranked, missed)
    rank_summary = summarize_rank_buckets(ranked)

    sections = [
        "# Candidate Rank Diagnostics",
        "",
        f"- Source: {source or 'in-memory dataframe'}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Rank rule: score desc, Top{top_n} vs rank {top_n + 1}-{compare_max_rank}",
        "",
        "## 先看结论",
        build_plain_chinese_summary(ranked, missed, diff),
        "",
        "## Rank Bucket 表现",
        rank_summary.to_markdown(index=False) if not rank_summary.empty else "_No data._",
        "",
        "## Top3 vs 错过好票因子差异",
        diff.head(top).to_markdown(index=False) if not diff.empty else "_No missed candidates._",
        "",
        "## 错过好票样例",
        _sample_table(missed, top),
    ]

    for group_col in ["market_style", "macro_mode"]:
        group = summarize_groups(ranked, missed, group_col)
        if not group.empty:
            sections.extend(["", f"## 按 {group_col} 拆分", group.head(top).to_markdown(index=False)])
    return "\n".join(sections) + "\n"


def _sample_table(missed: pd.DataFrame, top: int) -> str:
    if missed.empty:
        return "_No missed candidates._"
    columns = [col for col in IDENTITY_COLUMNS + ["candidate_rank", "mfe_pct", "window_end_pct", "miss_reason"] if col in missed.columns]
    return missed.sort_values(["mfe_pct", "window_end_pct"], ascending=[False, False]).head(top)[columns].to_markdown(index=False)


def default_output_path() -> Path:
    return Path("reports") / f"candidate_rank_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"


def main() -> None:
    args = parse_args()
    paths = [Path(p) for p in args.candidates] if args.candidates else [find_latest_candidates(args.results_dir)]
    frames = [load_candidates(path) for path in paths]
    df = pd.concat(frames, ignore_index=True)
    source = ", ".join(str(path) for path in paths)
    report = build_markdown_report(
        df,
        source=source,
        top_n=args.top_n,
        compare_max_rank=args.compare_max_rank,
        top=args.top,
    )
    output_path = Path(args.output) if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Report written: {output_path}")
    print("\n".join(report.splitlines()[6:12]))


if __name__ == "__main__":
    main()
