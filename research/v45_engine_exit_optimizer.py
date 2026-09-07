from __future__ import annotations

from itertools import product
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from backtest_v2 import BacktestV2
from entry_timing_bucket_research import build_entry_outcomes, load_daily_subset, load_stage3_samples
from local_data_proxy import LocalDataProxy
from v45_engine_exit_backtest import _group_metrics, _metrics, _to_float
from v45_t1_t5_confirmation_backtest import _strong_baseline


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
CANDIDATE_EXITS = REPORTS / "v45_engine_all_t5_candidate_exits_20260706.csv"


def _year_bucket(date: str) -> str:
    date = str(date)
    if date.startswith("2026"):
        return "2026H1"
    return date[:4]


def _load_t5_candidates() -> pd.DataFrame:
    samples = load_stage3_samples()
    daily = load_daily_subset(samples[["sample", "select_date", "buy_date", "ts_code"]])
    outcomes, _ = build_entry_outcomes(samples, daily)
    t5 = outcomes[outcomes["entry_bucket"].eq("T5")].copy()
    t5["entry_date"] = t5["entry_date"].astype(str)
    t5["ts_code"] = t5["ts_code"].astype(str)
    return t5.reset_index(drop=True)


def build_candidate_engine_exits(force: bool = False) -> pd.DataFrame:
    if CANDIDATE_EXITS.exists() and not force:
        return pd.read_csv(CANDIDATE_EXITS, encoding="utf-8-sig")

    candidates = _load_t5_candidates()
    pro = LocalDataProxy(cache_dir=str(ROOT / "data" / "cache"))
    engine = BacktestV2(
        pro=pro,
        start_date=str(candidates["entry_date"].min()),
        end_date=str(candidates["entry_date"].max()),
        hold_days=5,
        top_n=1,
        use_market_timing=False,
        min_open_ratio=0.0,
    )
    price_cache = {}
    for date in engine.all_trade_dates:
        df = pro.daily(trade_date=date)
        if df is not None and not df.empty:
            price_cache[date] = df

    rows = []
    for _, event in candidates.iterrows():
        buy_date = str(event["entry_date"])
        future_dates = [date for date in engine.all_trade_dates if date >= buy_date]
        result = engine._simulate_trade(
            ts_code=str(event["ts_code"]),
            buy_date=buy_date,
            future_dates=future_dates,
            price_cache=price_cache,
            tech_stop_price=0.0,
            tech_target_price=0.0,
            volatility=3.0,
            tech_low20=0.0,
            select_close=0.0,
            regime_max_hold=5,
            track_type="candidate_T5",
            signal_row=event,
        )
        if result is None:
            continue
        for column in [
            "sample",
            "select_date",
            "ts_code",
            "name",
            "industry",
            "n_versions",
            "best_rank",
            "avg_rank",
            "factor_pattern",
            "factor_inflow",
            "factor_sector",
            "sector_ma10_ratio",
            "limit_up_count",
            "limit_down_count",
            "market_style",
            "macro_mode",
            "regime",
            "operation_mode",
            "hybrid_score",
            "consensus_score",
            "pre_T5_low_pct",
            "pre_T5_close_min_pct",
        ]:
            if column in event:
                result[column] = event.get(column)
        result["entry_date"] = buy_date
        result["entry_rule"] = "expansion_T5"
        result["ret"] = _to_float(pd.Series(result), "profit_after_fee", _to_float(pd.Series(result), "profit_pct", 0.0))
        result["win"] = result["ret"] > 0
        result["year"] = _year_bucket(str(result.get("buy_date", buy_date)))
        rows.append(result)

    out = pd.DataFrame(rows)
    out.to_csv(CANDIDATE_EXITS, index=False, encoding="utf-8-sig")
    return out


