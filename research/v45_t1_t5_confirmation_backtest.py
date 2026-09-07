from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from entry_timing_bucket_research import (
    build_entry_outcomes,
    load_daily_subset,
    load_stage3_samples,
)
from hybrid_delayed_confirmation_experiment import _load_base_events, _strong_direct_events


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"


@dataclass(frozen=True)
class ExpansionRule:
    name: str
    max_best_rank: float
    max_avg_rank: float
    min_pattern: float
    max_limit_down: float
    min_pre_t5_low: float
    min_pre_t5_close: float


EXPANSION_RULES = [
    ExpansionRule(
        name="v45_quality_t5_guard",
        max_best_rank=2.0,
        max_avg_rank=2.0,
        min_pattern=50.0,
        max_limit_down=8.0,
        min_pre_t5_low=-1.0,
        min_pre_t5_close=-1.0,
    ),
    ExpansionRule(
        name="v45_strict_t5_confirm",
        max_best_rank=1.5,
        max_avg_rank=2.0,
        min_pattern=50.0,
        max_limit_down=12.0,
        min_pre_t5_low=-2.0,
        min_pre_t5_close=-1.0,
    ),
    ExpansionRule(
        name="v45_balanced_t5_confirm",
        max_best_rank=2.0,
        max_avg_rank=2.5,
        min_pattern=50.0,
        max_limit_down=8.0,
        min_pre_t5_low=-2.0,
        min_pre_t5_close=-1.0,
    ),
]


def _year_bucket(date: str) -> str:
    date = str(date)
    if date.startswith("2026"):
        return "2026H1"
    return date[:4]


def _strong_baseline() -> pd.DataFrame:
    _, rule_events = _load_base_events()
    strong = _strong_direct_events(rule_events)
    strong = strong.copy()
    strong["strategy"] = "strong_direct_only"
    strong["entry_rule"] = "strong_T1"
    strong["ret"] = pd.to_numeric(strong["ret_5d_from_entry"], errors="coerce")
    strong["win"] = strong["ret"] > 0
    strong["hit3"] = pd.to_numeric(strong["mfe_from_entry"], errors="coerce") >= 3.0
    strong["year"] = strong["entry_date"].map(_year_bucket)
    return strong


def _entry_outcomes() -> pd.DataFrame:
    samples = load_stage3_samples()
    daily = load_daily_subset(samples[["sample", "select_date", "buy_date", "ts_code"]])
    outcomes, _ = build_entry_outcomes(samples, daily)
    return outcomes


def _apply_expansion_rule(outcomes: pd.DataFrame, rule: ExpansionRule) -> pd.DataFrame:
    work = outcomes[outcomes["entry_bucket"].eq("T5")].copy()
    work = work[
        (pd.to_numeric(work["best_rank"], errors="coerce") <= rule.max_best_rank)
        & (pd.to_numeric(work["avg_rank"], errors="coerce") <= rule.max_avg_rank)
        & (pd.to_numeric(work["factor_pattern"], errors="coerce") >= rule.min_pattern)
        & (pd.to_numeric(work["limit_down_count"], errors="coerce") <= rule.max_limit_down)
        & (pd.to_numeric(work["pre_T5_low_pct"], errors="coerce") > rule.min_pre_t5_low)
        & (pd.to_numeric(work["pre_T5_close_min_pct"], errors="coerce") > rule.min_pre_t5_close)
    ].copy()
    if work.empty:
        return work

    score_col = "hybrid_score" if "hybrid_score" in work.columns else "consensus_score"
    work[score_col] = pd.to_numeric(work[score_col], errors="coerce")
    work = (
        work.sort_values(["select_date", score_col, "ts_code"], ascending=[True, False, True])
        .groupby("select_date", group_keys=False)
        .head(1)
        .reset_index(drop=True)
    )
    work["strategy"] = rule.name
    work["entry_rule"] = "expansion_T5"
    work["ret"] = pd.to_numeric(work["ret_5d_from_entry"], errors="coerce")
    work["win"] = work["ret"] > 0
    work["hit3"] = pd.to_numeric(work["mfe_from_entry"], errors="coerce") >= 3.0
    work["year"] = work["entry_date"].map(_year_bucket)
    return work


