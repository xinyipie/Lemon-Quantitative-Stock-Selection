from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


NUMERIC_FACTORS = (
    "score",
    "original_score",
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_wyckoff",
    "factor_accel",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
    "market_index_change",
    "sector_ma10_ratio",
    "limit_up_count",
    "limit_down_count",
    "limit_up_down_ratio",
    "consensus_votes",
    "consensus_avg_rank",
    "consensus_avg_score",
    "n_versions",
    "best_rank",
    "avg_rank",
    "avg_score",
    "mfe_pct",
    "mae_pct",
)

CATEGORICAL_FACTORS = (
    "market_style",
    "macro_mode",
    "market_state",
    "operation_mode",
    "regime",
    "industry",
    "rule",
)

CSV_SOURCES = (
    ("v19_v25_v27_snapshot", "reports/consensus_snapshot_v19_v25_v27_20260703.csv"),
    ("stage3_consensus_candidates", "reports/stage3_candidate_consensus_topn_selected.csv"),
    ("stage3_gated_consensus", "reports/stage3_gated_candidate_consensus_topn_selected.csv"),
    ("v29_top1_trades", "reports/v29_top1_all_trades.csv"),
    ("v35_top1_aggregate", "reports/v35_top1_annual_aggregate_trades_20260704.csv"),
    ("v39_top1_aggregate", "reports/v39_top1_annual_aggregate_trades_20260704.csv"),
    ("v35_v39_v40_samples", "reports/winner_commonality_audit_20260706.samples.csv"),
)

JSON_REPORTS = (
    ("v9_v19_trades_miner", "reports/short_signal_factor_miner_v9_v19.json"),
    ("v9_v19_candidates_miner", "reports/short_signal_factor_miner_candidates_v9_v19.json"),
    ("v19_v25_v27_stage2_all", "reports/stage2_factor_miner_v19_v25_v27_all.json"),
    ("v19_v25_v27_stage2_recent", "reports/stage2_factor_miner_v19_v25_v27_recent.json"),
    ("current_factor_stability", "reports/short_factor_stability_current.json"),
)


def load_samples(include_ic_short: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    inventory: list[dict] = []

    for family, file_name in CSV_SOURCES:
        path = Path(file_name)
        if not path.exists():
            inventory.append({"family": family, "file": file_name, "status": "missing"})
            continue
        df = _read_csv(path)
        if df.empty:
            inventory.append({"family": family, "file": file_name, "status": "empty"})
            continue
        normalized = _normalize_frame(df, family, path.name)
        frames.append(normalized)
        inventory.append(_inventory_row(family, path, df, normalized))

    if include_ic_short:
        for path in sorted(Path("backtest_results").glob("ic_short_*.csv")):
            df = _read_csv(path, nrows=None)
            if df.empty or "consensus_profile" not in df.columns:
                continue
            normalized = _normalize_frame(df, "ic_short_consensus_profile", path.name)
            if normalized.empty:
                continue
            frames.append(normalized)
            inventory.append(_inventory_row("ic_short_consensus_profile", path, df, normalized))

    if not frames:
        return pd.DataFrame(), pd.DataFrame(inventory)

    samples = pd.concat(frames, ignore_index=True)
    for column in NUMERIC_FACTORS + ("ret_5d", "profit_after_fee", "profit_pct"):
        if column in samples.columns:
            samples[column] = pd.to_numeric(samples[column], errors="coerce")
    if "select_date" in samples.columns:
        samples["select_date"] = samples["select_date"].astype(str).str.replace(".0", "", regex=False)
        samples["year"] = samples["select_date"].str.slice(0, 4)

    samples["return_pct"] = _first_numeric(samples, ("ret_5d", "profit_after_fee", "profit_pct"))
    samples["win"] = samples["return_pct"] > 0
    samples["hit3"] = _hit3(samples)
    samples["pit"] = (samples["return_pct"] < 0) & (pd.to_numeric(samples.get("mae_pct"), errors="coerce") <= -5)

    dedupe_cols = [c for c in ("source_family", "version_tag", "select_date", "ts_code") if c in samples.columns]
    if dedupe_cols:
        samples = samples.drop_duplicates(dedupe_cols, keep="last")
    return samples.reset_index(drop=True), pd.DataFrame(inventory)


def build_report(samples: pd.DataFrame, inventory: pd.DataFrame) -> dict:
    miner = load_miner_reports()
    if samples.empty:
        return {"sample_count": 0, "inventory": inventory, "miner": miner}
    execution_samples = samples[~samples["source_family"].isin(["stage3_consensus_candidates"])].copy()

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sample_count": int(len(samples)),
        "version_count": int(samples["version_tag"].nunique()),
        "inventory": inventory,
        "coverage": _coverage(samples),
        "version_summary": _group_summary(samples, "version_tag"),
        "family_summary": _group_summary(samples, "source_family"),
        "year_summary": _group_summary(samples, "year"),
        "numeric_edges": _numeric_edges(samples),
        "category_edges": _category_edges(samples),
        "rule_edges": _rule_edges(samples),
        "rule_year_stability": _rule_year_stability(samples),
        "execution_sample_count": int(len(execution_samples)),
        "execution_version_summary": _group_summary(execution_samples, "version_tag"),
        "execution_rule_edges": _rule_edges(execution_samples),
        "execution_numeric_edges": _numeric_edges(execution_samples),
        "miner": miner,
    }


