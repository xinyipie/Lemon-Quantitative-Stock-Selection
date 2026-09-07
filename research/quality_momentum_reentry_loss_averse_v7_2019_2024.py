"""质量动量浅回调策略：亏损厌恶的排序与在线门控。"""

from __future__ import annotations

import json

import pandas as pd

from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.quality_momentum_reentry_online_gate_v5_2019_2024 import (
    BASE_QUANTILE,
    CACHE,
    REPORT_DIR,
    SOURCE,
    WARMUP_DAYS,
    online_gate_decisions,
)
from research.quality_momentum_reentry_rank_only_v4_2019_2024 import (
    BASE_MARGIN,
    select_by_prediction_margin,
)
from research.two_stage_walkforward_research import (
    FEATURE_COLUMNS,
    MARKET_FEATURES,
    _bootstrap_probability,
    _matrix,
    _metrics,
    _period,
    _prepare,
    fit_ridge,
    predict_ridge,
)

RESEARCH_ID = "quality_momentum_reentry_loss_averse_v7_2019_2024_20260808"
BASE_LOSS_PENALTY = 1.0
NEIGHBOR_LOSS_PENALTIES = (0.75, 1.25)


def loss_averse_utility(values: pd.Series, penalty: float) -> pd.Series:
    """对负收益追加冻结倍数惩罚，正收益保持不变。"""

    numeric = pd.to_numeric(values, errors="coerce")
    return numeric - penalty * (-numeric.clip(upper=0))


