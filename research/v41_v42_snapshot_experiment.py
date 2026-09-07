from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


SNAPSHOT = Path("reports") / "consensus_snapshot_v19_v25_v27_20260703.csv"
OUTPUT = Path("reports") / "v41_v44_snapshot_experiment_20260706.csv"


def load_snapshot(path: Path = SNAPSHOT) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    numeric_cols = [
        "consensus_votes",
        "consensus_avg_rank",
        "consensus_avg_score",
        "consensus_score",
        "sector_ma10_ratio",
        "factor_pattern",
        "limit_down_count",
        "ret_5d",
        "mfe_pct",
        "mae_pct",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.drop_duplicates(["select_date", "ts_code"], keep="last").copy()


def select_v41(df: pd.DataFrame, topn: int) -> pd.DataFrame:
    work = df[
        (df["consensus_votes"] >= 2)
        & (df["consensus_avg_rank"] <= 1.5)
        & (df["sector_ma10_ratio"] <= 70.0)
        & (df["factor_pattern"] >= 60.0)
    ].copy()
    return _topn(work, topn, "consensus_score")


def select_v42(df: pd.DataFrame, topn: int) -> pd.DataFrame:
    work = df[
        (df["consensus_votes"] >= 2)
        & (df["consensus_avg_rank"] <= 1.5)
        & (df["sector_ma10_ratio"] <= 70.0)
    ].copy()
    if work.empty:
        return work
    base = work["consensus_score"].fillna(0)
    pattern = work["factor_pattern"].fillna(50.0)
    breadth = work["sector_ma10_ratio"].fillna(70.0)
    limit_down = work["limit_down_count"].fillna(5.0)
    work["v42_score"] = (
        base
        + (pattern - 50.0).clip(lower=-20.0, upper=40.0) * 0.65
        + (70.0 - breadth).clip(lower=0.0, upper=40.0) * 0.25
        - limit_down.clip(lower=0.0, upper=20.0) * 0.12
    ).round(4)
    return _topn(work, topn, "v42_score")


def select_v43(df: pd.DataFrame, topn: int) -> pd.DataFrame:
    work = df[
        (df["consensus_votes"] >= 2)
        & (df["consensus_avg_rank"] <= 2.0)
        & (df["macro_mode"].astype(str) == "cautious")
    ].copy()
    return _topn(work, topn, "consensus_score")


def select_v44(df: pd.DataFrame, topn: int) -> pd.DataFrame:
    work = df[
        (df["consensus_votes"] >= 2)
        & (df["consensus_avg_rank"] <= 2.0)
        & (df["factor_pattern"] >= 50.0)
        & (df["limit_down_count"] <= 8.0)
    ].copy()
    return _topn(work, topn, "consensus_score")


def summarize(selected: pd.DataFrame, name: str) -> dict:
    if selected.empty:
        return {
            "strategy": name,
            "trades": 0,
            "years": 0,
            "positive_years": 0,
            "win_rate": 0.0,
            "total_return": 0.0,
            "avg_return": 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "hit3_rate": 0.0,
        }
    selected = selected.copy()
    selected["period"] = selected["period"].astype(str)
    by_year = selected.groupby("period")["ret_5d"].sum()
    return {
        "strategy": name,
        "trades": int(len(selected)),
        "years": int(selected["period"].nunique()),
        "positive_years": int((by_year > 0).sum()),
        "win_rate": round(float((selected["ret_5d"] > 0).mean() * 100), 2),
        "total_return": round(float(selected["ret_5d"].sum()), 2),
        "avg_return": round(float(selected["ret_5d"].mean()), 2),
        "avg_mfe": round(float(selected["mfe_pct"].mean()), 2),
        "avg_mae": round(float(selected["mae_pct"].mean()), 2),
        "hit3_rate": round(float((selected["mfe_pct"] >= 3.0).mean() * 100), 2),
        "loss_years": ",".join(by_year[by_year <= 0].index.astype(str).tolist()),
    }


def run_experiment() -> pd.DataFrame:
    snapshot = load_snapshot()
    rows = []
    for topn in (1, 2):
        rows.append(summarize(select_v41(snapshot, topn), f"v41_snapshot_top{topn}"))
        rows.append(summarize(select_v42(snapshot, topn), f"v42_snapshot_top{topn}"))
        rows.append(summarize(select_v43(snapshot, topn), f"v43_snapshot_top{topn}"))
        rows.append(summarize(select_v44(snapshot, topn), f"v44_snapshot_top{topn}"))
    return pd.DataFrame(rows)


def _topn(df: pd.DataFrame, topn: int, score_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    return (
        df.sort_values(["select_date", score_col, "ts_code"], ascending=[True, False, True])
        .groupby("select_date", group_keys=False)
        .head(topn)
        .reset_index(drop=True)
    )


def main() -> None:
    result = run_experiment()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"generated_at={datetime.now().isoformat(timespec='seconds')}")
    print(result.to_string(index=False))
    print(f"saved={OUTPUT}")


if __name__ == "__main__":
    main()