def write_report(output: str | Path, samples_output: str | Path | None = None) -> dict:
    samples, inventory = load_samples()
    report = build_report(samples, inventory)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_format_markdown(report), encoding="utf-8")
    if samples_output and not samples.empty:
        Path(samples_output).parent.mkdir(parents=True, exist_ok=True)
        samples.to_csv(samples_output, index=False, encoding="utf-8-sig")
    return {"output": str(output), "samples": int(len(samples))}


def load_miner_reports() -> list[dict]:
    rows: list[dict] = []
    for family, file_name in JSON_REPORTS:
        path = Path(file_name)
        if not path.exists():
            rows.append({"family": family, "file": file_name, "status": "missing"})
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            rows.append({"family": family, "file": file_name, "status": f"error: {exc}"})
            continue
        if family == "current_factor_stability":
            short = data.get("short", {})
            for bucket in ("stable_positive", "stable_negative", "unstable", "weak"):
                for item in short.get(bucket, [])[:8]:
                    rows.append(
                        {
                            "family": family,
                            "file": file_name,
                            "bucket": bucket,
                            "rule": item.get("factor") or item.get("rule") or str(item)[:80],
                            "sample_count": item.get("sample_count", ""),
                            "period_count": item.get("period_count", ""),
                            "win_rate": item.get("win_rate", ""),
                            "total_profit_pct": item.get("total_profit_pct", ""),
                            "avg_profit_pct": item.get("avg_profit_pct", ""),
                        }
                    )
            continue
        for bucket in ("top_candidates", "fragile"):
            for item in data.get(bucket, [])[:10]:
                rows.append(
                    {
                        "family": family,
                        "file": file_name,
                        "bucket": bucket,
                        "rule": item.get("rule", ""),
                        "sample_count": item.get("sample_count", ""),
                        "period_count": item.get("period_count", ""),
                        "win_rate": item.get("win_rate", ""),
                        "total_profit_pct": item.get("total_profit_pct", ""),
                        "avg_profit_pct": item.get("avg_profit_pct", ""),
                        "avg_mfe_pct": item.get("avg_mfe_pct", ""),
                        "avg_mae_pct": item.get("avg_mae_pct", ""),
                    }
                )
    return rows


def _normalize_frame(df: pd.DataFrame, family: str, source_file: str) -> pd.DataFrame:
    if "ts_code" not in df.columns:
        return pd.DataFrame()
    if not any(col in df.columns for col in ("ret_5d", "profit_after_fee", "profit_pct")):
        return pd.DataFrame()
    normalized = df.copy()
    normalized["source_family"] = family
    normalized["source_file"] = source_file
    normalized["version_tag"] = _version_tag(normalized, family, source_file)
    keep = list(dict.fromkeys(
        col
        for col in (
            "source_family",
            "source_file",
            "version_tag",
            "period",
            "select_date",
            "buy_date",
            "ts_code",
            "name",
            "industry",
            "ret_5d",
            "profit_after_fee",
            "profit_pct",
            "mfe_pct",
            "mae_pct",
            "hit_3pct",
        )
        + NUMERIC_FACTORS
        + CATEGORICAL_FACTORS
        if col in normalized.columns
    ))
    return normalized[keep].copy()


