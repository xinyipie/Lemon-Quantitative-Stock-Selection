from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from t3_confirmation_quality_search import (
    _apply_rule,
    _condition_sets,
    _load_candidates,
    _load_strong,
    _metrics,
)


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"


SPLITS = [
    ("wf_2016_2021_to_2022_2026H1", ["2016", "2017", "2018", "2019", "2020", "2021"], ["2022", "2023", "2024", "2025", "2026H1"]),
    ("wf_2016_2022_to_2023_2026H1", ["2016", "2017", "2018", "2019", "2020", "2021", "2022"], ["2023", "2024", "2025", "2026H1"]),
    ("wf_2016_2023_to_2024_2026H1", ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023"], ["2024", "2025", "2026H1"]),
]

QUALITY_SEARCH = REPORTS / "t3_confirmation_quality_search_20260707.csv"


def _parse_condition(part: str) -> tuple[str, str, float] | None:
    match = re.match(r"^(.+?)(>=|<=|>|<)(-?\d+(?:\.\d+)?)$", str(part).strip())
    if not match:
        return None
    col, op, value = match.groups()
    return col, op, float(value)


def _rules_from_quality_top(limit: int = 120) -> list[dict]:
    if not QUALITY_SEARCH.exists():
        return _candidate_rules()
    source = pd.read_csv(QUALITY_SEARCH, encoding="utf-8-sig").head(limit)
    rules = []
    seen = set()
    for row in source.itertuples(index=False):
        rule_text = str(getattr(row, "rule"))
        conditions = []
        for part in rule_text.split(" & "):
            parsed = _parse_condition(part)
            if parsed is not None:
                conditions.append(parsed)
        key = (
            rule_text,
            str(getattr(row, "macro_mode")),
            str(getattr(row, "market_style")),
            str(getattr(row, "score_col")),
            int(getattr(row, "topn", 1)),
        )
        if key in seen:
            continue
        seen.add(key)
        macro_mode = getattr(row, "macro_mode")
        market_style = getattr(row, "market_style")
        rules.append({
            "rule": rule_text,
            "conditions": conditions,
            "macro_mode": None if pd.isna(macro_mode) else str(macro_mode),
            "market_style": None if pd.isna(market_style) else str(market_style),
            "score_col": str(getattr(row, "score_col")),
            "topn": int(getattr(row, "topn", 1)),
        })
    return rules


def _candidate_rules() -> list[dict]:
    rules = []
    for name, conditions in _condition_sets():
        for macro_mode in [None, "active", "cautious"]:
            for market_style in [None, "weak_momentum", "sideways", "momentum"]:
                for score_col in ["hybrid_score", "consensus_score"]:
                    for topn in [1, 2]:
                        rules.append({
                            "rule": name,
                            "conditions": conditions,
                            "macro_mode": macro_mode,
                            "market_style": market_style,
                            "score_col": score_col,
                            "topn": topn,
                        })
    return rules


def _select_universe(df: pd.DataFrame, strong: pd.DataFrame) -> pd.DataFrame:
    strong_dates = set(strong["select_date"].astype(str))
    return df[~df["select_date"].astype(str).isin(strong_dates)].copy()


def _score_train(expansion_metrics: dict[str, float], combo_metrics: dict[str, float]) -> float:
    return (
        expansion_metrics["win_rate"] * 1.3
        + min(expansion_metrics["total_ret"], 120.0) * 0.22
        + min(expansion_metrics["trades"], 80) * 0.18
        + combo_metrics["win_rate"] * 0.8
        + min(combo_metrics["total_ret"], 260.0) * 0.08
        - expansion_metrics["loss_years"] * 6.0
        - combo_metrics["loss_years"] * 7.0
        - abs(min(combo_metrics["worst_year"], 0.0)) * 1.2
    )


def _evaluate_rule(rule: dict, candidates: pd.DataFrame, strong: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float], dict[str, float]]:
    expansion = _apply_rule(candidates, rule)
    combo = pd.concat([strong, expansion], ignore_index=True, sort=False)
    combo = combo.sort_values(["select_date", "ts_code"]).drop_duplicates(["year", "select_date", "ts_code"])
    return expansion, _metrics(expansion), _metrics(combo)


