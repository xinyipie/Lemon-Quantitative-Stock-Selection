"""复现2026-04-22光迅科技归档中的强动量量化层。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import all_market_multi_engine_research as market_research
from research.flow_breadth_factor_research import _year_flow_features, add_industry_breadth
from research.regime_conditioned_opportunity_research import SPLITS, _split_label, normalize_regime


VARIANTS = [
    {"variant": "archive_strict", "label": "归档源码严格版", "min_volume_ratio": 1.5},
    {"variant": "archive_report_reconciled", "label": "原报告量比校准版", "min_volume_ratio": 1.2},
]

SCORE_WEIGHTS = {
    "mf_3_ratio": 0.20,
    "industry_rs_20": 0.20,
    "volume_ratio": 0.15,
    "near_high_strength": 0.10,
    "ret_20": 0.10,
    "industry_amount_accel": 0.10,
    "relative_turnover": 0.05,
    "market_relative_strength": 0.05,
    "amount": 0.05,
}


def archive_momentum_eligibility(panel: pd.DataFrame, min_volume_ratio: float) -> pd.Series:
    """按归档证据构造强动量硬过滤，不使用未来收益。"""
    if panel.empty:
        return pd.Series(False, index=panel.index, dtype=bool)
    regimes = normalize_regime(panel.get("regime", pd.Series("UNKNOWN", index=panel.index)))
    names = panel.get("name", pd.Series("", index=panel.index)).fillna("").astype(str)
    close = pd.to_numeric(panel.get("synthetic_close"), errors="coerce")
    ma20 = pd.to_numeric(panel.get("ma_20"), errors="coerce")
    ma60 = pd.to_numeric(panel.get("ma_60"), errors="coerce")
    eligible = (
        regimes.ne("BEAR_TREND")
        & regimes.ne("UNKNOWN")
        & ~names.str.upper().str.contains("ST|退", regex=True)
        & pd.to_numeric(panel.get("history_count"), errors="coerce").ge(60)
        & pd.to_numeric(panel.get("amount"), errors="coerce").ge(100000)
        & pd.to_numeric(panel.get("pct_chg"), errors="coerce").between(1.0, 7.0, inclusive="both")
        & pd.to_numeric(panel.get("ret_5"), errors="coerce").gt(5.0)
        & pd.to_numeric(panel.get("ret_20"), errors="coerce").gt(25.0)
        & pd.to_numeric(panel.get("drawdown_20"), errors="coerce").le(5.0)
        & pd.to_numeric(panel.get("volume_ratio"), errors="coerce").ge(float(min_volume_ratio))
        & pd.to_numeric(panel.get("industry_rs_20"), errors="coerce").gt(15.0)
        & close.gt(ma20)
        & ma20.gt(ma60)
    )
    if "tradeable" in panel.columns:
        eligible &= panel["tradeable"].fillna(False).astype(bool)
    return eligible.fillna(False).astype(bool)


def _daily_percentile(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.rank(method="average", pct=True).fillna(0.5)


def _score_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    """在同日硬过滤候选内复现归档非AI量化权重。"""
    if candidates.empty:
        return candidates.copy()
    work = candidates.copy()
    turnover = pd.to_numeric(work.get("turnover_rate"), errors="coerce")
    industry_median = work.groupby(["trade_date", "industry"])["turnover_rate"].transform("median")
    work["relative_turnover"] = turnover / pd.to_numeric(industry_median, errors="coerce").replace(0, np.nan)
    market_median = work.groupby("trade_date")["pct_chg"].transform("median")
    work["market_relative_strength"] = pd.to_numeric(work["pct_chg"], errors="coerce") - pd.to_numeric(market_median, errors="coerce")
    work["near_high_strength"] = -pd.to_numeric(work["drawdown_20"], errors="coerce")
    work["archive_score"] = 0.0
    for factor, weight in SCORE_WEIGHTS.items():
        source = work[factor] if factor in work.columns else pd.Series(np.nan, index=work.index)
        percentile = work.assign(_factor=source).groupby("trade_date", group_keys=False)["_factor"].transform(_daily_percentile)
        work[f"factor_{factor}"] = percentile
        work["archive_score"] += percentile * float(weight) * 100.0
    return work


def select_archive_momentum_candidates(panel: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    """运行两个冻结版本并在T日评分后取每日TopN。"""
    if panel.empty:
        return pd.DataFrame()
    selected_frames = []
    for variant in VARIANTS:
        eligible = archive_momentum_eligibility(panel, variant["min_volume_ratio"])
        scored = _score_candidates(panel[eligible].copy())
        if scored.empty:
            continue
        selected = (
            scored.sort_values(
                ["trade_date", "archive_score", "amount", "ts_code"],
                ascending=[True, False, False, True],
                kind="mergesort",
            )
            .groupby("trade_date", group_keys=False)
            .head(int(top_n))
            .copy()
        )
        selected["selection_rank"] = selected.groupby("trade_date").cumcount() + 1
        selected = selected[
            pd.to_numeric(selected.get("entry_open"), errors="coerce").gt(0)
            & pd.to_numeric(selected.get("entry_gap_pct"), errors="coerce").lt(9.5)
        ]
        if selected.empty:
            continue
        selected["variant"] = variant["variant"]
        selected["variant_label"] = variant["label"]
        selected["top_n"] = int(top_n)
        selected_frames.append(selected)
    return pd.concat(selected_frames, ignore_index=True, sort=False) if selected_frames else pd.DataFrame()


def _profit_factor(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(numeric[numeric > 0].sum())
    losses = abs(float(numeric[numeric < 0].sum()))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def summarize(selected: pd.DataFrame, cost_pct: float = 0.30) -> pd.DataFrame:
    """按固定3日持有汇总归档策略，不优化退出。"""
    if selected.empty:
        return pd.DataFrame()
    work = selected.copy()
    work["net_3d_pct"] = pd.to_numeric(work["ret_3d"], errors="coerce") - float(cost_pct)
    rows = []
    keys = ["variant", "variant_label", "top_n", "split"]
    for values, group in work.groupby(keys, sort=False):
        net = group["net_3d_pct"].dropna()
        yearly = group.groupby("year")["net_3d_pct"].mean().dropna()
        rows.append(
            {
                **dict(zip(keys, values)),
                "trades": int(net.size),
                "active_days": int(group.loc[net.index, "trade_date"].astype(str).nunique()) if not net.empty else 0,
                "avg_net_3d_pct": round(float(net.mean()), 4) if not net.empty else np.nan,
                "median_net_3d_pct": round(float(net.median()), 4) if not net.empty else np.nan,
                "win_rate_3d": round(float(net.gt(0).mean()), 4) if not net.empty else np.nan,
                "profit_factor_3d": round(float(_profit_factor(net)), 4) if not net.empty else 0.0,
                "positive_year_ratio": round(float(yearly.gt(0).mean()), 4) if not yearly.empty else 0.0,
                "worst_year_avg_3d_pct": round(float(yearly.min()), 4) if not yearly.empty else np.nan,
                "avg_mfe_8d_pct": round(float(pd.to_numeric(group.get("mfe_8d"), errors="coerce").mean()), 4),
                "avg_mae_8d_pct": round(float(pd.to_numeric(group.get("mae_8d"), errors="coerce").mean()), 4),
            }
        )
    return pd.DataFrame(rows)


def apply_acceptance(metrics: pd.DataFrame) -> pd.DataFrame:
    """把训练稳定性固定到验证行并执行硬验收。"""
    if metrics.empty:
        return metrics.copy()
    train = metrics[metrics["split"].eq("train")][
        ["variant", "top_n", "avg_net_3d_pct", "profit_factor_3d", "positive_year_ratio", "worst_year_avg_3d_pct"]
    ].rename(
        columns={
            "avg_net_3d_pct": "train_avg_net_3d_pct",
            "profit_factor_3d": "train_profit_factor_3d",
            "positive_year_ratio": "train_positive_year_ratio",
            "worst_year_avg_3d_pct": "train_worst_year_avg_3d_pct",
        }
    )
    result = metrics.merge(train, on=["variant", "top_n"], how="left", validate="many_to_one")
    result["research_pass"] = (
        result["split"].eq("validation")
        & pd.to_numeric(result["train_avg_net_3d_pct"], errors="coerce").gt(0.10)
        & pd.to_numeric(result["train_profit_factor_3d"], errors="coerce").gt(1.03)
        & pd.to_numeric(result["train_positive_year_ratio"], errors="coerce").ge(0.50)
        & pd.to_numeric(result["train_worst_year_avg_3d_pct"], errors="coerce").gt(-0.75)
        & pd.to_numeric(result["trades"], errors="coerce").ge(150)
        & pd.to_numeric(result["active_days"], errors="coerce").ge(80)
        & pd.to_numeric(result["avg_net_3d_pct"], errors="coerce").gt(0.30)
        & pd.to_numeric(result["profit_factor_3d"], errors="coerce").gt(1.10)
        & pd.to_numeric(result["positive_year_ratio"], errors="coerce").ge(2 / 3)
        & pd.to_numeric(result["worst_year_avg_3d_pct"], errors="coerce").gt(-0.75)
    )
    return result


def _write_report(result: pd.DataFrame, capture: pd.DataFrame, start: str, end: str) -> str:
    validation = result[result["split"].eq("validation")].sort_values("avg_net_3d_pct", ascending=False)
    passed = validation[validation["research_pass"]]
    lines = [
        "# 光迅科技归档强动量策略复现",
        "",
        f"- 数据范围：{start} 至 {end}",
        "- 两个冻结版本：源码量比>=1.5；原报告校准量比>=1.2。",
        "- T+1开盘买入、固定持有3日、往返成本0.30%、每日Top3。",
        f"- 独立验证通过：{len(passed)} 个版本。",
        "",
        "## 光迅科技捕捉审计",
        "",
    ]
    if capture.empty:
        lines.append("2026-04-22 的 Top3 中未捕捉到光迅科技。")
    else:
        display = ["variant_label", "selection_rank", "archive_score", "entry_open", "ret_3d", "ret_5d", "mfe_8d", "mae_8d"]
        lines.append(capture[[column for column in display if column in capture.columns]].to_markdown(index=False))
    columns = [
        "variant_label", "train_avg_net_3d_pct", "train_profit_factor_3d", "trades", "active_days",
        "avg_net_3d_pct", "median_net_3d_pct", "win_rate_3d", "profit_factor_3d",
        "positive_year_ratio", "worst_year_avg_3d_pct", "avg_mfe_8d_pct", "avg_mae_8d_pct", "research_pass",
    ]
    lines.extend(["", "## 独立验证", "", validation[columns].to_markdown(index=False) if not validation.empty else "无结果。"])
    lines.extend(["", "## 结论", ""])
    if passed.empty:
        lines.append("归档策略能够解释单一成功案例，但未达到跨年份独立验证门槛，不能直接恢复为正式策略。")
    else:
        lines.append("存在通过独立验证的归档复现版本，下一步进入成本、TopN、阈值和尾部依赖压力测试。")
    return "\n".join(lines) + "\n"


def run_research(root: Path, start: str, end: str) -> dict[str, pd.DataFrame | Path]:
    cache_dir = root / "data" / "cache"
    history_start = f"{int(start[:4]) - 1}0101"
    all_dates = market_research._available_dates(cache_dir, history_start, end)
    stock_info = market_research._load_stock_info(cache_dir)
    regimes = market_research._build_regimes(cache_dir, all_dates)
    selected_frames = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        print(f"processing {year}", flush=True)
        panel = market_research.build_year_panel(cache_dir, stock_info, regimes, all_dates, year, start, end)
        if panel.empty:
            continue
        panel["split"] = _split_label(panel["trade_date"])
        panel["year"] = panel["trade_date"].astype(str).str[:4].astype(int)
        target_dates = sorted(panel["trade_date"].astype(str).unique())
        flow = _year_flow_features(cache_dir, all_dates, target_dates)
        panel = panel.merge(flow, on=["ts_code", "trade_date"], how="left")
        panel = add_industry_breadth(panel)
        selected = select_archive_momentum_candidates(panel, top_n=3)
        if not selected.empty:
            selected_frames.append(selected)
    selected_all = pd.concat(selected_frames, ignore_index=True, sort=False) if selected_frames else pd.DataFrame()
    metrics = summarize(selected_all)
    result = apply_acceptance(metrics)
    capture = selected_all[
        selected_all["trade_date"].astype(str).eq("20260422")
        & selected_all["ts_code"].astype(str).eq("002281.SZ")
    ].copy() if not selected_all.empty else pd.DataFrame()

    output_dir = root / "reports" / "research"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = "20260807"
    report_path = output_dir / f"archived_momentum_reconstruction_{stamp}.md"
    metrics_path = output_dir / f"archived_momentum_reconstruction_metrics_{stamp}.csv"
    trades_path = output_dir / f"archived_momentum_reconstruction_trades_{stamp}.csv"
    report_path.write_text(_write_report(result, capture, start, end), encoding="utf-8")
    result.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    compact = [
        "trade_date", "year", "split", "variant", "variant_label", "selection_rank", "ts_code", "name", "industry",
        "archive_score", "regime", "pct_chg", "ret_5", "ret_20", "drawdown_20", "volume_ratio", "turnover_rate",
        "industry_rs_20", "mf_3_ratio", "industry_amount_accel", "amount", "entry_open", "entry_gap_pct",
        "ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d",
    ]
    selected_all[[column for column in compact if column in selected_all.columns]].to_csv(trades_path, index=False, encoding="utf-8-sig")
    return {"result": result, "trades": selected_all, "capture": capture, "report_path": report_path, "trades_path": trades_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="光迅科技归档强动量策略复现")
    parser.add_argument("--start", default=SPLITS["train"][0])
    parser.add_argument("--end", default=SPLITS["observed"][1])
    args = parser.parse_args()
    research = run_research(ROOT, args.start, args.end)
    validation = research["result"][research["result"]["split"].eq("validation")]
    print("\nVALIDATION")
    print(validation.to_string(index=False))
    print("\nGUANGXUN CAPTURE")
    print(research["capture"].to_string(index=False))
    print(f"passed={int(validation['research_pass'].sum())} report={research['report_path']}")


if __name__ == "__main__":
    main()
