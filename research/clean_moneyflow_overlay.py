"""在干净全市场样本上检验资金流对低波动动量候选的独立增量。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.clean_archetype_family import archetype_candidates
from research.clean_financial_relative_confidence import enforce_same_stock_cooldown
from research.no_future_signal_pipeline import apply_next_open_execution


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research" / "clean_all_market"
MONEYFLOW_STORE = ROOT / "data" / "cache" / "moneyflow"
REPORT_DIR = ROOT / "reports" / "research"
YEARS = tuple(range(2016, 2022))
COST_PCT = 0.25
COOLDOWN_DAYS = 8
TARGET = "ret_8d"

CLEAN_COLUMNS = [
    "ts_code",
    "name",
    "industry",
    "trade_date",
    "close",
    "amount",
    "ret_20",
    "ret_60",
    "ma_20",
    "ma_60",
    "rsi_14",
    "volatility_20",
    "turnover_rate",
    "volume_ratio",
    "industry_rs_20",
    "regime",
    "entry_open",
    "entry_gap_pct",
    "ret_8d",
    "mfe_8d",
    "mae_8d",
]


def moneyflow_ratio(net_mf_amount: pd.Series, amount: pd.Series) -> pd.Series:
    """把万元资金净额换算为千元后，计算其占当日成交额比例。"""

    denominator = pd.to_numeric(amount, errors="coerce").where(lambda value: value > 0)
    numerator = pd.to_numeric(net_mf_amount, errors="coerce") * 10.0
    return numerator / denominator


def compute_moneyflow_features(frame: pd.DataFrame) -> pd.DataFrame:
    """仅使用当日及过去两个交易日生成资金流特征。"""

    work = frame.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work["net_mf_ratio"] = moneyflow_ratio(work["net_mf_amount"], work["amount"])
    work["mf_amount_rank"] = work.groupby("trade_date")["net_mf_amount"].rank(pct=True)
    work["mf_ratio_rank"] = work.groupby("trade_date")["net_mf_ratio"].rank(pct=True)
    work = work.sort_values(["ts_code", "trade_date"], kind="mergesort")
    work["mf_positive"] = np.where(
        work["net_mf_amount"].notna(),
        (work["net_mf_amount"] > 0).astype(float),
        np.nan,
    )
    work["mf_rank_3d"] = (
        work.groupby("ts_code", sort=False)["mf_amount_rank"]
        .rolling(3, min_periods=3)
        .mean()
        .reset_index(level=0, drop=True)
    )
    work["mf_positive_fraction_3d"] = (
        work.groupby("ts_code", sort=False)["mf_positive"]
        .rolling(3, min_periods=3)
        .mean()
        .reset_index(level=0, drop=True)
    )
    return work.sort_values(["trade_date", "ts_code"], kind="mergesort")


def load_training_panel() -> tuple[pd.DataFrame, dict]:
    """读取训练期干净样本并合并逐日资金流。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=CLEAN_COLUMNS) for year in YEARS]
    clean = pd.concat(frames, ignore_index=True)
    clean["trade_date"] = clean["trade_date"].astype(str)
    valid_dates = set(clean["trade_date"].unique())

    moneyflow_parts: list[pd.DataFrame] = []
    for path in sorted(MONEYFLOW_STORE.glob("*.parquet")):
        trade_date = path.stem
        if trade_date not in valid_dates:
            continue
        part = pd.read_parquet(path, columns=["ts_code", "net_mf_amount"])
        part["trade_date"] = trade_date
        moneyflow_parts.append(part)
    if not moneyflow_parts:
        raise RuntimeError("训练期没有可用的moneyflow本地缓存")

    moneyflow = pd.concat(moneyflow_parts, ignore_index=True)
    work = clean.merge(moneyflow, on=["trade_date", "ts_code"], how="left", validate="one_to_one")
    coverage = {}
    for year, part in work.groupby(work["trade_date"].str[:4]):
        coverage[year] = {
            "rows": int(len(part)),
            "moneyflow_rows": int(part["net_mf_amount"].notna().sum()),
            "coverage": round(float(part["net_mf_amount"].notna().mean()), 6),
        }
    return compute_moneyflow_features(work), coverage


