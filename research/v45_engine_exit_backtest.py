from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from backtest_v2 import BacktestV2
from local_data_proxy import LocalDataProxy
from v45_t1_t5_confirmation_backtest import (
    _entry_outcomes,
    _strong_baseline,
    build_v45_variants,
)


def _year_bucket(date: str) -> str:
    date = str(date)
    if date.startswith("2026"):
        return "2026H1"
    return date[:4]


def _to_float(row: pd.Series, column: str, default: float = 0.0) -> float:
    value = row.get(column, default)
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _prepare_events() -> pd.DataFrame:
    strong = _strong_baseline()
    outcomes = _entry_outcomes()
    variants = build_v45_variants(strong, outcomes)
    events = variants["v45_quality_t5_guard"].copy()
    events["entry_date"] = events["entry_date"].astype(str)
    events["ts_code"] = events["ts_code"].astype(str)
    return events.sort_values(["entry_date", "entry_rule", "ts_code"]).reset_index(drop=True)


def _build_price_cache(pro: LocalDataProxy, dates: list[str]) -> dict[str, pd.DataFrame]:
    cache = {}
    for date in dates:
        df = pro.daily(trade_date=date)
        if df is not None and not df.empty:
            cache[date] = df
    return cache


def run_engine_exit_backtest() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    events = _prepare_events()
    if events.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty

    start = str(events["entry_date"].min())
    end = str(events["entry_date"].max())
    pro = LocalDataProxy(cache_dir=str(ROOT / "data" / "cache"))
    engine = BacktestV2(
        pro=pro,
        start_date=start,
        end_date=end,
        hold_days=5,
        top_n=1,
        use_market_timing=False,
        min_open_ratio=0.0,
    )

    all_dates = engine.all_trade_dates
    price_cache = _build_price_cache(pro, all_dates)
    trades = []

    for _, event in events.iterrows():
        buy_date = str(event["entry_date"])
        future_dates = [date for date in all_dates if date >= buy_date]
        result = engine._simulate_trade(
            ts_code=str(event["ts_code"]),
            buy_date=buy_date,
            future_dates=future_dates,
            price_cache=price_cache,
            tech_stop_price=_to_float(event, "stop_loss_price", 0.0),
            tech_target_price=_to_float(event, "target_price", 0.0),
            volatility=_to_float(event, "volatility", 3.0),
            tech_low20=_to_float(event, "low20", 0.0),
            select_close=_to_float(event, "select_close", 0.0),
            regime_max_hold=5,
            track_type=str(event.get("entry_rule", "v45")),
            signal_row=event,
        )
        if result is None:
            continue
        for column in [
            "strategy",
            "entry_rule",
            "select_date",
            "name",
            "industry",
            "best_rank",
            "avg_rank",
            "factor_pattern",
            "limit_down_count",
            "pre_T5_low_pct",
            "pre_T5_close_min_pct",
        ]:
            if column in event:
                result[column] = event.get(column)
        result["signal_entry_date"] = buy_date
        result["year"] = _year_bucket(str(result.get("buy_date", buy_date)))
        trades.append(result)

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return events, trades_df, pd.DataFrame(), pd.DataFrame()

    profit_col = "profit_after_fee" if "profit_after_fee" in trades_df.columns else "profit_pct"
    trades_df["ret"] = pd.to_numeric(trades_df[profit_col], errors="coerce").fillna(0.0)
    trades_df["win"] = trades_df["ret"] > 0

    summary = pd.DataFrame([{"scope": "all", **_metrics(trades_df)}])
    yearly = _group_metrics(trades_df, "year").sort_values("year")
    layers = _group_metrics(trades_df, "entry_rule").sort_values("entry_rule")
    exits = (
        trades_df.groupby("exit_reason", dropna=False)
        .agg(trades=("ts_code", "count"), win_rate=("win", "mean"), total_ret=("ret", "sum"), avg_ret=("ret", "mean"))
        .reset_index()
        .sort_values("trades", ascending=False)
    )
    exits["win_rate"] = exits["win_rate"] * 100
    return trades_df, summary, yearly, layers.merge(exits, how="cross") if False else layers


def _metrics(df: pd.DataFrame) -> dict:
    yearly = df.groupby("year")["ret"].sum() if "year" in df.columns else pd.Series(dtype=float)
    return {
        "trades": int(len(df)),
        "win_rate": float(df["win"].mean() * 100) if len(df) else 0.0,
        "total_ret": float(df["ret"].sum()) if len(df) else 0.0,
        "avg_ret": float(df["ret"].mean()) if len(df) else 0.0,
        "avg_hold_days": float(pd.to_numeric(df.get("hold_days", pd.Series(dtype=float)), errors="coerce").mean()) if len(df) else 0.0,
        "positive_years": int((yearly > 0).sum()) if len(yearly) else 0,
        "loss_years": int((yearly <= 0).sum()) if len(yearly) else 0,
        "worst_year": float(yearly.min()) if len(yearly) else 0.0,
    }


def _group_metrics(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for value, frame in df.groupby(group_col, dropna=False):
        rows.append({group_col: value, **_metrics(frame)})
    return pd.DataFrame(rows)


def _exit_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    out = (
        trades.groupby("exit_reason", dropna=False)
        .agg(trades=("ts_code", "count"), win_rate=("win", "mean"), total_ret=("ret", "sum"), avg_ret=("ret", "mean"))
        .reset_index()
        .sort_values(["trades", "total_ret"], ascending=[False, False])
    )
    out["win_rate"] = out["win_rate"] * 100
    return out


def _write_doc(summary: pd.DataFrame, yearly: pd.DataFrame, layers: pd.DataFrame, exits: pd.DataFrame, output: Path) -> None:
    lines = [
        "# v45 真实退出规则回测（2026-07-06）",
        "",
        "## 口径",
        "",
        "- 入场事件来自 `v45_quality_t5_guard`：强信号 T1，扩容信号 T5。",
        "- 单笔退出复用 `BacktestV2._simulate_trade`，包含涨停跳过、技术/硬止损、止盈、移动止损、动态到期、弱收盘退出。",
        "- 该脚本仍是研究回测：只复盘选股与退出，不生成任何自动下单逻辑。",
        "",
        "## 总览",
        "",
        summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 分层",
        "",
        layers.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 年度",
        "",
        yearly.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 退出原因",
        "",
        exits.to_markdown(index=False, floatfmt=".2f") if not exits.empty else "无",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    trades, summary, yearly, layers = run_engine_exit_backtest()
    exits = _exit_summary(trades)

    trades.to_csv(REPORTS / "v45_engine_exit_trades_20260706.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(REPORTS / "v45_engine_exit_summary_20260706.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(REPORTS / "v45_engine_exit_yearly_20260706.csv", index=False, encoding="utf-8-sig")
    layers.to_csv(REPORTS / "v45_engine_exit_layers_20260706.csv", index=False, encoding="utf-8-sig")
    exits.to_csv(REPORTS / "v45_engine_exit_reasons_20260706.csv", index=False, encoding="utf-8-sig")
    _write_doc(summary, yearly, layers, exits, DOCS / "V45_ENGINE_EXIT_BACKTEST_20260706.md")

    print(summary.to_string(index=False))
    print()
    print(layers.to_string(index=False))
    print()
    print(yearly.to_string(index=False))
    print()
    print(exits.to_string(index=False))


if __name__ == "__main__":
    main()
