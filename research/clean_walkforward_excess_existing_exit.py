"""修正尺度选股接入既有短线退出规则的内部确认。"""

from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd

from backtest_v2 import BacktestV2
from local_data_proxy import LocalDataProxy
from research.clean_walkforward_technical_hgb_excess_target import (
    ALL_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    account_metrics,
    add_excess_target,
    build_features,
    evaluate,
    execute_daily_top3,
    predict_walkforward_excess,
    summarize_cohorts,
    tradable_universe,
)

RESEARCH_ID = "clean_walkforward_excess_existing_exit_20260808"


def add_stress_exit_cost(trades: list[dict], extra_cost_pct: float = 0.25) -> list[dict]:
    """只在退出时额外扣除冻结压力成本，不改变持仓路径。"""

    stressed = []
    for trade in trades:
        item = dict(trade)
        item["profit_after_fee"] = float(item.get("profit_after_fee", 0.0) or 0.0) - extra_cost_pct
        stressed.append(item)
    return stressed


def add_position_counts(curve: pd.DataFrame, trades: list[dict]) -> pd.DataFrame:
    """为既有净值曲线补充研究统计器需要的在途持仓数。"""

    result = curve.copy()
    result["positions"] = result["trade_date"].map(
        lambda date: sum(
            str(trade.get("buy_date", "")) <= str(date) < str(trade.get("sell_date", ""))
            for trade in trades
        )
    )
    return result


def normalize_nav_base(curve: pd.DataFrame) -> pd.DataFrame:
    """将BacktestV2的100基准净值转换为研究统计器的1基准。"""

    result = curve.copy()
    result["nav"] = pd.to_numeric(result["nav"], errors="coerce") / 100.0
    return result


def simulate_existing_exit(selected: pd.DataFrame) -> tuple[list[dict], pd.DataFrame, pd.DataFrame]:
    """按日期锁定候选，并调用既有BacktestV2退出与槽位逻辑。"""

    pro = LocalDataProxy(cache_dir="data/cache")
    engine = BacktestV2(
        pro=pro,
        start_date="20190101",
        end_date="20220131",
        hold_days=5,
        top_n=3,
        fallback_stop_pct=-7.0,
        fallback_profit_pct=15.0,
        trailing_stop_pct=7.0,
        use_market_timing=False,
        max_positions=15,
    )
    dates = list(engine.all_trade_dates)
    date_index = {date: index for index, date in enumerate(dates)}
    price_cache = {}
    for date in dates:
        day = pro.daily(trade_date=date)
        if day is not None and not day.empty:
            price_cache[date] = day

    by_signal_date = defaultdict(list)
    for _, row in selected.sort_values(["trade_date", "prediction"], ascending=[True, False]).iterrows():
        by_signal_date[str(row["trade_date"])].append(row)

    all_trades: list[dict] = []
    for signal_date, rows in sorted(by_signal_date.items()):
        signal_index = date_index.get(signal_date)
        if signal_index is None or signal_index + 1 >= len(dates):
            continue
        buy_date = dates[signal_index + 1]
        items = [{"ts_code": str(row["ts_code"]), "signal_row": row} for row in rows]
        allowed = engine._filter_selected_items_for_portfolio(items, all_trades, buy_date)
        for item in allowed:
            buy_index = date_index[buy_date]
            result = engine._simulate_trade(
                ts_code=item["ts_code"],
                buy_date=buy_date,
                future_dates=dates[buy_index:],
                price_cache=price_cache,
                tech_stop_price=0.0,
                tech_target_price=0.0,
                volatility=3.0,
                tech_low20=0.0,
                select_close=0.0,
                regime_max_hold=5,
                track_type="corrected_excess_hgb",
                signal_row=item["signal_row"],
            )
            if result is None:
                continue
            result["portfolio_slot"] = item["portfolio_slot"]
            result["signal_date"] = signal_date
            result["prediction"] = float(item["signal_row"].get("prediction", 0.0) or 0.0)
            all_trades.append(result)

    base_curve = normalize_nav_base(
        add_position_counts(
            engine._build_mark_to_market_equity(all_trades, price_cache).rename(
                columns={"date": "trade_date"}
            ),
            all_trades,
        )
    )
    stress_trades = add_stress_exit_cost(all_trades)
    stress_curve = normalize_nav_base(
        add_position_counts(
            engine._build_mark_to_market_equity(stress_trades, price_cache).rename(
                columns={"date": "trade_date"}
            ),
            stress_trades,
        )
    )
    return all_trades, base_curve, stress_curve


def run() -> dict:
    """联合评估固定口径选股质量和既有退出后的账户质量。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = add_excess_target(tradable_universe(build_features(pd.concat(frames, ignore_index=True))))
    predictions, model_meta = predict_walkforward_excess(featured)
    selected = execute_daily_top3(predictions)
    cohort = summarize_cohorts(selected, predictions)
    exit_trades, base_curve, stress_curve = simulate_existing_exit(selected)
    base_account = account_metrics(base_curve)
    stress_account = account_metrics(stress_curve)
    decision = evaluate(cohort, base_account, stress_account)
    exit_frame = pd.DataFrame(exit_trades)
    result = {
        "research_id": RESEARCH_ID,
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "exit_diagnostics": {
            "selected_stock_trades": int(len(selected)),
            "executed_portfolio_trades": int(len(exit_frame)),
            "average_profit_after_fee_pct": float(exit_frame["profit_after_fee"].mean()) if len(exit_frame) else None,
            "exit_reasons": exit_frame["exit_reason"].value_counts().to_dict() if "exit_reason" in exit_frame else {},
        },
        "cohort_summary": cohort,
        "base_cost_account": base_account,
        "double_cost_account": stress_account,
        "decision": decision,
        "external_years_opened": False,
        "note": "选股口径保持固定5日；账户层仅复用项目既有冻结退出参数。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    exit_frame.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    base_curve.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_account_curve.csv", index=False, encoding="utf-8-sig"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
