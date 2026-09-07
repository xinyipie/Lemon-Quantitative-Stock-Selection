"""冻结质量动量领先幅度 v3 的一次性 2025 独立验证。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from research.all_market_multi_engine_research import (
    _available_dates,
    _build_regimes,
    _load_stock_info,
    build_year_panel,
)
from research.contrarian_candidate_stress import annual_path_metrics, max_drawdown
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.quality_momentum_reentry import build_candidates
from research.quality_momentum_reentry_sealed_2025 import evaluate_candidates
from research.two_stage_walkforward_research import _bootstrap_probability, _metrics

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
REPORT_DIR = ROOT / "reports" / "research"
HISTORICAL_CANDIDATES = REPORT_DIR / "quality_momentum_reentry_sealed_2025_20260808_candidates.csv"
FROZEN_CODE = ROOT / "research" / "quality_momentum_reentry_margin_v3_2019_2024.py"
FROZEN_PREREG = REPORT_DIR / "prereg_quality_momentum_reentry_margin_v3_2019_2024_20260808.json"
BASE_PREREG = REPORT_DIR / "prereg_quality_momentum_reentry_20260808.json"
EXPECTED_HASHES = {
    FROZEN_CODE: "FECA845CACB39D1C4B321B611FA1AE280389F1D98C58127788D9BFA51996FDF1",
    FROZEN_PREREG: "25CF31121D00656D5C2E2CB9396C258D0210EBD40CC64D7BC81DAFA626759621",
    BASE_PREREG: "3EF5E9390AD0E28DACF4E68F91E83D802DC6AB59894C4FBC48F4AEB827EECCE1",
}
RESEARCH_ID = "quality_momentum_reentry_margin_v3_holdout_2025_20260808"
HOLDOUT_YEAR = 2025
MINIMUM_PREDICTION_MARGIN = 0.02


def verify_frozen_hashes() -> None:
    """验证候选代码和预注册文件未在独立验证前被修改。"""

    for path, expected in EXPECTED_HASHES.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if actual != expected:
            raise RuntimeError(f"冻结文件哈希不一致：{path.name}")


def select_holdout_v3(trades: pd.DataFrame) -> pd.DataFrame:
    """在 2025 两阶段 Top2 输出上原样执行 v3 领先幅度规则。"""

    work = trades.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work = work[work["trade_date"].str[:4].astype(int) == HOLDOUT_YEAR].copy()
    ordered = work.sort_values(
        ["trade_date", "rank_prediction", "ts_code"],
        ascending=[True, False, True],
        kind="mergesort",
    ).copy()
    ordered["selected_rank"] = ordered.groupby("trade_date").cumcount() + 1
    if ordered.empty:
        ordered["prediction_margin"] = pd.Series(dtype=float)
        return ordered
    predictions = ordered.pivot(
        index="trade_date", columns="selected_rank", values="rank_prediction"
    ).reindex(columns=[1, 2])
    predictions["prediction_margin"] = predictions[1] - predictions[2]
    top1 = ordered[ordered["selected_rank"] == 1].merge(
        predictions[["prediction_margin"]],
        left_on="trade_date",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    return top1[top1["prediction_margin"] > MINIMUM_PREDICTION_MARGIN].copy()


def run() -> dict:
    """构建一次 2025 面板并执行冻结候选验证。"""

    verify_frozen_hashes()
    dates = _available_dates(CACHE, "20160101", "20251231")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    panel = build_year_panel(
        CACHE,
        stock_info,
        regimes,
        dates,
        HOLDOUT_YEAR,
        "20250101",
        "20251231",
    )
    holdout_candidates = build_candidates(panel)
    holdout_candidates.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_candidates.csv", index=False, encoding="utf-8-sig"
    )
    historical = pd.read_csv(HISTORICAL_CANDIDATES, dtype={"trade_date": str})
    combined_path = REPORT_DIR / f"{RESEARCH_ID}_walkforward_input.csv"
    pd.concat([historical, holdout_candidates], ignore_index=True).to_csv(
        combined_path, index=False, encoding="utf-8-sig"
    )
    all_base_trades = evaluate_candidates(combined_path, cost=0.25)
    base_trades = select_holdout_v3(all_base_trades)
    stress_trades = base_trades.copy()
    stress_trades["net_ret"] = stress_trades["net_ret"] - 0.25
    metrics = _metrics(base_trades)
    holdout_days = base_trades.groupby("trade_date", as_index=False)["net_ret"].mean()
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(
        holdout_days, block=5, repetitions=10000
    )
    base_overlap = overlap_adjusted_portfolio(base_trades, CACHE, cost=0.25)
    stress_overlap = overlap_adjusted_portfolio(stress_trades, CACHE, cost=0.50)
    base_yearly = annual_path_metrics(base_overlap)
    stress_yearly = annual_path_metrics(stress_overlap)
    base_row = base_yearly.loc[base_yearly["year"] == HOLDOUT_YEAR, "return_pct"]
    stress_row = stress_yearly.loc[stress_yearly["year"] == HOLDOUT_YEAR, "return_pct"]
    # 无信号不是异常，也不能按通过处理；收益记为 0，由最小交易数门槛明确否决。
    base_return = float(base_row.iloc[0]) if not base_row.empty else 0.0
    stress_return = float(stress_row.iloc[0]) if not stress_row.empty else 0.0
    base_drawdown = max_drawdown(base_overlap["net_ret"]) if not base_overlap.empty else float("nan")
    stress_drawdown = (
        max_drawdown(stress_overlap["net_ret"]) if not stress_overlap.empty else float("nan")
    )
    checks = {
        "minimum_trades": metrics["trades"] >= 15,
        "minimum_base_average_net_return": metrics["avg_net"] > 0.25,
        "minimum_profit_factor": metrics["profit_factor"] > 1.10,
        "bootstrap_nonpositive_probability": p_nonpositive < 0.10,
        "base_overlap_return_positive": base_return > 0,
        "stress_overlap_return_positive": stress_return > 0,
        "base_overlap_drawdown": base_drawdown > -20.0,
        "stress_overlap_drawdown": stress_drawdown > -25.0,
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "holdout_pass" if all(checks.values()) else "holdout_failed",
        "holdout_metrics": metrics,
        "bootstrap": {
            "ci_low": ci_low,
            "ci_high": ci_high,
            "p_nonpositive": p_nonpositive,
        },
        "base_overlap_return_pct": base_return,
        "stress_overlap_return_pct": stress_return,
        "base_overlap_max_drawdown_pct": base_drawdown,
        "stress_overlap_max_drawdown_pct": stress_drawdown,
        "checks": {key: bool(value) for key, value in checks.items()},
        "holdout_opened_once": True,
        "parameters_changed_after_holdout": False,
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base_trades.to_csv(
        REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
