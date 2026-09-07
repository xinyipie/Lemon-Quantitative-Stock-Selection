from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


DEFAULT_PROFILES = ("v35", "v39", "v40")
NUMERIC_COLUMNS = (
    "ret_5d",
    "ret_10d",
    "ret_20d",
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
    "consensus_votes",
    "consensus_avg_rank",
    "consensus_avg_score",
    "score",
    "original_score",
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_counter_trend",
    "factor_wyckoff",
    "factor_accel",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
    "score_base",
    "market_index_change",
    "sector_ma10_ratio",
    "limit_up_count",
    "limit_down_count",
    "limit_up_down_ratio",
)
CATEGORICAL_COLUMNS = (
    "consensus_profile",
    "consensus_layer",
    "market_style",
    "macro_mode",
    "market_state",
    "operation_mode",
    "regime",
    "industry",
)


def load_ic_samples(
    backtest_dir: str | Path = "backtest_results",
    profiles: tuple[str, ...] = DEFAULT_PROFILES,
) -> pd.DataFrame:
    frames = []
    for path in sorted(Path(backtest_dir).glob("ic_short_*.csv")):
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            continue
        if df.empty or "consensus_profile" not in df.columns:
            continue
        df = df[df["consensus_profile"].astype(str).isin(profiles)].copy()
        if df.empty:
            continue
        df["source_file"] = path.name
        if "select_date" in df.columns:
            df["select_year"] = df["select_date"].astype(str).str.slice(0, 4)
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    for column in NUMERIC_COLUMNS:
        if column in combined.columns:
            combined[column] = pd.to_numeric(combined[column], errors="coerce")
    for column in ("hit_3pct", "hit_5pct", "hit_10pct"):
        if column in combined.columns:
            combined[column] = combined[column].map(_to_bool)
    combined = combined.sort_values("source_file")
    dedupe_keys = [col for col in ("consensus_profile", "select_date", "ts_code") if col in combined.columns]
    if dedupe_keys:
        combined = combined.drop_duplicates(dedupe_keys, keep="last")
    if "ret_5d" in combined.columns:
        combined["win_5d"] = combined["ret_5d"] > 0
    if "hit_3pct" not in combined.columns and "mfe_pct" in combined.columns:
        combined["hit_3pct"] = combined["mfe_pct"] >= 3.0
    return combined.reset_index(drop=True)


def build_winner_commonality(samples: pd.DataFrame) -> dict:
    if samples.empty:
        return {"sample_count": 0}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sample_count": int(len(samples)),
        "profiles": sorted(samples["consensus_profile"].dropna().astype(str).unique()),
        "overall": _profile_summary(samples),
        "numeric_edges": _numeric_edges(samples),
        "rule_edges": _rule_edges(samples),
        "category_edges": _category_edges(samples),
        "year_profile": _year_profile(samples),
    }


def write_winner_commonality(
    backtest_dir: str | Path = "backtest_results",
    output: str | Path = "reports/winner_commonality_audit_20260706.md",
    profiles: tuple[str, ...] = DEFAULT_PROFILES,
) -> dict:
    samples = load_ic_samples(backtest_dir=backtest_dir, profiles=profiles)
    result = build_winner_commonality(samples)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_format_markdown(result), encoding="utf-8")
    if not samples.empty:
        samples.to_csv(output.with_suffix(".samples.csv"), index=False, encoding="utf-8-sig")
    return {"output": str(output), "sample_count": int(len(samples))}


def _profile_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for profile, group in df.groupby("consensus_profile", dropna=False):
        rows.append(_metrics(str(profile), group))
    rows.append(_metrics("ALL", df))
    return pd.DataFrame(rows)


def _metrics(label: str, df: pd.DataFrame) -> dict:
    return {
        "group": label,
        "samples": int(len(df)),
        "win_5d_rate": _rate(df, "win_5d"),
        "hit_3pct_rate": _rate(df, "hit_3pct"),
        "hit_5pct_rate": _rate(df, "hit_5pct"),
        "avg_ret_5d": _mean(df, "ret_5d"),
        "avg_mfe": _mean(df, "mfe_pct"),
        "avg_mae": _mean(df, "mae_pct"),
        "avg_rank": _mean(df, "consensus_avg_rank"),
        "votes3_rate": _rate_expr(df, lambda x: pd.to_numeric(x.get("consensus_votes"), errors="coerce") >= 3),
    }


def _numeric_edges(df: pd.DataFrame) -> pd.DataFrame:
    if "win_5d" not in df.columns:
        return pd.DataFrame()
    rows = []
    for column in NUMERIC_COLUMNS:
        if column not in df.columns:
            continue
        winners = df[df["win_5d"]][column].dropna()
        losers = df[~df["win_5d"]][column].dropna()
        if len(winners) < 3 or len(losers) < 3:
            continue
        rows.append(
            {
                "factor": column,
                "winner_mean": round(float(winners.mean()), 3),
                "loser_mean": round(float(losers.mean()), 3),
                "delta": round(float(winners.mean() - losers.mean()), 3),
                "winner_median": round(float(winners.median()), 3),
                "loser_median": round(float(losers.median()), 3),
            }
        )
    return pd.DataFrame(rows).sort_values("delta", ascending=False).reset_index(drop=True)


