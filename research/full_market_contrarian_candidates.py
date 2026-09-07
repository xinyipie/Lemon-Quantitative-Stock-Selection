from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.all_market_multi_engine_research import (
    _available_dates,
    _build_regimes,
    _load_stock_info,
    build_year_panel,
)


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
OUTPUT = ROOT / "reports" / "research" / "full_market_contrarian_top50_20260808.csv"
FORBIDDEN_COLUMNS = {"ret_3d", "ret_5d", "ret_8d", "mfe_8d", "mae_8d", "opportunity_score", "opportunity_rank"}
SCORE_COLUMNS = {
    "drawdown_20",
    "ret_5",
    "ret_10",
    "ret_20",
    "ret_60",
    "turnover_rate",
    "volatility_20",
    "volume_ratio",
    "rsi_14",
    "industry_rs_20",
}


def _rank(frame: pd.DataFrame, column: str, higher: bool) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    return values.groupby(frame["trade_date"]).rank(pct=True, ascending=higher, method="average") * 100


def build_candidates(panel: pd.DataFrame, topn: int = 50) -> pd.DataFrame:
    work = panel.copy()
    for column in SCORE_COLUMNS | {"pct_chg", "history_count"}:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    mask = (
        (work["history_count"] >= 60)
        & work["pct_chg"].between(-4, 7)
        & work["turnover_rate"].between(0.8, 20)
        & work["volume_ratio"].between(0.4, 4)
    )
    work = work[mask].copy()
    if work.empty:
        return work
    work["contrarian_score"] = (
        _rank(work, "drawdown_20", True) * 0.15
        + _rank(work, "ret_5", False) * 0.15
        + _rank(work, "ret_10", False) * 0.10
        + _rank(work, "ret_20", False) * 0.10
        + _rank(work, "ret_60", False) * 0.05
        + _rank(work, "turnover_rate", False) * 0.10
        + _rank(work, "volatility_20", False) * 0.10
        + _rank(work, "volume_ratio", False) * 0.05
        + _rank(work, "rsi_14", False) * 0.05
        + _rank(work, "industry_rs_20", False) * 0.05
    ).round(4)
    selected = (
        work.sort_values(["trade_date", "contrarian_score", "ts_code"], ascending=[True, False, True])
        .groupby("trade_date", group_keys=False)
        .head(topn)
        .drop_duplicates(["trade_date", "ts_code"])
        .copy()
    )
    selected["engine"] = "contrarian"
    selected["engine_score"] = selected["contrarian_score"]
    selected["engine_rank"] = selected.groupby("trade_date")["contrarian_score"].rank(ascending=False, method="first")
    return selected


def run() -> None:
    dates = _available_dates(CACHE, "20160101", "20260630")
    regimes = _build_regimes(CACHE, dates)
    stock_info = _load_stock_info(CACHE)
    frames = []
    for year in range(2016, 2027):
        panel = build_year_panel(CACHE, stock_info, regimes, dates, year, f"{year}0101", "20260630" if year == 2026 else f"{year}1231")
        candidates = build_candidates(panel)
        frames.append(candidates)
        print(f"year={year} panel={len(panel)} candidates={len(candidates)}")
    result = pd.concat(frames, ignore_index=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"rows={len(result)} dates={result['trade_date'].nunique()} wrote={OUTPUT}")


if __name__ == "__main__":
    run()
