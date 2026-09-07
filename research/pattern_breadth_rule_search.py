from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


SNAPSHOT = Path("reports") / "consensus_snapshot_v19_v25_v27_20260703.csv"
OUTPUT = Path("reports") / "pattern_breadth_rule_search_20260706.csv"
RECENT_PERIODS = {"2025", "2026H1"}
BAD_PERIODS = {"2018", "2022", "2023"}


@dataclass(frozen=True)
class Rule:
    topn: int
    min_votes: int
    max_rank: float
    min_pattern: float | None
    max_sector_ma10: float | None
    min_limit_up: float | None
    max_limit_down: float | None
    macro_mode: str | None
    score_mode: str

    @property
    def name(self) -> str:
        parts = [f"top{self.topn}", f"votes>={self.min_votes}", f"rank<={self.max_rank}"]
        if self.min_pattern is not None:
            parts.append(f"pattern>={self.min_pattern:g}")
        if self.max_sector_ma10 is not None:
            parts.append(f"sector<={self.max_sector_ma10:g}")
        if self.min_limit_up is not None:
            parts.append(f"up>={self.min_limit_up:g}")
        if self.max_limit_down is not None:
            parts.append(f"down<={self.max_limit_down:g}")
        if self.macro_mode is not None:
            parts.append(f"macro={self.macro_mode}")
        parts.append(self.score_mode)
        return "|".join(parts)


def load_snapshot(path: Path = SNAPSHOT) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    numeric_cols = [
        "consensus_votes",
        "consensus_avg_rank",
        "consensus_score",
        "factor_pattern",
        "factor_sector",
        "sector_ma10_ratio",
        "limit_up_count",
        "limit_down_count",
        "volume_ratio",
        "drawdown_from_high",
        "change",
        "ret_5d",
        "mfe_pct",
        "mae_pct",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.drop_duplicates(["select_date", "ts_code"], keep="last").copy()


def generate_rules() -> list[Rule]:
    rules = []
    for topn in (1, 2):
        for min_votes in (2, 3):
            for max_rank in (1.2, 1.5, 2.0):
                for min_pattern in (None, 50.0, 60.0, 65.0):
                    for max_sector in (None, 45.0, 55.0, 70.0, 85.0):
                        for min_limit_up in (None, 50.0, 60.0, 70.0):
                            for max_limit_down in (None, 4.0, 8.0, 12.0):
                                for macro_mode in (None, "active", "cautious"):
                                    for score_mode in ("consensus", "pattern_breadth"):
                                        rules.append(
                                            Rule(
                                                topn=topn,
                                                min_votes=min_votes,
                                                max_rank=max_rank,
                                                min_pattern=min_pattern,
                                                max_sector_ma10=max_sector,
                                                min_limit_up=min_limit_up,
                                                max_limit_down=max_limit_down,
                                                macro_mode=macro_mode,
                                                score_mode=score_mode,
                                            )
                                        )
    return rules


def apply_rule(df: pd.DataFrame, rule: Rule) -> pd.DataFrame:
    work = df[
        (df["consensus_votes"] >= rule.min_votes)
        & (df["consensus_avg_rank"] <= rule.max_rank)
    ].copy()
    if rule.min_pattern is not None:
        work = work[work["factor_pattern"] >= rule.min_pattern]
    if rule.max_sector_ma10 is not None:
        work = work[work["sector_ma10_ratio"] <= rule.max_sector_ma10]
    if rule.min_limit_up is not None:
        work = work[work["limit_up_count"] >= rule.min_limit_up]
    if rule.max_limit_down is not None:
        work = work[work["limit_down_count"] <= rule.max_limit_down]
    if rule.macro_mode is not None:
        work = work[work["macro_mode"].astype(str) == rule.macro_mode]
    if work.empty:
        return work

    if rule.score_mode == "pattern_breadth":
        work["rule_score"] = (
            work["consensus_score"].fillna(0)
            + (work["factor_pattern"].fillna(50.0) - 50.0).clip(lower=-20.0, upper=40.0) * 0.65
            + (70.0 - work["sector_ma10_ratio"].fillna(70.0)).clip(lower=0.0, upper=40.0) * 0.25
            - work["limit_down_count"].fillna(5.0).clip(lower=0.0, upper=20.0) * 0.12
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
    score = (
        win_rate * 0.7
        + recent_win * 1.1
        + total_return * 0.12
        + min(len(selected), 100) * 0.2
        + int((by_period > 0).sum()) * 2.0
        - abs(min(0.0, float(bad["ret_5d"].sum()) if len(bad) else 0.0)) * 2.0
        - max(0, 35 - len(selected)) * 1.5
    )
    return {
        "rule": rule.name,
        "topn": rule.topn,
        "trades": int(len(selected)),
        "years": int(selected["period"].nunique()),
        "positive_years": int((by_period > 0).sum()),
        "win_rate": round(win_rate, 2),
        "recent_trades": int(len(recent)),
        "recent_win_rate": round(recent_win, 2),
        "recent_return": round(float(recent["ret_5d"].sum()) if len(recent) else 0.0, 2),
        "bad_return": round(float(bad["ret_5d"].sum()) if len(bad) else 0.0, 2),
        "total_return": round(total_return, 2),
        "avg_return": round(float(selected["ret_5d"].mean()), 2),
        "avg_mfe": round(float(selected["mfe_pct"].mean()), 2),
        "avg_mae": round(float(selected["mae_pct"].mean()), 2),
        "hit3_rate": round(float((selected["mfe_pct"] >= 3.0).mean() * 100), 2),
        "loss_years": ",".join(by_period[by_period <= 0].index.astype(str).tolist()),
        "score": round(score, 4),
    }


def run_search(min_trades: int = 20) -> pd.DataFrame:
    snapshot = load_snapshot()
    rows = []
    for rule in generate_rules():
        selected = apply_rule(snapshot, rule)
        if len(selected) < min_trades:
            continue
        rows.append(metrics(rule, selected))
    return pd.DataFrame(rows).sort_values(
        ["score", "recent_win_rate", "win_rate", "total_return"],
        ascending=False,
    )


def main() -> None:
    result = run_search()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(result.head(30).to_string(index=False))
    print(f"saved={OUTPUT}")


if __name__ == "__main__":
    main()
