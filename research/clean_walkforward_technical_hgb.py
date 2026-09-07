"""技术面与市场上下文的走步HGB高置信度选股研究。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from research.clean_financial_relative_confidence import enforce_same_stock_cooldown
from research.research_integrity import purge_overlapping_label_tail


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research" / "clean_all_market"
REPORT_DIR = ROOT / "reports" / "research"
ALL_YEARS = tuple(range(2016, 2022))
PREDICT_YEARS = (2019, 2020, 2021)
TARGET = "ret_5d"
COST_PCT = 0.25
RANDOM_STATE = 20260808

RAW_COLUMNS = [
    "ts_code", "name", "industry", "trade_date", "close", "synthetic_close", "pct_chg", "amount",
    "ret_5", "ret_10", "ret_20", "ret_60", "ma_5", "ma_20", "ma_60",
    "prior_high_20", "drawdown_20", "rsi_14", "volatility_20", "turnover_rate",
    "volume_ratio", "industry_rs_20", "entry_open", "entry_gap_pct", "ret_3d", "ret_5d",
    "label_exit_date_3d", "label_exit_date_5d", "label_exit_date_8d",
]

FEATURES = [
    "ret_5", "ret_10", "ret_20", "ret_60", "drawdown_20", "rsi_14",
    "volatility_20", "turnover_rate", "volume_ratio", "industry_rs_20",
    "close_to_ma5", "close_to_ma20", "ma20_to_ma60", "close_to_prior_high20",
    "log_amount", "amount_rank", "market_breadth_ma20", "market_breadth_ma60",
    "market_median_ret5", "market_median_ret20", "market_median_ret60",
    "market_median_pct_chg", "market_dispersion_pct_chg",
]


def walkforward_splits() -> list[tuple[tuple[int, ...], int]]:
    """返回严格只用过去年份训练的冻结切分。"""

    return [
        ((2016, 2017, 2018), 2019),
        ((2016, 2017, 2018, 2019), 2020),
        ((2016, 2017, 2018, 2019, 2020), 2021),
    ]


def build_features(frame: pd.DataFrame) -> pd.DataFrame:
    """仅从T日个股和T日市场截面构造模型特征。"""

    work = frame.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work["year"] = work["trade_date"].str[:4].astype(int)
    work["close_to_ma5"] = work["synthetic_close"] / work["ma_5"] - 1.0
    work["close_to_ma20"] = work["synthetic_close"] / work["ma_20"] - 1.0
    work["ma20_to_ma60"] = work["ma_20"] / work["ma_60"] - 1.0
    work["close_to_prior_high20"] = work["synthetic_close"] / work["prior_high_20"] - 1.0
    work["log_amount"] = np.log1p(pd.to_numeric(work["amount"], errors="coerce").clip(lower=0))
    work["amount_rank"] = work.groupby("trade_date")["amount"].rank(pct=True)
    work["above_ma20"] = (work["synthetic_close"] > work["ma_20"]).astype(float)
    work["above_ma60"] = (work["synthetic_close"] > work["ma_60"]).astype(float)
    daily = work.groupby("trade_date", as_index=False).agg(
        market_breadth_ma20=("above_ma20", "mean"),
        market_breadth_ma60=("above_ma60", "mean"),
        market_median_ret5=("ret_5", "median"),
        market_median_ret20=("ret_20", "median"),
        market_median_ret60=("ret_60", "median"),
        market_median_pct_chg=("pct_chg", "median"),
        market_dispersion_pct_chg=("pct_chg", "std"),
    )
    return work.merge(daily, on="trade_date", how="left", validate="many_to_one")


def tradable_universe(frame: pd.DataFrame) -> pd.DataFrame:
    """应用冻结的T日可交易性地板，不读取次日信息。"""

    return frame[
        frame["amount_rank"].between(0.30, 0.95, inclusive="both")
        & (frame["close"] >= 3.0)
        & frame["turnover_rate"].between(0.3, 20.0, inclusive="both")
    ].copy()


def sample_training_rows(
    frame: pd.DataFrame,
    years: tuple[int, ...],
    *,
    prediction_start_date: str | None = None,
) -> pd.DataFrame:
    """按年份等上限抽样，避免后期上市公司数量主导模型。"""

    parts = []
    for year in years:
        part = frame[(frame["year"] == year) & frame[TARGET].notna()].dropna(subset=FEATURES)
        if len(part) > 150000:
            part = part.sample(n=150000, random_state=RANDOM_STATE + year)
        parts.append(part)
    sampled = pd.concat(parts, ignore_index=True)
    return purge_overlapping_label_tail(
        sampled,
        horizon=5,
        prediction_start_date=prediction_start_date,
    )


def new_model() -> HistGradientBoostingRegressor:
    """构造冻结参数的稳健小树模型。"""

    return HistGradientBoostingRegressor(
        learning_rate=0.05,
        max_iter=100,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        l2_regularization=1.0,
        random_state=RANDOM_STATE,
    )


def predict_walkforward(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """逐年扩展训练并预测下一年，绝不混入预测年标签。"""

    predictions = []
    model_meta = {}
    for train_years, predict_year in walkforward_splits():
        train = sample_training_rows(
            frame,
            train_years,
            prediction_start_date=f"{predict_year}0101",
        )
        target = frame[frame["year"] == predict_year].dropna(subset=FEATURES).copy()
        model = new_model()
        model.fit(train[FEATURES], train[TARGET].clip(-15.0, 15.0))
        target["prediction"] = model.predict(target[FEATURES])
        target["prediction_rank"] = target.groupby("trade_date")["prediction"].rank(pct=True)
        target["train_end_year"] = max(train_years)
        predictions.append(target)
        model_meta[str(predict_year)] = {
            "train_years": list(train_years),
            "training_rows": int(len(train)),
            "prediction_rows": int(len(target)),
        }
    return pd.concat(predictions, ignore_index=True), model_meta


def select_trades(predictions: pd.DataFrame, all_dates: list[str]) -> pd.DataFrame:
    """高置信度筛选后锁定Top1，再执行次日可成交检查。"""

    candidates = predictions[
        (predictions["prediction_rank"] >= 0.995)
        & (predictions["prediction"] > COST_PCT)
    ].copy()
    locked = (
        candidates.sort_values(
            ["trade_date", "prediction", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(1)
        .copy()
    )
    executed = locked[
        locked["entry_open"].notna()
        & locked[TARGET].notna()
        & (locked["entry_gap_pct"] < 7.0)
        & (locked["entry_gap_pct"] > -9.5)
    ].copy()
    executed = enforce_same_stock_cooldown(executed, all_dates, cooldown_days=5)
    executed["net_return"] = executed[TARGET] - COST_PCT
    return executed


def _profit_factor(values: pd.Series) -> float | None:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    return gains / losses if losses > 0 else None


def summarize(trades: pd.DataFrame, predictions: pd.DataFrame) -> dict:
    """汇总走步确认期的收益、超额、集中度和校准。"""

    values = trades["net_return"].dropna()
    ordered = values.sort_values().reset_index(drop=True)
    trim = int(len(ordered) * 0.05)
    trimmed = ordered.iloc[trim:-trim] if trim and len(ordered) > trim * 2 else ordered
    benchmark = predictions.groupby("trade_date")[TARGET].mean().sub(COST_PCT)
    same_day_benchmark = trades["trade_date"].map(benchmark)
    yearly = {}
    calibration = {}
    for year in PREDICT_YEARS:
        year_trades = trades[trades["year"] == year]
        year_values = year_trades["net_return"].dropna()
        yearly[str(year)] = {
            "trades": int(len(year_values)),
            "average_net_return_pct": float(year_values.mean()) if len(year_values) else None,
            "profit_factor": _profit_factor(year_values),
        }
        year_predictions = predictions[(predictions["year"] == year) & predictions[TARGET].notna()].copy()
        year_predictions["prediction_quintile"] = pd.qcut(
            year_predictions["prediction"],
            5,
            labels=False,
            duplicates="drop",
        )
        quintile_returns = year_predictions.groupby("prediction_quintile")[TARGET].mean()
        calibration[str(year)] = {
            "bottom_quintile_return_pct": float(quintile_returns.iloc[0]) if len(quintile_returns) else None,
            "top_quintile_return_pct": float(quintile_returns.iloc[-1]) if len(quintile_returns) else None,
            "top_minus_bottom_pct": float(quintile_returns.iloc[-1] - quintile_returns.iloc[0]) if len(quintile_returns) else None,
        }
    stock_share = trades["ts_code"].value_counts(normalize=True)
    industry_share = trades["industry"].fillna("未知").value_counts(normalize=True)
    return {
        "trades": int(len(values)),
        "average_net_return_pct": float(values.mean()) if len(values) else None,
        "profit_factor": _profit_factor(values),
        "win_rate": float((values > 0).mean()) if len(values) else None,
        "trimmed_mean_pct": float(trimmed.mean()) if len(trimmed) else None,
        "double_cost_stress_mean_pct": float(values.mean() - COST_PCT) if len(values) else None,
        "same_day_universe_benchmark_pct": float(same_day_benchmark.mean()) if len(same_day_benchmark) else None,
        "edge_vs_same_day_universe_pct": float(values.mean() - same_day_benchmark.mean()) if len(values) else None,
        "maximum_single_stock_share": float(stock_share.iloc[0]) if len(stock_share) else None,
        "maximum_single_industry_share": float(industry_share.iloc[0]) if len(industry_share) else None,
        "yearly": yearly,
        "prediction_calibration": calibration,
    }


def evaluate(summary: dict) -> dict:
    """执行冻结的内部走步确认门槛。"""

    checks = {
        "minimum_total_trades": summary["trades"] >= 300,
        "minimum_trades_each_year": all(summary["yearly"][str(year)]["trades"] >= 80 for year in PREDICT_YEARS),
        "minimum_average_net_return_pct": (summary["average_net_return_pct"] or -999) >= 0.50,
        "minimum_profit_factor": (summary["profit_factor"] or 0) >= 1.20,
        "required_positive_years": all(
            (summary["yearly"][str(year)]["average_net_return_pct"] or -999) > 0
            for year in PREDICT_YEARS
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
    """运行内部走步确认，失败时不打开外部年份。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    predictions, model_meta = predict_walkforward(featured)
    trades = select_trades(predictions, sorted(featured["trade_date"].unique().tolist()))
    summary = summarize(trades, predictions)
    decision = evaluate(summary)
    result = {
        "research_id": "clean_walkforward_technical_hgb_20260808",
        "status": "internal_confirmation_pass" if decision["passed"] else "internal_confirmation_failed",
        "model_meta": model_meta,
        "summary": summary,
        "decision": decision,
        "external_years_opened": False,
        "note": "模型只使用T日数值特征，内部确认失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    predictions[["trade_date", "ts_code", "prediction", "prediction_rank", TARGET, "train_end_year"]].to_parquet(
        REPORT_DIR / "clean_walkforward_technical_hgb_predictions_20260808.parquet",
        index=False,
    )
    trades.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_trades_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
