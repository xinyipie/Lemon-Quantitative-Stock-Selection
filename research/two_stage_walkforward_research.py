from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "reports" / "research" / "all_market_multi_engine_nofuture_trades_20260807.csv"
DEFAULT_OUTPUT = ROOT / "reports" / "research" / "two_stage_walkforward_20260807.md"

RAW_FEATURES = [
    "pct_chg",
    "ret_5",
    "ret_10",
    "ret_20",
    "ret_60",
    "drawdown_20",
    "rsi_14",
    "volatility_20",
    "turnover_rate",
    "volume_ratio",
    "industry_rs_20",
    "entry_gap_pct",
]
FEATURE_COLUMNS = [f"rank_{name}" for name in RAW_FEATURES] + [
    "engine_pullback",
    "engine_breakout",
    "engine_reversal",
] + [
    f"rank_{feature}_x_{engine}"
    for feature in RAW_FEATURES
    for engine in ("pullback", "breakout", "reversal")
]
MARKET_FEATURES = [
    "candidate_count",
    "reversal_share",
    "pullback_share",
    "breakout_share",
    "median_ret_5",
    "median_ret_20",
    "median_rsi_14",
    "median_pct_chg",
    "median_volume_ratio",
    "regime_bull_trend",
    "regime_bull_pullback",
    "regime_bear_bounce",
    "regime_bear_trend",
    "advance_share",
    "strong_up_share",
    "strong_down_share",
    "limit_up_count",
    "limit_down_count",
    "median_market_pct",
    "csi_pct_chg",
    "csi_ret_5",
    "csi_ret_20",
    "csi_ma20_gap",
    "csi_drawdown_20",
    "csi_volatility_20",
    "amount_ratio_5",
]


@dataclass(frozen=True)
class RidgeModel:
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray


def add_cross_sectional_features(frame: pd.DataFrame, columns: list[str] = RAW_FEATURES) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        values = pd.to_numeric(result.get(column), errors="coerce")
        result[f"rank_{column}"] = values.groupby(result["trade_date"]).rank(pct=True, method="average")
    engine = result.get("engine", pd.Series("", index=result.index)).astype(str)
    for name in ("pullback", "breakout", "reversal"):
        result[f"engine_{name}"] = engine.eq(name).astype(float)
        for column in columns:
            result[f"rank_{column}_x_{name}"] = result[f"rank_{column}"] * result[f"engine_{name}"]
    return result


