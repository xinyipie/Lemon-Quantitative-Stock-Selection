"""质量动量资金确认策略的2026冻结观察与光迅科技漏斗审计。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research import quality_momentum_reentry_margin_v3_holdout_2025 as holdout
from research import quality_momentum_moneyflow_confirm_v11_2019_2025 as v11


RESEARCH_ID = "quality_momentum_moneyflow_v12_observation_2026_20260808"
ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "research"
OBSERVATION_YEAR = 2026
MINIMUM_PREDICTION_MARGIN = 0.02
HISTORICAL_INPUT = (
    REPORT_DIR / "quality_momentum_reentry_margin_v3_holdout_2025_20260808_walkforward_input.csv"
)


def select_observation_v3(trades: pd.DataFrame) -> pd.DataFrame:
    """在2026两阶段Top2输出上原样执行冻结的v3领先幅度规则。"""

    work = trades.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work = work[work["trade_date"].str[:4].astype(int).eq(OBSERVATION_YEAR)].copy()
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
    top1 = ordered[ordered["selected_rank"].eq(1)].merge(
        predictions[["prediction_margin"]],
        left_on="trade_date",
        right_index=True,
        how="left",
        validate="one_to_one",
    )
    return top1[top1["prediction_margin"].gt(MINIMUM_PREDICTION_MARGIN)].copy()


def _stage_row(frame: pd.DataFrame, ts_code: str, trade_date: str) -> dict:
    match = frame[
        frame["ts_code"].astype(str).eq(ts_code)
        & frame["trade_date"].astype(str).eq(trade_date)
    ]
    result = {"present": not match.empty}
    if not match.empty:
        row = match.iloc[0]
        for column in (
            "rank_prediction",
            "gate_prediction",
            "prediction_margin",
            "flow_ratio_5d",
            "flow_positive_days_5d",
            "net_ret",
        ):
            if column in match.columns and pd.notna(row[column]):
                result[column] = float(row[column])
    return result


def run() -> dict:
    """构建2026候选并执行冻结观察，不改变任何参数。"""

    holdout.verify_frozen_hashes()
    dates = holdout._available_dates(holdout.CACHE, "20160101", "20260807")
    regimes = holdout._build_regimes(holdout.CACHE, dates)
    stock_info = holdout._load_stock_info(holdout.CACHE)
    panel = holdout.build_year_panel(
        holdout.CACHE,
        stock_info,
        regimes,
        dates,
        OBSERVATION_YEAR,
        "20260101",
        "20260807",
    )
    candidates = holdout.build_candidates(panel)
    candidate_path = REPORT_DIR / f"{RESEARCH_ID}_candidates.csv"
    candidates.to_csv(candidate_path, index=False, encoding="utf-8-sig")
    historical = pd.read_csv(HISTORICAL_INPUT, dtype={"trade_date": str})
    combined_path = REPORT_DIR / f"{RESEARCH_ID}_walkforward_input.csv"
    pd.concat([historical, candidates], ignore_index=True).to_csv(
        combined_path, index=False, encoding="utf-8-sig"
    )

    all_gate_kept = holdout.evaluate_candidates(combined_path, cost=0.25)
    v3_signals = select_observation_v3(all_gate_kept)
    enriched = v11.attach_moneyflow(v3_signals)
    confirmed = v11.apply_confirmation(enriched, "flow_ratio_5d", 0.0)
    confirmed["net_ret"] = pd.to_numeric(confirmed["ret_5d"], errors="coerce") - 0.25
    completed = confirmed[confirmed["ret_5d"].notna()].copy()
    stress = completed.copy()
    stress["net_ret"] = pd.to_numeric(stress["ret_5d"], errors="coerce") - 0.50
    metrics = holdout._metrics(completed)
    base_path = holdout.overlap_adjusted_portfolio(completed, holdout.CACHE, cost=0.25)
    stress_path = holdout.overlap_adjusted_portfolio(stress, holdout.CACHE, cost=0.50)
    base_return = float(base_path["net_ret"].sum()) if not base_path.empty else 0.0
    stress_return = float(stress_path["net_ret"].sum()) if not stress_path.empty else 0.0

    code = "002281.SZ"
    signal_date = "20260422"
    guangxun_audit = {
        "candidate_top60": _stage_row(candidates, code, signal_date),
        "gate_kept_top2": _stage_row(all_gate_kept, code, signal_date),
        "v3_margin_top1": _stage_row(v3_signals, code, signal_date),
        "moneyflow_confirmed": _stage_row(confirmed, code, signal_date),
    }
    checks = {
        "minimum_completed_trades": metrics["trades"] >= 5,
        "average_net_return_positive": metrics["avg_net"] > 0,
        "profit_factor": metrics["profit_factor"] > 1.0,
        "base_path_positive": base_return > 0,
        "stress_path_positive": stress_return > 0,
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "recent_observation_supporting" if all(checks.values()) else "recent_observation_not_supporting",
        "completed_metrics": metrics,
        "generated_v3_signals": int(len(v3_signals)),
        "moneyflow_confirmed_signals": int(len(confirmed)),
        "base_path_return_sum_pct": base_return,
        "stress_path_return_sum_pct": stress_return,
        "guangxun_audit": guangxun_audit,
        "checks": {key: bool(value) for key, value in checks.items()},
        "recent_observation_is_not_formal_validation": True,
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    confirmed.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
