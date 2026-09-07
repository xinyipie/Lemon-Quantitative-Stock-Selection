from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from delayed_entry_path_audit import build_event_rows, load_daily_subset, load_samples


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
STAGE3_PATH = REPORTS / "stage3_candidate_consensus_topn_selected.csv"


@dataclass(frozen=True)
class HybridRule:
    name: str
    expansion_rule: str
    require_no_break: bool
    min_versions: int = 3
    max_avg_rank: float = 3.0
    max_best_rank: float = 2.0
    min_pattern: float = 60.0
    max_limit_down: float = 8.0
    macro_mode: str = "cautious"
    daily_top_n: int = 1


RULES = [
    HybridRule("hybrid_strong_plus_wait_T3", "wait_T3_open", False),
    HybridRule("hybrid_strong_plus_wait_T3_no_preentry_break", "wait_T3_open", True),
    HybridRule("hybrid_strong_plus_wait_T2_no_preentry_break", "wait_T2_open", True),
]

DYNAMIC_STRATEGY_NAME = "hybrid_dynamic_T1_T3_T5_by_ticket"


def _date(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace("-", "")[:8]


def _year_bucket(date: str) -> str:
    if date.startswith("2026"):
        return "2026H1"
    return date[:4]


def _preentry_low_pct(paths: pd.DataFrame, samples: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    daily_by_code = {code: part.reset_index(drop=True) for code, part in daily.groupby("ts_code")}
    rows = []
    for row in samples.itertuples(index=False):
        code_df = daily_by_code.get(str(row.ts_code))
        if code_df is None:
            continue
        idx = code_df.index[code_df["trade_date"] >= str(row.buy_date)]
        if len(idx) == 0:
            continue
        pos = code_df.index.get_loc(idx[0])
        path = code_df.iloc[pos : pos + 5].reset_index(drop=True)
        if len(path) < 2:
            continue
        base_open = float(path.iloc[0]["open"])
        first4_low_pct = pd.NA
        first4_close_min_pct = pd.NA
        if len(path) >= 4:
            first4_low_pct = (path.iloc[:4]["low"].min() / base_open - 1) * 100
            first4_close_min_pct = (path.iloc[:4]["close"].min() / base_open - 1) * 100
        rows.append(
            {
                "sample": row.sample,
                "select_date": row.select_date,
                "buy_date": row.buy_date,
                "ts_code": row.ts_code,
                "first1_low_pct": (path.iloc[:1]["low"].min() / base_open - 1) * 100,
                "first1_close_min_pct": (path.iloc[:1]["close"].min() / base_open - 1) * 100,
                "first2_low_pct": (path.iloc[:2]["low"].min() / base_open - 1) * 100,
                "first2_close_min_pct": (path.iloc[:2]["close"].min() / base_open - 1) * 100,
                "first4_low_pct": first4_low_pct,
                "first4_close_min_pct": first4_close_min_pct,
            }
        )
    first2 = pd.DataFrame(rows)
    if first2.empty:
        paths["first1_low_pct"] = pd.NA
        paths["first1_close_min_pct"] = pd.NA
        paths["first2_low_pct"] = pd.NA
        paths["first2_close_min_pct"] = pd.NA
        paths["first4_low_pct"] = pd.NA
        paths["first4_close_min_pct"] = pd.NA
        return paths
    keys = ["sample", "select_date", "buy_date", "ts_code"]
    return paths.merge(first2, on=keys, how="left")


def _load_base_events() -> tuple[pd.DataFrame, pd.DataFrame]:
    samples = load_samples()
    daily = load_daily_subset(samples)
    paths, rule_events = build_event_rows(samples, daily)
    paths = _preentry_low_pct(paths, samples, daily)
    return paths, rule_events


def _strong_direct_events(rule_events: pd.DataFrame) -> pd.DataFrame:
    strong = rule_events[
        rule_events["sample"].isin(["v35_top1", "v39_top1"])
        & rule_events["rule"].eq("direct_T1_open")
    ].copy()
    strong["layer"] = "strong_direct"
    strong["ret"] = pd.to_numeric(strong["ret_5d_from_entry"], errors="coerce")
    strong["year"] = strong["buy_date"].map(_year_bucket)
    strong = strong.sort_values(["select_date", "sample", "ts_code"])
    return strong.drop_duplicates(["select_date", "ts_code"])


def _expansion_candidates(paths: pd.DataFrame, rule_events: pd.DataFrame, rule: HybridRule) -> pd.DataFrame:
    stage3 = pd.read_csv(STAGE3_PATH)
    stage3["select_date"] = stage3["select_date"].map(_date)
    stage3["ts_code"] = stage3["ts_code"].astype(str)
    for col in [
        "n_versions",
        "avg_rank",
        "best_rank",
        "factor_pattern",
        "limit_down_count",
        "hybrid_score",
        "consensus_score",
        "recent_factor_score",
    ]:
        if col in stage3.columns:
            stage3[col] = pd.to_numeric(stage3[col], errors="coerce")

    scoped = stage3[
        (stage3["n_versions"] >= rule.min_versions)
        & (stage3["avg_rank"] <= rule.max_avg_rank)
        & (stage3["best_rank"] <= rule.max_best_rank)
        & (stage3["factor_pattern"] >= rule.min_pattern)
        & (stage3["limit_down_count"] <= rule.max_limit_down)
        & (stage3["macro_mode"].astype(str).eq(rule.macro_mode))
    ].copy()
    if scoped.empty:
        return pd.DataFrame()

    score_col = "hybrid_score" if "hybrid_score" in scoped.columns else "consensus_score"
    scoped = scoped.sort_values(["select_date", score_col], ascending=[True, False])
    scoped = scoped.groupby("select_date", group_keys=False).head(rule.daily_top_n)

    path_cols = [
        "sample",
        "select_date",
        "buy_date",
        "ts_code",
        "first1_low_pct",
        "first1_close_min_pct",
        "first2_low_pct",
        "first2_close_min_pct",
        "first4_low_pct",
        "first4_close_min_pct",
        "first3_low_pct",
        "day5_close_pct",
    ]
    stage3_paths = paths[paths["sample"].eq("stage3_candidates")][path_cols]
    scoped = scoped.merge(
        stage3_paths,
        on=["select_date", "ts_code"],
        how="inner",
        suffixes=("", "_path"),
    )
    if scoped.empty:
        return pd.DataFrame()
    if rule.require_no_break:
        preentry_col = "first2_low_pct" if rule.expansion_rule == "wait_T3_open" else "first1_low_pct"
        scoped = scoped[pd.to_numeric(scoped[preentry_col], errors="coerce") > -2.0]
    if scoped.empty:
        return pd.DataFrame()

    rule_rows = rule_events[
        rule_events["sample"].eq("stage3_candidates")
        & rule_events["rule"].eq(rule.expansion_rule)
    ].copy()
    scoped = scoped.merge(
        rule_rows,
        on=["sample", "select_date", "buy_date", "ts_code"],
        how="inner",
        suffixes=("", "_rule"),
    )
    if scoped.empty:
        return pd.DataFrame()

    scoped["layer"] = f"expansion_{rule.expansion_rule}"
    scoped["ret"] = pd.to_numeric(scoped["ret_5d_from_entry"], errors="coerce")
    scoped["year"] = scoped["entry_date"].map(_year_bucket)
    return scoped


def _base_stage3_candidates(paths: pd.DataFrame) -> pd.DataFrame:
    stage3 = pd.read_csv(STAGE3_PATH)
    stage3["select_date"] = stage3["select_date"].map(_date)
    stage3["ts_code"] = stage3["ts_code"].astype(str)
    numeric_cols = [
        "n_versions",
        "avg_rank",
        "best_rank",
        "factor_pattern",
        "limit_down_count",
        "hybrid_score",
        "consensus_score",
        "recent_factor_score",
    ]
    for col in numeric_cols:
        if col in stage3.columns:
            stage3[col] = pd.to_numeric(stage3[col], errors="coerce")

    scoped = stage3[
        (stage3["n_versions"] >= 3)
        & (stage3["avg_rank"] <= 3.0)
        & (stage3["best_rank"] <= 2.0)
        & (stage3["factor_pattern"] >= 60.0)
        & (stage3["limit_down_count"] <= 8.0)
        & (stage3["macro_mode"].astype(str).eq("cautious"))
    ].copy()
    if scoped.empty:
        return scoped
    score_col = "hybrid_score" if "hybrid_score" in scoped.columns else "consensus_score"
    scoped = scoped.sort_values(["select_date", score_col, "ts_code"], ascending=[True, False, True])
    scoped = scoped.groupby("select_date", group_keys=False).head(1)
    path_cols = [
        "sample",
        "select_date",
        "buy_date",
        "ts_code",
        "first1_low_pct",
        "first2_low_pct",
        "first4_low_pct",
        "first4_close_min_pct",
    ]
    stage3_paths = paths[paths["sample"].eq("stage3_candidates")][path_cols]
    return scoped.merge(stage3_paths, on=["select_date", "ts_code"], how="inner")


def _choose_dynamic_entry(row: pd.Series) -> str | None:
    """按入场前已知信息给扩容票分配 T1/T3/T5。"""
    best_rank = float(row.get("best_rank", 99) or 99)
    avg_rank = float(row.get("avg_rank", 99) or 99)
    pattern = float(row.get("factor_pattern", 0) or 0)
    limit_down = float(row.get("limit_down_count", 99) or 99)
    first2_low = float(row.get("first2_low_pct", -99) or -99)
    first4_low = float(row.get("first4_low_pct", -99) or -99)
    first4_close = float(row.get("first4_close_min_pct", -99) or -99)

    if best_rank <= 1.0 and avg_rank <= 1.5 and pattern >= 70.0 and limit_down <= 4.0:
        return "direct_T1_open"
    if first2_low > -2.0 and pattern >= 62.0:
        return "wait_T3_open"
    if first4_low > -3.0 and first4_close > -2.5 and pattern >= 60.0:
        return "wait_T5_open"
    return None


def _dynamic_expansion_candidates(paths: pd.DataFrame, rule_events: pd.DataFrame) -> pd.DataFrame:
    scoped = _base_stage3_candidates(paths)
    if scoped.empty:
        return pd.DataFrame()
    scoped = scoped.copy()
    scoped["dynamic_entry_rule"] = scoped.apply(_choose_dynamic_entry, axis=1)
    scoped = scoped[scoped["dynamic_entry_rule"].notna()]
    if scoped.empty:
        return pd.DataFrame()

    frames = []
    for entry_rule, group in scoped.groupby("dynamic_entry_rule"):
        rule_rows = rule_events[
            rule_events["sample"].eq("stage3_candidates")
            & rule_events["rule"].eq(entry_rule)
        ].copy()
        merged = group.merge(
            rule_rows,
            on=["sample", "select_date", "buy_date", "ts_code"],
            how="inner",
            suffixes=("", "_rule"),
        )
        if not merged.empty:
            frames.append(merged)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    out["layer"] = "expansion_dynamic"
    out["ret"] = pd.to_numeric(out["ret_5d_from_entry"], errors="coerce")
    out["year"] = out["entry_date"].map(_year_bucket)
    return out


def _combine_dynamic(rule_events: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    strong = _strong_direct_events(rule_events)
    expansion = _dynamic_expansion_candidates(paths, rule_events)
    if not expansion.empty:
        strong_dates = set(strong["select_date"].astype(str))
        expansion = expansion[~expansion["select_date"].astype(str).isin(strong_dates)]
        combined = pd.concat([strong, expansion], ignore_index=True, sort=False)
    else:
        combined = strong.copy()
    combined["strategy"] = DYNAMIC_STRATEGY_NAME
    combined["win"] = combined["ret"] > 0
    combined["hit3"] = pd.to_numeric(combined["mfe_from_entry"], errors="coerce") >= 3
    return combined.sort_values(["select_date", "layer", "ts_code"]).reset_index(drop=True)


def _combine(rule_events: pd.DataFrame, paths: pd.DataFrame, rule: HybridRule) -> pd.DataFrame:
    strong = _strong_direct_events(rule_events)
    expansion = _expansion_candidates(paths, rule_events, rule)
    if expansion.empty:
        combined = strong.copy()
    else:
        strong_dates = set(strong["select_date"].astype(str))
        expansion = expansion[~expansion["select_date"].astype(str).isin(strong_dates)]
        combined = pd.concat([strong, expansion], ignore_index=True, sort=False)
    combined["strategy"] = rule.name
    combined["win"] = combined["ret"] > 0
    combined["hit3"] = pd.to_numeric(combined["mfe_from_entry"], errors="coerce") >= 3
    return combined.sort_values(["select_date", "layer", "ts_code"]).reset_index(drop=True)


def _metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "total_ret": 0.0,
            "avg_ret": 0.0,
            "hit3_rate": 0.0,
            "avg_mae": 0.0,
            "positive_years": 0,
            "loss_years": 0,
        }
    yearly = df.groupby("year")["ret"].sum()
    return {
        "trades": int(len(df)),
        "win_rate": float(df["win"].mean() * 100),
        "total_ret": float(df["ret"].sum()),
        "avg_ret": float(df["ret"].mean()),
        "hit3_rate": float(df["hit3"].mean() * 100),
        "avg_mae": float(pd.to_numeric(df["mae_from_entry"], errors="coerce").mean()),
        "positive_years": int((yearly > 0).sum()),
        "loss_years": int((yearly <= 0).sum()),
    }


def _summaries(results: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = []
    yearly_rows = []
    for name, df in results.items():
        row = {"strategy": name, **_metrics(df)}
        summary_rows.append(row)
        for year, g in df.groupby("year"):
            yearly_rows.append({"strategy": name, "year": year, **_metrics(g)})
    summary = pd.DataFrame(summary_rows).sort_values(["total_ret", "win_rate"], ascending=[False, False])
    yearly = pd.DataFrame(yearly_rows).sort_values(["strategy", "year"])
    return summary, yearly


def _write_doc(summary: pd.DataFrame, yearly: pd.DataFrame, output: Path) -> None:
    lines = [
        "# 混合延迟确认实验（2026-07-06）",
        "",
        "## 研究假设",
        "",
        "强信号（v35/v39 Top1）保持 T+1 开盘直接买；只有没有强信号的日期，才允许扩容层候选进入，并测试 T+2/T+3 延迟确认。该实验只研究选股/入场时点，不生成任何自动交易代码。",
        "",
        "## 总览",
        "",
        summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 年度拆分",
        "",
        yearly.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 解读",
        "",
        "- 若 `hybrid_strong_plus_wait_T3` 笔数明显增加但胜率被拉低，说明扩容层还需要质量门，不宜直接补票。",
        "- 若 `no_preentry_break` 版本胜率更高但笔数过少，说明入场前不破位可以当作确认因子，但不能单独解决交易数。",
        "- 该结果仍属于历史研究，不能直接上线；下一步应放入完整十年回测引擎，复用真实退出规则和年度分段。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    paths, rule_events = _load_base_events()
    strong_only = _strong_direct_events(rule_events)
    strong_only["strategy"] = "strong_direct_only"
    strong_only["win"] = strong_only["ret"] > 0
    strong_only["hit3"] = pd.to_numeric(strong_only["mfe_from_entry"], errors="coerce") >= 3
    results = {"strong_direct_only": strong_only}
    results.update({rule.name: _combine(rule_events, paths, rule) for rule in RULES})
    results[DYNAMIC_STRATEGY_NAME] = _combine_dynamic(rule_events, paths)
    all_events = pd.concat(results.values(), ignore_index=True, sort=False)
    summary, yearly = _summaries(results)

    all_events.to_csv(REPORTS / "hybrid_delayed_confirmation_events_20260706.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(REPORTS / "hybrid_delayed_confirmation_summary_20260706.csv", index=False, encoding="utf-8-sig")
    yearly.to_csv(REPORTS / "hybrid_delayed_confirmation_yearly_20260706.csv", index=False, encoding="utf-8-sig")
    _write_doc(summary, yearly, DOCS / "HYBRID_DELAYED_CONFIRMATION_EXPERIMENT_20260706.md")

    print(summary.to_string(index=False))
    print()
    print(yearly.to_string(index=False))


if __name__ == "__main__":
    main()