def build_loss_averse_oos_predictions(
    frame: pd.DataFrame,
    market: pd.DataFrame,
    loss_penalty: float,
) -> pd.DataFrame:
    """逐年训练亏损厌恶排序和门控，并保留每天 Top2。"""

    model_features = [
        column
        for column in FEATURE_COLUMNS
        if column in frame.columns
        and pd.to_numeric(frame[column], errors="coerce").fillna(0).abs().sum() > 0
    ]
    all_days: list[pd.DataFrame] = []
    outputs: list[pd.DataFrame] = []
    for test_year in range(2018, 2025):
        train = frame[(frame["year"] < test_year) & frame["ret_5d"].notna()].copy()
        test = frame[frame["year"].eq(test_year)].copy()
        if train.empty or test.empty:
            continue
        utility = loss_averse_utility(train["ret_5d"], loss_penalty)
        target = utility - utility.groupby(train["trade_date"]).transform("mean")
        rank_model = fit_ridge(
            _matrix(train, model_features), target.to_numpy(float), 100.0
        )
        test["rank_prediction"] = predict_ridge(
            _matrix(test, model_features), rank_model
        )
        test_top = (
            test.sort_values(
                ["trade_date", "rank_prediction", "ts_code"],
                ascending=[True, False, True],
                kind="mergesort",
            )
            .groupby("trade_date", group_keys=False)
            .head(2)
            .copy()
        )
        prior_days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame()
        test_market = market[market["year"].eq(test_year)].copy()
        if prior_days.empty:
            test_market["gate_prediction"] = 1.0
        else:
            gate_train = prior_days.merge(
                market.drop(columns="year"), on="trade_date", how="left"
            )
            gate_target = loss_averse_utility(gate_train["net_ret"], loss_penalty)
            gate_model = fit_ridge(
                _matrix(gate_train, MARKET_FEATURES), gate_target.to_numpy(float), 100.0
            )
            test_market["gate_prediction"] = predict_ridge(
                _matrix(test_market, MARKET_FEATURES), gate_model
            )
        test_top = test_top.merge(
            test_market[["trade_date", "gate_prediction"]], on="trade_date", how="left"
        )
        outputs.append(test_top)
        daily = test_top.groupby("trade_date", as_index=False).agg(
            gross_ret=("ret_5d", "mean"), trades=("ts_code", "size")
        )
        daily["net_ret"] = daily["gross_ret"] - 0.25
        daily["year"] = test_year
        all_days.append(daily)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def select_loss_averse_online(predicted: pd.DataFrame, cost: float) -> pd.DataFrame:
    """执行年内在线门控和冻结领先幅度规则。"""

    outputs: list[pd.DataFrame] = []
    for _, group in predicted.groupby("year", sort=True):
        daily = group[["trade_date", "gate_prediction"]].drop_duplicates("trade_date")
        decisions = online_gate_decisions(daily, BASE_QUANTILE, WARMUP_DAYS)
        passed_dates = set(decisions.loc[decisions["online_gate_pass"], "trade_date"])
        passed = group[group["trade_date"].isin(passed_dates)].copy()
        if not passed.empty:
            outputs.append(select_by_prediction_margin(passed, BASE_MARGIN, cost))
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def _yearly(trades: pd.DataFrame) -> pd.DataFrame:
    return (
        trades.groupby(trades["trade_date"].str[:4].astype(int))
        .apply(lambda group: pd.Series(_metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def _evaluate_penalty(frame: pd.DataFrame, market: pd.DataFrame, penalty: float) -> dict:
    predicted = build_loss_averse_oos_predictions(frame, market, penalty)
    trades = _period(select_loss_averse_online(predicted, cost=0.25), 2019, 2024)
    yearly = _yearly(trades)
    validation = _metrics(_period(trades, 2022, 2024))
    return {
        "loss_penalty": penalty,
        "metrics": _metrics(trades),
        "validation": validation,
        "yearly": yearly.to_dict(orient="records"),
        "six_years_positive": bool(len(yearly) == 6 and (yearly["avg_net"] > 0).all()),
        "validation_every_year_positive": bool(
            validation["years"] == validation["positive_years"] == 3
        ),
    }


def run() -> dict:
    """执行主惩罚系数、成本和邻域压力审计。"""

    frame, market = _prepare(SOURCE)
    predicted = build_loss_averse_oos_predictions(frame, market, BASE_LOSS_PENALTY)
    base = _period(select_loss_averse_online(predicted, cost=0.25), 2019, 2024)
    stress = _period(select_loss_averse_online(predicted, cost=0.50), 2019, 2024)
    internal = _metrics(_period(base, 2019, 2021))
    validation = _metrics(_period(base, 2022, 2024))
    yearly = _yearly(base)
    days = _period(base.groupby("trade_date", as_index=False)["net_ret"].mean(), 2022, 2024)
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(days, block=20, repetitions=10000)
    base_overlap = overlap_adjusted_portfolio(base, CACHE, cost=0.25)
    stress_overlap = overlap_adjusted_portfolio(stress, CACHE, cost=0.50)
    base_yearly = annual_path_metrics(base_overlap)
    stress_yearly = annual_path_metrics(stress_overlap)
    base_yearly = base_yearly[base_yearly["year"].between(2019, 2024)].copy()
    stress_yearly = stress_yearly[stress_yearly["year"].between(2019, 2024)].copy()
    base_drawdown = max_drawdown(base_overlap["net_ret"]) if not base_overlap.empty else float("nan")
    stress_drawdown = max_drawdown(stress_overlap["net_ret"]) if not stress_overlap.empty else float("nan")
    neighbors = [
        _evaluate_penalty(frame, market, value) for value in NEIGHBOR_LOSS_PENALTIES
    ]
    checks = {
        "internal_minimum_trades": internal["trades"] >= 60,
        "internal_profit_factor": internal["profit_factor"] > 1.10,
        "internal_every_year_positive": internal["positive_years"] == internal["years"] == 3,
        "validation_minimum_trades": validation["trades"] >= 60,
        "validation_average_net_return": validation["avg_net"] > 0.25,
        "validation_profit_factor": validation["profit_factor"] > 1.15,
        "validation_every_year_positive": validation["positive_years"] == validation["years"] == 3,
        "six_years_positive": len(yearly) == 6 and (yearly["avg_net"] > 0).all(),
        "bootstrap_lower_bound_positive": ci_low > 0,
        "bootstrap_nonpositive_probability": p_nonpositive < 0.05,
        "base_overlap_every_year_positive": len(base_yearly) == 6 and (base_yearly["return_pct"] > 0).all(),
        "stress_overlap_every_year_positive": len(stress_yearly) == 6 and (stress_yearly["return_pct"] > 0).all(),
        "base_overlap_drawdown": base_drawdown > -20.0,
        "stress_overlap_drawdown": stress_drawdown > -25.0,
        "neighbor_stability": all(
            item["six_years_positive"] and item["validation_every_year_positive"]
            for item in neighbors
        ),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "six_year_confirmation_pass" if all(checks.values()) else "six_year_confirmation_failed",
        "internal_metrics": internal,
        "validation_metrics": validation,
        "yearly_metrics": yearly.to_dict(orient="records"),
        "bootstrap": {"ci_low": ci_low, "ci_high": ci_high, "p_nonpositive": p_nonpositive},
        "base_overlap_yearly": base_yearly.to_dict(orient="records"),
        "stress_overlap_yearly": stress_yearly.to_dict(orient="records"),
        "base_overlap_max_drawdown_pct": base_drawdown,
        "stress_overlap_max_drawdown_pct": stress_drawdown,
        "neighbor_audit": neighbors,
        "checks": {key: bool(value) for key, value in checks.items()},
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
