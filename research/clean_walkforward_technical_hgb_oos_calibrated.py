"""训练、时间外校准、下一年预测三段式技术HGB研究。"""

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
)


def oos_calibration_splits() -> list[tuple[tuple[int, ...], int, int]]:
    """返回训练、校准、预测严格递增的冻结切分。"""

    return [
        ((2016, 2017), 2018, 2019),
        ((2016, 2017, 2018), 2019, 2020),
        ((2016, 2017, 2018, 2019), 2020, 2021),
    ]


def oos_calibrated_predictions(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """用未参与拟合的过去一年预测分布确定下一年阈值。"""

    predictions = []
    metadata = {}
    for train_years, calibration_year, predict_year in oos_calibration_splits():
        train = sample_training_rows(
            frame,
            train_years,
            prediction_start_date=f"{predict_year}0101",
        )
        calibration = frame[frame["year"] == calibration_year].dropna(subset=FEATURES).copy()
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES).copy()
        model = new_model()
        model.fit(train[FEATURES], train[TARGET].clip(-15.0, 15.0))
        calibration_prediction = model.predict(calibration[FEATURES])
        threshold = float(pd.Series(calibration_prediction).quantile(0.99))
        target["prediction"] = model.predict(target[FEATURES])
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["calibrated_threshold"] = threshold
        target["train_end_year"] = max(train_years)
        predictions.append(target)
        metadata[str(predict_year)] = {
            "train_years": list(train_years),
            "calibration_year": calibration_year,
            "training_rows": int(len(train)),
            "calibration_rows": int(len(calibration)),
            "prediction_rows": int(len(target)),
            "oos_calibration_prediction_q99": threshold,
        }
    return pd.concat(predictions, ignore_index=True), metadata


def select_trades(predictions: pd.DataFrame, all_dates: list[str]) -> pd.DataFrame:
    """锁定每日Top1，并按过去校准年阈值决定是否执行。"""

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
    """执行冻结的三段式内部确认门槛。"""

    checks = {
        "minimum_total_trades": summary["trades"] >= 240,
        "minimum_trades_each_year": all(summary["yearly"][str(year)]["trades"] >= 60 for year in PREDICT_YEARS),
        "minimum_average_net_return_pct": (summary["average_net_return_pct"] or -999) >= 0.75,
        "minimum_profit_factor": (summary["profit_factor"] or 0) >= 1.30,
        "required_positive_years": all(
            (summary["yearly"][str(year)]["average_net_return_pct"] or -999) > 0 for year in PREDICT_YEARS
        ),
        "minimum_edge_vs_same_day_universe_pct": (summary["edge_vs_same_day_universe_pct"] or -999) >= 0.40,
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
    """运行三段式时间外校准内部确认。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    predictions, model_meta = oos_calibrated_predictions(featured)
    trades = select_trades(predictions, sorted(featured["trade_date"].unique().tolist()))
    summary = summarize(trades, predictions)
    decision = evaluate(summary)
    result = {
        "research_id": "clean_walkforward_technical_hgb_oos_calibrated_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "summary": summary,
        "decision": decision,
        "external_years_opened": False,
        "note": "校准年标签未用于阈值；内部确认失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_oos_calibrated_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    trades.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_oos_calibrated_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
