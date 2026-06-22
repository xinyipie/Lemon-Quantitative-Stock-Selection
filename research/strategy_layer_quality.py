#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Research-only Top layer quality diagnostics for short v9 and long v18."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_OUTPUT = Path("reports") / "research" / "dragon_boat_layer_quality.md"
SHORT_PROFILE_FILTER = "profile_v9_sector_quality_guard"
SHORT_TARGET = "ret_5d"
LONGTERM_TARGET = "ret_80d"


def build_layer_quality(
    root: str | Path = ".",
    short_layers: Iterable[int | str] = (1, 3, 5, "all"),
    long_layers: Iterable[int | str] = (1, 3, 5, 10, "all"),
    max_short_files: int = 12,
    short_profile_filter: str = SHORT_PROFILE_FILTER,
) -> dict:
    root_path = Path(root)
    short_frames = _load_short_frames(root_path / "backtest_results", max_short_files, short_profile_filter)
    long_frames = _load_longterm_frames(root_path / "reports")
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rules": {
            "short_profile_filter": short_profile_filter,
            "short_layers": list(short_layers),
            "long_layers": list(long_layers),
            "note": "Layer quality compares score-ranked TopN with all candidates per date; it is research evidence only.",
        },
        "short": _analyze_layer_set(
            frames=short_frames,
            target=SHORT_TARGET,
            score_column="score",
            date_column="select_date",
            layers=short_layers,
            mfe_column="mfe_pct",
            mae_column="mae_pct",
        ),
        "longterm": _analyze_layer_set(
            frames=long_frames,
            target=LONGTERM_TARGET,
            score_column="longterm_score",
            date_column="select_date",
            layers=long_layers,
            mfe_column="mfe_80d",
            mae_column="mae_80d",
        ),
    }


def write_layer_quality_report(
    root: str | Path = ".",
    output: str | Path = DEFAULT_OUTPUT,
    max_short_files: int = 12,
    short_profile_filter: str = SHORT_PROFILE_FILTER,
) -> dict:
    result = build_layer_quality(
        root=root,
        max_short_files=max_short_files,
        short_profile_filter=short_profile_filter,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_format_markdown(result), encoding="utf-8")
    output_path.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _load_short_frames(backtest_dir: Path, max_files: int, profile_filter: str) -> list[dict]:
    frames = []
    files = sorted(backtest_dir.glob("ic_short_*.csv"), key=lambda path: path.stat().st_size, reverse=True) if backtest_dir.exists() else []
    for path in files:
        df = _read_csv(path)
        if df.empty or SHORT_TARGET not in df.columns or "score" not in df.columns:
            continue
        if not _matches_profile(df, profile_filter):
            continue
        frames.append({"period": _short_period(path), "file": path.name, "df": df})
        if len(frames) >= max_files:
            break
    return frames


def _load_longterm_frames(reports_dir: Path) -> list[dict]:
    frames = []
    files = sorted(reports_dir.glob("longterm_pool_quality_*_v18_market_sync_full.csv"), key=lambda path: path.name) if reports_dir.exists() else []
    for path in files:
        df = _read_csv(path)
        if df.empty or LONGTERM_TARGET not in df.columns:
            continue
        if "longterm_score" not in df.columns and "score" in df.columns:
            df = df.copy()
            df["longterm_score"] = df["score"]
        if "longterm_score" not in df.columns:
            continue
        frames.append({"period": _longterm_period(path), "file": path.name, "df": df})
    return frames


