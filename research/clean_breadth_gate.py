"""检验全市场参与广度对低波动动量策略的入场门控价值。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.clean_archetype_family import archetype_candidates
from research.clean_financial_relative_confidence import enforce_same_stock_cooldown
from research.clean_moneyflow_overlay import summarize


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "research" / "clean_all_market"
REPORT_DIR = ROOT / "reports" / "research"
YEARS = tuple(range(2016, 2022))
COST_PCT = 0.25
COOLDOWN_DAYS = 8

COLUMNS = [
    "ts_code",
    "name",
    "industry",
    "trade_date",
    "close",
    "ret_5",
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


def add_breadth_features(frame: pd.DataFrame) -> pd.DataFrame:
    """用T日截面与过去交易日生成全市场广度，不使用未来数据。"""

    work = frame.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work["above_ma20"] = (work["close"] > work["ma_20"]).astype(float)
    work["above_ma60"] = (work["close"] > work["ma_60"]).astype(float)
    daily = (
        work.groupby("trade_date", as_index=False)
        .agg(
            breadth_ma20=("above_ma20", "mean"),
            breadth_ma60=("above_ma60", "mean"),
            market_median_ret5=("ret_5", "median"),
            market_median_ret20=("ret_20", "median"),
        )
        .sort_values("trade_date")
    )
    daily["breadth_ma20_change_5d"] = daily["breadth_ma20"] - daily["breadth_ma20"].shift(5)
    return work.merge(daily, on="trade_date", how="left", validate="many_to_one")


def state_mask(frame: pd.DataFrame, variant: str) -> pd.Series:
    """返回预注册的日期级广度状态。"""

    broad = (
        (frame["breadth_ma20"] >= 0.55)
        & (frame["breadth_ma60"] >= 0.55)
        & (frame["market_median_ret20"] > 0)
    )
    improving = (
        (frame["breadth_ma20"] >= 0.45)
        & (frame["breadth_ma20_change_5d"] >= 0.05)
        & (frame["market_median_ret5"] > 0)
    )
    if variant == "baseline":
        return pd.Series(True, index=frame.index)
    if variant == "broad_support":
        return broad
    if variant == "improving_support":
        return improving
    if variant == "adaptive_support":
        return broad | improving
    raise ValueError(f"未知版本: {variant}")


def load_training_panel() -> pd.DataFrame:
    """读取六年训练样本并连续计算广度变化。"""

    frames = [pd.read_parquet(STORE / f"{year}.parquet", columns=COLUMNS) for year in YEARS]
    return add_breadth_features(pd.concat(frames, ignore_index=True))


def select_variant(enriched: pd.DataFrame, variant: str) -> pd.DataFrame:
    """对原型候选应用日期级门控，并保持相同排序和执行口径。"""

    candidates = archetype_candidates(enriched, "low_vol_momentum").copy()
    candidates = candidates[state_mask(candidates, variant)].copy()
    selected = (
        candidates.sort_values(
            ["trade_date", "score", "ts_code"],
            ascending=[True, False, True],
            kind="mergesort",
        )
        .groupby("trade_date", group_keys=False)
        .head(1)
        .copy()
    )
    all_signal_dates = sorted(enriched["trade_date"].astype(str).unique().tolist())
    selected = enforce_same_stock_cooldown(selected, all_signal_dates, COOLDOWN_DAYS)
    selected = selected[pd.to_numeric(selected["ret_8d"], errors="coerce").notna()].copy()
    selected["net_return"] = pd.to_numeric(selected["ret_8d"], errors="coerce") - COST_PCT
    selected["year"] = selected["trade_date"].astype(str).str[:4].astype(int)
    selected["variant"] = variant
    return selected


def segment_summary(selected: pd.DataFrame, years: tuple[int, ...]) -> dict:
    """计算发现期或内部确认期的简洁指标。"""

    part = selected[selected["year"].isin(years)]
    values = part["net_return"].dropna()
    gains = float(values[values > 0].sum())
    losses = float(-values[values < 0].sum())
    return {
        "trades": int(len(values)),
        "average_net_return_pct": round(float(values.mean()), 6) if len(values) else None,
        "profit_factor": round(gains / losses, 6) if losses > 0 else None,
    }


def evaluate(summary: dict, discovery: dict, confirmation: dict, baseline: dict) -> dict:
    """按预注册标准判定训练期是否有资格进入压力测试。"""

    yearly = summary["yearly"]
    checks = {
        "minimum_total_trades": summary["trades"] >= 120,
        "minimum_trades_each_year": all(yearly[str(year)]["trades"] >= 12 for year in YEARS),
        "minimum_average_net_return_pct": (summary["average_net_return_pct"] or -999) >= 0.45,
        "minimum_profit_factor": (summary["profit_factor"] or 0) >= 1.20,
        "minimum_positive_years": summary["positive_years"] >= 5,
        "required_positive_years": all((yearly[str(year)]["average_net_return_pct"] or -999) > 0 for year in (2019, 2020, 2021)),
        "minimum_discovery_average_net_return_pct": (discovery["average_net_return_pct"] or -999) > 0,
        "minimum_confirmation_trades": confirmation["trades"] >= 60,
        "minimum_confirmation_average_net_return_pct": (confirmation["average_net_return_pct"] or -999) >= 0.45,
        "minimum_confirmation_profit_factor": (confirmation["profit_factor"] or 0) >= 1.20,
        "minimum_trimmed_mean_pct": (summary["trimmed_mean_pct"] or -999) > 0,
        "minimum_double_cost_stress_mean_pct": (summary["double_cost_stress_mean_pct"] or -999) > 0,
        "maximum_single_stock_share": (summary["maximum_single_stock_share"] or 999) <= 0.05,
        "maximum_single_industry_share": (summary["maximum_single_industry_share"] or 999) <= 0.20,
        "minimum_average_return_increment_vs_baseline_pct": (
            (summary["average_net_return_pct"] or -999) - (baseline["average_net_return_pct"] or 0)
        ) >= 0.20,
    }
    return {"passed": all(checks.values()), "checks": checks}


def run() -> dict:
    """运行训练期广度门控研究并保存全部交易明细。"""

    enriched = load_training_panel()
    variants = ("baseline", "broad_support", "improving_support", "adaptive_support")
    selections = {variant: select_variant(enriched, variant) for variant in variants}
    summaries = {variant: summarize(frame) for variant, frame in selections.items()}
    segments = {
        variant: {
            "discovery_2016_2018": segment_summary(frame, (2016, 2017, 2018)),
            "confirmation_2019_2021": segment_summary(frame, (2019, 2020, 2021)),
        }
        for variant, frame in selections.items()
    }
    baseline = summaries["baseline"]
    decisions = {
        variant: evaluate(
            summaries[variant],
            segments[variant]["discovery_2016_2018"],
            segments[variant]["confirmation_2019_2021"],
            baseline,
        )
        for variant in variants
        if variant != "baseline"
    }
    result = {
        "research_id": "clean_breadth_gate_20260808",
        "status": "training_pass" if any(item["passed"] for item in decisions.values()) else "training_failed",
        "summaries": summaries,
        "segments": segments,
        "decisions": decisions,
        "external_years_opened": False,
        "note": "训练门槛未通过时不打开外部年份，研究结果不自动接入正式策略。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "clean_breadth_gate_training_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for variant, frame in selections.items():
        frame.to_csv(
            REPORT_DIR / f"clean_breadth_gate_{variant}_trades_20260808.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
