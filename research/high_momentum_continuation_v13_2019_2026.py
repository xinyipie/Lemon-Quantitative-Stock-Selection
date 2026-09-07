"""高动量延续v13：独立于质量回踩的强势突破候选引擎。"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from research import quality_momentum_reentry_margin_v3_2019_2024 as metrics_lib


RESEARCH_ID = "high_momentum_continuation_v13_2019_2026_20260808"
ROOT = Path(__file__).resolve().parents[1]
PRICE_DIR = ROOT / "data" / "research" / "clean_all_market"
FLOW_DIR = ROOT / "data" / "research" / "clean_moneyflow"
REPORT_DIR = ROOT / "reports" / "research"


@dataclass(frozen=True)
class RuleConfig:
    ret20_min: float = 30.0
    industry_rs_min: float = 5.0
    flow_ratio_min: float = 0.0
    cooldown_days: int = 10


BASE_CONFIG = RuleConfig()


def candidate_mask(frame: pd.DataFrame, config: RuleConfig = BASE_CONFIG) -> pd.Series:
    """高动量延续候选的当日可见条件。"""

    name = frame["name"].fillna("").astype(str)
    return (
        ~name.str.upper().str.contains("ST", regex=False)
        & ~frame["ts_code"].astype(str).str.endswith(".BJ")
        & pd.to_numeric(frame["history_count"], errors="coerce").ge(120)
        & pd.to_numeric(frame["pct_chg"], errors="coerce").between(-1.0, 6.0)
        & pd.to_numeric(frame["turnover_rate"], errors="coerce").between(1.0, 15.0)
        & pd.to_numeric(frame["volume_ratio"], errors="coerce").between(0.8, 2.5)
        & pd.to_numeric(frame["ret_20"], errors="coerce").between(config.ret20_min, 80.0)
        & pd.to_numeric(frame["ret_60"], errors="coerce").between(40.0, 160.0)
        & pd.to_numeric(frame["drawdown_20"], errors="coerce").between(-8.0, 3.0)
        & pd.to_numeric(frame["rsi_14"], errors="coerce").between(65.0, 90.0)
        & pd.to_numeric(frame["industry_rs_20"], errors="coerce").ge(config.industry_rs_min)
        & pd.to_numeric(frame["flow_ratio_5d"], errors="coerce").gt(config.flow_ratio_min)
        & pd.to_numeric(frame["ma_20"], errors="coerce").gt(
            pd.to_numeric(frame["ma_60"], errors="coerce")
        )
        & pd.to_numeric(frame["synthetic_close"], errors="coerce").ge(
            pd.to_numeric(frame["ma_20"], errors="coerce")
        )
        & frame["regime"].astype(str).eq("BULL_TREND")
    )


def _rank(frame: pd.DataFrame, values: pd.Series, higher_better: bool = True) -> pd.Series:
    work = values if higher_better else -values
    return work.groupby(frame["trade_date"]).rank(pct=True, method="average")


def score_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    """使用预注册权重进行当日横截面排序。"""

    work = frame.copy()
    volume_quality = -(pd.to_numeric(work["volume_ratio"], errors="coerce") - 1.3).abs()
    day_move_quality = -pd.to_numeric(work["pct_chg"], errors="coerce").abs()
    work["momentum_score"] = (
        _rank(work, work["ret_20"]) * 0.25
        + _rank(work, work["industry_rs_20"]) * 0.25
        + _rank(work, work["ret_60"]) * 0.15
        + _rank(work, work["flow_ratio_5d"]) * 0.15
        + _rank(work, volume_quality) * 0.10
        + _rank(work, work["volatility_20"], higher_better=False) * 0.05
        + _rank(work, day_move_quality) * 0.05
    )
    return work


def select_with_cooldown(
    candidates: pd.DataFrame, topn: int = 3, cooldown_days: int = 10
) -> pd.DataFrame:
    """逐日选择行业不重复的TopN，并仅使用此前选择记录执行同股冷却。"""

    if candidates.empty:
        return candidates.copy()
    dates = sorted(candidates["trade_date"].astype(str).unique().tolist())
    date_index = {date: index for index, date in enumerate(dates)}
    last_selected: dict[str, int] = {}
    outputs = []
    for trade_date, group in candidates.groupby("trade_date", sort=True):
        current_index = date_index[str(trade_date)]
        industries: set[str] = set()
        selected = 0
        ordered = group.sort_values(
            ["momentum_score", "ts_code"], ascending=[False, True], kind="mergesort"
        )
        for row_index, row in ordered.iterrows():
            code = str(row["ts_code"])
            industry = str(row["industry"])
            if industry in industries:
                continue
            if code in last_selected and current_index - last_selected[code] < cooldown_days:
                continue
            outputs.append(row_index)
            industries.add(industry)
            last_selected[code] = current_index
            selected += 1
            if selected >= topn:
                break
    return candidates.loc[outputs].copy().reset_index(drop=True)


def load_year_candidates(year: int, config: RuleConfig) -> pd.DataFrame:
    """逐年读取清洁仓，避免把全市场九年面板一次性放入内存。"""

    price_columns = [
        "ts_code", "name", "industry", "trade_date", "history_count", "synthetic_close",
        "pct_chg", "ret_20", "ret_60", "drawdown_20", "rsi_14", "volatility_20",
        "turnover_rate", "volume_ratio", "industry_rs_20", "ma_20", "ma_60", "regime",
        "entry_gap_pct", "ret_5d", "mfe_8d", "mae_8d",
    ]
    price = pd.read_parquet(PRICE_DIR / f"{year}.parquet", columns=price_columns)
    flow = pd.read_parquet(
        FLOW_DIR / f"{year}.parquet",
        columns=["trade_date", "ts_code", "flow_ratio_5d", "flow_positive_days_5d"],
    )
    price["trade_date"] = price["trade_date"].astype(str)
    flow["trade_date"] = flow["trade_date"].astype(str)
    work = price.merge(flow, on=["trade_date", "ts_code"], how="left", validate="one_to_one")
    selected = work[candidate_mask(work, config)].copy()
    return score_candidates(selected)


def build_signals(years: range, config: RuleConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.concat([load_year_candidates(year, config) for year in years], ignore_index=True)
    signals = select_with_cooldown(raw, topn=3, cooldown_days=config.cooldown_days)
    signals["net_ret"] = pd.to_numeric(signals["ret_5d"], errors="coerce") - 0.25
    return raw, signals


def _period(frame: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    years = frame["trade_date"].astype(str).str[:4].astype(int)
    return frame[years.between(start, end) & frame["ret_5d"].notna()].copy()


def _yearly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    return (
        frame.groupby(frame["trade_date"].astype(str).str[:4].astype(int))
        .apply(lambda group: pd.Series(metrics_lib._metrics(group)), include_groups=False)
        .reset_index(names="year")
    )


def _all_years_positive(yearly: pd.DataFrame, start: int, end: int) -> bool:
    if yearly.empty:
        return False
    sample = yearly[yearly["year"].between(start, end)]
    return len(sample) == end - start + 1 and sample["avg_net"].gt(0).all()


def run() -> dict:
    """先过内部期，依次打开验证期和近期观察期。"""

    internal_raw, internal_signals = build_signals(range(2019, 2022), BASE_CONFIG)
    internal = _period(internal_signals, 2019, 2021)
    internal_metrics = metrics_lib._metrics(internal)
    internal_yearly = _yearly(internal)
    internal_checks = {
        "minimum_trades": internal_metrics["trades"] >= 150,
        "average_net_return": internal_metrics["avg_net"] > 0.25,
        "profit_factor": internal_metrics["profit_factor"] > 1.15,
        "every_year_positive": _all_years_positive(internal_yearly, 2019, 2021),
    }
    if not all(internal_checks.values()):
        result = {
            "research_id": RESEARCH_ID,
            "status": "internal_gate_failed",
            "internal_candidate_rows": int(len(internal_raw)),
            "internal_metrics": internal_metrics,
            "internal_yearly": internal_yearly.to_dict(orient="records"),
            "internal_checks": {key: bool(value) for key, value in internal_checks.items()},
            "validation_opened": False,
            "recent_observation_opened": False,
            "production_changed": False,
        }
        (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    validation_raw, validation_signals = build_signals(range(2022, 2025), BASE_CONFIG)
    validation = _period(validation_signals, 2022, 2024)
    validation_metrics = metrics_lib._metrics(validation)
    validation_yearly = _yearly(validation)
    days = validation.groupby("trade_date", as_index=False)["net_ret"].mean()
    ci_low, ci_high, p_nonpositive = metrics_lib._bootstrap_probability(
        days, block=20, repetitions=10000
    )
    historical_signals = pd.concat([internal_signals, validation_signals], ignore_index=True)
    stress = historical_signals.copy()
    stress["net_ret"] = pd.to_numeric(stress["ret_5d"], errors="coerce") - 0.50
    base_path = metrics_lib.overlap_adjusted_portfolio(
        historical_signals, metrics_lib.CACHE, cost=0.25
    )
    stress_path = metrics_lib.overlap_adjusted_portfolio(stress, metrics_lib.CACHE, cost=0.50)
    base_path_yearly = metrics_lib.annual_path_metrics(base_path)
    stress_path_yearly = metrics_lib.annual_path_metrics(stress_path)
    base_drawdown = metrics_lib.max_drawdown(base_path["net_ret"])
    stress_drawdown = metrics_lib.max_drawdown(stress_path["net_ret"])
    validation_checks = {
        "minimum_trades": validation_metrics["trades"] >= 150,
        "average_net_return": validation_metrics["avg_net"] > 0.25,
        "profit_factor": validation_metrics["profit_factor"] > 1.15,
        "every_year_positive": _all_years_positive(validation_yearly, 2022, 2024),
        "bootstrap_lower_bound_positive": ci_low > 0,
        "bootstrap_nonpositive_probability": p_nonpositive < 0.05,
        "base_path_every_year_positive": _all_years_positive(
            base_path_yearly.rename(columns={"return_pct": "avg_net"}), 2019, 2024
        ),
        "stress_path_every_year_positive": _all_years_positive(
            stress_path_yearly.rename(columns={"return_pct": "avg_net"}), 2019, 2024
        ),
        "base_drawdown": base_drawdown > -20.0,
        "stress_drawdown": stress_drawdown > -25.0,
    }
    if not all(validation_checks.values()):
        result = {
            "research_id": RESEARCH_ID,
            "status": "validation_failed",
            "internal_metrics": internal_metrics,
            "internal_yearly": internal_yearly.to_dict(orient="records"),
            "validation_candidate_rows": int(len(validation_raw)),
            "validation_metrics": validation_metrics,
            "validation_yearly": validation_yearly.to_dict(orient="records"),
            "bootstrap": {"ci_low": ci_low, "ci_high": ci_high, "p_nonpositive": p_nonpositive},
            "base_path_yearly": base_path_yearly.to_dict(orient="records"),
            "stress_path_yearly": stress_path_yearly.to_dict(orient="records"),
            "validation_checks": {key: bool(value) for key, value in validation_checks.items()},
            "recent_observation_opened": False,
            "production_changed": False,
        }
        (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    recent_raw, recent_signals = build_signals(range(2025, 2027), BASE_CONFIG)
    recent = _period(recent_signals, 2025, 2026)
    recent_yearly = _yearly(recent)
    perturbations = []
    for label, config in (
        ("ret20_min_25", replace(BASE_CONFIG, ret20_min=25.0)),
        ("ret20_min_35", replace(BASE_CONFIG, ret20_min=35.0)),
        ("industry_rs_min_0", replace(BASE_CONFIG, industry_rs_min=0.0)),
        ("industry_rs_min_10", replace(BASE_CONFIG, industry_rs_min=10.0)),
        ("flow_ratio_min_minus_0_02", replace(BASE_CONFIG, flow_ratio_min=-0.02)),
        ("flow_ratio_min_plus_0_02", replace(BASE_CONFIG, flow_ratio_min=0.02)),
        ("cooldown_5", replace(BASE_CONFIG, cooldown_days=5)),
        ("cooldown_15", replace(BASE_CONFIG, cooldown_days=15)),
    ):
        _, sample = build_signals(range(2022, 2025), config)
        yearly = _yearly(_period(sample, 2022, 2024))
        perturbations.append(
            {"label": label, "yearly": yearly.to_dict(orient="records"), "all_positive": bool(_all_years_positive(yearly, 2022, 2024))}
        )
    all_raw = pd.concat([internal_raw, validation_raw, recent_raw], ignore_index=True)
    all_signals = pd.concat([historical_signals, recent_signals], ignore_index=True)
    code = "002281.SZ"
    date = "20260422"
    guangxun_candidate = all_raw[
        all_raw["ts_code"].eq(code) & all_raw["trade_date"].astype(str).eq(date)
    ]
    guangxun_signal = all_signals[
        all_signals["ts_code"].eq(code) & all_signals["trade_date"].astype(str).eq(date)
    ]
    checks = {
        **validation_checks,
        "perturbation_stability": all(item["all_positive"] for item in perturbations),
    }
    result = {
        "research_id": RESEARCH_ID,
        "status": "confirmation_pass" if all(checks.values()) else "confirmation_failed",
        "internal_metrics": internal_metrics,
        "validation_metrics": validation_metrics,
        "internal_yearly": internal_yearly.to_dict(orient="records"),
        "validation_yearly": validation_yearly.to_dict(orient="records"),
        "recent_yearly": recent_yearly.to_dict(orient="records"),
        "bootstrap": {"ci_low": ci_low, "ci_high": ci_high, "p_nonpositive": p_nonpositive},
        "base_path_yearly": base_path_yearly.to_dict(orient="records"),
        "stress_path_yearly": stress_path_yearly.to_dict(orient="records"),
        "base_max_drawdown_pct": base_drawdown,
        "stress_max_drawdown_pct": stress_drawdown,
        "perturbations": perturbations,
        "guangxun_audit": {
            "candidate_on_20260422": not guangxun_candidate.empty,
            "selected_on_20260422": not guangxun_signal.empty,
            "first_candidate_date": (
                str(all_raw.loc[all_raw["ts_code"].eq(code), "trade_date"].min())
                if all_raw["ts_code"].eq(code).any()
                else None
            ),
            "first_selected_date": (
                str(all_signals.loc[all_signals["ts_code"].eq(code), "trade_date"].min())
                if all_signals["ts_code"].eq(code).any()
                else None
            ),
        },
        "checks": {key: bool(value) for key, value in checks.items()},
        "case_inspired_not_independent": True,
        "production_changed": False,
    }
    (REPORT_DIR / f"{RESEARCH_ID}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    all_signals.to_csv(REPORT_DIR / f"{RESEARCH_ID}_trades.csv", index=False, encoding="utf-8-sig")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
