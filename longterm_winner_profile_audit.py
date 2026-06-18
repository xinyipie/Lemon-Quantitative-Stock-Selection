#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reverse-audit longterm pool winners and losers from quality-audit CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_FACTORS = [
    "winner_profile_score",
    "pool_rank_score",
    "quality_rank_score",
    "longterm_score",
    "industry_rs",
    "price_vs_ma60",
    "drawdown_from_high",
    "ma20_slope",
    "turnover",
    "volume_ratio",
    "roe",
    "debt_ratio",
    "netprofit_yoy",
    "total_mv",
    "circ_mv",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "dv_ratio",
    "main_net_inflow",
]

DISPLAY_COLUMNS = [
    "select_date",
    "ts_code",
    "name",
    "industry",
    "pool_type",
    "ret_10d",
    "ret_40d",
    "ret_80d",
    "excess_ret_80d",
    "winner_profile_score",
    "pool_rank_score",
    "quality_rank_score",
    "v8_timing_gate",
    "v8_timing_reasons",
    "market_admission",
    "market_admission_reasons",
    "v9_quality_floor",
    "v9_quality_reasons",
    "risk_flags",
]


def _fmt_pct(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):+.2f}%"


def _table(df: pd.DataFrame, max_rows: int = 40) -> str:
    if df.empty:
        return "无样本\n"
    return df.head(max_rows).to_markdown(index=False) + "\n"


