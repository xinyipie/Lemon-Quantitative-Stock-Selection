#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit alert-level quality after applying duplicate-stock cooldown."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from longterm_pool_lifecycle_audit import lifecycle_entry_table, load_quality_csv


DEFAULT_HORIZONS = [10, 40, 80]
DISPLAY_COLUMNS = [
    "first_select_date",
    "alert_type",
    "ts_code",
    "name",
    "industry",
    "compression_score",
    "pool_rank_score",
    "recent_appearances",
    "ret_10d",
    "ret_40d",
    "ret_80d",
    "outperform_80d",
]


def _fmt_pct(value) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):+.2f}%"


def _table(df: pd.DataFrame, max_rows: int = 80, columns: list[str] | None = None) -> str:
    if df.empty:
        return "无样本\n"
    view = df.copy()
    if columns:
        view = view[[col for col in columns if col in view.columns]]
    return view.head(max_rows).to_markdown(index=False) + "\n"


def apply_alert_cooldown(events: pd.DataFrame, cooldown_days: int = 80) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    data = events.copy()
    date_col = "first_select_date" if "first_select_date" in data.columns else "select_date"
    data[date_col] = data[date_col].astype(str).str.replace("-", "", regex=False).str[:8]
    data["_entry_dt"] = pd.to_datetime(data[date_col], format="%Y%m%d", errors="coerce")
    data = data.dropna(subset=["_entry_dt"]).sort_values([date_col, "ts_code"]).copy()

    kept = []
    last_alert: dict[str, pd.Timestamp] = {}
    alert_counts: dict[str, int] = {}
    for _, row in data.iterrows():
        code = str(row.get("ts_code", ""))
        entry_dt = row["_entry_dt"]
        if code in last_alert and (entry_dt - last_alert[code]).days <= int(cooldown_days):
            continue
        alert_counts[code] = alert_counts.get(code, 0) + 1
        out = row.to_dict()
        out["alert_type"] = "new_alert" if alert_counts[code] == 1 else "re_alert"
        out["cooldown_days"] = int(cooldown_days)
        kept.append(out)
        last_alert[code] = entry_dt
    result = pd.DataFrame(kept)
    if result.empty:
        return result
    return result.drop(columns=[col for col in ["_entry_dt"] if col in result.columns]).reset_index(drop=True)


def filter_elite_alerts(
    alerts: pd.DataFrame,
    min_score: float = 80.0,
    min_industry_rs: float = 8.0,
    min_drawdown: float = 7.0,
    max_drawdown: float = 15.0,
) -> pd.DataFrame:
    if alerts.empty:
        return alerts.copy()
    data = alerts.copy()
    for col in ["compression_score", "industry_rs", "drawdown_from_high"]:
        if col not in data.columns:
            data[col] = pd.NA
        data[col] = pd.to_numeric(data[col], errors="coerce")
    mask = (
        (data["compression_score"] >= float(min_score))
        & (data["industry_rs"] >= float(min_industry_rs))
        & (data["drawdown_from_high"] >= float(min_drawdown))
        & (data["drawdown_from_high"] <= float(max_drawdown))
    )
    result = data[mask].copy()
    result["elite_alert"] = True
    result["elite_rule"] = (
        f"score>={min_score}, industry_rs>={min_industry_rs}, "
        f"drawdown {min_drawdown}-{max_drawdown}"
    )
    return result.reset_index(drop=True)


def summarize_alerts(alerts: pd.DataFrame, horizons: list[int] | None = None) -> pd.DataFrame:
    horizons = horizons or DEFAULT_HORIZONS
    rows = []
    for horizon in horizons:
        ret_col = f"ret_{horizon}d"
        if ret_col not in alerts.columns:
            continue
        valid = alerts.dropna(subset=[ret_col])
        if valid.empty:
            continue
        out_col = f"outperform_{horizon}d"
        rows.append(
            {
                "horizon": f"{horizon}d",
                "count": int(len(valid)),
                "avg_ret": round(float(valid[ret_col].mean()), 2),
                "median_ret": round(float(valid[ret_col].median()), 2),
                "win_rate": round(float((valid[ret_col] > 0).mean() * 100), 2),
                "outperform_rate": round(float(valid[out_col].mean() * 100), 2) if out_col in valid.columns else None,
            }
        )
    return pd.DataFrame(rows)


