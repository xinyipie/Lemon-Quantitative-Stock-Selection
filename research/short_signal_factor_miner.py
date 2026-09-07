from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd


DEFAULT_FILES = (
    "backtest_results/trades_20260702_160634.csv",
    "backtest_results/trades_20260702_142957.csv",
    "backtest_results/trades_20260702_142535.csv",
)
DEFAULT_OUTPUT = Path("reports") / "short_signal_factor_miner.md"
NUMERIC_COLUMNS = (
    "profit_after_fee",
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_wyckoff",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
    "score_base",
)
CLASSIFICATION_RANK = {"candidate": 3, "fragile": 2, "reject": 1}


def load_trade_frames(paths: Iterable[str | Path]) -> pd.DataFrame:
    frames = []
    for path_value in paths:
        path = Path(path_value)
        df = _read_csv(path)
        if df.empty:
            continue
        work = df.copy()
        work["source_file"] = path.name
        work["period"] = _period_label(path, work)
        if "profit_after_fee" not in work.columns and "ret_5d" in work.columns:
            work["profit_after_fee"] = pd.to_numeric(work["ret_5d"], errors="coerce")
            work["return_source"] = "ret_5d"
        elif "profit_after_fee" in work.columns:
            work["return_source"] = "profit_after_fee"
        for column in NUMERIC_COLUMNS:
            if column in work.columns:
                work[column] = pd.to_numeric(work[column], errors="coerce")
        for column in ("hit_3pct", "hit_5pct", "hit_10pct"):
            if column in work.columns:
                work[column] = work[column].map(_to_bool)
        frames.append(work)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_signal_miner_report(
    files: Iterable[str | Path] = DEFAULT_FILES,
    min_samples: int = 3,
) -> dict:
    df = load_trade_frames(files)
    candidates = build_rule_candidates(df, min_samples=min_samples)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rules": {
            "min_samples": min_samples,
            "note": "Research evidence only; this does not alter live selection or create trade execution.",
        },
        "input_files": [str(path) for path in files],
        "sample_count": int(len(df)),
        "periods": sorted(df["period"].dropna().astype(str).unique()) if "period" in df.columns else [],
        "candidates": candidates,
        "top_candidates": [item for item in candidates if item["classification"] == "candidate"][:20],
        "fragile": [item for item in candidates if item["classification"] == "fragile"][:20],
        "rejects": [item for item in candidates if item["classification"] == "reject"][:20],
    }


def write_signal_miner_report(
    files: Iterable[str | Path] = DEFAULT_FILES,
    output: str | Path = DEFAULT_OUTPUT,
    min_samples: int = 3,
) -> dict:
    result = build_signal_miner_report(files=files, min_samples=min_samples)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_format_markdown(result), encoding="utf-8")
    output_path.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_rule_candidates(df: pd.DataFrame, min_samples: int = 3) -> list[dict]:
    if df.empty:
        return []

    rule_specs: list[tuple[str, Callable[[pd.DataFrame], pd.Series]]] = []
    rule_specs.extend(_categorical_rules(df, "market_style"))
    rule_specs.extend(_categorical_rules(df, "macro_mode"))
    rule_specs.extend(_categorical_pair_rules(df, "market_style", "macro_mode"))
    numeric_specs = _numeric_rules(df)
    numeric_pair_specs = _pair_rules(numeric_specs)
    rule_specs.extend(numeric_specs)
    rule_specs.extend(numeric_pair_specs)

    categorical_specs = _categorical_rules(df, "market_style") + _categorical_rules(df, "macro_mode")
    pair_specs = _categorical_pair_rules(df, "market_style", "macro_mode")
    for cat_name, cat_mask in categorical_specs + pair_specs:
        for num_name, num_mask in numeric_specs + numeric_pair_specs:
            rule_specs.append((f"{cat_name} & {num_name}", _and(cat_mask, num_mask)))

    summaries = []
    seen = set()
    for name, mask_func in rule_specs:
        if name in seen:
            continue
        seen.add(name)
        mask = mask_func(df).fillna(False)
        scoped = df.loc[mask].copy()
        if len(scoped) < min_samples:
            continue
        summary = summarize_rule(name, scoped)
        summary["classification"] = classify_summary(summary, min_samples=min_samples)
        summaries.append(summary)

    summaries.sort(key=_sort_key, reverse=True)
    return summaries


def summarize_rule(rule: str, df: pd.DataFrame) -> dict:
    periods = []
    if "period" in df.columns:
        for period, scoped in df.groupby("period", dropna=False):
            periods.append(_metrics(str(period), scoped))
    return {
        "rule": rule,
        "sample_count": int(len(df)),
        "period_count": int(df["period"].nunique()) if "period" in df.columns else 0,
        "win_rate": _positive_rate(df, "profit_after_fee"),
        "total_profit_pct": _sum(df, "profit_after_fee"),
        "avg_profit_pct": _mean(df, "profit_after_fee"),
        "avg_mfe_pct": _mean(df, "mfe_pct"),
        "avg_mae_pct": _mean(df, "mae_pct"),
        "avg_window_end_pct": _mean(df, "window_end_pct"),
        "hit_3pct_rate": _bool_rate(df, "hit_3pct"),
        "hit_5pct_rate": _bool_rate(df, "hit_5pct"),
        "hit_10pct_rate": _bool_rate(df, "hit_10pct"),
        "periods": periods,
    }


