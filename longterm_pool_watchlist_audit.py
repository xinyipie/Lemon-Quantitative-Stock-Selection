#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit a longterm observation-pool promotion rule.

This tool does not change the live selector. It reads existing
longterm_pool_quality_*.csv files and checks whether "repeat appearance
before promotion" improves pool quality.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from longterm_pool_path_diagnostics import (
    DISPLAY_COLUMNS,
    classify_paths,
    load_pool_paths,
    normalize_pool_paths,
    path_summary,
)


WATCH_COLUMNS = [
    "source_label",
    "stage",
    "first_seen_date",
    "promote_date",
    "select_date",
    "scan_index",
    "ts_code",
    "name",
    "industry",
    "watch_appearances",
    "days_since_first_seen",
    "path_group",
    "ret_h",
    "mfe_h",
    "mae_h",
    "longterm_score",
    "pool_rank_score",
    "quality_rank_score",
    "industry_rs",
    "price_vs_ma60",
    "drawdown_from_high",
    "turnover",
    "roe",
]


def _fmt_pct(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):+.2f}%"


def _table(df: pd.DataFrame, cols: list[str] | None = None, max_rows: int = 30) -> str:
    if df.empty:
        return "无样本\n"
    view = df.copy()
    if cols:
        view = view[[col for col in cols if col in view.columns]]
    return view.head(max_rows).to_markdown(index=False) + "\n"


def _date_key(value) -> int:
    try:
        return int(str(value).replace("-", "")[:8])
    except (TypeError, ValueError):
        return 0


def add_scan_index(df: pd.DataFrame) -> pd.DataFrame:
    data = normalize_pool_paths(df)
    if data.empty:
        return data
    data["_date_key"] = data["select_date"].map(_date_key)
    data = data.sort_values(["source_label", "stage", "_date_key", "ts_code"]).reset_index(drop=True)
    data["scan_index"] = (
        data.groupby(["source_label", "stage"], dropna=False)["_date_key"].rank(method="dense").astype(int)
    )
    return data.drop(columns=["_date_key"])


def promote_watchlist(df: pd.DataFrame, lookback_scans: int = 10, min_appearances: int = 2) -> pd.DataFrame:
    """Promote a stock only after repeated appearances in recent scan dates."""
    data = add_scan_index(df)
    if data.empty:
        return data.copy()
    promoted_keys: set[tuple[str, str, str]] = set()
    rows = []

    # 按阶段单独统计，避免不同实验区间之间互相“续命”。
    for (_, _), group in data.groupby(["source_label", "stage"], dropna=False, sort=False):
        group = group.sort_values(["scan_index", "ts_code"]).reset_index(drop=True)
        for idx, row in group.iterrows():
            key = (str(row["source_label"]), str(row["stage"]), str(row["ts_code"]))
            if key in promoted_keys:
                continue
            current_scan = int(row["scan_index"])
            recent = group[
                (group["ts_code"].astype(str) == str(row["ts_code"]))
                & (group["scan_index"] >= current_scan - lookback_scans + 1)
                & (group["scan_index"] <= current_scan)
            ]
            if len(recent) < min_appearances:
                continue
            first = recent.sort_values("scan_index").iloc[0]
            out = row.copy()
            out["watch_appearances"] = int(len(recent))
            out["first_seen_date"] = str(first["select_date"])
            out["promote_date"] = str(row["select_date"])
            out["days_since_first_seen"] = _date_key(row["select_date"]) - _date_key(first["select_date"])
            promoted_keys.add(key)
            rows.append(out)

    if not rows:
        return pd.DataFrame(columns=list(data.columns) + ["watch_appearances", "first_seen_date", "promote_date"])
    return pd.DataFrame(rows).reset_index(drop=True)


def pool_metrics(df: pd.DataFrame, horizon: int) -> dict[str, float | int | None]:
    ret_col = f"ret_{horizon}d"
    mfe_col = f"mfe_{horizon}d"
    mae_col = f"mae_{horizon}d"
    if df.empty or ret_col not in df.columns:
        return {"count": 0, "complete": 0, "avg_ret": None, "win_rate": None, "avg_mfe": None, "avg_mae": None}
    ret = pd.to_numeric(df[ret_col], errors="coerce")
    mfe = pd.to_numeric(df[mfe_col], errors="coerce") if mfe_col in df.columns else pd.Series(dtype=float)
    mae = pd.to_numeric(df[mae_col], errors="coerce") if mae_col in df.columns else pd.Series(dtype=float)
    complete = ret.notna()
    return {
        "count": int(len(df)),
        "complete": int(complete.sum()),
        "avg_ret": float(ret.mean()) if complete.any() else None,
        "win_rate": float((ret.dropna() > 0).mean() * 100) if complete.any() else None,
        "avg_mfe": float(mfe.mean()) if not mfe.empty and mfe.notna().any() else None,
        "avg_mae": float(mae.mean()) if not mae.empty and mae.notna().any() else None,
    }


