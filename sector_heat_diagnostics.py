#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose sector heat and rank top stock candidates inside hot sectors."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


DEFAULT_DB = Path("data/stock_history.db")


def _normalize_date(value) -> str:
    return str(value or "").replace("-", "")[:8]


def _num(value, default=None):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _scale(value, low: float, high: float) -> float:
    number = _num(value, 0.0)
    if high == low:
        return 0.0
    return _clip((number - low) / (high - low) * 100, 0, 100)


def _fmt_pct(value) -> str:
    number = _num(value)
    if number is None:
        return "NA"
    return f"{number:+.2f}%"


def _ret_from_close(closes: list[float], days: int) -> float | None:
    if len(closes) < 2:
        return None
    idx = max(0, len(closes) - int(days) - 1)
    base = closes[idx]
    latest = closes[-1]
    if not base:
        return None
    return (latest - base) / base * 100


def _latest_rows(df: pd.DataFrame, end_date: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    data["trade_date"] = data["trade_date"].astype(str).map(_normalize_date)
    data = data[data["trade_date"] <= end_date].sort_values(["ts_code", "trade_date"])
    if data.empty:
        return data
    return data.groupby("ts_code", as_index=False).tail(1)


def _benchmark_return(index_daily: pd.DataFrame | None, end_date: str, days: int, code: str = "000300.SH") -> float:
    if index_daily is None or index_daily.empty:
        return 0.0
    data = index_daily.copy()
    data["trade_date"] = data["trade_date"].astype(str).map(_normalize_date)
    data = data[(data["ts_code"] == code) & (data["trade_date"] <= end_date)].sort_values("trade_date")
    closes = pd.to_numeric(data["close"], errors="coerce").dropna().astype(float).tolist()
    return _num(_ret_from_close(closes, days), 0.0)


def _stock_metrics(daily: pd.DataFrame, stock_basic: pd.DataFrame, end_date: str) -> pd.DataFrame:
    prices = daily.copy()
    prices["trade_date"] = prices["trade_date"].astype(str).map(_normalize_date)
    prices = prices[prices["trade_date"] <= end_date].sort_values(["ts_code", "trade_date"])
    basics = stock_basic.copy()
    if "list_status" in basics.columns:
        basics = basics[basics["list_status"].fillna("L") != "D"]

    basic_map = basics.set_index("ts_code").to_dict("index") if not basics.empty else {}
    rows = []
    for ts_code, grp in prices.groupby("ts_code"):
        info = basic_map.get(ts_code)
        if not info:
            continue
        industry = str(info.get("industry") or "").strip()
        if not industry or industry == "None":
            continue
        g = grp.sort_values("trade_date")
        closes = pd.to_numeric(g["close"], errors="coerce").dropna().astype(float).tolist()
        if len(closes) < 2:
            continue
        latest = g.iloc[-1]
        latest_close = closes[-1]
        recent_closes = closes[-min(20, len(closes)) :]
        ma20 = sum(recent_closes) / len(recent_closes)
        high20 = max(recent_closes)
        low20 = min(recent_closes)
        position_20d = 0.5 if high20 == low20 else (latest_close - low20) / (high20 - low20)

        amounts = pd.to_numeric(g.get("amount", pd.Series(dtype=float)), errors="coerce").dropna().astype(float).tolist()
        latest_amount = amounts[-1] if amounts else 0.0
        prev_amounts = amounts[-6:-1] if len(amounts) >= 6 else amounts[:-1]
        amount_ratio_5d = latest_amount / (sum(prev_amounts) / len(prev_amounts)) if prev_amounts and sum(prev_amounts) else 1.0

        rows.append(
            {
                "trade_date": str(latest["trade_date"]),
                "ts_code": ts_code,
                "name": info.get("name") or ts_code,
                "industry": industry,
                "close": latest_close,
                "pct_chg": _num(latest.get("pct_chg"), 0.0),
                "ret_5d": _ret_from_close(closes, 5),
                "ret_10d": _ret_from_close(closes, 10),
                "ret_20d": _ret_from_close(closes, 20),
                "above_ma20": latest_close >= ma20,
                "position_20d": position_20d,
                "amount_ratio_5d": amount_ratio_5d,
            }
        )
    return pd.DataFrame(rows)


def _classify_sector(row: pd.Series) -> str:
    if row["avg_ret_5d"] <= -2 and row["above_ma20_ratio"] < 0.45:
        return "退潮中"
    if row["overheat_ratio"] >= 0.50 or (
        row["rel_ret_5d"] >= 25 and row["avg_position_20d"] >= 0.90 and row["volume_expansion_ratio"] >= 0.45
    ):
        return "过热高潮"
    if row["rel_ret_10d"] >= 6 and row["above_ma20_ratio"] >= 0.70 and row["up_ratio"] >= 0.50:
        if row["rel_ret_5d"] <= 4 and row["avg_position_20d"] <= 0.75:
            return "低位启动"
        return "趋势延续"
    if row["rel_ret_5d"] >= 1 and row["above_ma20_ratio"] >= 0.50:
        return "弱修复"
    return "观望"


def calculate_sector_heat(
    daily: pd.DataFrame,
    stock_basic: pd.DataFrame,
    daily_basic: pd.DataFrame | None = None,
    moneyflow: pd.DataFrame | None = None,
    index_daily: pd.DataFrame | None = None,
    end_date: str | None = None,
    min_stocks: int = 8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate sector heat and stock-level metrics from history frames."""
    end_date = _normalize_date(end_date or daily["trade_date"].max())
    stocks = _stock_metrics(daily, stock_basic, end_date)
    if stocks.empty:
        return pd.DataFrame(), stocks

    latest_basic = _latest_rows(daily_basic, end_date) if daily_basic is not None else pd.DataFrame()
    if not latest_basic.empty:
        stocks = stocks.merge(
            latest_basic[["ts_code", "turnover_rate", "volume_ratio", "total_mv"]],
            on="ts_code",
            how="left",
        )
    else:
        stocks["turnover_rate"] = 0.0
        stocks["volume_ratio"] = 1.0
        stocks["total_mv"] = pd.NA

    latest_flow = _latest_rows(moneyflow, end_date) if moneyflow is not None else pd.DataFrame()
    if not latest_flow.empty:
        stocks = stocks.merge(latest_flow[["ts_code", "net_mf_amount"]], on="ts_code", how="left")
    else:
        stocks["net_mf_amount"] = 0.0

    for col in ["ret_5d", "ret_10d", "ret_20d", "pct_chg", "turnover_rate", "volume_ratio", "net_mf_amount"]:
        stocks[col] = pd.to_numeric(stocks.get(col), errors="coerce").fillna(0.0)
    stocks["volume_active"] = (stocks["amount_ratio_5d"] >= 1.2) | (stocks["volume_ratio"] >= 1.2)
    stocks["limit_up_like"] = stocks["pct_chg"] >= 9.5
    stocks["overheated_stock"] = (stocks["ret_5d"] >= 25) | ((stocks["position_20d"] >= 0.94) & (stocks["ret_10d"] >= 45))

    bench5 = _benchmark_return(index_daily, end_date, 5)
    bench10 = _benchmark_return(index_daily, end_date, 10)
    bench20 = _benchmark_return(index_daily, end_date, 20)

    grouped = stocks.groupby("industry")
    heat = grouped.agg(
        stock_count=("ts_code", "count"),
        up_ratio=("pct_chg", lambda s: float((s > 0).mean())),
        above_ma20_ratio=("above_ma20", "mean"),
        volume_expansion_ratio=("volume_active", "mean"),
        limit_up_count=("limit_up_like", "sum"),
        overheat_ratio=("overheated_stock", "mean"),
        avg_position_20d=("position_20d", "mean"),
        avg_ret_5d=("ret_5d", "mean"),
        avg_ret_10d=("ret_10d", "mean"),
        avg_ret_20d=("ret_20d", "mean"),
        net_mf_amount=("net_mf_amount", "sum"),
        avg_turnover=("turnover_rate", "mean"),
    ).reset_index()
    heat = heat[heat["stock_count"] >= int(min_stocks)].copy()
    if heat.empty:
        return heat, stocks

    heat["rel_ret_5d"] = heat["avg_ret_5d"] - bench5
    heat["rel_ret_10d"] = heat["avg_ret_10d"] - bench10
    heat["rel_ret_20d"] = heat["avg_ret_20d"] - bench20
    heat["heat_score"] = (
        0.30 * heat["rel_ret_10d"].apply(lambda v: _scale(v, -5, 12))
        + 0.20 * heat["rel_ret_20d"].apply(lambda v: _scale(v, -8, 20))
        + 0.20 * heat["above_ma20_ratio"] * 100
        + 0.15 * heat["up_ratio"] * 100
        + 0.10 * heat["volume_expansion_ratio"] * 100
        + 0.05 * (heat["net_mf_amount"] / heat["stock_count"]).apply(lambda v: _scale(v, -2000, 3000))
        - heat["overheat_ratio"] * 12
    )
    heat.loc[heat["avg_ret_5d"] < -3, "heat_score"] -= 8
    heat["heat_score"] = heat["heat_score"].clip(0, 100).round(1)
    heat["stage"] = heat.apply(_classify_sector, axis=1)
    heat["summary"] = heat.apply(_sector_summary, axis=1)
    heat = heat.sort_values(["heat_score", "rel_ret_10d"], ascending=[False, False]).reset_index(drop=True)

    sector_cols = heat[["industry", "heat_score", "stage", "avg_ret_10d", "rel_ret_10d"]].rename(
        columns={"avg_ret_10d": "sector_ret_10d", "rel_ret_10d": "sector_rel_ret_10d"}
    )
    stocks = stocks.merge(sector_cols, on="industry", how="left")
    return heat, stocks


def _sector_summary(row: pd.Series) -> str:
    return (
        f"10日超额{_fmt_pct(row['rel_ret_10d'])}，"
        f"MA20上方占比{row['above_ma20_ratio'] * 100:.0f}%，"
        f"放量扩散{row['volume_expansion_ratio'] * 100:.0f}%"
    )


def _candidate_risk_note(row: pd.Series) -> str:
    if row.get("ret_5d", 0) >= 18 or row.get("position_20d", 0) >= 0.96:
        return "涨幅偏大，不追高，等分歧再看"
    if row.get("stage") == "过热高潮":
        return "板块偏热，降低追价冲动"
    if row.get("stage") == "退潮中":
        return "板块退潮，仅作复盘观察"
    return "节奏相对健康，继续跟踪承接"


def _candidate_reason(row: pd.Series) -> str:
    return (
        f"相对板块{_fmt_pct(row.get('stock_vs_sector_10d'))}，"
        f"量能{row.get('amount_ratio_5d', 1):.2f}倍，"
        f"资金{row.get('net_mf_amount', 0):+.0f}万"
    )


def rank_sector_stocks(
    stocks: pd.DataFrame,
    sector_heat: pd.DataFrame,
    top_sectors: int = 8,
    top_stocks: int = 3,
) -> pd.DataFrame:
    """Rank top stock candidates inside the hottest sectors."""
    if stocks.empty or sector_heat.empty:
        return pd.DataFrame()
    sectors = sector_heat.head(int(top_sectors))[["industry", "stage", "heat_score"]]
    data = stocks.merge(sectors, on="industry", how="inner", suffixes=("", "_sector"))
    if data.empty:
        return data
    data["stock_vs_sector_10d"] = data["ret_10d"] - data["sector_ret_10d"]
    data["candidate_score"] = (
        0.30 * data["stock_vs_sector_10d"].apply(lambda v: _scale(v, -5, 8))
        + 0.20 * data["ret_10d"].apply(lambda v: _scale(v, 0, 25))
        + 0.15 * data["above_ma20"].astype(float) * 100
        + 0.15 * data["amount_ratio_5d"].apply(lambda v: _scale(v, 0.8, 2.0))
        + 0.15 * data["net_mf_amount"].apply(lambda v: _scale(v, -2000, 5000))
        + 0.05 * data["turnover_rate"].apply(lambda v: _scale(v, 1, 8))
    )
    data["chase_penalty"] = (data["ret_5d"] - 18).clip(lower=0) + (data["position_20d"] - 0.92).clip(lower=0) * 50
    data.loc[data["ret_5d"] >= 18, "candidate_score"] -= 30
    data.loc[data["ret_5d"] >= 40, "candidate_score"] -= 20
    data.loc[data["ret_5d"] >= 60, "candidate_score"] -= 20
    data.loc[data["stock_vs_sector_10d"] >= 15, "candidate_score"] -= 25
    data.loc[data["position_20d"] >= 0.97, "candidate_score"] -= 15
    data["candidate_priority"] = 0
    data.loc[data["stock_vs_sector_10d"] < -3, "candidate_priority"] = 1
    data.loc[data["stock_vs_sector_10d"] <= -8, "candidate_priority"] = 2
    extreme_chase = data["ret_5d"] >= 60
    data.loc[extreme_chase, "candidate_priority"] = data.loc[extreme_chase, "candidate_priority"].clip(lower=3)
    data.loc[data["stock_vs_sector_10d"] < -3, "candidate_score"] -= 8
    data.loc[data["stock_vs_sector_10d"] <= -8, "candidate_score"] -= 18
    data["candidate_score"] = data["candidate_score"].clip(0, 100).round(1)
    data["risk_note"] = data.apply(_candidate_risk_note, axis=1)
    data["candidate_reason"] = data.apply(_candidate_reason, axis=1)
    data = data.sort_values(
        ["industry", "candidate_priority", "candidate_score", "chase_penalty", "ret_10d"],
        ascending=[True, True, False, True, False],
    ).copy()
    data["candidate_rank"] = data.groupby("industry").cumcount() + 1
    return data[data["candidate_rank"] <= int(top_stocks)].sort_values(
        ["heat_score", "industry", "candidate_rank"], ascending=[False, True, True]
    ).reset_index(drop=True)


def _table(df: pd.DataFrame, max_rows: int = 30) -> str:
    if df.empty:
        return "无样本\n"
    return df.head(max_rows).to_markdown(index=False) + "\n"


def _display_sector_frame(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    for col in ["avg_ret_5d", "rel_ret_10d"]:
        if col in data.columns:
            data[col] = data[col].map(_fmt_pct)
    for col in ["above_ma20_ratio", "volume_expansion_ratio"]:
        if col in data.columns:
            data[col] = data[col].map(lambda v: f"{_num(v, 0) * 100:.0f}%")
    if "heat_score" in data.columns:
        data["heat_score"] = data["heat_score"].map(lambda v: f"{_num(v, 0):.1f}")
    return data


def _display_stock_frame(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    for col in ["ret_5d", "ret_10d", "stock_vs_sector_10d"]:
        if col in data.columns:
            data[col] = data[col].map(_fmt_pct)
    if "candidate_score" in data.columns:
        data["candidate_score"] = data["candidate_score"].map(lambda v: f"{_num(v, 0):.1f}")
    return data


def build_markdown_report(sector_heat: pd.DataFrame, ranked_stocks: pd.DataFrame, end_date: str) -> str:
    healthy = sector_heat[sector_heat["stage"].isin(["低位启动", "趋势延续", "弱修复"])].copy()
    risky = sector_heat[sector_heat["stage"].isin(["过热高潮", "退潮中"])].copy()
    lines = [
        f"# 板块热度追踪 {end_date}",
        "",
        "## 先看结论",
    ]
    if sector_heat.empty:
        lines.append("- 当前没有足够样本生成板块热度。")
    else:
        top = sector_heat.iloc[0]
        lines.append(
            f"- 热度最高板块：`{top['industry']}`，状态 `{top['stage']}`，热度分 `{top['heat_score']}`。"
        )
        lines.append(f"- 健康主线 `{len(healthy)}` 个，过热/退潮风险板块 `{len(risky)}` 个。")
        lines.append("- 板块内 Top3 是候选观察名单，不是直接追价买入指令。")

    show_cols = [
        "industry",
        "stage",
        "heat_score",
        "stock_count",
        "avg_ret_5d",
        "rel_ret_10d",
        "above_ma20_ratio",
        "volume_expansion_ratio",
        "summary",
    ]
    stock_cols = [
        "industry",
        "candidate_rank",
        "ts_code",
        "name",
        "candidate_score",
        "ret_5d",
        "ret_10d",
        "stock_vs_sector_10d",
        "candidate_reason",
        "risk_note",
    ]
    lines.extend(
        [
            "",
            "## 健康主线 Top",
            _table(_display_sector_frame(healthy[[col for col in show_cols if col in healthy.columns]]), 12),
            "",
            "## 过热/退潮提醒",
            _table(_display_sector_frame(risky[[col for col in show_cols if col in risky.columns]]), 12),
            "",
            "## 板块内候选 Top3",
            _table(_display_stock_frame(ranked_stocks[[col for col in stock_cols if col in ranked_stocks.columns]]), 36),
        ]
    )
    return "\n".join(lines)


def _latest_trade_date(db_path: str | Path, end_date: str | None = None) -> str:
    conn = sqlite3.connect(db_path)
    try:
        if end_date:
            row = conn.execute(
                "select max(trade_date) from stock_daily where trade_date <= ?",
                (_normalize_date(end_date),),
            ).fetchone()
        else:
            row = conn.execute("select max(trade_date) from stock_daily").fetchone()
        if not row or not row[0]:
            raise ValueError("stock_daily has no trade_date")
        return str(row[0])
    finally:
        conn.close()


def load_history_frames(db_path: str | Path, end_date: str, lookback_days: int = 90) -> dict[str, pd.DataFrame]:
    conn = sqlite3.connect(db_path)
    try:
        dates = [
            row[0]
            for row in conn.execute(
                """
                select distinct trade_date
                from stock_daily
                where trade_date <= ?
                order by trade_date desc
                limit ?
                """,
                (end_date, int(lookback_days)),
            ).fetchall()
        ]
        if not dates:
            raise ValueError(f"No stock_daily rows before {end_date}")
        start_date = min(dates)
        frames = {
            "daily": pd.read_sql_query(
                """
                select trade_date, ts_code, open, high, low, close, pct_chg, amount
                from stock_daily
                where trade_date between ? and ?
                """,
                conn,
                params=(start_date, end_date),
            ),
            "stock_basic": pd.read_sql_query("select ts_code, name, industry, list_status from stock_basic", conn),
            "daily_basic": pd.read_sql_query(
                """
                select trade_date, ts_code, turnover_rate, volume_ratio, total_mv
                from stock_daily_basic
                where trade_date between ? and ?
                """,
                conn,
                params=(start_date, end_date),
            ),
            "moneyflow": pd.read_sql_query(
                """
                select trade_date, ts_code, net_mf_amount
                from stock_moneyflow
                where trade_date between ? and ?
                """,
                conn,
                params=(start_date, end_date),
            ),
            "index_daily": pd.read_sql_query(
                """
                select trade_date, ts_code, close, pct_chg, amount
                from index_daily
                where trade_date between ? and ?
                """,
                conn,
                params=(start_date, end_date),
            ),
        }
        return frames
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track sector heat and rank top stock candidates.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="History SQLite database path.")
    parser.add_argument("--end", default=None, help="End trade date, e.g. 20260616. Defaults to latest.")
    parser.add_argument("--output", default=None, help="Markdown report path.")
    parser.add_argument("--csv-output", default=None, help="Sector heat CSV path.")
    parser.add_argument("--stocks-output", default=None, help="Ranked stock candidates CSV path.")
    parser.add_argument("--top-sectors", type=int, default=8, help="Number of sectors to rank for stock candidates.")
    parser.add_argument("--top-stocks", type=int, default=3, help="Top stock candidates per sector.")
    parser.add_argument("--min-stocks", type=int, default=8, help="Minimum stock count per sector.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    end_date = _latest_trade_date(db_path, args.end)
    frames = load_history_frames(db_path, end_date)
    heat, stocks = calculate_sector_heat(
        frames["daily"],
        frames["stock_basic"],
        daily_basic=frames["daily_basic"],
        moneyflow=frames["moneyflow"],
        index_daily=frames["index_daily"],
        end_date=end_date,
        min_stocks=args.min_stocks,
    )
    ranked = rank_sector_stocks(stocks, heat, top_sectors=args.top_sectors, top_stocks=args.top_stocks)
    report = build_markdown_report(heat, ranked, end_date=end_date)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = Path(args.output or f"reports/sector_heat_{end_date}_{timestamp}.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")

    csv_output = Path(args.csv_output) if args.csv_output else output.with_suffix(".csv")
    heat.to_csv(csv_output, index=False, encoding="utf-8-sig")
    stocks_output = Path(args.stocks_output) if args.stocks_output else output.with_name(output.stem + "_stocks.csv")
    ranked.to_csv(stocks_output, index=False, encoding="utf-8-sig")

    print(f"Report written: {output}")
    print(report.split("\n\n## 健康主线 Top", 1)[0])


if __name__ == "__main__":
    main()