def _version_tag(df: pd.DataFrame, family: str, source_file: str) -> pd.Series:
    if "consensus_profile" in df.columns:
        return df["consensus_profile"].astype(str)
    if "virtual_profile" in df.columns:
        return df["virtual_profile"].astype(str)
    if "consensus_profiles" in df.columns:
        return "consensus:" + df["consensus_profiles"].astype(str)
    match = re.search(r"(v\d+)", source_file, flags=re.I)
    if match:
        return pd.Series(match.group(1).lower(), index=df.index)
    return pd.Series(family, index=df.index)


def _inventory_row(family: str, path: Path, raw: pd.DataFrame, normalized: pd.DataFrame) -> dict:
    return {
        "family": family,
        "file": str(path),
        "raw_rows": int(len(raw)),
        "usable_rows": int(len(normalized)),
        "columns": int(len(raw.columns)),
        "factor_columns": int(sum(c in raw.columns for c in NUMERIC_FACTORS + CATEGORICAL_FACTORS)),
        "versions": ",".join(sorted(normalized.get("version_tag", pd.Series(dtype=str)).dropna().astype(str).unique())[:12]),
        "status": "ok",
    }


def _coverage(samples: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for version, group in samples.groupby("version_tag", dropna=False):
        years = sorted(group.get("year", pd.Series(dtype=str)).dropna().astype(str).unique())
        rows.append(
            {
                "version": str(version),
                "samples": int(len(group)),
                "years": f"{years[0]}-{years[-1]}" if years else "",
                "year_count": len(years),
                "factor_cols": int(sum(col in group.columns and group[col].notna().any() for col in NUMERIC_FACTORS)),
            }
        )
    return pd.DataFrame(rows).sort_values(["samples", "version"], ascending=[False, True])


def _group_summary(samples: pd.DataFrame, column: str) -> pd.DataFrame:
    if column not in samples.columns:
        return pd.DataFrame()
    rows = []
    for key, group in samples.groupby(column, dropna=False):
        rows.append(_metrics(str(key), group))
    return pd.DataFrame(rows).sort_values(["samples", "total_return_pct"], ascending=[False, False])


def _metrics(label: str, group: pd.DataFrame) -> dict:
    returns = pd.to_numeric(group["return_pct"], errors="coerce").dropna()
    return {
        "group": label,
        "samples": int(len(group)),
        "win_rate": _rate(group["win"]),
        "hit3_rate": _rate(group["hit3"]),
        "pit_rate": _rate(group["pit"]),
        "avg_return_pct": round(float(returns.mean()), 2) if len(returns) else 0.0,
        "total_return_pct": round(float(returns.sum()), 2) if len(returns) else 0.0,
        "avg_mfe_pct": _mean(group, "mfe_pct"),
        "avg_mae_pct": _mean(group, "mae_pct"),
    }


def _numeric_edges(samples: pd.DataFrame) -> pd.DataFrame:
    rows = []
    winners = samples[samples["win"]]
    losers = samples[~samples["win"]]
    for column in NUMERIC_FACTORS:
        if column not in samples.columns:
            continue
        w = pd.to_numeric(winners[column], errors="coerce").dropna()
        l = pd.to_numeric(losers[column], errors="coerce").dropna()
        if len(w) < 10 or len(l) < 10:
            continue
        rows.append(
            {
                "factor": column,
                "winner_mean": round(float(w.mean()), 3),
                "loser_mean": round(float(l.mean()), 3),
                "delta": round(float(w.mean() - l.mean()), 3),
                "winner_median": round(float(w.median()), 3),
                "loser_median": round(float(l.median()), 3),
                "samples": int(len(w) + len(l)),
            }
        )
    return pd.DataFrame(rows).sort_values("delta", key=lambda s: s.abs(), ascending=False)


def _category_edges(samples: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in CATEGORICAL_FACTORS:
        if column not in samples.columns:
            continue
        for value, group in samples.groupby(column, dropna=False):
            if len(group) < 10:
                continue
            row = _metrics(f"{column}={value}", group)
            row["coverage_pct"] = round(len(group) / len(samples) * 100, 2)
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["win_rate", "total_return_pct"], ascending=False)


def _rule_edges(samples: pd.DataFrame) -> pd.DataFrame:
    candidates = [
        ("rank<=1.5", _le("consensus_avg_rank", 1.5)),
        ("avg_rank<=1.5", _le("avg_rank", 1.5)),
        ("n_versions>=3", _ge("n_versions", 3)),
        ("sector_ma10<=70", _le("sector_ma10_ratio", 70)),
        ("sector_ma10<=70 & rank<=1.5", lambda df: _le("sector_ma10_ratio", 70)(df) & _le("consensus_avg_rank", 1.5)(df)),
        ("factor_pattern>=60", _ge("factor_pattern", 60)),
        ("factor_pattern<=40", _le("factor_pattern", 40)),
        ("pattern>=60 & sector<=70", lambda df: _ge("factor_pattern", 60)(df) & _le("sector_ma10_ratio", 70)(df)),
        ("volume 1.4-2.8", lambda df: _between("volume_ratio", 1.4, 2.8)(df)),
        ("drawdown<=7", _le("drawdown_from_high", 7)),
        ("change<=4.5", _le("change", 4.5)),
        ("wyckoff 60-75", _between("factor_wyckoff", 60, 75)),
        ("macro=active", _eq("macro_mode", "active")),
        ("macro=cautious", _eq("macro_mode", "cautious")),
        ("style=weak_momentum", _eq("market_style", "weak_momentum")),
    ]
    rows = []
    for name, func in candidates:
        try:
            mask = func(samples).fillna(False)
        except Exception:
            continue
        group = samples[mask]
        if len(group) < 10:
            continue
        row = _metrics(name, group)
        row["coverage_pct"] = round(len(group) / len(samples) * 100, 2)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["win_rate", "hit3_rate", "samples"], ascending=False)


