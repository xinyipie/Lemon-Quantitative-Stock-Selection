#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""波段候选信号诊断工具。

核心目的不是再跑回测，而是回答：
1. 哪些交易曾经有较高 MFE，最后却亏损；
2. Top3 是否错过后排更好的候选；
3. 入场位置、动量、换手等特征是否对应更高风险或更好收益。
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


FACTOR_COLUMNS = [
    "longterm_score",
    "score_momentum",
    "score_flow",
    "score_rs",
    "score_fin",
    "score_entry",
    "drawdown_from_high",
    "industry_rs",
    "price_vs_ma60",
    "main_net_inflow",
    "volume_ratio",
    "turnover",
    "ma20_slope",
    "roe",
    "debt_ratio",
    "netprofit_yoy",
]

TARGET_COLUMNS = [
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
    "ret_5d",
    "ret_10d",
    "ret_20d",
    "profit_after_fee",
]

FACTOR_LABELS = {
    "longterm_score": "波段总分",
    "score_momentum": "动量分",
    "score_flow": "资金流分",
    "score_rs": "行业RS分",
    "score_fin": "财务分",
    "score_entry": "入场质量分",
    "drawdown_from_high": "距高点回撤",
    "industry_rs": "行业相对强度",
    "price_vs_ma60": "价格相对MA60",
    "main_net_inflow": "主力净流入",
    "volume_ratio": "量比",
    "turnover": "换手率",
    "ma20_slope": "MA20斜率",
    "roe": "ROE",
    "debt_ratio": "资产负债率",
    "netprofit_yoy": "净利润同比",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成波段候选信号诊断 Markdown 报告")
    parser.add_argument("--candidates", nargs="+", required=True, help="一个或多个 ic_longterm_*.csv")
    parser.add_argument("--trades", nargs="*", default=None, help="可选：对应 trades_*.csv，用于分析高MFE亏损交易")
    parser.add_argument("--output", required=True, help="输出 Markdown 路径")
    parser.add_argument("--title", default="波段信号诊断", help="报告标题")
    parser.add_argument("--top-n", type=int, default=3, help="默认比较 Top3")
    parser.add_argument("--compare-max-rank", type=int, default=10, help="后排候选比较到第几名")
    parser.add_argument("--mfe-threshold", type=float, default=10.0, help="高MFE亏损阈值")
    return parser.parse_args()


def load_csvs(paths: list[str | Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        p = Path(path)
        df = pd.read_csv(p, encoding="utf-8-sig")
        df["source_file"] = p.name
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return normalize_frame(pd.concat(frames, ignore_index=True))


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    for col in set(FACTOR_COLUMNS + TARGET_COLUMNS + ["score", "original_score"]):
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    for col in ["select_date", "buy_date", "sell_date", "ts_code", "exit_reason", "source_file"]:
        if col in data.columns:
            data[col] = data[col].fillna("NA").astype(str)
    if "score" not in data.columns and "longterm_score" in data.columns:
        data["score"] = data["longterm_score"]
    return data


def add_candidate_rank(df: pd.DataFrame, top_n: int = 3, score_col: str = "score") -> pd.DataFrame:
    data = normalize_frame(df)
    required = {"select_date", score_col}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    data = data.sort_values(["select_date", score_col], ascending=[True, False]).copy()
    data["candidate_rank"] = data.groupby("select_date")[score_col].rank(method="first", ascending=False).astype(int)
    data["is_top_n"] = data["candidate_rank"] <= top_n
    return data.reset_index(drop=True)


def find_missed_good_candidates(
    df: pd.DataFrame,
    top_n: int = 3,
    compare_max_rank: int = 10,
) -> pd.DataFrame:
    ranked = df.copy() if "candidate_rank" in df.columns else add_candidate_rank(df, top_n=top_n)
    top = ranked[ranked["candidate_rank"] <= top_n]
    compare = ranked[(ranked["candidate_rank"] > top_n) & (ranked["candidate_rank"] <= compare_max_rank)].copy()
    if top.empty or compare.empty:
        return compare.iloc[0:0].copy()

    baselines = top.groupby("select_date").agg(
        top_mfe_median=("mfe_pct", "median"),
        top_end_median=("window_end_pct", "median"),
    )
    compare = compare.merge(baselines, left_on="select_date", right_index=True, how="left")
    mask = (compare["mfe_pct"] > compare["top_mfe_median"]) | (
        compare["window_end_pct"] > compare["top_end_median"]
    )
    return compare[mask].sort_values(["select_date", "candidate_rank"]).reset_index(drop=True)


def find_high_mfe_losers(trades: pd.DataFrame, mfe_threshold: float = 10.0) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()
    data = normalize_frame(trades)
    profit_col = "profit_after_fee" if "profit_after_fee" in data.columns else "profit_pct"
    if profit_col not in data.columns or "mfe_pct" not in data.columns:
        return data.iloc[0:0].copy()
    result = data[(data["mfe_pct"] >= mfe_threshold) & (data[profit_col] < 0)].copy()
    if result.empty:
        return result
    result["opportunity_gap_pct"] = result["mfe_pct"] - result[profit_col]
    return result.sort_values(["opportunity_gap_pct", "mfe_pct"], ascending=[False, False]).reset_index(drop=True)


def compare_topn_vs_missed(ranked: pd.DataFrame, missed: pd.DataFrame) -> pd.DataFrame:
    data = ranked.copy() if "candidate_rank" in ranked.columns else add_candidate_rank(ranked)
    top = data[data["is_top_n"]]
    rows = []
    for factor in [c for c in FACTOR_COLUMNS if c in data.columns and c in missed.columns]:
        top_avg = top[factor].mean()
        missed_avg = missed[factor].mean()
        if pd.isna(top_avg) or pd.isna(missed_avg):
            continue
        rows.append(
            {
                "factor": factor,
                "meaning": FACTOR_LABELS.get(factor, factor),
                "topn_avg": round(float(top_avg), 2),
                "missed_avg": round(float(missed_avg), 2),
                "missed_minus_topn": round(float(missed_avg - top_avg), 2),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["factor", "meaning", "topn_avg", "missed_avg", "missed_minus_topn"])
    return pd.DataFrame(rows).sort_values("missed_minus_topn", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def summarize_entry_buckets(df: pd.DataFrame, column: str, bins: list[float]) -> pd.DataFrame:
    data = normalize_frame(df)
    if column not in data.columns:
        return pd.DataFrame()
    labels = []
    for left, right in zip(bins[:-1], bins[1:]):
        if left <= -90:
            labels.append(f"<={right:g}")
        elif right >= 90:
            labels.append(f">{left:g}")
        else:
            labels.append(f"{left:g}-{right:g}")
    data = data.copy()
    if "hit_10pct" not in data.columns:
        data["hit_10pct"] = data["mfe_pct"] >= 10 if "mfe_pct" in data.columns else False
    data["bucket"] = pd.cut(data[column], bins=bins, labels=labels, include_lowest=True)
    rows = (
        data.groupby("bucket", observed=False)
        .agg(
            count=("ts_code", "size"),
            avg_mfe_pct=("mfe_pct", "mean"),
            avg_mae_pct=("mae_pct", "mean"),
            avg_window_end_pct=("window_end_pct", "mean"),
            hit_10_rate=("hit_10pct", lambda s: float(pd.Series(s).astype(bool).mean() * 100) if len(s) else 0),
        )
        .reset_index()
    )
    for col in ["avg_mfe_pct", "avg_mae_pct", "avg_window_end_pct", "hit_10_rate"]:
        rows[col] = rows[col].round(2)
    rows["bucket"] = rows["bucket"].astype(str)
    return rows


def summarize_factor_correlations(df: pd.DataFrame) -> pd.DataFrame:
    data = normalize_frame(df)
    rows = []
    for target in ["mfe_pct", "mae_pct", "window_end_pct", "ret_20d"]:
        if target not in data.columns:
            continue
        for factor in FACTOR_COLUMNS:
            if factor not in data.columns:
                continue
            sub = data[[factor, target]].dropna()
            if len(sub) < 30 or sub[factor].nunique() <= 1:
                continue
            corr = sub[factor].corr(sub[target], method="spearman")
            if pd.isna(corr):
                continue
            rows.append(
                {
                    "target": target,
                    "factor": factor,
                    "meaning": FACTOR_LABELS.get(factor, factor),
                    "spearman": round(float(corr), 3),
                    "n": int(len(sub)),
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("spearman", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def _table(df: pd.DataFrame, max_rows: int = 12) -> str:
    if df is None or df.empty:
        return "_无样本。_"
    return df.head(max_rows).to_markdown(index=False)


def build_plain_summary(candidates: pd.DataFrame, trades: pd.DataFrame, high_mfe_losers: pd.DataFrame, missed: pd.DataFrame) -> str:
    lines = [
        f"- 候选池样本 `{len(candidates)}` 条，覆盖 `{candidates['select_date'].nunique() if 'select_date' in candidates.columns else 0}` 个选股日。",
    ]
    if trades is not None and not trades.empty:
        profit_col = "profit_after_fee" if "profit_after_fee" in trades.columns else "profit_pct"
        avg_profit = pd.to_numeric(trades[profit_col], errors="coerce").mean() if profit_col in trades.columns else float("nan")
        avg_mfe = pd.to_numeric(trades.get("mfe_pct", pd.Series(dtype=float)), errors="coerce").mean()
        lines.append(f"- 交易样本 `{len(trades)}` 笔，平均扣费收益 `{avg_profit:+.2f}%`，平均 MFE `{avg_mfe:+.2f}%`。")
    lines.append(f"- 高MFE但最终亏损样本 `{len(high_mfe_losers)}` 笔，这是优先检查出场/入场时机的核心样本。")
    lines.append(f"- Top3 后排错过好票 `{len(missed)}` 条，用来判断当前波段排序是否把好票排低。")
    if len(high_mfe_losers) > 0:
        lines.append("- 如果高MFE亏损集中在止损或弱收盘退出，优先研究止损/移动止盈，而不是先改评分。")
    if len(missed) > 0:
        lines.append("- 如果后排好票入场质量或位置明显优于Top3，再考虑波段评分权重。")
    return "\n".join(lines)


def build_markdown_report(
    candidates: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    source: str = "",
    title: str = "波段信号诊断",
    top_n: int = 3,
    compare_max_rank: int = 10,
    mfe_threshold: float = 10.0,
) -> str:
    candidates = normalize_frame(candidates)
    trades = normalize_frame(trades) if trades is not None and not trades.empty else pd.DataFrame()
    ranked = add_candidate_rank(candidates, top_n=top_n)
    missed = find_missed_good_candidates(ranked, top_n=top_n, compare_max_rank=compare_max_rank)
    high_mfe_losers = find_high_mfe_losers(trades, mfe_threshold=mfe_threshold)
    diff = compare_topn_vs_missed(ranked, missed)
    corr = summarize_factor_correlations(candidates)

    price_bucket = summarize_entry_buckets(candidates, "price_vs_ma60", [-99, 6, 12, 99])
    drawdown_bucket = summarize_entry_buckets(candidates, "drawdown_from_high", [-99, 5, 15, 35, 99])
    turnover_bucket = summarize_entry_buckets(candidates, "turnover", [-99, 2, 5, 99])
    slope_bucket = summarize_entry_buckets(candidates, "ma20_slope", [-99, 0, 1, 99])

    high_mfe_cols = [
        "ts_code",
        "select_date",
        "buy_date",
        "sell_date",
        "profit_after_fee",
        "exit_reason",
        "mfe_pct",
        "mae_pct",
        "opportunity_gap_pct",
        "price_vs_ma60",
        "drawdown_from_high",
        "turnover",
        "ma20_slope",
    ]
    missed_cols = [
        "select_date",
        "ts_code",
        "candidate_rank",
        "score",
        "mfe_pct",
        "window_end_pct",
        "top_mfe_median",
        "top_end_median",
        "score_entry",
        "price_vs_ma60",
        "drawdown_from_high",
        "turnover",
        "ma20_slope",
    ]

    sections = [
        f"# {title}",
        "",
        f"- Source: {source or 'in-memory dataframe'}",
        f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 先看结论",
        build_plain_summary(candidates, trades, high_mfe_losers, missed),
        "",
        "## 高MFE但最终亏损",
        _table(high_mfe_losers[[c for c in high_mfe_cols if c in high_mfe_losers.columns]], max_rows=20),
        "",
        "## Top3 vs 后排好票",
        _table(diff, max_rows=20),
        "",
        "## 后排好票样例",
        _table(missed[[c for c in missed_cols if c in missed.columns]], max_rows=20),
        "",
        "## 入场风险分桶",
        "### price_vs_ma60",
        _table(price_bucket, max_rows=10),
        "",
        "### drawdown_from_high",
        _table(drawdown_bucket, max_rows=10),
        "",
        "### turnover",
        _table(turnover_bucket, max_rows=10),
        "",
        "### ma20_slope",
        _table(slope_bucket, max_rows=10),
        "",
        "## 因子相关性线索",
        _table(corr, max_rows=30),
        "",
        "## 下一步建议",
        "- 先把高MFE亏损样本按退出原因复盘，判断是否需要更早锁利或调整止损触发。",
        "- 再看后排好票与Top3的差异，确认排序问题是否稳定存在。",
        "- 若入场风险分桶显示高位/高换手/弱斜率风险明显，再做单变量规则实验。",
    ]
    return "\n".join(sections) + "\n"


def main() -> None:
    args = parse_args()
    candidates = load_csvs(args.candidates)
    trades = load_csvs(args.trades) if args.trades else pd.DataFrame()
    report = build_markdown_report(
        candidates=candidates,
        trades=trades,
        source=", ".join([Path(p).name for p in args.candidates]),
        title=args.title,
        top_n=args.top_n,
        compare_max_rank=args.compare_max_rank,
        mfe_threshold=args.mfe_threshold,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Report written: {output}")
    print("\n".join(report.splitlines()[:10]))


if __name__ == "__main__":
    main()