def _matrix(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    return frame.reindex(columns=columns).apply(pd.to_numeric, errors="coerce").fillna(0.5).to_numpy(float)


def fit_ridge(x: np.ndarray, y: np.ndarray, ridge: float) -> RidgeModel:
    mean = np.nanmean(x, axis=0)
    scale = np.nanstd(x, axis=0)
    scale = np.where(scale < 1e-8, 1.0, scale)
    z = (np.nan_to_num(x, nan=mean) - mean) / scale
    design = np.column_stack([np.ones(len(z)), z])
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    coef = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return RidgeModel(mean=mean, scale=scale, coef=coef)


def predict_ridge(x: np.ndarray, model: RidgeModel) -> np.ndarray:
    z = (np.nan_to_num(x, nan=model.mean) - model.mean) / model.scale
    return np.column_stack([np.ones(len(z)), z]) @ model.coef


def make_market_features(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    engine = work["engine"].astype(str)
    work["is_reversal"] = engine.eq("reversal").astype(float)
    work["is_pullback"] = engine.eq("pullback").astype(float)
    work["is_breakout"] = engine.eq("breakout").astype(float)
    grouped = work.groupby("trade_date", as_index=False).agg(
        candidate_count=("ts_code", "size"),
        reversal_share=("is_reversal", "mean"),
        pullback_share=("is_pullback", "mean"),
        breakout_share=("is_breakout", "mean"),
        median_ret_5=("ret_5", "median"),
        median_ret_20=("ret_20", "median"),
        median_rsi_14=("rsi_14", "median"),
        median_pct_chg=("pct_chg", "median"),
        median_volume_ratio=("volume_ratio", "median"),
        regime=("regime", "first"),
    )
    regime = grouped["regime"].astype(str)
    for value, suffix in (
        ("BULL_TREND", "bull_trend"),
        ("BULL_PULLBACK", "bull_pullback"),
        ("BEAR_BOUNCE", "bear_bounce"),
        ("BEAR_TREND", "bear_trend"),
    ):
        grouped[f"regime_{suffix}"] = regime.eq(value).astype(float)
    return grouped


def finalize_broad_market_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.sort_values("trade_date").copy()
    close = pd.to_numeric(result["csi_close"], errors="coerce")
    amount = pd.to_numeric(result["total_amount"], errors="coerce")
    result["csi_ret_5"] = close.pct_change(5, fill_method=None) * 100
    result["csi_ret_20"] = close.pct_change(20, fill_method=None) * 100
    result["csi_ma20_gap"] = (close / close.rolling(20, min_periods=5).mean() - 1) * 100
    result["csi_drawdown_20"] = (close / close.rolling(20, min_periods=5).max() - 1) * 100
    result["csi_volatility_20"] = pd.to_numeric(result["csi_pct_chg"], errors="coerce").rolling(20, min_periods=5).std()
    result["amount_ratio_5"] = amount / amount.rolling(5, min_periods=3).mean()
    return result


def load_broad_market_features(cache_dir: Path, dates: set[str]) -> pd.DataFrame:
    rows: list[dict] = []
    daily_dir = cache_dir / "daily"
    index_dir = cache_dir / "index_daily"
    for date in sorted(dates):
        daily_path = daily_dir / f"{date}.parquet"
        index_path = index_dir / f"{date}.parquet"
        if not daily_path.exists() or not index_path.exists():
            continue
        try:
            daily = pd.read_parquet(daily_path, columns=["pct_chg", "amount"])
            index = pd.read_parquet(index_path, columns=["ts_code", "close", "pct_chg"])
        except Exception:
            continue
        pct = pd.to_numeric(daily["pct_chg"], errors="coerce").dropna()
        csi = index[index["ts_code"].astype(str).eq("000300.SH")]
        if pct.empty or csi.empty:
            continue
        rows.append(
            {
                "trade_date": date,
                "advance_share": float((pct > 0).mean()),
                "strong_up_share": float((pct >= 3).mean()),
                "strong_down_share": float((pct <= -3).mean()),
                "limit_up_count": int((pct >= 9.5).sum()),
                "limit_down_count": int((pct <= -9.5).sum()),
                "median_market_pct": float(pct.median()),
                "total_amount": float(pd.to_numeric(daily["amount"], errors="coerce").sum()),
                "csi_close": float(csi.iloc[0]["close"]),
                "csi_pct_chg": float(csi.iloc[0]["pct_chg"]),
            }
        )
    return finalize_broad_market_features(pd.DataFrame(rows)) if rows else pd.DataFrame()


def select_by_gate(trades: pd.DataFrame, threshold: float) -> pd.DataFrame:
    return trades[pd.to_numeric(trades["gate_prediction"], errors="coerce") > threshold].copy()


def _prepare(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    frame["year"] = frame["trade_date"].str[:4].astype(int)
    frame = frame[frame.get("tradeable", True).astype(str).str.lower().isin(["true", "1"])].copy()
    frame = frame.drop_duplicates(["trade_date", "ts_code", "engine"])
    frame = add_cross_sectional_features(frame)
    frame["relative_target"] = pd.to_numeric(frame["ret_5d"], errors="coerce") - frame.groupby("trade_date")["ret_5d"].transform("mean")
    market = make_market_features(frame)
    broad = load_broad_market_features(ROOT / "data" / "cache", set(frame["trade_date"].unique()))
    if not broad.empty:
        market = market.merge(broad, on="trade_date", how="left")
    market["year"] = market["trade_date"].str[:4].astype(int)
    return frame, market


def _topn(frame: pd.DataFrame, topn: int) -> pd.DataFrame:
    return (
        frame.sort_values(["trade_date", "rank_prediction", "ts_code"], ascending=[True, False, True])
        .groupby("trade_date", group_keys=False)
        .head(topn)
        .copy()
    )


def _daily_portfolio(selected: pd.DataFrame, cost: float) -> pd.DataFrame:
    daily = selected.groupby("trade_date", as_index=False).agg(gross_ret=("ret_5d", "mean"), trades=("ts_code", "size"))
    daily["net_ret"] = daily["gross_ret"] - cost
    daily["year"] = daily["trade_date"].str[:4].astype(int)
    return daily


def walk_forward(
    frame: pd.DataFrame,
    market: pd.DataFrame,
    *,
    topn: int,
    rank_ridge: float,
    gate_ridge: float,
    gate_window_years: int,
    gate_quantile: float,
    cost: float,
    regime_mode: str = "all",
    target_clip: float = 0.0,
    target_mode: str = "raw",
    loss_penalty: float = 1.0,
    rank_window_years: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_trades: list[pd.DataFrame] = []
    all_days: list[pd.DataFrame] = []
    # 单一候选族会产生大量全零交互列，剔除它们不改变模型含义并提升数值稳定性。
    model_features = [
        column
        for column in FEATURE_COLUMNS
        if column in frame.columns and pd.to_numeric(frame[column], errors="coerce").fillna(0).abs().sum() > 0
    ]
    # 2018 年只生成横截面样本外组合，作为择时层校准种子；正式策略收益从 2019 年开始。
    for test_year in range(2018, 2027):
        rank_train = frame[(frame["year"] < test_year) & frame["relative_target"].notna()]
        if rank_window_years > 0:
            rank_train = rank_train[
                rank_train["year"] >= test_year - rank_window_years
            ].copy()
        rank_test = frame[frame["year"].eq(test_year)].copy()
        if rank_train.empty or rank_test.empty:
            continue
        if target_mode == "loss_averse":
            raw_target = pd.to_numeric(rank_train["ret_5d"], errors="coerce")
            utility = raw_target - loss_penalty * (-raw_target.clip(upper=0))
            rank_target = utility - utility.groupby(rank_train["trade_date"]).transform("mean")
        elif target_mode == "binary":
            binary = (pd.to_numeric(rank_train["ret_5d"], errors="coerce") > 0).astype(float)
            rank_target = binary - binary.groupby(rank_train["trade_date"]).transform("mean")
        elif target_clip > 0:
            clipped = pd.to_numeric(rank_train["ret_5d"], errors="coerce").clip(-target_clip, target_clip)
            rank_target = clipped - clipped.groupby(rank_train["trade_date"]).transform("mean")
        else:
            rank_target = rank_train["relative_target"]
        rank_model = fit_ridge(_matrix(rank_train, model_features), rank_target.to_numpy(float), rank_ridge)
        rank_test["rank_prediction"] = predict_ridge(_matrix(rank_test, model_features), rank_model)
        if regime_mode == "risk_on":
            rank_test = rank_test[~rank_test["regime"].astype(str).eq("BEAR_TREND")].copy()
        elif regime_mode == "bull_only":
            rank_test = rank_test[rank_test["regime"].astype(str).isin(["BULL_TREND", "BULL_PULLBACK"])].copy()
        test_top = _topn(rank_test, topn)

        # 择时层只使用此前年度逐年样本外的组合结果，避免用拟合内收益训练开关。
        prior_days = pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame()
        if not prior_days.empty and gate_window_years > 0:
            prior_days = prior_days[prior_days["year"] >= test_year - gate_window_years].copy()
        test_market = market[market["year"].eq(test_year)].copy()
        emit_trades = not prior_days.empty
        if prior_days.empty:
            test_market["gate_prediction"] = 1.0
            threshold = -np.inf
        else:
            gate_train = prior_days.merge(market.drop(columns="year"), on="trade_date", how="left")
            gate_target = pd.to_numeric(gate_train["net_ret"], errors="coerce")
            # 数据末端没有完整持有期标签，必须先剔除，否则会令下一年度模型整体变为 NaN。
            valid_gate_target = gate_target.notna() & np.isfinite(gate_target)
            gate_train = gate_train.loc[valid_gate_target].copy()
            gate_target = gate_target.loc[valid_gate_target].copy()
            if target_mode == "loss_averse":
                gate_target = gate_target - loss_penalty * (-gate_target.clip(upper=0))
            elif target_mode == "binary":
                gate_target = (gate_target > 0).astype(float)
            elif target_clip > 0:
                gate_target = gate_target.clip(-target_clip, target_clip)
            gate_model = fit_ridge(_matrix(gate_train, MARKET_FEATURES), gate_target.to_numpy(float), gate_ridge)
            test_market["gate_prediction"] = predict_ridge(_matrix(test_market, MARKET_FEATURES), gate_model)
            train_prediction = predict_ridge(_matrix(gate_train, MARKET_FEATURES), gate_model)
            threshold = float(np.quantile(train_prediction, gate_quantile))
        test_top = test_top.merge(test_market[["trade_date", "gate_prediction"]], on="trade_date", how="left")
        kept = select_by_gate(test_top, threshold)
        kept["net_ret"] = pd.to_numeric(kept["ret_5d"], errors="coerce") - cost
        kept["test_year"] = test_year
        if emit_trades:
            all_trades.append(kept)

        # 日级结果保留所有预测日，供下一年度训练择时层。
        daily = _daily_portfolio(test_top, cost)
        daily["gate_prediction"] = test_market.set_index("trade_date")["gate_prediction"].reindex(daily["trade_date"]).to_numpy()
        all_days.append(daily)
    return (
        pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame(),
        pd.concat(all_days, ignore_index=True) if all_days else pd.DataFrame(),
    )


def _metrics(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {"trades": 0, "avg_net": np.nan, "win_rate": np.nan, "profit_factor": np.nan, "positive_years": 0, "years": 0}
    values = pd.to_numeric(frame["net_ret"], errors="coerce").dropna()
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    yearly = frame.assign(year=frame["trade_date"].astype(str).str[:4]).groupby("year")["net_ret"].mean()
    return {
        "trades": int(len(values)),
        "avg_net": float(values.mean()),
        "win_rate": float((values > 0).mean()),
        "profit_factor": float(gains / losses) if losses > 0 else np.inf,
        "positive_years": int((yearly > 0).sum()),
        "years": int(len(yearly)),
    }


def _period(frame: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    year = frame["trade_date"].astype(str).str[:4].astype(int)
    return frame[year.between(start, end)]


def _bootstrap_probability(days: pd.DataFrame, block: int = 20, repetitions: int = 5000, seed: int = 20260807) -> tuple[float, float, float]:
    values = days.sort_values("trade_date")["net_ret"].to_numpy(float)
    if len(values) < block:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    starts = np.arange(0, len(values) - block + 1)
    means = []
    blocks_needed = int(np.ceil(len(values) / block))
    for _ in range(repetitions):
        sampled = np.concatenate([values[s : s + block] for s in rng.choice(starts, blocks_needed, replace=True)])[: len(values)]
        means.append(float(sampled.mean()))
    array = np.asarray(means)
    return float(np.quantile(array, 0.025)), float(np.quantile(array, 0.975)), float((array <= 0).mean())


def run(input_path: Path, output: Path) -> None:
    frame, market = _prepare(input_path)
    rows: list[dict] = []
    trade_sets: dict[str, pd.DataFrame] = {}
    day_sets: dict[str, pd.DataFrame] = {}
    # 网格只保留具有明确扰动意义的相邻组合，避免对同一历史样本做无效穷举。
    for topn in (2, 3, 5):
        for rank_ridge in (100.0,):
            for gate_ridge in (10.0, 100.0):
                for gate_window_years in (2, 3, 99):
                    for gate_quantile in (0.5, 0.65, 0.8):
                        for regime_mode in ("all", "risk_on", "bull_only"):
                            cost = 0.25
                            name = f"top{topn}_rr{rank_ridge:g}_gr{gate_ridge:g}_gw{gate_window_years}_q{gate_quantile:.2f}_m{regime_mode}_c{cost:.2f}"
                            trades, days = walk_forward(
                                frame,
                                market,
                                topn=topn,
                                rank_ridge=rank_ridge,
                                gate_ridge=gate_ridge,
                                gate_window_years=gate_window_years,
                                gate_quantile=gate_quantile,
                                cost=cost,
                                regime_mode=regime_mode,
                            )
                            train = _metrics(_period(trades, 2019, 2021))
                            validation = _metrics(_period(trades, 2022, 2024))
                            recent = _metrics(_period(trades, 2025, 2026))
                            rows.append({"name": name, **{f"train_{k}": v for k, v in train.items()}, **{f"validation_{k}": v for k, v in validation.items()}, **{f"recent_{k}": v for k, v in recent.items()}})
                            trade_sets[name] = trades
                            day_sets[name] = days
    search = pd.DataFrame(rows)
    # 参数只允许在训练期裁决；0.25% 是基准成本，0.15/0.35 仅用于压力测试。
    base_search = search.copy()
    eligible = base_search[
        (base_search["train_avg_net"] > 0)
        & (base_search["train_profit_factor"] > 1.05)
        & (base_search["train_positive_years"] >= 2)
    ].copy()
    if eligible.empty:
        chosen = base_search.sort_values(["train_positive_years", "train_profit_factor", "train_avg_net"], ascending=False).iloc[0]
    else:
        chosen = eligible.sort_values(["train_positive_years", "train_profit_factor", "train_avg_net"], ascending=False).iloc[0]
    name = str(chosen["name"])
    trades = trade_sets[name]
    kept_days = trades.groupby("trade_date", as_index=False)["net_ret"].mean()
    validation_days = _period(kept_days, 2022, 2024)
    ci_low, ci_high, p_nonpositive = _bootstrap_probability(validation_days)
    yearly = trades.assign(year=trades["trade_date"].str[:4]).groupby("year").apply(lambda g: pd.Series(_metrics(g)), include_groups=False).reset_index()
    parts = name.split("_")
    topn_value = int(parts[0].replace("top", ""))
    quantile_value = parts[4]
    neighbor_topn = search[
        search["name"].isin(
            [
                name.replace(f"top{topn_value}", f"top{neighbor}", 1)
                for neighbor in (2, 3, 5)
                if neighbor != topn_value
            ]
        )
    ]
    neighbor_quantile = search[
        search["name"].isin(
            [
                name.replace(quantile_value, replacement, 1)
                for replacement in ("q0.50", "q0.65", "q0.80")
                if replacement != quantile_value
            ]
        )
    ]
    cost_stress_trades = trades.copy()
    cost_stress_trades["net_ret"] = pd.to_numeric(cost_stress_trades["ret_5d"], errors="coerce") - 0.35
    cost_stress_metrics = _metrics(_period(cost_stress_trades, 2022, 2024))
    cost_stress_pass = bool(
        cost_stress_metrics["avg_net"] > 0
        and cost_stress_metrics["profit_factor"] > 1.05
        and cost_stress_metrics["positive_years"] == 3
    )
    neighbor_pass = bool(
        (
            (neighbor_topn["validation_avg_net"] > 0)
            & (neighbor_topn["validation_profit_factor"] > 1.05)
            & (neighbor_topn["validation_positive_years"] == 3)
        ).any()
        and (
            (neighbor_quantile["validation_avg_net"] > 0)
            & (neighbor_quantile["validation_profit_factor"] > 1.05)
            & (neighbor_quantile["validation_positive_years"] == 3)
        ).any()
    )
    strict_pass = bool(
        chosen["validation_avg_net"] > 0
        and chosen["validation_profit_factor"] > 1.10
        and chosen["validation_positive_years"] == chosen["validation_years"] == 3
        and chosen["recent_avg_net"] > 0
        and chosen["recent_positive_years"] >= 1
        and cost_stress_pass
        and neighbor_pass
        and p_nonpositive < 0.10
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    search.sort_values(["validation_positive_years", "validation_profit_factor", "validation_avg_net"], ascending=False).to_csv(output.with_name(output.stem + "_search.csv"), index=False, encoding="utf-8-sig")
    trades.to_csv(output.with_name(output.stem + "_trades.csv"), index=False, encoding="utf-8-sig")
    lines = [
        "# 双层逐年走步短线研究",
        "",
        "## 结论",
        "",
        f"- 严格验收：{'通过' if strict_pass else '不通过'}。",
        f"- 选中参数：`{name}`。参数选择完全由 2019-2021 训练期 OOS 指标决定，验证期不参与排名。",
        f"- 成本压力通过：{'是' if cost_stress_pass else '否'}；相邻 TopN 与门槛扰动通过：{'是' if neighbor_pass else '否'}。",
        f"- 验证期分块 bootstrap 95% 区间：{ci_low:+.4f}% 至 {ci_high:+.4f}%，均值不大于 0 的概率 {p_nonpositive:.2%}。",
        "- 未通过时不得接入正式策略，也不得把该结果描述为已找到稳定策略。",
        "",
        "## 分期指标",
        "",
        pd.DataFrame([
            {"period": "训练OOS 2019-2021", **_metrics(_period(trades, 2019, 2021))},
            {"period": "独立验证 2022-2024", **_metrics(_period(trades, 2022, 2024))},
            {"period": "近期观察 2025-2026", **_metrics(_period(trades, 2025, 2026))},
        ]).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 逐年指标",
        "",
        yearly.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 搜索前 20",
        "",
        search.sort_values(["validation_positive_years", "validation_profit_factor", "validation_avg_net"], ascending=False).head(20).to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 方法约束",
        "",
        "- 每个测试年度的横截面模型只读取此前年度。",
        "- 择时模型只读取此前年度已经产生的样本外日级组合结果。",
        "- 所有结果按 T+1 开盘后的 5 日收益计量并扣除交易成本。",
        "- 本研究没有修改正式策略。",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"chosen={name}")
    print(f"strict_pass={strict_pass}")
    print(pd.DataFrame([chosen]).to_string(index=False))
    print(yearly.to_string(index=False))
    print(f"bootstrap_ci=({ci_low:.4f},{ci_high:.4f}) p_nonpositive={p_nonpositive:.4f}")
    print(f"wrote={output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="双层逐年走步短线策略研究")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
