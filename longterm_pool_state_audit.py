#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audit daily state transitions for a compressed longterm watchlist."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


STATE_ORDER = ["new", "continue", "downgraded_watch", "removed"]
DISPLAY_COLUMNS = [
    "select_date",
    "state",
    "ts_code",
    "name",
    "industry",
    "days_in_top",
    "days_in_candidate",
    "compression_score",
    "ret_80d",
    "note",
]


def _normalize_date(value) -> str:
    return str(value).replace("-", "")[:8]


def _table(df: pd.DataFrame, max_rows: int = 80, columns: list[str] | None = None) -> str:
    if df.empty:
        return "无样本\n"
    view = df.copy()
    if columns:
        view = view[[col for col in columns if col in view.columns]]
    return view.head(max_rows).to_markdown(index=False) + "\n"


def normalize_pool(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    if data.empty:
        return data
    if "select_date" in data.columns:
        data["select_date"] = data["select_date"].astype(str).map(_normalize_date)
    for col in ["ts_code", "name", "industry"]:
        if col in data.columns:
            data[col] = data[col].fillna("NA").astype(str)
    for col in ["compression_score", "pool_rank_score", "ret_10d", "ret_40d", "ret_80d"]:
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    return data


def load_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists() or p.stat().st_size <= 5:
        return pd.DataFrame()
    try:
        data = pd.read_csv(p, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    return normalize_pool(data)


def _representative(row: pd.Series, state: str, select_date: str, note: str, days_top: int, days_candidate: int) -> dict:
    out = row.to_dict()
    out["select_date"] = select_date
    out["state"] = state
    out["note"] = note
    out["days_in_top"] = int(days_top)
    out["days_in_candidate"] = int(days_candidate)
    return out


def build_state_events(snapshot_pool: pd.DataFrame, candidate_pool: pd.DataFrame) -> pd.DataFrame:
    snapshot = normalize_pool(snapshot_pool)
    candidates = normalize_pool(candidate_pool)
    if snapshot.empty and candidates.empty:
        return pd.DataFrame()

    dates = sorted(set(snapshot.get("select_date", pd.Series(dtype=str)).astype(str)) | set(candidates.get("select_date", pd.Series(dtype=str)).astype(str)))
    previous_top: dict[str, pd.Series] = {}
    days_in_top: dict[str, int] = {}
    days_in_candidate: dict[str, int] = {}
    events = []

    for select_date in dates:
        day_top = snapshot[snapshot["select_date"] == select_date] if not snapshot.empty else pd.DataFrame()
        day_candidates = candidates[candidates["select_date"] == select_date] if not candidates.empty else pd.DataFrame()
        top_codes = set(day_top["ts_code"].astype(str)) if not day_top.empty else set()
        candidate_codes = set(day_candidates["ts_code"].astype(str)) if not day_candidates.empty else set()
        top_rows = {str(row["ts_code"]): row for _, row in day_top.iterrows()}
        candidate_rows = {str(row["ts_code"]): row for _, row in day_candidates.iterrows()}

        for code in candidate_codes:
            days_in_candidate[code] = days_in_candidate.get(code, 0) + 1

        for code in sorted(top_codes):
            row = top_rows[code]
            if code in previous_top:
                state = "continue"
                note = "仍在Top快照池"
                days_in_top[code] = days_in_top.get(code, 0) + 1
            else:
                state = "new"
                note = "新进入Top快照池"
                days_in_top[code] = 1
            events.append(_representative(row, state, select_date, note, days_in_top[code], days_in_candidate.get(code, 1)))

        for code, row in previous_top.items():
            if code in top_codes:
                continue
            if code in candidate_codes:
                cand_row = candidate_rows.get(code, row)
                events.append(
                    _representative(
                        cand_row,
                        "downgraded_watch",
                        select_date,
                        "跌出Top快照池，但仍在v18候选池",
                        days_in_top.get(code, 0),
                        days_in_candidate.get(code, 0),
                    )
                )
            else:
                events.append(
                    _representative(
                        row,
                        "removed",
                        select_date,
                        "不在Top快照池，也不在v18候选池",
                        days_in_top.get(code, 0),
                        days_in_candidate.get(code, 0),
                    )
                )
                days_in_top.pop(code, None)

        previous_top = top_rows

    result = pd.DataFrame(events)
    if result.empty:
        return result
    result["state"] = pd.Categorical(result["state"], STATE_ORDER, ordered=True)
    return result.sort_values(["select_date", "state", "compression_score"], ascending=[True, True, False]).reset_index(drop=True)


def summarize_state_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["select_date", *STATE_ORDER])
    summary = events.pivot_table(index="select_date", columns="state", values="ts_code", aggfunc="count", fill_value=0, observed=False)
    for state in STATE_ORDER:
        if state not in summary.columns:
            summary[state] = 0
    return summary[STATE_ORDER].reset_index()


def current_pool(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    latest = str(events["select_date"].max())
    return events[(events["select_date"] == latest) & (events["state"].astype(str).isin(["new", "continue"]))].copy()


def state_quality(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty or "ret_80d" not in events.columns:
        return pd.DataFrame()
    rows = []
    for state, group in events.groupby("state", observed=False):
        valid = group.dropna(subset=["ret_80d"])
        if valid.empty:
            continue
        rows.append(
            {
                "state": str(state),
                "count": int(len(valid)),
                "avg_ret_80d": round(float(valid["ret_80d"].mean()), 2),
                "median_ret_80d": round(float(valid["ret_80d"].median()), 2),
                "win_rate_80d": round(float((valid["ret_80d"] > 0).mean() * 100), 2),
            }
        )
    return pd.DataFrame(rows)


def build_report(events: pd.DataFrame, title: str = "长线推荐池状态机审计") -> str:
    summary = summarize_state_events(events)
    quality = state_quality(events)
    latest_pool = current_pool(events)
    latest_date = str(events["select_date"].max()) if not events.empty else "NA"
    lines = [
        f"# {title}\n\n",
        "## 先看结论\n",
        f"- 共生成 `{len(events)}` 条状态事件，最新扫描日 `{latest_date}`。\n",
        f"- 最新Top池 `{len(latest_pool)}` 只；`new/continue` 代表可展示主池，`downgraded_watch` 代表观察降级，`removed` 代表移出。\n",
        "\n## 每日状态变化\n",
        _table(summary, max_rows=120),
        "\n## 状态后验表现\n",
        _table(quality, max_rows=20),
        "\n## 当前池状态\n",
        _table(latest_pool, max_rows=20, columns=DISPLAY_COLUMNS),
        "\n## 近期事件明细\n",
        _table(events.sort_values("select_date", ascending=False), max_rows=120, columns=DISPLAY_COLUMNS),
    ]
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit longterm watchlist state transitions.")
    parser.add_argument("--snapshot", required=True, help="Compressed snapshot CSV.")
    parser.add_argument("--candidates", nargs="+", required=True, help="Original v18 candidate CSV files.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--csv-output", default=None, help="Optional state-event CSV output.")
    parser.add_argument("--title", default="长线推荐池状态机审计")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = load_csv(args.snapshot)
    candidate_frames = [load_csv(path) for path in args.candidates]
    candidates = pd.concat([frame for frame in candidate_frames if not frame.empty], ignore_index=True) if candidate_frames else pd.DataFrame()
    events = build_state_events(snapshot, candidates)
    report = build_report(events, title=args.title)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if args.csv_output:
        csv_out = Path(args.csv_output)
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        events.to_csv(csv_out, index=False, encoding="utf-8-sig")
    print(f"Report written: {out}")
    print("\n".join(report.splitlines()[:8]))


if __name__ == "__main__":
    main()
