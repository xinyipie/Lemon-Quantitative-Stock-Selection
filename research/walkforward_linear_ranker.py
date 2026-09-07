from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


FUTURE_COLUMNS = ("ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d")
NUMERIC_SIGNAL_COLUMNS = (
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
)
ENGINE_COLUMNS = ("member_breakout", "member_pullback", "member_reversal")
REGIME_COLUMNS = ("regime_BEAR_TREND", "regime_BEAR_BOUNCE", "regime_BULL_PULLBACK", "regime_BULL_TREND")
FEATURE_COLUMNS = tuple(f"rank_{name}" for name in NUMERIC_SIGNAL_COLUMNS) + ENGINE_COLUMNS + REGIME_COLUMNS

RIDGE_LAMBDAS = (1.0, 10.0, 100.0)
TOPNS = (1, 3, 5)
ABSTENTION_QUANTILES = (0.70, 0.80, 0.90)
ROUND_TRIP_COST_PCT = 0.25


@dataclass(frozen=True)
class Choice:
    ridge_lambda: float
    topn: int
    quantile: float


def phase_for_date(value: str | int) -> str:
    date = int(str(value).replace("-", "")[:8])
    if date <= 20211231:
        return "train"
    if date <= 20241231:
        return "validation"
    return "recent"


def load_candidates(path: str | Path) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig")
    raw["trade_date"] = raw["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]

    members = pd.crosstab([raw["trade_date"], raw["ts_code"]], raw["engine"]).clip(upper=1)
    members = members.rename(columns={name: f"member_{name}" for name in members.columns}).reset_index()
    base = raw.sort_values(["trade_date", "ts_code", "engine_rank"]).drop_duplicates(["trade_date", "ts_code"])
    base = base.drop(columns=[column for column in base.columns if column.startswith("member_")], errors="ignore")
    base = base.merge(members, on=["trade_date", "ts_code"], how="left")
    for column in ENGINE_COLUMNS:
        if column not in base:
            base[column] = 0.0
        base[column] = pd.to_numeric(base[column], errors="coerce").fillna(0.0)
    return base.reset_index(drop=True)


def add_cross_sectional_features(
    frame: pd.DataFrame,
    numeric_columns: tuple[str, ...] | list[str] = NUMERIC_SIGNAL_COLUMNS,
) -> tuple[pd.DataFrame, list[str]]:
    result = frame.copy()
    columns: list[str] = []
    for source in numeric_columns:
        values = pd.to_numeric(result.get(source, pd.Series(index=result.index, dtype=float)), errors="coerce")
        feature = f"rank_{source}"
        result[feature] = values.groupby(result["trade_date"]).rank(method="average", pct=True).fillna(0.5)
        columns.append(feature)
    regimes = result.get("regime", pd.Series("", index=result.index)).astype(str)
    for feature in REGIME_COLUMNS:
        regime = feature.removeprefix("regime_")
        result[feature] = (regimes == regime).astype(float)
    return result, columns


def prepare_dataset(path: str | Path) -> pd.DataFrame:
    frame = load_candidates(path)
    frame, _ = add_cross_sectional_features(frame)
    for column in FEATURE_COLUMNS + FUTURE_COLUMNS:
        if column not in frame:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["phase"] = frame["trade_date"].map(phase_for_date)
    return frame.dropna(subset=["ret_5d"]).reset_index(drop=True)


def fit_weighted_ridge(
    x: np.ndarray,
    y: np.ndarray,
    dates: pd.Series,
    ridge_lambda: float,
) -> np.ndarray:
    if len(x) == 0:
        raise ValueError("训练集为空")
    day_counts = dates.astype(str).value_counts()
    weights = dates.astype(str).map(lambda value: 1.0 / day_counts[value]).to_numpy(dtype=float)
    weights = weights / weights.mean()
    design = np.column_stack([np.ones(len(x)), np.asarray(x, dtype=float)])
    sqrt_w = np.sqrt(weights)[:, None]
    weighted_x = design * sqrt_w
    weighted_y = np.asarray(y, dtype=float) * sqrt_w[:, 0]
    penalty = np.eye(design.shape[1]) * float(ridge_lambda)
    penalty[0, 0] = 0.0
    return np.linalg.pinv(weighted_x.T @ weighted_x + penalty) @ weighted_x.T @ weighted_y


def predict(frame: pd.DataFrame, beta: np.ndarray) -> np.ndarray:
    x = frame.loc[:, FEATURE_COLUMNS].fillna(0.5).to_numpy(dtype=float)
    return np.column_stack([np.ones(len(x)), x]) @ beta


def fit_model(frame: pd.DataFrame, ridge_lambda: float) -> np.ndarray:
    target = pd.to_numeric(frame["ret_5d"], errors="coerce").clip(-10.0, 10.0).to_numpy(dtype=float)
    x = frame.loc[:, FEATURE_COLUMNS].fillna(0.5).to_numpy(dtype=float)
    return fit_weighted_ridge(x, target, frame["trade_date"], ridge_lambda)


def select_predictions(frame: pd.DataFrame, topn: int, threshold: float) -> pd.DataFrame:
    eligible = frame[pd.to_numeric(frame["prediction"], errors="coerce") >= float(threshold)].copy()
    return (
        eligible.sort_values(["trade_date", "prediction", "ts_code"], ascending=[True, False, True])
        .groupby("trade_date", group_keys=False)
        .head(int(topn))
        .reset_index(drop=True)
    )


def metric_summary(frame: pd.DataFrame, cost_pct: float = ROUND_TRIP_COST_PCT) -> dict:
    if frame.empty:
        return {
            "trades": 0,
            "active_days": 0,
            "win_rate_pct": 0.0,
            "avg_net_pct": 0.0,
            "median_net_pct": 0.0,
            "profit_factor": 0.0,
            "max_cohort_drawdown_pct": 0.0,
            "positive_years": 0,
            "year_count": 0,
            "worst_year_avg_net_pct": 0.0,
        }
    work = frame.copy()
    work["net_return"] = pd.to_numeric(work["ret_5d"], errors="coerce") - float(cost_pct)
    work = work.dropna(subset=["net_return"])
    positive = work.loc[work["net_return"] > 0, "net_return"].sum()
    negative = -work.loc[work["net_return"] < 0, "net_return"].sum()
    daily = work.groupby("trade_date")["net_return"].mean().sort_index()
    curve = daily.cumsum()
    drawdown = curve - curve.cummax()
    yearly = work.assign(year=work["trade_date"].astype(str).str[:4]).groupby("year")["net_return"].mean()
    return {
        "trades": int(len(work)),
        "active_days": int(work["trade_date"].nunique()),
        "win_rate_pct": round(float((work["net_return"] > 0).mean() * 100), 4),
        "avg_net_pct": round(float(work["net_return"].mean()), 4),
        "median_net_pct": round(float(work["net_return"].median()), 4),
        "profit_factor": round(float(positive / negative), 4) if negative > 0 else 99.0,
        "max_cohort_drawdown_pct": round(float(drawdown.min()), 4),
        "positive_years": int((yearly > 0).sum()),
        "year_count": int(len(yearly)),
        "worst_year_avg_net_pct": round(float(yearly.min()), 4),
    }


def expanding_oof(frame: pd.DataFrame, ridge_lambda: float) -> pd.DataFrame:
    pieces = []
    for validation_year in (2019, 2020, 2021):
        train = frame[frame["trade_date"] < f"{validation_year}0101"]
        valid = frame[frame["trade_date"].str.startswith(str(validation_year))].copy()
        if train.empty or valid.empty:
            continue
        beta = fit_model(train, ridge_lambda)
        valid["prediction"] = predict(valid, beta)
        pieces.append(valid)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def _choice_score(metrics: dict) -> float:
    return (
        metrics["avg_net_pct"] * 100
        + (metrics["profit_factor"] - 1.0) * 40
        + metrics["positive_years"] * 8
        + min(metrics["trades"], 500) * 0.01
        + metrics["worst_year_avg_net_pct"] * 30
    )


def choose_on_oof(frame: pd.DataFrame) -> tuple[Choice, pd.DataFrame, pd.DataFrame]:
    rows = []
    selected_by_key: dict[tuple[float, int, float], pd.DataFrame] = {}
    for ridge_lambda in RIDGE_LAMBDAS:
        oof = expanding_oof(frame, ridge_lambda)
        for quantile in ABSTENTION_QUANTILES:
            threshold = float(oof["prediction"].quantile(quantile))
            for topn in TOPNS:
                selected = select_predictions(oof, topn, threshold)
                metrics = metric_summary(selected)
                key = (ridge_lambda, topn, quantile)
                selected_by_key[key] = selected
                rows.append({
                    "ridge_lambda": ridge_lambda,
                    "topn": topn,
                    "quantile": quantile,
                    "threshold": threshold,
                    **metrics,
                    "choice_score": _choice_score(metrics),
                })
    summary = pd.DataFrame(rows).sort_values(
        ["choice_score", "avg_net_pct", "profit_factor", "trades"], ascending=False
    ).reset_index(drop=True)
    best = summary.iloc[0]
    choice = Choice(float(best["ridge_lambda"]), int(best["topn"]), float(best["quantile"]))
    return choice, summary, selected_by_key[(choice.ridge_lambda, choice.topn, choice.quantile)]


def _yearly(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, group in frame.groupby(frame["trade_date"].astype(str).str[:4]):
        rows.append({"year": year, **metric_summary(group)})
    return pd.DataFrame(rows)


def _acceptance(oof_metrics: dict, validation_metrics: dict, stress: pd.DataFrame) -> tuple[bool, list[str]]:
    blockers = []
    if oof_metrics["trades"] < 100 or oof_metrics["avg_net_pct"] <= 0 or oof_metrics["profit_factor"] <= 1:
        blockers.append("训练期外收益或样本门槛未通过")
    if oof_metrics["positive_years"] < 2:
        blockers.append("训练期外正收益年份少于2/3")
    if validation_metrics["trades"] < 150:
        blockers.append("验证期样本少于150")
    if validation_metrics["avg_net_pct"] < 0.15:
        blockers.append("验证期净平均收益低于0.15%")
    if validation_metrics["profit_factor"] < 1.08:
        blockers.append("验证期盈亏比低于1.08")
    if validation_metrics["positive_years"] < 3:
        blockers.append("验证期未实现3/3年度正收益")
    stable = int(((stress["avg_net_pct"] > 0) & (stress["profit_factor"] > 1)).sum())
    if stable < int(np.ceil(len(stress) / 2)):
        blockers.append("参数扰动稳定组合不足一半")
    return not blockers, blockers


def run_research(input_path: str | Path, output: str | Path) -> dict:
    data = prepare_dataset(input_path)
    train = data[data["phase"] == "train"].copy()
    choice, search, oof_selected = choose_on_oof(train)

    final_beta = fit_model(train, choice.ridge_lambda)
    train_prediction = predict(train, final_beta)
    threshold = float(pd.Series(train_prediction).quantile(choice.quantile))

    evaluated = data.copy()
    evaluated["prediction"] = predict(evaluated, final_beta)
    validation_all = evaluated[evaluated["phase"] == "validation"]
    recent_all = evaluated[evaluated["phase"] == "recent"]
    validation = select_predictions(validation_all, choice.topn, threshold)
    recent = select_predictions(recent_all, choice.topn, threshold)

    stress_rows = []
    for ridge_lambda in RIDGE_LAMBDAS:
        beta = fit_model(train, ridge_lambda)
        train_pred = predict(train, beta)
        valid_copy = validation_all.copy()
        valid_copy["prediction"] = predict(valid_copy, beta)
        for topn in TOPNS:
            for quantile in ABSTENTION_QUANTILES:
                stressed_threshold = float(pd.Series(train_pred).quantile(quantile))
                selected = select_predictions(valid_copy, topn, stressed_threshold)
                stress_rows.append({
                    "ridge_lambda": ridge_lambda,
                    "topn": topn,
                    "quantile": quantile,
                    **metric_summary(selected),
                })
    stress = pd.DataFrame(stress_rows)

    oof_metrics = metric_summary(oof_selected)
    validation_metrics = metric_summary(validation)
    recent_metrics = metric_summary(recent)
    passed, blockers = _acceptance(oof_metrics, validation_metrics, stress)

    coefficients = pd.DataFrame(
        {"feature": ("intercept",) + FEATURE_COLUMNS, "coefficient": final_beta}
    ).sort_values("coefficient", key=lambda values: values.abs(), ascending=False)
    case = evaluated[(evaluated["trade_date"] == "20260422") & (evaluated["ts_code"] == "002281.SZ")].copy()
    if not case.empty:
        case["model_rank"] = case["prediction"].rank(method="min", ascending=False)
        case["passes_threshold"] = case["prediction"] >= threshold

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    search.to_csv(output.with_name(output.stem + "_search.csv"), index=False, encoding="utf-8-sig")
    pd.concat([oof_selected.assign(evaluation_phase="train_oof"), validation.assign(evaluation_phase="validation"), recent.assign(evaluation_phase="recent")], ignore_index=True).to_csv(
        output.with_name(output.stem + "_trades.csv"), index=False, encoding="utf-8-sig"
    )
    stress.to_csv(output.with_name(output.stem + "_stress.csv"), index=False, encoding="utf-8-sig")

    lines = [
        "# 全市场短线走样本外线性排序研究",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 固定参数：lambda={choice.ridge_lambda:g}，TopN={choice.topn}，弃权分位={choice.quantile:.2f}",
        f"- 固定执行阈值：{threshold:.6f}",
        f"- 正式验收：{'通过' if passed else '未通过'}",
        f"- 阻断项：{'；'.join(blockers) if blockers else '无'}",
        "",
        "## 三阶段指标",
        "",
        pd.DataFrame([
            {"phase": "train_oof_2019_2021", **oof_metrics},
            {"phase": "validation_2022_2024", **validation_metrics},
            {"phase": "recent_2025_2026H1", **recent_metrics},
        ]).to_markdown(index=False),
        "",
        "## 验证期逐年",
        "",
        _yearly(validation).to_markdown(index=False) if not validation.empty else "无交易",
        "",
        "## 近期观察逐年",
        "",
        _yearly(recent).to_markdown(index=False) if not recent.empty else "无交易",
        "",
        "## 系数绝对值排序",
        "",
        coefficients.to_markdown(index=False, floatfmt=".6f"),
        "",
        "## 参数扰动",
        "",
        stress.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## 光迅科技 2026-04-22",
        "",
        case[[column for column in ["trade_date", "ts_code", "name", "prediction", "model_rank", "passes_threshold", "ret_5d"] if column in case]].to_markdown(index=False) if not case.empty else "该日不在三引擎候选集内。",
        "",
        "## 边界",
        "",
        "- 模型不使用 AI、新闻和任何未来收益字段作为特征。",
        "- 最大回撤为按信号日等权队列收益的研究曲线回撤，不代表真实账户净值。",
        "- 未通过正式验收时不得接入 main.py。",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    return {"passed": passed, "blockers": blockers, "choice": choice, "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description="全市场短线走样本外线性排序研究")
    parser.add_argument("--input", default="reports/research/all_market_multi_engine_nofuture_trades_20260807.csv")
    parser.add_argument("--output", default="reports/research/walkforward_linear_ranker_20260807.md")
    args = parser.parse_args()
    result = run_research(args.input, args.output)
    print(result)


if __name__ == "__main__":
    main()
