"""技术HGB走步预测的每日Top3五批次错峰组合研究。"""

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


def lock_daily_top3(predictions: pd.DataFrame) -> pd.DataFrame:
    """每天仅按相对预测锁定Top3。"""

    return (
        predictions.sort_values(
            ["trade_date", "prediction", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(3)
        .copy()
    )


def execute_daily_top3(predictions: pd.DataFrame) -> pd.DataFrame:
    """锁定后执行T+1可成交检查，不递补。"""

    locked = lock_daily_top3(predictions)
    executed = locked[
        locked["entry_open"].notna()
        & locked[TARGET].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
    ].copy()
    executed["net_return"] = executed[TARGET] - COST_PCT
    return executed


def summarize_cohorts(trades: pd.DataFrame, predictions: pd.DataFrame) -> dict:
    """按每日新建的Top3批次统计五日等权收益。"""

    cohorts = trades.groupby("trade_date", as_index=False).agg(
        net_return=("net_return", "mean"),
        members=("ts_code", "size"),
    )
    cohorts["year"] = cohorts["trade_date"].str[:4].astype(int)
    values = cohorts["net_return"]
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    ordered = values.sort_values().reset_index(drop=True)
    trim = int(len(ordered) * 0.05)
    trimmed = ordered.iloc[trim:-trim] if trim and len(ordered) > trim * 2 else ordered
    benchmark = predictions.groupby("trade_date")[TARGET].mean().sub(COST_PCT)
    same_day_benchmark = cohorts["trade_date"].map(benchmark)
    yearly = {}
    for year in PREDICT_YEARS:
        part = cohorts.loc[cohorts["year"] == year, "net_return"]
        year_gains = float(part[part > 0].sum())
        year_losses = float(-part[part < 0].sum())
        yearly[str(year)] = {
            "cohorts": int(len(part)),
            "average_net_return_pct": float(part.mean()) if len(part) else None,
            "profit_factor": year_gains / year_losses if year_losses > 0 else None,
        }
    stock_share = trades["ts_code"].value_counts(normalize=True)
    industry_share = trades["industry"].fillna("未知").value_counts(normalize=True)
    return {
        "cohorts": int(len(cohorts)),
        "stock_trades": int(len(trades)),
        "average_members": float(cohorts["members"].mean()) if len(cohorts) else None,
        "average_cohort_net_return_pct": float(values.mean()) if len(values) else None,
        "cohort_profit_factor": gains / losses if losses > 0 else None,
        "win_rate": float((values > 0).mean()) if len(values) else None,
        "trimmed_mean_pct": float(trimmed.mean()) if len(trimmed) else None,
        "double_cost_stress_mean_pct": float(values.mean() - COST_PCT) if len(values) else None,
        "same_day_universe_benchmark_pct": float(same_day_benchmark.mean()) if len(same_day_benchmark) else None,
        "edge_vs_same_day_universe_pct": float(values.mean() - same_day_benchmark.mean()) if len(values) else None,
        "maximum_single_stock_share": float(stock_share.iloc[0]) if len(stock_share) else None,
        "maximum_single_industry_share": float(industry_share.iloc[0]) if len(industry_share) else None,
        "yearly": yearly,
    }


def evaluate(summary: dict) -> dict:
    """执行冻结的每日Top3内部确认门槛。"""

    checks = {
        "minimum_daily_cohorts": summary["cohorts"] >= 600,
        "minimum_cohorts_each_year": all(summary["yearly"][str(year)]["cohorts"] >= 200 for year in PREDICT_YEARS),
        "minimum_average_cohort_net_return_pct": (summary["average_cohort_net_return_pct"] or -999) >= 0.60,
        "minimum_cohort_profit_factor": (summary["cohort_profit_factor"] or 0) >= 1.25,
        "required_positive_years": all(
            (summary["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in PREDICT_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": (summary["edge_vs_same_day_universe_pct"] or -999) >= 0.30,
        "minimum_trimmed_mean_pct": (summary["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (summary["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (summary["maximum_single_stock_share"] or 999) <= 0.03,
        "maximum_single_industry_share": (summary["maximum_single_industry_share"] or 999) <= 0.15,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行每日Top3内部走步确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    predictions, model_meta = predict_walkforward(featured)
    trades = execute_daily_top3(predictions)
    summary = summarize_cohorts(trades, predictions)
    decision = evaluate(summary)
    result = {
        "research_id": "clean_walkforward_technical_hgb_daily_top3_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "summary": summary,
        "decision": decision,
        "external_years_opened": False,
        "note": "每日启动一批Top3并持有5日；内部确认失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_daily_top3_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trades.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_daily_top3_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