def build_variant_candidates(enriched: pd.DataFrame, variant: str) -> pd.DataFrame:
    """按预注册规则生成某一资金流版本的候选。"""

    candidates = archetype_candidates(enriched, "low_vol_momentum").copy()
    candidates["base_rank"] = candidates.groupby("trade_date")["score"].rank(pct=True)

    if variant == "baseline":
        candidates["research_score"] = candidates["base_rank"]
    elif variant == "current_flow":
        candidates = candidates[
            (candidates["mf_amount_rank"] >= 0.70)
            & (candidates["mf_ratio_rank"] >= 0.60)
        ].copy()
        candidates["research_score"] = (
            candidates["base_rank"] * 0.70
            + candidates["mf_amount_rank"] * 0.15
            + candidates["mf_ratio_rank"] * 0.15
        )
    elif variant == "persistent_flow":
        candidates = candidates[
            (candidates["mf_rank_3d"] >= 0.60)
            & (candidates["mf_positive_fraction_3d"] >= 2.0 / 3.0)
        ].copy()
        candidates["research_score"] = (
            candidates["base_rank"] * 0.70 + candidates["mf_rank_3d"] * 0.30
        )
    elif variant == "consensus_flow":
        candidates = candidates[
            (candidates["mf_amount_rank"] >= 0.70)
            & (candidates["mf_ratio_rank"] >= 0.60)
            & (candidates["mf_rank_3d"] >= 0.60)
            & (candidates["mf_positive_fraction_3d"] >= 2.0 / 3.0)
        ].copy()
        candidates["research_score"] = (
            candidates["base_rank"] * 0.60
            + candidates["mf_amount_rank"] * 0.15
            + candidates["mf_ratio_rank"] * 0.10
            + candidates["mf_rank_3d"] * 0.15
        )
    else:
        raise ValueError(f"未知版本: {variant}")

    selected = (
        candidates.sort_values(
            ["trade_date", "research_score", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(1)
        .copy()
    )
    all_signal_dates = sorted(enriched["trade_date"].astype(str).unique().tolist())
    selected = enforce_same_stock_cooldown(selected, all_signal_dates, COOLDOWN_DAYS)
    selected = apply_next_open_execution(
        selected,
        cost=COST_PCT,
        outcome_column=TARGET,
    )
    selected = selected[selected["evaluable"]].copy()
    selected["net_return"] = pd.to_numeric(selected["net_ret"], errors="coerce")
    selected["year"] = selected["trade_date"].astype(str).str[:4].astype(int)
    selected["variant"] = variant
    return selected


def _profit_factor(values: pd.Series) -> float | None:
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / losses


def _trimmed_mean(values: pd.Series, proportion: float = 0.05) -> float | None:
    clean = values.dropna().sort_values().reset_index(drop=True)
    if clean.empty:
        return None
    trim = int(len(clean) * proportion)
    if trim and len(clean) > trim * 2:
        clean = clean.iloc[trim:-trim]
    return float(clean.mean())


def summarize(selected: pd.DataFrame) -> dict:
    """汇总成本后收益、年度一致性与集中度。"""

    values = selected["net_return"].dropna()
    yearly = {}
    for year in YEARS:
        part = selected[selected["year"] == year]["net_return"].dropna()
        yearly[str(year)] = {
            "trades": int(len(part)),
            "average_net_return_pct": round(float(part.mean()), 6) if len(part) else None,
            "profit_factor": round(float(_profit_factor(part)), 6) if len(part) and np.isfinite(_profit_factor(part)) else _profit_factor(part),
        }
    stock_share = selected["ts_code"].value_counts(normalize=True)
    industry_share = selected["industry"].fillna("未知").value_counts(normalize=True)
    pf = _profit_factor(values)
    return {
        "trades": int(len(values)),
        "average_net_return_pct": round(float(values.mean()), 6) if len(values) else None,
        "median_net_return_pct": round(float(values.median()), 6) if len(values) else None,
        "win_rate": round(float((values > 0).mean()), 6) if len(values) else None,
        "profit_factor": round(float(pf), 6) if pf is not None and np.isfinite(pf) else pf,
        "trimmed_mean_pct": round(float(_trimmed_mean(values)), 6) if len(values) else None,
        "double_cost_stress_mean_pct": round(float(values.mean() - COST_PCT), 6) if len(values) else None,
        "positive_years": int(sum((item["average_net_return_pct"] or 0) > 0 for item in yearly.values())),
        "maximum_single_stock_share": round(float(stock_share.iloc[0]), 6) if len(stock_share) else None,
        "maximum_single_industry_share": round(float(industry_share.iloc[0]), 6) if len(industry_share) else None,
        "top_stock": str(stock_share.index[0]) if len(stock_share) else None,
        "top_industry": str(industry_share.index[0]) if len(industry_share) else None,
        "yearly": yearly,
    }


def evaluate_gates(summary: dict, baseline: dict) -> dict:
    """按预注册门槛判定，禁止用结果反向修改阈值。"""

    yearly = summary["yearly"]
    checks = {
        "minimum_total_trades": summary["trades"] >= 180,
        "minimum_trades_each_year": all(yearly[str(year)]["trades"] >= 20 for year in YEARS),
        "minimum_average_net_return_pct": (summary["average_net_return_pct"] or -999) >= 0.45,
        "minimum_profit_factor": (summary["profit_factor"] or 0) >= 1.20,
        "minimum_positive_years": summary["positive_years"] >= 5,
        "required_positive_years": all((yearly[str(year)]["average_net_return_pct"] or -999) > 0 for year in (2019, 2020, 2021)),
        "minimum_trimmed_mean_pct": (summary["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (summary["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (summary["maximum_single_stock_share"] or 999) <= 0.05,
        "maximum_single_industry_share": (summary["maximum_single_industry_share"] or 999) <= 0.20,
        "minimum_average_return_increment_vs_baseline_pct": (
            (summary["average_net_return_pct"] or -999) - (baseline["average_net_return_pct"] or 0)
        ) >= 0.20,
        "minimum_profit_factor_increment_vs_baseline": (
            (summary["profit_factor"] or 0) - (baseline["profit_factor"] or 0)
        ) >= 0.05,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """执行训练期检验并写出可复查结果。"""

    enriched, coverage = load_training_panel()
    variants = ("baseline", "current_flow", "persistent_flow", "consensus_flow")
    selections = {variant: build_variant_candidates(enriched, variant) for variant in variants}
    summaries = {variant: summarize(frame) for variant, frame in selections.items()}
    baseline = summaries["baseline"]
    decisions = {
        variant: evaluate_gates(summary, baseline)
        for variant, summary in summaries.items()
        if variant != "baseline"
    }
    result = {
        "research_id": "clean_moneyflow_overlay_20260808",
        "status": "training_pass" if any(item["passed"] for item in decisions.values()) else "training_failed",
        "coverage": coverage,
        "summaries": summaries,
        "decisions": decisions,
        "external_years_opened": False,
        "note": "训练门槛未通过时不查看外部年份；本结果不接入正式策略。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_json = REPORT_DIR / "clean_moneyflow_overlay_training_20260808.json"
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for variant, frame in selections.items():
        frame.to_csv(
            REPORT_DIR / f"clean_moneyflow_overlay_{variant}_trades_20260808.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