def validate() -> tuple[pd.DataFrame, pd.DataFrame]:
    all_candidates = _select_universe(_load_candidates(), _load_strong())
    all_strong = _load_strong()
    rules = _rules_from_quality_top()
    summary_rows = []
    selected_trade_frames = []

    for split_name, train_years, test_years in SPLITS:
        train_candidates = all_candidates[all_candidates["year"].isin(train_years)].copy()
        test_candidates = all_candidates[all_candidates["year"].isin(test_years)].copy()
        train_strong = all_strong[all_strong["year"].isin(train_years)].copy()
        test_strong = all_strong[all_strong["year"].isin(test_years)].copy()

        trained_rules = []
        for rule in rules:
            train_expansion, train_expansion_metrics, train_combo_metrics = _evaluate_rule(rule, train_candidates, train_strong)
            if train_expansion_metrics["trades"] < 3:
                continue
            train_score = _score_train(train_expansion_metrics, train_combo_metrics)
            trained_rules.append((train_score, str(rule["rule"]), rule, train_expansion_metrics, train_combo_metrics))

        # 每个切分只按训练期资料锁定一个规则；测试期只做一次评价。
        trained_rules.sort(key=lambda item: (-item[0], item[1]))
        for split_rank, (train_score, _, rule, train_expansion_metrics, train_combo_metrics) in enumerate(
            trained_rules[:1], start=1
        ):
            test_expansion, test_expansion_metrics, test_combo_metrics = _evaluate_rule(rule, test_candidates, test_strong)
            selected = test_expansion.copy()
            selected["split"] = split_name
            selected["rank"] = split_rank
            selected_trade_frames.append(selected)
            summary_rows.append({
                "split": split_name,
                "rank": split_rank,
                "rule": rule["rule"],
                "macro_mode": rule["macro_mode"],
                "market_style": rule["market_style"],
                "score_col": rule["score_col"],
                "topn": rule["topn"],
                "train_score": train_score,
                **{f"train_expansion_{key}": value for key, value in train_expansion_metrics.items()},
                **{f"train_combo_{key}": value for key, value in train_combo_metrics.items()},
                **{f"test_expansion_{key}": value for key, value in test_expansion_metrics.items()},
                **{f"test_combo_{key}": value for key, value in test_combo_metrics.items()},
                "test_pass": (
                    test_expansion_metrics["trades"] >= 5
                    and test_expansion_metrics["win_rate"] >= 50.0
                    and test_expansion_metrics["avg_ret"] > 0
                    and test_combo_metrics["loss_years"] <= 1
                ),
            })

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values(
            ["split", "rank", "train_score"],
            ascending=[True, True, False],
        ).reset_index(drop=True)
    trades = pd.concat(selected_trade_frames, ignore_index=True) if selected_trade_frames else pd.DataFrame()
    return summary, trades


def _write_doc(summary: pd.DataFrame, output: Path) -> None:
    cols = [
        "split",
        "rank",
        "test_pass",
        "train_expansion_trades",
        "train_expansion_win_rate",
        "train_expansion_total_ret",
        "test_expansion_trades",
        "test_expansion_win_rate",
        "test_expansion_total_ret",
        "test_combo_trades",
        "test_combo_win_rate",
        "test_combo_total_ret",
        "test_combo_loss_years",
        "test_combo_worst_year",
        "rule",
        "macro_mode",
        "market_style",
        "topn",
    ]
    pass_rows = summary[summary["test_pass"]] if not summary.empty else pd.DataFrame()
    lines = [
        "# T3 确认质量门走前验证（2026-07-07）",
        "",
        "## 研究口径",
        "",
        "- 不用全样本直接挑最优；先在训练年份选规则，再到后续年份验证。",
        "- 训练集只允许 T3 入场前已知的路径因子，避免偷看 T5/T7。",
        "- 验证通过标准：测试扩容层至少 5 笔、胜率 >=50%、平均收益为正，合并 strong_T1 后亏损年份 <=1。",
        "- 本报告用于决定是否进入观察层，不代表正式上线策略。",
        "",
        "## 验证通过规则",
        "",
        pass_rows[[c for c in cols if c in pass_rows.columns]].to_markdown(index=False, floatfmt=".2f") if not pass_rows.empty else "无",
        "",
        "## 各切分 Top20",
        "",
        summary[[c for c in cols if c in summary.columns]].head(60).to_markdown(index=False, floatfmt=".2f") if not summary.empty else "无",
        "",
        "## 初步读法",
        "",
        "- 如果没有规则通过走前验证，T3 只保留为研究观察，不进入实盘推荐。",
        "- 如果规则只在含 2025 的测试集通过，要警惕被 2025 单一年份拉高。",
        "- 更稳的候选应在多个切分通过，且测试扩容层自身收益为正。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    summary, trades = validate()
    summary.to_csv(REPORTS / "t3_confirmation_walkforward_validation_20260707.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(REPORTS / "t3_confirmation_walkforward_trades_20260707.csv", index=False, encoding="utf-8-sig")
    _write_doc(summary, DOCS / "T3_CONFIRMATION_WALKFORWARD_VALIDATION_20260707.md")
    print(summary.head(40).to_string(index=False) if not summary.empty else "no validation rows")


if __name__ == "__main__":
    main()