def _analyze_layer_set(
    frames: list[dict],
    target: str,
    score_column: str,
    date_column: str,
    layers: Iterable[int | str],
    mfe_column: str,
    mae_column: str,
) -> dict:
    normalized_layers = [_layer_key(layer) for layer in layers]
    per_period = []
    layer_rows: dict[str, list[pd.DataFrame]] = {layer: [] for layer in normalized_layers}
    layer_period_metrics: dict[str, list[dict]] = {layer: [] for layer in normalized_layers}

    for frame in frames:
        ranked = _rank_frame(frame["df"], score_column=score_column, date_column=date_column)
        if ranked.empty:
            continue
        all_metrics = _metrics(ranked, target, mfe_column, mae_column)
        period_entry = {"period": frame["period"], "file": frame["file"], "layers": {}}
        for layer in normalized_layers:
            scoped = _select_layer(ranked, layer)
            if scoped.empty:
                continue
            layer_rows[layer].append(scoped)
            metrics = _metrics(scoped, target, mfe_column, mae_column)
            metrics["edge_vs_all"] = _edge(metrics.get("avg_ret"), all_metrics.get("avg_ret"))
            metrics["period"] = frame["period"]
            metrics["file"] = frame["file"]
            layer_period_metrics[layer].append(metrics)
            period_entry["layers"][layer] = metrics
        per_period.append(period_entry)

    layer_summary = {}
    all_avg_by_period = {
        item["period"]: item["layers"].get("all", {}).get("avg_ret")
        for item in per_period
        if "all" in item.get("layers", {})
    }
    for layer in normalized_layers:
        combined = pd.concat(layer_rows[layer], ignore_index=True) if layer_rows[layer] else pd.DataFrame()
        summary = _metrics(combined, target, mfe_column, mae_column)
        period_metrics = layer_period_metrics[layer]
        edge_values = []
        beat_count = 0
        comparable_count = 0
        for item in period_metrics:
            benchmark = all_avg_by_period.get(item["period"])
            edge = _edge(item.get("avg_ret"), benchmark)
            if edge is None:
                continue
            comparable_count += 1
            edge_values.append(edge)
            if edge > 0:
                beat_count += 1
        summary.update(
            {
                "layer": layer,
                "period_count": len(period_metrics),
                "avg_edge_vs_all": _round_mean(edge_values),
                "beat_all_periods": beat_count,
                "comparable_periods": comparable_count,
                "beat_all_rate": round(beat_count / comparable_count, 4) if comparable_count else None,
                "classification": _layer_classification(layer, beat_count, comparable_count, _round_mean(edge_values)),
                "periods": period_metrics,
            }
        )
        layer_summary[layer] = summary

    return {
        "target": target,
        "score_column": score_column,
        "period_count": len(per_period),
        "files": [frame["file"] for frame in frames],
        "layers": layer_summary,
        "per_period": per_period,
    }


def _rank_frame(df: pd.DataFrame, score_column: str, date_column: str) -> pd.DataFrame:
    if df.empty or score_column not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    if date_column not in work.columns:
        work[date_column] = "single"
    work[score_column] = pd.to_numeric(work[score_column], errors="coerce")
    work = work.dropna(subset=[score_column])
    if work.empty:
        return pd.DataFrame()
    work["_rank"] = work.groupby(date_column)[score_column].rank(method="first", ascending=False)
    return work


def _select_layer(df: pd.DataFrame, layer: str) -> pd.DataFrame:
    if layer == "all":
        return df
    top_n = int(layer.replace("top", ""))
    return df[df["_rank"] <= top_n]


def _metrics(df: pd.DataFrame, target: str, mfe_column: str, mae_column: str) -> dict:
    if df.empty:
        return {
            "sample_count": 0,
            "date_count": 0,
            "avg_ret": None,
            "win_rate": None,
            "avg_mfe": None,
            "avg_mae": None,
        }
    return {
        "sample_count": int(len(df)),
        "date_count": int(df["select_date"].nunique()) if "select_date" in df.columns else 0,
        "avg_ret": _mean(df, target),
        "win_rate": _positive_ratio(df, target),
        "avg_mfe": _mean(df, mfe_column),
        "avg_mae": _mean(df, mae_column),
    }


def _layer_classification(layer: str, beat_count: int, comparable_count: int, avg_edge: float | None) -> str:
    if layer == "all":
        return "benchmark"
    if not comparable_count or avg_edge is None:
        return "insufficient"
    beat_rate = beat_count / comparable_count
    if beat_rate >= 0.6 and avg_edge > 0:
        return "quality_edge"
    if beat_rate <= 0.4 and avg_edge < 0:
        return "negative_edge"
    return "mixed"