def classify_summary(summary: dict, min_samples: int = 3) -> str:
    sample_ok = summary.get("sample_count", 0) >= min_samples
    profit_ok = (summary.get("avg_profit_pct") or 0.0) > 0.0
    hit3_ok = (summary.get("hit_3pct_rate") or 0.0) >= 70.0
    hit5_ok = (summary.get("hit_5pct_rate") or 0.0) >= 50.0
    period_ok = summary.get("period_count", 0) >= 2
    stable_periods = _periods_are_stable(summary.get("periods", []))
    if sample_ok and period_ok and profit_ok and hit3_ok and hit5_ok and stable_periods:
        return "candidate"
    if sample_ok and profit_ok and hit3_ok and not _has_bad_period(summary.get("periods", [])):
        return "fragile"
    return "reject"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine short-line regime/factor signal rules from trade CSV files.")
    parser.add_argument("--files", nargs="*", default=list(DEFAULT_FILES), help="Trade CSV files to analyze.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Markdown report path.")
    parser.add_argument("--min-samples", type=int, default=3, help="Minimum samples per rule.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = write_signal_miner_report(files=args.files, output=args.output, min_samples=args.min_samples)
    print(f"Report written: {args.output}")
    print(
        "rules={rules} candidates={candidates} fragile={fragile}".format(
            rules=len(result["candidates"]),
            candidates=len(result["top_candidates"]),
            fragile=len(result["fragile"]),
        )
    )


def _categorical_rules(df: pd.DataFrame, column: str) -> list[tuple[str, Callable[[pd.DataFrame], pd.Series]]]:
    if column not in df.columns:
        return []
    values = sorted(value for value in df[column].dropna().astype(str).unique() if value)
    return [(f"{column}={value}", lambda data, col=column, val=value: data[col].astype(str) == val) for value in values]


def _categorical_pair_rules(
    df: pd.DataFrame,
    first: str,
    second: str,
) -> list[tuple[str, Callable[[pd.DataFrame], pd.Series]]]:
    if first not in df.columns or second not in df.columns:
        return []
    pairs = sorted(
        {
            (str(row[first]), str(row[second]))
            for _, row in df[[first, second]].dropna().iterrows()
            if str(row[first]) and str(row[second])
        }
    )
    rules = []
    for left, right in pairs:
        rules.append(
            (
                f"{first}={left} & {second}={right}",
                lambda data, left_value=left, right_value=right: (data[first].astype(str) == left_value)
                & (data[second].astype(str) == right_value),
            )
        )
    return rules


def _numeric_rules(df: pd.DataFrame) -> list[tuple[str, Callable[[pd.DataFrame], pd.Series]]]:
    specs: list[tuple[str, str, Callable[[pd.Series], pd.Series]]] = [
        ("factor_sector<=45", "factor_sector", lambda s: s <= 45.0),
        ("factor_sector>60", "factor_sector", lambda s: s > 60.0),
        ("factor_pattern<=40", "factor_pattern", lambda s: s <= 40.0),
        ("factor_pattern>70", "factor_pattern", lambda s: s > 70.0),
        ("factor_wyckoff between 60 and 75", "factor_wyckoff", lambda s: (s >= 60.0) & (s <= 75.0)),
        ("volume_ratio between 1.4 and 2.8", "volume_ratio", lambda s: (s >= 1.4) & (s <= 2.8)),
        ("drawdown_from_high<=7", "drawdown_from_high", lambda s: s <= 7.0),
        ("change<=4.5", "change", lambda s: s <= 4.5),
    ]
    rules = []
    for name, column, condition in specs:
        if column in df.columns:
            rules.append((name, lambda data, col=column, cond=condition: cond(pd.to_numeric(data[col], errors="coerce"))))
    return rules


def _and(
    left: Callable[[pd.DataFrame], pd.Series],
    right: Callable[[pd.DataFrame], pd.Series],
) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda data: left(data).fillna(False) & right(data).fillna(False)


def _pair_rules(
    specs: list[tuple[str, Callable[[pd.DataFrame], pd.Series]]],
) -> list[tuple[str, Callable[[pd.DataFrame], pd.Series]]]:
    pairs = []
    for index, (left_name, left_mask) in enumerate(specs):
        for right_name, right_mask in specs[index + 1 :]:
            pairs.append((f"{left_name} & {right_name}", _and(left_mask, right_mask)))
    return pairs


def _metrics(period: str, df: pd.DataFrame) -> dict:
    return {
        "period": period,
        "sample_count": int(len(df)),
        "win_rate": _positive_rate(df, "profit_after_fee"),
        "avg_profit_pct": _mean(df, "profit_after_fee"),
        "avg_mfe_pct": _mean(df, "mfe_pct"),
        "avg_mae_pct": _mean(df, "mae_pct"),
        "hit_3pct_rate": _bool_rate(df, "hit_3pct"),
        "hit_5pct_rate": _bool_rate(df, "hit_5pct"),
    }


def _sort_key(row: dict) -> tuple:
    return (
        CLASSIFICATION_RANK.get(row.get("classification"), 0),
        row.get("period_count") or 0,
        row.get("hit_3pct_rate") or 0.0,
        row.get("hit_5pct_rate") or 0.0,
        row.get("avg_profit_pct") or 0.0,
        -(abs(row.get("avg_mae_pct") or 0.0)),
        row.get("sample_count") or 0,
    )


def _periods_are_stable(periods: list[dict]) -> bool:
    if not periods:
        return False
    for period in periods:
        if period.get("sample_count", 0) <= 0:
            continue
        if (period.get("avg_profit_pct") or 0.0) <= 0.0:
            return False
        if (period.get("hit_3pct_rate") or 0.0) < 60.0:
            return False
        if (period.get("hit_5pct_rate") or 0.0) < 40.0:
            return False
    return True


def _has_bad_period(periods: list[dict]) -> bool:
    for period in periods:
        if period.get("sample_count", 0) <= 0:
            continue
        if (period.get("avg_profit_pct") or 0.0) < 0.0 and (period.get("hit_3pct_rate") or 0.0) < 60.0:
            return True
    return False


def _format_markdown(result: dict) -> str:
    lines = [
        "# Short Signal Factor Miner",
        "",
        "## Research Boundary",
        "- This report is research evidence only.",
        "- It does not change live selection, portfolio sizing, or trade execution.",
        "- Good rules here still require a separate backtest profile before promotion.",
        "",
        "## Inputs",
        f"- Samples: `{result['sample_count']}`",
        f"- Periods: `{', '.join(result.get('periods', []))}`",
    ]
    lines.extend(f"- `{path}`" for path in result.get("input_files", []))
    lines.append("")
    lines.extend(_table_section("Top Candidates", result.get("top_candidates", [])))
    lines.extend(_table_section("Fragile", result.get("fragile", [])))
    lines.extend(_table_section("Rejected Patterns", result.get("rejects", [])))
    lines.extend(
        [
            "## Interpretation",
            "- `candidate` rules have cross-period evidence, positive average profit, and acceptable 3/5 day hit rates.",
            "- `fragile` rules may be useful, but currently rely on fewer periods or weaker 5-day confirmation.",
            "- If no candidate is robust enough, expand the miner to candidate-level `ic_short` files before writing a new profile.",
            "",
        ]
    )
    return "\n".join(lines)


def _table_section(title: str, rows: list[dict], limit: int = 20) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| Rule | Class | N | Periods | Win | Total | Avg | MFE | MAE | Hit3 | Hit5 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if not rows:
        lines.append("| None | - | 0 | 0 | - | - | - | - | - | - | - |")
    for row in rows[:limit]:
        lines.append(
            "| {rule} | {cls} | {n} | {periods} | {win} | {total} | {avg} | {mfe} | {mae} | {hit3} | {hit5} |".format(
                rule=row["rule"],
                cls=row.get("classification", ""),
                n=row.get("sample_count", 0),
                periods=row.get("period_count", 0),
                win=_pct(row.get("win_rate")),
                total=_pct(row.get("total_profit_pct")),
                avg=_pct(row.get("avg_profit_pct")),
                mfe=_pct(row.get("avg_mfe_pct")),
                mae=_pct(row.get("avg_mae_pct")),
                hit3=_pct(row.get("hit_3pct_rate")),
                hit5=_pct(row.get("hit_5pct_rate")),
            )
        )
    lines.append("")
    return lines


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except (FileNotFoundError, OSError, UnicodeDecodeError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _period_label(path: Path, df: pd.DataFrame) -> str:
    if "select_date" in df.columns:
        dates = pd.to_numeric(df["select_date"], errors="coerce").dropna()
        if not dates.empty:
            start = int(dates.min())
            end = int(dates.max())
            if 20240101 <= start <= 20241231:
                return "2024"
            if 20250101 <= start <= 20251231 and end <= 20251231:
                return "2025"
            if 20260101 <= start <= 20260630:
                return "2026H1"
    return path.stem


def _mean(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return round(float(values.mean()), 2) if not values.empty else None


def _sum(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return round(float(values.sum()), 2) if not values.empty else None


def _positive_rate(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return round(float((values > 0).mean() * 100), 2) if not values.empty else None


def _bool_rate(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns:
        return None
    values = df[column].map(_to_bool).dropna()
    return round(float(values.mean() * 100), 2) if not values.empty else None


def _to_bool(value) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _pct(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):+.2f}%"


if __name__ == "__main__":
    main()
