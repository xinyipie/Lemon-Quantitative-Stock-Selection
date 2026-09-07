"""每日Top3走步模型的15槽逐日盯市账户评估。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.clean_broad_cross_sectional_rank import simulate_portfolio
from research.clean_walkforward_technical_hgb import (
    ALL_YEARS,
    RAW_COLUMNS,
    REPORT_DIR,
    STORE,
    build_features,
    predict_walkforward,
    tradable_universe,
)
from research.clean_walkforward_technical_hgb_daily_top3 import execute_daily_top3


def account_metrics(curve: pd.DataFrame) -> dict:
    """从逐日净值计算年化、回撤、夏普和年度收益。"""

    if curve.empty:
        return {
            "days": 0,
            "total_return_pct": None,
            "annualized_return_pct": None,
            "max_drawdown_pct": None,
            "sharpe": None,
            "average_positions": None,
            "yearly_returns_pct": {},
        }
    work = curve.copy().sort_values("trade_date")
    work["trade_date"] = work["trade_date"].astype(str)
    work["daily_return"] = work["nav"].pct_change()
    first_return = float(work["nav"].iloc[0] - 1.0)
    work.loc[work.index[0], "daily_return"] = first_return
    total_return = float(work["nav"].iloc[-1] - 1.0)
    annualized = (float(work["nav"].iloc[-1]) ** (252.0 / len(work)) - 1.0) if work["nav"].iloc[-1] > 0 else -1.0
    running_peak = work["nav"].cummax()
    drawdown = work["nav"] / running_peak - 1.0
    daily_std = float(work["daily_return"].std(ddof=1))
    sharpe = float(work["daily_return"].mean() / daily_std * np.sqrt(252.0)) if daily_std > 0 else None
    work["year"] = work["trade_date"].str[:4]
    yearly = {
        str(year): float((1.0 + part["daily_return"]).prod() - 1.0) * 100.0
        for year, part in work.groupby("year")
    }
    return {
        "days": int(len(work)),
        "total_return_pct": total_return * 100.0,
        "annualized_return_pct": annualized * 100.0,
        "max_drawdown_pct": float(drawdown.min()) * 100.0,
        "sharpe": sharpe,
        "average_positions": float(work["positions"].mean()),
        "maximum_positions": int(work["positions"].max()),
        "yearly_returns_pct": yearly,
    }


def evaluate(base: dict, stress: dict) -> dict:
    """执行冻结的账户级门槛。"""

    expected_years = ("2019", "2020", "2021")
    yearly_values = [base["yearly_returns_pct"].get(year, -999.0) for year in expected_years]
    checks = {
        "minimum_base_annualized_return_pct": (base["annualized_return_pct"] or -999) >= 12.0,
        "maximum_base_drawdown_pct": (base["max_drawdown_pct"] or -999) >= -20.0,
        "minimum_base_sharpe": (base["sharpe"] or -999) >= 0.80,
        "required_positive_years": all(value > 0 for value in yearly_values),
        "minimum_worst_year_return_pct": min(yearly_values) >= 3.0,
        "minimum_stress_annualized_return_pct": (stress["annualized_return_pct"] or -999) >= 8.0,
        "maximum_stress_drawdown_pct": (stress["max_drawdown_pct"] or -999) >= -25.0,
        "minimum_average_positions": (base["average_positions"] or 0) >= 8.0,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行基础成本和双倍成本的逐日账户评估。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=RAW_COLUMNS) for year in ALL_YEARS]
    featured = tradable_universe(build_features(pd.concat(frames, ignore_index=True)))
    predictions, model_meta = predict_walkforward(featured)
    trades = execute_daily_top3(predictions)
    base_curve = simulate_portfolio(trades, slots=15, cost_pct=0.25, holding_days=5)
    stress_curve = simulate_portfolio(trades, slots=15, cost_pct=0.50, holding_days=5)
    base = account_metrics(base_curve)
    stress = account_metrics(stress_curve)
    decision = evaluate(base, stress)
    result = {
        "research_id": "clean_walkforward_technical_hgb_daily_top3_account_20260808",
        "status": "account_gate_pass" if decision["passed"] else "account_gate_failed",
        "model_meta": model_meta,
        "base_cost_account": base,
        "double_cost_account": stress,
        "decision": decision,
        "external_years_opened": False,
        "note": "账户逐日盯市且最多15槽；失败时不打开2022-2024。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_walkforward_technical_hgb_daily_top3_account_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    base_curve.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_daily_top3_account_curve_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    stress_curve.to_csv(
        REPORT_DIR / "clean_walkforward_technical_hgb_daily_top3_account_double_cost_curve_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