def _select_by_rule(candidates: pd.DataFrame, rule: dict) -> pd.DataFrame:
    work = candidates.copy()
    for col in ["best_rank", "avg_rank", "factor_pattern", "limit_down_count", "pre_T5_low_pct", "pre_T5_close_min_pct", "hybrid_score", "consensus_score"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work[
        (work["best_rank"] <= rule["best_rank"])
        & (work["avg_rank"] <= rule["avg_rank"])
        & (work["factor_pattern"] >= rule["pattern"])
        & (work["limit_down_count"] <= rule["limit_down"])
        & (work["pre_T5_low_pct"] > rule["pre_low"])
        & (work["pre_T5_close_min_pct"] > rule["pre_close"])
    ].copy()
    if "macro_mode" in work.columns and rule["macro_mode"] is not None:
        work = work[work["macro_mode"].astype(str).eq(rule["macro_mode"])]
    if "market_style" in work.columns and rule["market_style"] is not None:
        work = work[work["market_style"].astype(str).eq(rule["market_style"])]
    if work.empty:
        return work
    score_col = "hybrid_score" if "hybrid_score" in work.columns else "consensus_score"
    return (
        work.sort_values(["select_date", score_col, "ts_code"], ascending=[True, False, True])
        .groupby("select_date", group_keys=False)
        .head(1)
        .reset_index(drop=True)
    )


def search_engine_rules(candidates: pd.DataFrame, strong: pd.DataFrame) -> pd.DataFrame:
    strong_dates = set(strong["select_date"].astype(str))
    candidates = candidates[~candidates["select_date"].astype(str).isin(strong_dates)].copy()
    rows = []
    grids = {
        "best_rank": [1.0, 1.5, 2.0],
        "avg_rank": [1.5, 2.0, 2.5],
        "pattern": [50.0, 55.0, 60.0],
        "limit_down": [4.0, 8.0, 12.0],
        "pre_low": [-0.5, -1.0, -1.5, -2.0],
        "pre_close": [-0.5, -1.0, -1.5, -2.0],
        "macro_mode": [None, "active", "cautious"],
        "market_style": [None, "momentum", "sideways", "weak_momentum"],
    }
    keys = list(grids)
    for values in product(*(grids[key] for key in keys)):
        rule = dict(zip(keys, values))
        expansion = _select_by_rule(candidates, rule)
        if not (20 <= len(expansion) <= 100):
            continue
        combined = pd.concat([strong, expansion], ignore_index=True, sort=False)
        combined["ret"] = pd.to_numeric(combined["ret"], errors="coerce").fillna(0.0)
        combined["win"] = combined["ret"] > 0
        metrics = _metrics(combined)
        expansion_metrics = _metrics(expansion)
        if metrics["trades"] < 45:
            continue
        score = (
            metrics["win_rate"] * 1.2
            + min(metrics["total_ret"], 260) * 0.12
            + min(metrics["trades"], 120) * 0.15
            - metrics["loss_years"] * 8.0
            - abs(min(metrics["worst_year"], 0.0)) * 1.5
        )
        row = {
            **rule,
            "trades": metrics["trades"],
            "win_rate": metrics["win_rate"],
            "total_ret": metrics["total_ret"],
            "avg_ret": metrics["avg_ret"],
            "positive_years": metrics["positive_years"],
            "loss_years": metrics["loss_years"],
            "worst_year": metrics["worst_year"],
            "expansion_trades": expansion_metrics["trades"],
            "expansion_win_rate": expansion_metrics["win_rate"],
            "expansion_total_ret": expansion_metrics["total_ret"],
            "score": score,
        }
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["score", "win_rate", "total_ret"], ascending=[False, False, False]).reset_index(drop=True)


def _strong_engine_trades() -> pd.DataFrame:
    path = REPORTS / "v45_engine_exit_trades_20260706.csv"
    if path.exists():
        trades = pd.read_csv(path, encoding="utf-8-sig")
        strong = trades[trades["entry_rule"].eq("strong_T1")].copy()
        if not strong.empty:
            return strong
    # 兜底：强信号样本级收益，仅用于搜索前置失败时避免崩溃。
    strong = _strong_baseline().copy()
    strong["ret"] = pd.to_numeric(strong["ret"], errors="coerce").fillna(0.0)
    strong["win"] = strong["ret"] > 0
    return strong


def _write_doc(result: pd.DataFrame, output: Path) -> None:
    lines = [
        "# v45 真实退出规则优化搜索（2026-07-06）",
        "",
        "## 口径",
        "",
        "- 先对所有 T5 候选复用 `BacktestV2._simulate_trade` 生成真实退出收益。",
        "- 搜索只使用选股日已知因子与 T5 入场前已发生路径。",
        "- 每个选股日最多保留 1 只扩容票，并跳过已有强信号日期。",
        "",
        "## Top30",
        "",
        result.head(30).to_markdown(index=False, floatfmt=".2f") if not result.empty else "无候选",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    candidates = build_candidate_engine_exits()
    strong = _strong_engine_trades()
    result = search_engine_rules(candidates, strong)
    result.to_csv(REPORTS / "v45_engine_exit_rule_search_20260706.csv", index=False, encoding="utf-8-sig")
    _write_doc(result, DOCS / "V45_ENGINE_EXIT_RULE_SEARCH_20260706.md")
    print(result.head(40).to_string(index=False) if not result.empty else "no candidates")


if __name__ == "__main__":
    main()