def _rule_year_stability(samples: pd.DataFrame) -> pd.DataFrame:
    rules = _rule_edges(samples)
    if rules.empty or "year" not in samples.columns:
        return pd.DataFrame()
    rows = []
    for rule in rules["group"].head(20):
        mask = _named_rule(rule, samples)
        if mask is None:
            continue
        group = samples[mask.fillna(False)]
        year_stats = _group_summary(group, "year")
        if year_stats.empty:
            continue
        rows.append(
            {
                "rule": rule,
                "years": int(len(year_stats)),
                "min_year_win_rate": round(float(year_stats["win_rate"].min()), 2),
                "positive_years": int((year_stats["total_return_pct"] > 0).sum()),
                "total_years": int(len(year_stats)),
                "samples": int(len(group)),
            }
        )
    return pd.DataFrame(rows).sort_values(["positive_years", "min_year_win_rate", "samples"], ascending=False)


def _named_rule(rule: str, df: pd.DataFrame) -> pd.Series | None:
    mapping = {
        "rank<=1.5": _le("consensus_avg_rank", 1.5),
        "avg_rank<=1.5": _le("avg_rank", 1.5),
        "n_versions>=3": _ge("n_versions", 3),
        "sector_ma10<=70": _le("sector_ma10_ratio", 70),
        "factor_pattern>=60": _ge("factor_pattern", 60),
        "factor_pattern<=40": _le("factor_pattern", 40),
        "volume 1.4-2.8": _between("volume_ratio", 1.4, 2.8),
        "drawdown<=7": _le("drawdown_from_high", 7),
        "change<=4.5": _le("change", 4.5),
        "wyckoff 60-75": _between("factor_wyckoff", 60, 75),
        "macro=active": _eq("macro_mode", "active"),
        "macro=cautious": _eq("macro_mode", "cautious"),
        "style=weak_momentum": _eq("market_style", "weak_momentum"),
    }
    if rule == "sector_ma10<=70 & rank<=1.5":
        return _le("sector_ma10_ratio", 70)(df) & _le("consensus_avg_rank", 1.5)(df)
    if rule == "pattern>=60 & sector<=70":
        return _ge("factor_pattern", 60)(df) & _le("sector_ma10_ratio", 70)(df)
    func = mapping.get(rule)
    return func(df) if func else None