def build_v45_variants(strong: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    result = {"strong_direct_only": strong.copy()}
    strong_dates = set(strong["select_date"].astype(str))
    for rule in EXPANSION_RULES:
        expansion = _apply_expansion_rule(outcomes, rule)
        if not expansion.empty:
            expansion = expansion[~expansion["select_date"].astype(str).isin(strong_dates)].copy()
        combined = pd.concat([strong, expansion], ignore_index=True, sort=False)
        combined["strategy"] = rule.name
        result[rule.name] = combined.sort_values(["entry_date", "entry_rule", "ts_code"]).reset_index(drop=True)
    return result


def _metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "total_ret": 0.0,
            "avg_ret": 0.0,
            "hit3_rate": 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "positive_years": 0,
            "loss_years": 0,
            "worst_year": 0.0,
        }
    yearly = df.groupby("year")["ret"].sum()
    return {
        "trades": int(len(df)),
        "win_rate": float(df["win"].mean() * 100),
        "total_ret": float(df["ret"].sum()),
        "avg_ret": float(df["ret"].mean()),
        "hit3_rate": float(df["hit3"].mean() * 100),
        "avg_mfe": float(pd.to_numeric(df["mfe_from_entry"], errors="coerce").mean()),
        "avg_mae": float(pd.to_numeric(df["mae_from_entry"], errors="coerce").mean()),
        "positive_years": int((yearly > 0).sum()),
        "loss_years": int((yearly <= 0).sum()),
        "worst_year": float(yearly.min()),
    }


def summarise(variants: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    yearly_rows = []
    layer_rows = []
    for name, df in variants.items():
        summary_rows.append({"strategy": name, **_metrics(df)})
        for year, frame in df.groupby("year"):
            yearly_rows.append({"strategy": name, "year": year, **_metrics(frame)})
        for entry_rule, frame in df.groupby("entry_rule", dropna=False):
            layer_rows.append({"strategy": name, "entry_rule": entry_rule, **_metrics(frame)})
    summary = pd.DataFrame(summary_rows).sort_values(["total_ret", "win_rate"], ascending=[False, False])
    yearly = pd.DataFrame(yearly_rows).sort_values(["strategy", "year"])
    layers = pd.DataFrame(layer_rows).sort_values(["strategy", "entry_rule"])
    return summary, yearly, layers


def write_doc(summary: pd.DataFrame, yearly: pd.DataFrame, layers: pd.DataFrame, output: Path) -> None:
    lines = [
        "# v45 T1/T5 确认策略研究回测（2026-07-06）",
        "",
        "## 口径",
        "",
        "- 强信号层沿用 v35/v39 Top1 聚合样本，T1 开盘入场。",
        "- 扩容层只在强信号空窗日补票，使用 T5 开盘入场。",
        "- 扩容层入场前只使用已发生路径：前 4 个交易日低点、收盘低点，以及选股日已知排名/形态/跌停家数。",
        "- 收益口径为入场后 5 个交易日收盘收益；这是研究回测，不是自动交易逻辑。",
        "",
        "## 总览",
        "",
        summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 分层贡献",
        "",
        layers.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 年度拆分",
        "",
        yearly.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 初步结论",
        "",
        "- 如果 v45 能在 60 笔以上保持 70% 左右胜率，说明 T5 确认层有资格进入完整回测引擎。",
        "- 如果某一年扩容层亏损明显，下一轮优先从该年抽样查 NO_BUY 因子，而不是继续放宽规则。",
        "- 当前结果仍应避免直接上线，需要再接入真实短线退出规则验证。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    strong = _strong_baseline()
    outcomes = _entry_outcomes()
    variants = build_v45_variants(strong, outcomes)
    events = pd.concat(variants.values(), ignore_index=True, sort=False)
    summary, yearly, layers = summarise(variants)

    events.to_csv(REPORTS / "v45_t1_t5_confirmation_events_20260706.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(REPORTS / "v45_t1_t5_confirmation_summary_20260706.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(REPORTS / "v45_t1_t5_confirmation_yearly_20260706.csv", index=False, encoding="utf-8-sig")
    layers.to_csv(REPORTS / "v45_t1_t5_confirmation_layers_20260706.csv", index=False, encoding="utf-8-sig")
    write_doc(summary, yearly, layers, DOCS / "V45_T1_T5_CONFIRMATION_RESEARCH_20260706.md")

    print(summary.to_string(index=False))
    print()
    print(layers.to_string(index=False))
    print()
    print(yearly.to_string(index=False))


if __name__ == "__main__":
    main()
