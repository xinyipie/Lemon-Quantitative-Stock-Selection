from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


SOURCE = Path("reports") / "stage3_candidate_consensus_topn_selected.csv"
OUTPUT = Path("reports") / "expansion_layer_rule_search_20260706.csv"
RECENT_PERIODS = {"2025", "2026H1"}
BAD_PERIODS = {"2016", "2018", "2022", "2023"}


@dataclass(frozen=True)
class Rule:
    topn: int
    min_versions: int
    max_avg_rank: float | None
    max_best_rank: float | None
    min_pattern: float | None
    min_factor_sector: float | None
    max_factor_sector: float | None
    max_sector_ma10: float | None
    min_limit_up: float | None
    max_limit_down: float | None
    max_change: float | None
    max_volume: float | None
    macro_mode: str | None
    market_style: str | None
    score_mode: str

    @property
    def name(self) -> str:
        parts = [f"top{self.topn}", f"versions>={self.min_versions}"]
        if self.max_avg_rank is not None:
            parts.append(f"avg_rank<={self.max_avg_rank:g}")
        if self.max_best_rank is not None:
            parts.append(f"best_rank<={self.max_best_rank:g}")
        if self.min_pattern is not None:
            parts.append(f"pattern>={self.min_pattern:g}")
        if self.min_factor_sector is not None:
            parts.append(f"factor_sector>={self.min_factor_sector:g}")
        if self.max_factor_sector is not None:
            parts.append(f"factor_sector<={self.max_factor_sector:g}")
        if self.max_sector_ma10 is not None:
            parts.append(f"sector_ma10<={self.max_sector_ma10:g}")
        if self.min_limit_up is not None:
            parts.append(f"up>={self.min_limit_up:g}")
        if self.max_limit_down is not None:
            parts.append(f"down<={self.max_limit_down:g}")
        if self.max_change is not None:
            parts.append(f"chg<={self.max_change:g}")
        if self.max_volume is not None:
            parts.append(f"vol<={self.max_volume:g}")
        if self.macro_mode is not None:
            parts.append(f"macro={self.macro_mode}")
        if self.market_style is not None:
            parts.append(f"style={self.market_style}")
        parts.append(self.score_mode)
        return "|".join(parts)