def _metrics_table(raw: pd.DataFrame, promoted: pd.DataFrame, horizon: int) -> pd.DataFrame:
    rows = []
    for name, frame in [("原始入池样本", raw), ("升级样本", promoted)]:
        metrics = pool_metrics(frame, horizon)
        rows.append(
            {
                "group": name,
                "count": metrics["count"],
                "complete": metrics["complete"],
                "avg_ret": round(metrics["avg_ret"], 2) if metrics["avg_ret"] is not None else None,
                "win_rate": round(metrics["win_rate"], 2) if metrics["win_rate"] is not None else None,
                "avg_mfe": round(metrics["avg_mfe"], 2) if metrics["avg_mfe"] is not None else None,
                "avg_mae": round(metrics["avg_mae"], 2) if metrics["avg_mae"] is not None else None,
            }
        )
    return pd.DataFrame(rows)


def build_watchlist_report(
    raw: pd.DataFrame,
    promoted: pd.DataFrame,
    horizon: int = 40,
    title: str = "长线观察池升级审计",
    top: int = 30,
) -> str:
    raw_norm = normalize_pool_paths(raw)
    promoted_norm = normalize_pool_paths(promoted)
    raw_metrics = pool_metrics(raw_norm, horizon)
    promoted_metrics = pool_metrics(promoted_norm, horizon)
    if not promoted_norm.empty:
        promoted_labeled = classify_paths(promoted_norm, horizon=horizon)
    else:
        promoted_labeled = promoted_norm
    summary = path_summary(promoted_labeled) if not promoted_labeled.empty else pd.DataFrame()

    delta = None
    if raw_metrics["avg_ret"] is not None and promoted_metrics["avg_ret"] is not None:
        delta = float(promoted_metrics["avg_ret"]) - float(raw_metrics["avg_ret"])

    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        "- 观察池升级审计：先进入观察池，只有最近若干扫描日内重复出现，才视为“可买升级样本”。\n",
        f"- 原始入池样本 `{raw_metrics['count']}` 个，升级样本 `{promoted_metrics['count']}` 个，评估窗口 `{horizon}` 日。\n",
    ]
    if promoted_metrics["complete"]:
        lines.append(
            f"- 升级样本：平均收益 `{_fmt_pct(promoted_metrics['avg_ret'])}`，胜率 `{promoted_metrics['win_rate']:.2f}%`，MFE `{_fmt_pct(promoted_metrics['avg_mfe'])}`，MAE `{_fmt_pct(promoted_metrics['avg_mae'])}`。\n"
        )
    else:
        lines.append("- 升级样本不足或前瞻窗口未完成，暂时不能判断收益质量。\n")
    if delta is not None:
        lines.append(f"- 相比原始入池样本，升级后平均收益变化 `{_fmt_pct(delta)}`。\n")
    lines.append("- 这个工具只验证“池子确认机制”，不改变主策略，不用于证明某个参数已经定板。\n")

    promoted_display = promoted_labeled.copy() if not promoted_labeled.empty else promoted_norm
    if not promoted_display.empty and "ret_h" in promoted_display.columns:
        promoted_display = promoted_display.sort_values("ret_h", ascending=False)

    lines.extend(
        [
            "\n## 原始 vs 升级\n",
            _table(_metrics_table(raw_norm, promoted_norm, horizon), max_rows=10),
            "\n## 升级样本路径分类\n",
            _table(summary, max_rows=80),
            "\n## 升级样本明细\n",
            _table(promoted_display, WATCH_COLUMNS + DISPLAY_COLUMNS, max_rows=top),
            "\n## 使用提醒\n",
            "- 如果升级样本明显更少但收益没有提升，说明“重复出现”只是降低频率，不是提高质量。\n",
            "- 如果升级样本收益提高且坏票比例下降，下一步才值得跨阶段复验，并尝试接入长线推荐池。\n",
            "- 不要用单一小区间调 lookback 或 min_appearances，至少要在 2024H2、2025H2、2026Q1 三类环境里都能解释得通。\n",
        ]
    )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit longterm watchlist promotion quality.")
    parser.add_argument("--inputs", nargs="+", required=True, help="One or more longterm_pool_quality_*.csv files.")
    parser.add_argument("--labels", default=None, help="Comma separated labels. Defaults to file stems.")
    parser.add_argument("--horizon", type=int, default=40, help="Forward horizon, e.g. 40 or 80.")
    parser.add_argument("--lookback-scans", type=int, default=10, help="Recent scan dates used for repeated appearance.")
    parser.add_argument("--min-appearances", type=int, default=2, help="Appearances required before promotion.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--csv-output", default=None, help="Optional promoted samples CSV path.")
    parser.add_argument("--top", type=int, default=30, help="Max sample rows in report.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    labels = args.labels.split(",") if args.labels else [None] * len(args.inputs)
    if len(labels) != len(args.inputs):
        raise SystemExit("--labels 数量必须和 --inputs 文件数量一致")

    frames = [load_pool_paths(path, label) for path, label in zip(args.inputs, labels)]
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    promoted = promote_watchlist(raw, lookback_scans=args.lookback_scans, min_appearances=args.min_appearances)
    if args.csv_output:
        csv_out = Path(args.csv_output)
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        promoted.to_csv(csv_out, index=False, encoding="utf-8-sig")

    report = build_watchlist_report(raw, promoted, horizon=args.horizon, top=args.top)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