def _rule_edges(df: pd.DataFrame) -> pd.DataFrame:
    rules = []
    candidates = [
        ("votes=3", lambda x: pd.to_numeric(x.get("consensus_votes"), errors="coerce") >= 3),
        ("avg_rank<=1.5", lambda x: pd.to_numeric(x.get("consensus_avg_rank"), errors="coerce") <= 1.5),
        ("limit_down<=4", lambda x: pd.to_numeric(x.get("limit_down_count"), errors="coerce") <= 4),
        ("limit_down<=12", lambda x: pd.to_numeric(x.get("limit_down_count"), errors="coerce") <= 12),
        ("limit_up>=60", lambda x: pd.to_numeric(x.get("limit_up_count"), errors="coerce") >= 60),
        ("sector_ma10<=70", lambda x: pd.to_numeric(x.get("sector_ma10_ratio"), errors="coerce") <= 70),
        ("sector_ma10>70", lambda x: pd.to_numeric(x.get("sector_ma10_ratio"), errors="coerce") > 70),
        ("volume 1.4-2.8", lambda x: pd.to_numeric(x.get("volume_ratio"), errors="coerce").between(1.4, 2.8)),
        ("drawdown<=7", lambda x: pd.to_numeric(x.get("drawdown_from_high"), errors="coerce") <= 7),
        ("change<=4.5", lambda x: pd.to_numeric(x.get("change"), errors="coerce") <= 4.5),
        ("wyckoff 60-75", lambda x: pd.to_numeric(x.get("factor_wyckoff"), errors="coerce").between(60, 75)),
        ("pattern>=60", lambda x: pd.to_numeric(x.get("factor_pattern"), errors="coerce") >= 60),
        ("factor_sector<=60", lambda x: pd.to_numeric(x.get("factor_sector"), errors="coerce") <= 60),
    ]
    for name, func in candidates:
        try:
            mask = func(df).fillna(False)
        except Exception:
            continue
        scoped = df[mask].copy()
        if len(scoped) < 3:
            continue
        row = _metrics(name, scoped)
        row["coverage_rate"] = round(len(scoped) / len(df) * 100, 2)
        rules.append(row)
    if not rules:
        return pd.DataFrame()
    return pd.DataFrame(rules).sort_values(["hit_3pct_rate", "avg_ret_5d", "samples"], ascending=False).reset_index(drop=True)


def _category_edges(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in CATEGORICAL_COLUMNS:
        if column not in df.columns:
            continue
        for value, group in df.groupby(column, dropna=False):
            if len(group) < 3:
                continue
            row = _metrics(f"{column}={value}", group)
            row["coverage_rate"] = round(len(group) / len(df) * 100, 2)
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["hit_3pct_rate", "avg_ret_5d", "samples"], ascending=False).reset_index(drop=True)


def _year_profile(df: pd.DataFrame) -> pd.DataFrame:
    if "select_year" not in df.columns:
        return pd.DataFrame()
    rows = []
    for (year, profile), group in df.groupby(["select_year", "consensus_profile"], dropna=False):
        rows.append(_metrics(f"{year}/{profile}", group))
    return pd.DataFrame(rows)


def _format_markdown(result: dict) -> str:
    if not result.get("sample_count"):
        return "# 会涨股票共性分析\n\n没有可用样本。\n"
    lines = [
        "# 会涨股票共性分析",
        "",
        "## 口径",
        "",
        f"- 样本数：{result['sample_count']}",
        f"- 共识版本：{', '.join(result['profiles'])}",
        "- 样本来自 `backtest_results/ic_short_*.csv`，按 `consensus_profile + select_date + ts_code` 去重。",
        "- `win_5d` 表示 5 日前瞻收益为正；`hit_3pct` 表示持有窗口内曾冲高 3%。",
        "- 本报告只分析共性，不修改任何策略。",
        "",
        "## 分版本概览",
        "",
        result["overall"].to_markdown(index=False),
        "",
        "## 会涨票相对不涨票的数值差异",
        "",
        result["numeric_edges"].head(20).to_markdown(index=False),
        "",
        "## 单条件分组",
        "",
        result["rule_edges"].head(20).to_markdown(index=False),
        "",
        "## 类别分组",
        "",
        result["category_edges"].head(20).to_markdown(index=False),
        "",
        "## 年份/版本分组",
        "",
        result["year_profile"].to_markdown(index=False),
    ]
    return "\n".join(lines) + "\n"


def _to_bool(value) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _mean(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns or df.empty:
        return 0.0
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return round(float(values.mean()), 2) if len(values) else 0.0


def _rate(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns or df.empty:
        return 0.0
    values = df[column].dropna()
    return round(float(values.mean()) * 100, 2) if len(values) else 0.0


def _rate_expr(df: pd.DataFrame, expr) -> float:
    if df.empty:
        return 0.0
    try:
        values = expr(df).fillna(False)
    except Exception:
        return 0.0
    return round(float(values.mean()) * 100, 2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze common traits of short-line winners.")
    parser.add_argument("--backtest-dir", default="backtest_results")
    parser.add_argument("--output", default="reports/winner_commonality_audit_20260706.md")
    parser.add_argument("--profiles", nargs="*", default=list(DEFAULT_PROFILES))
    args = parser.parse_args()
    print(write_winner_commonality(args.backtest_dir, args.output, tuple(args.profiles)))


if __name__ == "__main__":
    main()