def _format_markdown(report: dict) -> str:
    if not report.get("sample_count"):
        return "# 历史短线赢家共性研究\n\n没有可用样本。\n"

    lines = [
        "# 历史短线赢家共性研究",
        "",
        "## 口径",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 可量化逐股样本：{report['sample_count']} 条，版本/版本族：{report['version_count']} 个。",
        "- `win` 为 3-5 日/实际短线收益为正；优先用 `ret_5d`，没有时用 `profit_after_fee/profit_pct`。",
        "- 早期大量 `ic_short` 文件只有收益和股票代码，缺少因子；这些文件不用于因子共性判断。",
        "- 本报告只做研究归因，不改任何策略逻辑。",
        "",
        "## 数据覆盖",
        "",
        _md(report["coverage"].head(40)),
        "",
        "## 数据源清单",
        "",
        _md(report["inventory"].tail(40)),
        "",
        "## 分版本/版本族表现",
        "",
        _md(report["version_summary"].head(40)),
        "",
        "## 分来源表现",
        "",
        _md(report["family_summary"].head(20)),
        "",
        "## 执行级样本分版本表现",
        "",
        f"- 排除大候选池 `stage3_consensus_candidates` 后，样本数：{report['execution_sample_count']}。",
        "",
        _md(report["execution_version_summary"].head(40)),
        "",
        "## 执行级样本单条件共性",
        "",
        _md(report["execution_rule_edges"].head(30)),
        "",
        "## 执行级样本数值差异",
        "",
        _md(report["execution_numeric_edges"].head(30)),
        "",
        "## 年份表现",
        "",
        _md(report["year_summary"].sort_values("group").head(20)),
        "",
        "## 赢家相对输家的数值差异",
        "",
        _md(report["numeric_edges"].head(30)),
        "",
        "## 单条件共性",
        "",
        _md(report["rule_edges"].head(30)),
        "",
        "## 条件跨年稳定性",
        "",
        _md(report["rule_year_stability"].head(20)),
        "",
        "## 类别共性",
        "",
        _md(report["category_edges"].head(30)),
        "",
        "## 历史因子矿工摘录",
        "",
        _md(pd.DataFrame(report["miner"]).head(80)),
        "",
        "## 初步结论",
        "",
        "1. 从可量化样本看，真正反复出现的不是单纯高分，而是“强共识/高排名 + 板块不过热 + 形态质量不差”。",
        "2. `sector_ma10_ratio` 过热时容易把胜率和收益拖下去；不过热但仍有共识的票，更接近我们要的 3-5 天短线弹性。",
        "3. v9-v19 历史矿工里出现过 `weak_momentum/active/cautious`、`wyckoff 60-75`、`volume_ratio 1.4-2.8`、`factor_pattern` 分层等规则，但部分胜率不高，适合当候选因子，不适合单独做硬门。",
        "4. 对 v30 以前的结论要标注可信度：v19/v25/v27/v29 有逐股因子可复算；更早 H1/v1-v8 多数只有文档或低维交易结果，不能和 v35/v39 一样精确比较。",
    ]
    return "\n".join(lines) + "\n"


def _read_csv(path: Path, nrows: int | None = None) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig", nrows=nrows)
    except Exception:
        return pd.DataFrame()


def _first_numeric(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    result = pd.Series(np.nan, index=df.index, dtype="float64")
    for column in columns:
        if column in df.columns:
            result = result.fillna(pd.to_numeric(df[column], errors="coerce"))
    return result


def _hit3(df: pd.DataFrame) -> pd.Series:
    if "hit_3pct" in df.columns:
        mapped = df["hit_3pct"].map(_to_bool)
        if mapped.notna().any():
            return mapped.astype("boolean").fillna(False).astype(bool)
    if "mfe_pct" in df.columns:
        return pd.to_numeric(df["mfe_pct"], errors="coerce") >= 3
    return pd.Series(False, index=df.index)


def _to_bool(value) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "1.0", "yes"}:
        return True
    if text in {"false", "0", "0.0", "no"}:
        return False
    return None


def _mean(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return round(float(values.mean()), 2) if len(values) else 0.0


def _rate(series: pd.Series) -> float:
    values = series.dropna()
    return round(float(values.mean()) * 100, 2) if len(values) else 0.0


def _le(column: str, value: float):
    return lambda df: pd.to_numeric(df.get(column), errors="coerce") <= value


def _ge(column: str, value: float):
    return lambda df: pd.to_numeric(df.get(column), errors="coerce") >= value


def _between(column: str, low: float, high: float):
    return lambda df: pd.to_numeric(df.get(column), errors="coerce").between(low, high)


def _eq(column: str, value: str):
    return lambda df: df.get(column, pd.Series(index=df.index, dtype=object)).astype(str) == value


def _md(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "（无）"
    return df.to_markdown(index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Research historical short-line winner commonality.")
    parser.add_argument("--output", default="reports/historical_winner_commonality_h1_v30_20260706.md")
    parser.add_argument("--samples-output", default="reports/historical_winner_commonality_h1_v30_20260706.samples.csv")
    args = parser.parse_args()
    print(write_report(args.output, args.samples_output))


if __name__ == "__main__":
    main()
