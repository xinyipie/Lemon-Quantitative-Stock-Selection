"""使用训练预测分布校准阈值的技术HGB走步研究。"""

from __future__ import annotations

import json

import pandas as pd

from research.clean_financial_relative_confidence import enforce_same_stock_cooldown
from research.clean_walkforward_technical_hgb import (
    ALL_YEARS,
    COST_PCT,
    FEATURES,
    PREDICT_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    TARGET,
    build_features,
    new_model,
    sample_training_rows,
    summarize,
    tradable_universe,
    walkforward_splits,
)


def calibrated_walkforward_predictions(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """阈值只由训练预测分布决定，再原样应用到下一年。"""

    predictions = []
    metadata = {}
    for train_years, predict_year in walkforward_splits():
        train = sample_training_rows(
            frame,
            train_years,
            prediction_start_date=f"{predict_year}0101",
        )
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES).copy()
        model = new_model()
        model.fit(train[FEATURES], train[TARGET].clip(-15.0, 15.0))
        train_prediction = model.predict(train[FEATURES])
        threshold = float(pd.Series(train_prediction).quantile(0.995))
        target["prediction"] = model.predict(target[FEATURES])
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["calibrated_threshold"] = threshold
        target["train_end_year"] = max(train_years)
        predictions.append(target)
        metadata[str(predict_year)] = {
            "train_years": list(train_years),
            "training_rows": int(len(train)),
            "prediction_rows": int(len(target)),
            "training_prediction_q995": threshold,
        }
    return pd.concat(predictions, ignore_index=True), metadata


def select_calibrated_trades(predictions: pd.DataFrame, all_dates: list[str]) -> pd.DataFrame:
    """锁定每日Top1，并按对应训练分布阈值弃权。"""

    locked = (
        predictions.sort_values(
            ["trade_date", "prediction", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(1)
        .copy()
    )
    locked = locked[locked["prediction"] >= locked["calibrated_threshold"]].copy()
    executed = locked[
        locked["entry_open"].notna()
        & locked[TARGET].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
    ].copy()
    executed = enforce_same_stock_cooldown(executed, all_dates, cooldown_days=5)
    executed["net_return"] = executed[TARGET] - COST_PCT
    return executed


def evaluate(summary: dict) -> dict:
    """执行冻结的训练分布校准门槛。"""

    checks = {
        "minimum_total_trades": summary["trades"] >= 300,
        "minimum_trades_each_year": all(summary["yearly"][str(year)]["trades"] >= 80 for year in PREDICT_YEARS),
        "minimum_average_net_return_pct": (summary["average_net_return_pct"] or -999) >= 0.50,
        "minimum_profit_factor": (summary["profit_factor"] or 0) >= 1.20,
        "required_positive_years": all(
            (summary["yearly"][str(year)]["average_net_return_pct"] or -999) > 0 for year in PREDICT_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": (summary["edge_vs_same_day_universe_pct"] or -999) >= 0.30,
        "minimum_trimmed_mean_pct": (summary["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (summary["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (summary["maximum_single_stock_share"] or 999) <= 0.03,
        "maximum_single_industry_share": (summary["maximum_single_industry_share"] or 999) <= 0.15,
        "minimum_top_prediction_quintile_edge_pct_each_year": all(
            (summary["prediction_calibration"][str(year)]["top_minus_bottom_pct"] or -999) >= 0.20
            for year in PREDICT_YEARS
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行训练分布校准的内部走步确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    predictions, model_meta = calibrated_walkforward_predictions(featured)
    trades = select_calibrated_trades(predictions, sorted(featured["trade_date"].unique().tolist()))
    summary = summarize(trades, predictions)
    decision = evaluate(summary)
    result = {
        "research_id": "clean_walkforward_technical_hgb_train_calibrated_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "summary": summary,
        "decision": decision,
        "external_years_opened": False,
        "note": "阈值只由训练预测分布确定；内部确认失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_train_calibrated_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trades.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_train_calibrated_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