def _numeric_columns(data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    for col in out.columns:
        if col in DEFAULT_FACTORS or col.startswith(("ret_", "mfe_", "mae_", "benchmark_ret_", "excess_ret_")):
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in out.columns:
        if col.startswith("outperform_"):
            if out[col].dtype == object:
                out[col] = out[col].astype(str).str.lower().map({"true": True, "false": False})
    return out


def load_quality_csv(paths: list[str]) -> pd.DataFrame:
    frames = []
    for path in paths:
        p = Path(path)
        if not p.exists() or p.stat().st_size <= 5:
            continue
        data = pd.read_csv(p, encoding="utf-8-sig")
        if data.empty:
            continue
        data["source_file"] = p.name
        frames.append(data)
    if not frames:
        return pd.DataFrame()
    return _numeric_columns(pd.concat(frames, ignore_index=True))


def classify_samples(
    df: pd.DataFrame,
    horizon: int = 80,
    winner_ret: float = 15.0,
    loser_ret: float = -10.0,
    winner_excess: float = 0.0,
    loser_excess: float = -10.0,
) -> pd.DataFrame:
    data = _numeric_columns(df)
    ret_col = f"ret_{horizon}d"
    excess_col = f"excess_ret_{horizon}d"
    out_col = f"outperform_{horizon}d"
    if data.empty or ret_col not in data.columns:
        data["sample_group"] = pd.Series(dtype=object)
        return data

    data = data.dropna(subset=[ret_col]).copy()
    if excess_col not in data.columns:
        data[excess_col] = data[ret_col]
    if out_col not in data.columns:
        data[out_col] = data[excess_col] > 0

    winner = (data[ret_col] >= winner_ret) & (data[excess_col] >= winner_excess) & (data[out_col] == True)
    loser = (data[ret_col] <= loser_ret) | (data[excess_col] <= loser_excess)
    data["sample_group"] = "中间"
    data.loc[winner, "sample_group"] = "赢家"
    data.loc[loser & ~winner, "sample_group"] = "输家"
    return data


def factor_difference_table(df: pd.DataFrame, factors: list[str] | None = None) -> pd.DataFrame:
    factors = factors or DEFAULT_FACTORS
    rows = []
    winners = df[df.get("sample_group") == "赢家"]
    losers = df[df.get("sample_group") == "输家"]
    for factor in factors:
        if factor not in df.columns:
            continue
        w = pd.to_numeric(winners[factor], errors="coerce").dropna()
        l = pd.to_numeric(losers[factor], errors="coerce").dropna()
        if w.empty or l.empty:
            continue
        rows.append(
            {
                "factor": factor,
                "winner_mean": round(float(w.mean()), 2),
                "loser_mean": round(float(l.mean()), 2),
                "diff": round(float(w.mean() - l.mean()), 2),
                "winner_n": int(len(w)),
                "loser_n": int(len(l)),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["factor", "winner_mean", "loser_mean", "diff", "winner_n", "loser_n"])
    return pd.DataFrame(rows).sort_values("diff", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def segment_summary(df: pd.DataFrame, column: str, horizon: int = 80) -> pd.DataFrame:
    ret_col = f"ret_{horizon}d"
    out_col = f"outperform_{horizon}d"
    if df.empty or column not in df.columns or ret_col not in df.columns:
        return pd.DataFrame()
    rows = []
    for value, group in df.groupby(column, dropna=False):
        valid = group.dropna(subset=[ret_col])
        if valid.empty:
            continue
        rows.append(
            {
                column: value,
                "count": int(len(valid)),
                "winner_count": int((valid["sample_group"] == "赢家").sum()),
                "loser_count": int((valid["sample_group"] == "输家").sum()),
                f"avg_ret_{horizon}d": round(float(valid[ret_col].mean()), 2),
                f"win_rate_{horizon}d": round(float((valid[ret_col] > 0).mean() * 100), 2),
                f"outperform_{horizon}d": round(float(valid[out_col].mean() * 100), 2) if out_col in valid.columns else None,
            }
        )
    return pd.DataFrame(rows).sort_values(["winner_count", f"avg_ret_{horizon}d"], ascending=[False, False])


def group_counts(df: pd.DataFrame, horizon: int = 80) -> pd.DataFrame:
    ret_col = f"ret_{horizon}d"
    if df.empty or ret_col not in df.columns:
        return pd.DataFrame()
    rows = []
    for group_name in ["赢家", "中间", "输家"]:
        sub = df[df["sample_group"] == group_name]
        rows.append(
            {
                "sample_group": group_name,
                "count": int(len(sub)),
                f"avg_ret_{horizon}d": round(float(sub[ret_col].mean()), 2) if not sub.empty else None,
                f"median_ret_{horizon}d": round(float(sub[ret_col].median()), 2) if not sub.empty else None,
            }
        )
    return pd.DataFrame(rows)


def build_report(df: pd.DataFrame, horizon: int = 80, title: str = "长线赢家画像审计") -> str:
    data = df.copy()
    counts = group_counts(data, horizon)
    factors = factor_difference_table(data)
    by_pool = segment_summary(data, "pool_type", horizon)
    by_industry = segment_summary(data, "industry", horizon)
    ret_col = f"ret_{horizon}d"
    excess_col = f"excess_ret_{horizon}d"

    valid = data.dropna(subset=[ret_col]) if ret_col in data.columns else pd.DataFrame()
    winners = data[data.get("sample_group") == "赢家"].sort_values(ret_col, ascending=False) if not data.empty else pd.DataFrame()
    losers = data[data.get("sample_group") == "输家"].sort_values(ret_col, ascending=True) if not data.empty else pd.DataFrame()
    display_cols = [c for c in DISPLAY_COLUMNS if c in data.columns]

    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 本报告反推已有长线池中，未来 `{horizon}` 日赢家和输家的共同特征。\n",
        f"- 有效样本 `{len(valid)}` 个；赢家 `{int((data.get('sample_group') == '赢家').sum()) if 'sample_group' in data.columns else 0}` 个，输家 `{int((data.get('sample_group') == '输家').sum()) if 'sample_group' in data.columns else 0}` 个。\n",
    ]
    if not valid.empty:
        avg_excess = valid[excess_col].mean() if excess_col in valid.columns else None
        lines.append(
            f"- 整体 `{horizon}` 日平均收益 `{_fmt_pct(valid[ret_col].mean())}`，"
            f"平均超额 `{_fmt_pct(avg_excess)}`。\n"
        )
    if not factors.empty:
        top = factors.iloc[0]
        lines.append(
            f"- 赢家/输家差异最大的字段：`{top['factor']}`，赢家均值 `{top['winner_mean']}`，"
            f"输家均值 `{top['loser_mean']}`，差值 `{top['diff']}`。\n"
        )

    lines.extend(
        [
            "\n## 样本分组\n",
            _table(counts, 20),
            "\n## 因子差异\n",
            _table(factors, 60),
            "\n## 按池类型\n",
            _table(by_pool, 20),
            "\n## 按行业\n",
            _table(by_industry, 30),
            "\n## 赢家样本\n",
            _table(winners[display_cols] if display_cols else winners, 30),
            "\n## 输家样本\n",
            _table(losers[display_cols] if display_cols else losers, 30),
        ]
    )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit longterm winners and losers from pool-quality CSV files.")
    parser.add_argument("--inputs", nargs="+", required=True, help="Quality-audit CSV files.")
    parser.add_argument("--horizon", type=int, default=80, help="Forward horizon in trading days.")
    parser.add_argument("--winner-ret", type=float, default=15.0, help="Winner minimum forward return.")
    parser.add_argument("--winner-excess", type=float, default=0.0, help="Winner minimum excess return.")
    parser.add_argument("--loser-ret", type=float, default=-10.0, help="Loser maximum forward return.")
    parser.add_argument("--loser-excess", type=float, default=-10.0, help="Loser maximum excess return.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--csv-output", default=None, help="Optional classified CSV output path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = load_quality_csv(args.inputs)
    classified = classify_samples(
        data,
        horizon=args.horizon,
        winner_ret=args.winner_ret,
        loser_ret=args.loser_ret,
        winner_excess=args.winner_excess,
        loser_excess=args.loser_excess,
    )
    report = build_report(classified, args.horizon)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8-sig")
    if args.csv_output:
        csv_output = Path(args.csv_output)
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        classified.to_csv(csv_output, index=False, encoding="utf-8-sig")
    print(f"Report written: {output}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
