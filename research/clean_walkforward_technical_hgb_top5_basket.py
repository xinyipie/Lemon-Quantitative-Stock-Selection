"""技术HGB走步预测的五日Top5等权篮子研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_walkforward_technical_hgb import (
    ALL_YEARS,
    COST_PCT,
    PREDICT_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    build_features,
    predict_walkforward,
    tradable_universe,
)


def lock_top5_baskets(predictions: pd.DataFrame, offset: int) -> pd.DataFrame:
    """每五个交易日按相对预测锁定Top5。"""

    if offset not in range(5):
        raise ValueError("offset必须位于0到4")
    dates = sorted(predictions["trade_date"].astype(str).unique().tolist())[offset::5]
    return (
        predictions[predictions["trade_date"].isin(dates)]
        .sort_values(
            ["trade_date", "prediction", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(5)
        .copy()
    )


def execute_baskets(predictions: pd.DataFrame, offset: int) -> pd.DataFrame:
    """锁定篮子后执行次日可成交检查，不递补。"""

    locked = lock_top5_baskets(predictions, offset)
    executed = locked[
        locked["entry_open"].notna()
        & locked[TARGET].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
    ].copy()
    executed["net_return"] = executed[TARGET] - COST_PCT
    return executed


def summarize_baskets(trades: pd.DataFrame, predictions: pd.DataFrame) -> dict:
    """按调仓日等权篮子统计收益和集中度。"""

    baskets = trades.groupby("trade_date", as_index=False).agg(
        net_return=("net_return", "mean"),
        members=("ts_code", "size"),
    )
    baskets["year"] = baskets["trade_date"].str[:4].astype(int)
    values = baskets["net_return"]
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    ordered = values.sort_values().reset_index(drop=True)
    trim = int(len(ordered) * 0.05)
    trimmed = ordered.iloc[trim:-trim] if trim and len(ordered) > trim * 2 else ordered
    benchmark = predictions.groupby("trade_date")[TARGET].mean().sub(COST_PCT)
    same_day_benchmark = baskets["trade_date"].map(benchmark)
    yearly = {}
    for year in PREDICT_YEARS:
        part = baskets.loc[baskets["year"] == year, "net_return"]
        year_gains = float(part[part > 0].sum())
        year_losses = float(-part[part < 0].sum())
        yearly[str(year)] = {
            "baskets": int(len(part)),
            "average_net_return_pct": float(part.mean()) if len(part) else None,
            "profit_factor": year_gains / year_losses if year_losses > 0 else None,
        }
    stock_share = trades["ts_code"].value_counts(normalize=True)
    industry_share = trades["industry"].fillna("未知").value_counts(normalize=True)
    return {
        "baskets": int(len(baskets)),
        "stock_trades": int(len(trades)),
        "average_members": float(baskets["members"].mean()) if len(baskets) else None,
        "average_basket_net_return_pct": float(values.mean()) if len(values) else None,
        "basket_profit_factor": gains / losses if losses > 0 else None,
        "win_rate": float((values > 0).mean()) if len(values) else None,
        "trimmed_mean_pct": float(trimmed.mean()) if len(trimmed) else None,
        "double_cost_stress_mean_pct": float(values.mean() - COST_PCT) if len(values) else None,
        "same_day_universe_benchmark_pct": float(same_day_benchmark.mean()) if len(same_day_benchmark) else None,
        "edge_vs_same_day_universe_pct": float(values.mean() - same_day_benchmark.mean()) if len(values) else None,
        "maximum_single_stock_share": float(stock_share.iloc[0]) if len(stock_share) else None,
        "maximum_single_industry_share": float(industry_share.iloc[0]) if len(industry_share) else None,
        "yearly": yearly,
    }


def evaluate(primary: dict, offsets: dict[str, dict]) -> dict:
    """执行主结果与五种日历偏移门槛。"""

    checks = {
        "minimum_baskets": primary["baskets"] >= 120,
        "minimum_baskets_each_year": all(primary["yearly"][str(year)]["baskets"] >= 40 for year in PREDICT_YEARS),
        "minimum_average_basket_net_return_pct": (primary["average_basket_net_return_pct"] or -999) >= 0.65,
        "minimum_basket_profit_factor": (primary["basket_profit_factor"] or 0) >= 1.25,
        "required_positive_years": all(
            (primary["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in PREDICT_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": (primary["edge_vs_same_day_universe_pct"] or -999) >= 0.30,
        "minimum_trimmed_mean_pct": (primary["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (primary["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (primary["maximum_single_stock_share"] or 999) <= 0.03,
        "maximum_single_industry_share": (primary["maximum_single_industry_share"] or 999) <= 0.15,
        "all_offsets_average_return_must_be_positive": all(
            (item["average_basket_net_return_pct"] or -999) > 0 for item in offsets.values()
        ),
        "minimum_profit_factor_each_offset": all(
            (item["basket_profit_factor"] or 0) >= 1.10 for item in offsets.values()
        ),
        "all_offsets_all_years_must_be_positive": all(
            (item["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for item in offsets.values()
            for year in PREDICT_YEARS
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行走步Top5篮子内部确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    predictions, model_meta = predict_walkforward(featured)
    trades = {offset: execute_baskets(predictions, offset) for offset in range(5)}
    summaries = {str(offset): summarize_baskets(frame, predictions) for offset, frame in trades.items()}
    decision = evaluate(summaries["0"], summaries)
    result = {
        "research_id": "clean_walkforward_technical_hgb_top5_basket_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "primary_offset_0": summaries["0"],
        "all_calendar_offsets": summaries,
        "decision": decision,
        "external_years_opened": False,
        "note": "按非重叠等权篮子统计；内部确认失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_top5_basket_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for offset, frame in trades.items():
        frame.to_csv(
            REPORT_DIR / f"clean_walkforward_technical_hgb_top5_basket_offset{offset}_trades_20260808.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