def load_source(path: Path = SOURCE) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    numeric_cols = [
        "n_versions",
        "best_rank",
        "avg_rank",
        "avg_score",
        "max_score",
        "ret_5d",
        "mfe_pct",
        "mae_pct",
        "hit_3pct",
        "hit_5pct",
        "factor_sector",
        "factor_pattern",
        "factor_wyckoff",
        "factor_inflow",
        "factor_volume_ratio",
        "factor_drawdown",
        "change",
        "volume_ratio",
        "drawdown_from_high",
        "market_index_change",
        "sector_ma10_ratio",
        "limit_up_count",
        "limit_down_count",
        "consensus_score",
        "recent_factor_score",
        "hybrid_score",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.drop_duplicates(["select_date", "ts_code"], keep="last").copy()


def generate_rules() -> list[Rule]:
    rules = []
    for topn in (1, 2, 3):
        for min_versions in (2, 3):
            for max_avg_rank in (None, 1.5, 2.0, 2.5, 3.0):
                for max_best_rank in (None, 1.0, 2.0):
                    for min_pattern in (None, 40.0, 50.0, 60.0):
                        for max_limit_down in (None, 8.0, 12.0, 20.0):
                            for macro_mode in (None, "active", "cautious", "defensive"):
                                for score_mode in ("consensus", "hybrid", "defensive_quality"):
                                    rules.append(
                                        Rule(
                                            topn=topn,
                                            min_versions=min_versions,
                                            max_avg_rank=max_avg_rank,
                                            max_best_rank=max_best_rank,
                                            min_pattern=min_pattern,
                                            min_factor_sector=None,
                                            max_factor_sector=None,
                                            max_sector_ma10=None,
                                            min_limit_up=None,
                                            max_limit_down=max_limit_down,
                                            max_change=None,
                                            max_volume=None,
                                            macro_mode=macro_mode,
                                            market_style=None,
                                            score_mode=score_mode,
                                        )
                                    )
    return rules


def apply_rule(df: pd.DataFrame, rule: Rule) -> pd.DataFrame:
    work = df[df["n_versions"] >= rule.min_versions].copy()
    if rule.max_avg_rank is not None:
        work = work[work["avg_rank"] <= rule.max_avg_rank]
    if rule.max_best_rank is not None:
        work = work[work["best_rank"] <= rule.max_best_rank]
    if rule.min_pattern is not None:
        work = work[work["factor_pattern"] >= rule.min_pattern]
    if rule.min_factor_sector is not None:
        work = work[work["factor_sector"] >= rule.min_factor_sector]
    if rule.max_factor_sector is not None:
        work = work[work["factor_sector"] <= rule.max_factor_sector]
    if rule.max_sector_ma10 is not None:
        work = work[work["sector_ma10_ratio"] <= rule.max_sector_ma10]
    if rule.min_limit_up is not None:
        work = work[work["limit_up_count"] >= rule.min_limit_up]
    if rule.max_limit_down is not None:
        work = work[work["limit_down_count"] <= rule.max_limit_down]
    if rule.max_change is not None:
        work = work[work["change"] <= rule.max_change]
    if rule.max_volume is not None:
        work = work[work["volume_ratio"] <= rule.max_volume]
    if rule.macro_mode is not None:
        work = work[work["macro_mode"].astype(str) == rule.macro_mode]
    if rule.market_style is not None:
        work = work[work["market_style"].astype(str) == rule.market_style]
    if work.empty:
        return work

    work = work.copy()
    if rule.score_mode == "hybrid":
        work["rule_score"] = work["hybrid_score"].fillna(work["consensus_score"])
    elif rule.score_mode == "defensive_quality":
        work["rule_score"] = (
            work["consensus_score"].fillna(0)
            - work["avg_rank"].fillna(3.0) * 12.0
            + (work["factor_pattern"].fillna(50.0) - 50.0).clip(lower=-20.0, upper=40.0) * 0.45
            + (70.0 - work["sector_ma10_ratio"].fillna(70.0)).clip(lower=0.0, upper=50.0) * 0.18
            - work["limit_down_count"].fillna(8.0).clip(lower=0.0, upper=30.0) * 0.25
            - (work["volume_ratio"].fillna(2.0) - 2.0).abs() * 1.8
        )
    else:
        work["rule_score"] = work["consensus_score"]
    return (
        work.sort_values(["select_date", "rule_score", "ts_code"], ascending=[True, False, True])
        .groupby("select_date", group_keys=False)
        .head(rule.topn)
        .reset_index(drop=True)
    )


def metrics(rule: Rule, selected: pd.DataFrame) -> dict:
    if selected.empty:
        return {}
    selected = selected.copy()
    selected["period"] = selected["period"].astype(str)
    by_period = selected.groupby("period")["ret_5d"].sum()
    recent = selected[selected["period"].isin(RECENT_PERIODS)]
    bad = selected[selected["period"].isin(BAD_PERIODS)]
    win_rate = float((selected["ret_5d"] > 0).mean() * 100)
    recent_win = float((recent["ret_5d"] > 0).mean() * 100) if len(recent) else 0.0
    total_return = float(selected["ret_5d"].sum())
    worst_year = float(by_period.min()) if len(by_period) else 0.0
    positive_years = int((by_period > 0).sum())
    loss_years = int((by_period <= 0).sum())
    bad_return = float(bad["ret_5d"].sum()) if len(bad) else 0.0
    trade_count = int(len(selected))
    # 扩容层偏好 80-150 笔；过少或过多都扣分。
    target_mid = 115
    size_penalty = abs(trade_count - target_mid) * 0.22
    loss_penalty = loss_years * 12.0 + abs(min(0.0, worst_year)) * 1.5
    score = (
        win_rate * 0.9
        + recent_win * 0.7
        + min(total_return, 260.0) * 0.12
        + positive_years * 4.0
        + min(trade_count, 160) * 0.18
        + float((selected["mfe_pct"] >= 3.0).mean() * 100) * 0.15
        - size_penalty
        - loss_penalty
        - abs(min(0.0, bad_return)) * 1.2
    )
    return {
        "rule": rule.name,
        "trades": trade_count,
        "years": int(selected["period"].nunique()),
        "positive_years": positive_years,
        "loss_years": loss_years,
        "win_rate": round(win_rate, 2),
        "recent_trades": int(len(recent)),
        "recent_win_rate": round(recent_win, 2),
        "recent_return": round(float(recent["ret_5d"].sum()) if len(recent) else 0.0, 2),
        "bad_return": round(bad_return, 2),
        "total_return": round(total_return, 2),
        "avg_return": round(float(selected["ret_5d"].mean()), 2),
        "avg_mfe": round(float(selected["mfe_pct"].mean()), 2),
        "avg_mae": round(float(selected["mae_pct"].mean()), 2),
        "hit3_rate": round(float((selected["mfe_pct"] >= 3.0).mean() * 100), 2),
        "hit5_rate": round(float((selected["mfe_pct"] >= 5.0).mean() * 100), 2),
        "worst_year": round(worst_year, 2),
        "loss_year_labels": ",".join(by_period[by_period <= 0].index.astype(str).tolist()),
        "score": round(score, 4),
    }


def run_search(min_trades: int = 80, max_trades: int = 180, min_win_rate: float = 55.0) -> pd.DataFrame:
    df = load_source()
    rows = []
    for rule in generate_rules():
        selected = apply_rule(df, rule)
        if not (min_trades <= len(selected) <= max_trades):
            continue
        row = metrics(rule, selected)
        if not row or row["win_rate"] < min_win_rate or row["total_return"] <= 0:
            continue
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["score", "win_rate", "total_return", "trades"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def main() -> None:
    result = run_search()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(result.head(40).to_string(index=False) if not result.empty else "no candidates")
    print(f"saved={OUTPUT}")


if __name__ == "__main__":
    main()