def period_summary(alerts: pd.DataFrame) -> pd.DataFrame:
    if alerts.empty or "ret_80d" not in alerts.columns:
        return pd.DataFrame()
    data = alerts.copy()
    data["period"] = data["first_select_date"].astype(str).str[:4] + data["first_select_date"].astype(str).str[4:6].astype(int).map(
        lambda month: "H1" if month <= 6 else "H2"
    )
    rows = []
    for period, group in data.groupby("period", dropna=False):
        valid = group.dropna(subset=["ret_80d"])
        rows.append(
            {
                "period": period,
                "count": int(len(valid)),
                "avg_ret_80d": round(float(valid["ret_80d"].mean()), 2) if not valid.empty else None,
                "median_ret_80d": round(float(valid["ret_80d"].median()), 2) if not valid.empty else None,
                "win_rate_80d": round(float((valid["ret_80d"] > 0).mean() * 100), 2) if not valid.empty else None,
                "outperform_rate_80d": round(float(valid["outperform_80d"].mean() * 100), 2)
                if "outperform_80d" in valid.columns and not valid.empty
                else None,
            }
        )
    return pd.DataFrame(rows)


def build_report(alerts: pd.DataFrame, original_events: pd.DataFrame, title: str = "长线推荐提醒冷却审计") -> str:
    summary = summarize_alerts(alerts, DEFAULT_HORIZONS)
    periods = period_summary(alerts)
    latest_date = str(alerts["first_select_date"].max()) if not alerts.empty and "first_select_date" in alerts.columns else "NA"
    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 原始入池事件 `{len(original_events)}` 次，冷却后实际提醒 `{len(alerts)}` 次，最新提醒日期 `{latest_date}`。\n",
    ]
    if not summary.empty:
        main = summary.iloc[-1]
        lines.append(
            f"- 最长窗口 `{main['horizon']}`：平均收益 `{_fmt_pct(main['avg_ret'])}`，"
            f"胜率 `{main['win_rate']:.2f}%`，跑赢沪深300比例 `{main['outperform_rate']:.2f}%`。\n"
        )
    lines.extend(
        [
            "\n## 提醒表现\n",
            _table(summary, max_rows=20),
            "\n## 分阶段表现\n",
            _table(periods, max_rows=20),
            "\n## 提醒明细\n",
            _table(alerts, max_rows=160, columns=DISPLAY_COLUMNS),
        ]
    )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit alert quality with duplicate-stock cooldown.")
    parser.add_argument("--input", nargs="+", required=True, help="Compressed snapshot CSV file(s).")
    parser.add_argument("--cooldown-days", type=int, default=80)
    parser.add_argument("--elite", action="store_true", help="Apply high-confidence alert filter.")
    parser.add_argument("--min-score", type=float, default=80.0)
    parser.add_argument("--min-industry-rs", type=float, default=8.0)
    parser.add_argument("--min-drawdown", type=float, default=7.0)
    parser.add_argument("--max-drawdown", type=float, default=15.0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--csv-output", default=None)
    parser.add_argument("--title", default="长线推荐提醒冷却审计")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = load_quality_csv(args.input)
    events = lifecycle_entry_table(data)
    alerts = apply_alert_cooldown(events, cooldown_days=args.cooldown_days)
    if args.elite:
        alerts = filter_elite_alerts(
            alerts,
            min_score=args.min_score,
            min_industry_rs=args.min_industry_rs,
            min_drawdown=args.min_drawdown,
            max_drawdown=args.max_drawdown,
        )
    report = build_report(alerts, events, title=args.title)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if args.csv_output:
        csv_out = Path(args.csv_output)
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        alerts.to_csv(csv_out, index=False, encoding="utf-8-sig")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
