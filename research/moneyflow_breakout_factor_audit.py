"""审计趋势突破候选中的主力资金流预测方向。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = ROOT / "data" / "research" / "clean_moneyflow"
REPORT_DIR = ROOT / "reports" / "research"
FEATURES = [
    "flow_ratio_1d",
    "flow_ratio_3d",
    "flow_ratio_5d",
    "flow_positive_days_5d",
    "flow_acceleration_3v5",
]


def breakout_candidate_mask(frame: pd.DataFrame) -> pd.Series:
    """固定宽松趋势突破候选，不使用资金流和未来收益。"""

    name = frame["name"].fillna("").astype(str)
    code = frame["ts_code"].fillna("").astype(str)
    synthetic = pd.to_numeric(frame["synthetic_close"], errors="coerce")
    prior_high = pd.to_numeric(frame["prior_high_20"], errors="coerce")
    distance_to_high = synthetic / prior_high - 1
    return (
        pd.to_numeric(frame["history_count"], errors="coerce").ge(120)
        & ~name.str.upper().str.contains("ST", regex=False)
        & ~code.str.endswith(".BJ")
        & pd.to_numeric(frame["ma_20"], errors="coerce").gt(
            pd.to_numeric(frame["ma_60"], errors="coerce")
        )
        & distance_to_high.between(-0.06, 0.02)
        & pd.to_numeric(frame["ret_20"], errors="coerce").between(3, 35)
        & pd.to_numeric(frame["ret_60"], errors="coerce").between(5, 100)
        & pd.to_numeric(frame["pct_chg"], errors="coerce").between(-1, 7)
        & pd.to_numeric(frame["turnover_rate"], errors="coerce").between(0.5, 15)
        & pd.to_numeric(frame["volume_ratio"], errors="coerce").between(0.8, 3)
    )


def factor_year_summary(frame: pd.DataFrame, year: int) -> list[dict]:
    """输出单年 IC 与高低五分位收益差。"""

    candidates = frame.loc[breakout_candidate_mask(frame)].copy()
    rows = []
    for feature in FEATURES:
        valid = candidates[[feature, "ret_5d"]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(valid) < 100 or valid[feature].nunique() < 5:
            continue
        ranked = valid[feature].rank(method="first", pct=True)
        top = valid.loc[ranked >= 0.8, "ret_5d"]
        bottom = valid.loc[ranked <= 0.2, "ret_5d"]
        rows.append(
            {
                "year": year,
                "feature": feature,
                "candidate_rows": int(len(valid)),
                "spearman_ic": float(valid[feature].corr(valid["ret_5d"], method="spearman")),
                "top_quintile_avg_ret_5d": float(top.mean()),
                "bottom_quintile_avg_ret_5d": float(bottom.mean()),
                "top_minus_bottom": float(top.mean() - bottom.mean()),
            }
        )
    return rows


def run() -> dict:
    rows = []
    required = [
        "ts_code", "name", "history_count", "synthetic_close", "prior_high_20",
        "ma_20", "ma_60", "ret_20", "ret_60", "pct_chg", "turnover_rate",
        "volume_ratio", "entry_gap_pct", "ret_5d", *FEATURES,
    ]
    for year in range(2016, 2025):
        frame = pd.read_parquet(STORE_DIR / f"{year}.parquet", columns=required)
        year_rows = factor_year_summary(frame, year)
        rows.extend(year_rows)
        count = year_rows[0]["candidate_rows"] if year_rows else 0
        print(f"year={year} candidate_rows={count}", flush=True)
    detail = pd.DataFrame(rows)
    internal = detail[detail["year"].between(2016, 2021)]
    aggregate = (
        internal.groupby("feature", as_index=False)
        .agg(
            internal_years=("year", "nunique"),
            positive_ic_years=("spearman_ic", lambda values: int((values > 0).sum())),
            positive_spread_years=("top_minus_bottom", lambda values: int((values > 0).sum())),
            average_ic=("spearman_ic", "mean"),
            average_top_minus_bottom=("top_minus_bottom", "mean"),
            worst_top_minus_bottom=("top_minus_bottom", "min"),
        )
        .sort_values(
            ["positive_spread_years", "worst_top_minus_bottom", "average_top_minus_bottom"],
            ascending=False,
        )
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    detail.to_csv(
        REPORT_DIR / "moneyflow_breakout_factor_audit_2016_2024_20260808.csv",
        index=False,
        encoding="utf-8-sig",
    )
    result = {
        "research_id": "moneyflow_breakout_factor_audit_2016_2024_20260808",
        "internal_factor_ranking": aggregate.to_dict(orient="records"),
        "validation_not_used_for_ranking": True,
        "production_changed": False,
    }
    (REPORT_DIR / "moneyflow_breakout_factor_audit_2016_2024_20260808.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