def _format_markdown(result: dict) -> str:
    lines = [
        "# 分层质量诊断",
        "",
        "## 研究边界",
        "- 本报告按每个选股日的分数排序比较 TopN 与 All，不改变线上策略。",
        "- `quality_edge` 只表示历史分层优势，不能直接作为上线依据。",
        "",
    ]
    lines.extend(_section_markdown("短线 v9", result["short"]))
    lines.extend(_section_markdown("长线 v18", result["longterm"]))
    lines.extend(
        [
            "## 下一步用法",
            "- 如果 Top 层持续优于 All，再研究更严格准入或候选压缩。",
            "- 如果 Top 层与 All 接近或反向，优先回到因子定义和市场阶段切分，不直接调权。",
        ]
    )
    return "\n".join(lines) + "\n"


def _section_markdown(title: str, section: dict) -> list[str]:
    lines = [
        f"## {title}",
        f"- 目标列：`{section.get('target')}`；有效文件数：`{section.get('period_count', 0)}`。",
        "",
        "| 层级 | 样本 | 平均收益 | 胜率 | MFE | MAE | 相对All | 跑赢All比例 | 结论 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for layer, row in section.get("layers", {}).items():
        lines.append(
            "| {layer} | {samples} | {ret} | {win} | {mfe} | {mae} | {edge} | {beat} | {cls} |".format(
                layer=layer,
                samples=row.get("sample_count", 0),
                ret=_pct(row.get("avg_ret")),
                win=_pct(row.get("win_rate"), ratio=True),
                mfe=_pct(row.get("avg_mfe")),
                mae=_pct(row.get("avg_mae")),
                edge=_pct(row.get("avg_edge_vs_all")),
                beat=_pct(row.get("beat_all_rate"), ratio=True),
                cls=_classification_text(row.get("classification")),
            )
        )
    lines.append("")
    return lines


def _matches_profile(df: pd.DataFrame, profile_filter: str) -> bool:
    if not profile_filter or "factor_profile" not in df.columns:
        return True
    profiles = set(df["factor_profile"].dropna().astype(str).unique())
    return bool(profiles and profile_filter in profiles)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except (pd.errors.EmptyDataError, FileNotFoundError, OSError, UnicodeDecodeError):
        return pd.DataFrame()


def _short_period(path: Path) -> str:
    match = re.search(r"ic_short_(\d{8})", path.stem)
    return match.group(1) if match else path.stem


def _longterm_period(path: Path) -> str:
    match = re.search(r"longterm_pool_quality_(.+?)_v18_market_sync_full", path.stem)
    return match.group(1) if match else path.stem


def _layer_key(layer: int | str) -> str:
    if isinstance(layer, str) and layer == "all":
        return "all"
    return f"top{int(layer)}"


def _mean(df: pd.DataFrame, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    return round(float(values.mean()), 4) if not values.empty else None


def _positive_ratio(df: pd.DataFrame, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return None
    return round(float((values > 0).mean()), 4)


def _edge(value: float | None, benchmark: float | None) -> float | None:
    if value is None or benchmark is None:
        return None
    return round(float(value) - float(benchmark), 4)


def _round_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(sum(values) / len(values)), 4)


def _pct(value, ratio: bool = False) -> str:
    if value is None:
        return "NA"
    number = float(value) * 100 if ratio else float(value)
    return f"{number:+.2f}%"


def _classification_text(value) -> str:
    return {
        "benchmark": "基准",
        "quality_edge": "分层有效",
        "negative_edge": "分层反向",
        "mixed": "阶段混合",
        "insufficient": "证据不足",
    }.get(str(value), str(value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成短线v9/长线v18分层质量诊断。")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-short-files", type=int, default=12)
    parser.add_argument("--short-profile-filter", default=SHORT_PROFILE_FILTER)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = write_layer_quality_report(
        root=args.root,
        output=args.output,
        max_short_files=args.max_short_files,
        short_profile_filter=args.short_profile_filter,
    )
    print(f"Report written: {args.output}")
    print(f"short_layers={len(result['short']['layers'])} longterm_layers={len(result['longterm']['layers'])}")


if __name__ == "__main__":
    main()
