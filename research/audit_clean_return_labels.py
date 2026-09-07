"""审计 clean_all_market 中的未来收益标签是否与原始日行情一致。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


HORIZONS = (3, 5, 8)


def _load_daily_path(cache_dir: Path, dates: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    columns = ["ts_code", "open", "high", "low", "close", "pct_chg"]
    for date in dates:
        path = cache_dir / "daily" / f"{date}.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path, columns=columns).copy()
        frame["trade_date"] = date
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    daily = pd.concat(frames, ignore_index=True)
    for column in columns[1:]:
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    return daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def reconstruct_path(path: pd.DataFrame) -> dict[str, float]:
    """按 T+1 开盘买入、T+N 收盘退出的定义重建标签。"""
    if len(path) < max(HORIZONS):
        return {}
    entry_open = float(path.iloc[0]["open"])
    if not np.isfinite(entry_open) or entry_open <= 0:
        return {}

    close_factor = float(path.iloc[0]["close"]) / entry_open
    returns: dict[str, float] = {}
    path_highs: list[float] = []
    path_lows: list[float] = []
    cumulative_close = close_factor

    for day_index, row in enumerate(path.iloc[: max(HORIZONS)].itertuples(index=False), start=1):
        if day_index == 1:
            high_factor = float(row.high) / entry_open
            low_factor = float(row.low) / entry_open
        else:
            # 与研究面板保持完全一致：高低路径使用上一交易日原始收盘价。
            pre_close = float(path.iloc[day_index - 2]["close"])
            high_factor = cumulative_close * float(row.high) / pre_close
            low_factor = cumulative_close * float(row.low) / pre_close
            cumulative_close *= 1.0 + float(row.pct_chg) / 100.0
        path_highs.append(high_factor - 1.0)
        path_lows.append(low_factor - 1.0)
        if day_index in HORIZONS:
            returns[f"ret_{day_index}d"] = (cumulative_close - 1.0) * 100.0

    returns["mfe_8d"] = max(path_highs) * 100.0
    returns["mae_8d"] = min(path_lows) * 100.0
    return returns


def audit_year(
    year: int,
    clean_dir: Path,
    cache_dir: Path,
    sample_size: int,
    seed: int,
) -> dict[str, object]:
    clean = pd.read_parquet(clean_dir / f"{year}.parquet")
    valid = clean.dropna(subset=["entry_open", "ret_3d", "ret_5d", "ret_8d"]).copy()
    if valid.empty:
        raise ValueError(f"{year} 没有可审计样本")

    random_sample = valid.sample(min(sample_size, len(valid)), random_state=seed)
    event_sample = valid.loc[
        valid["entry_gap_pct"].abs().ge(5)
        | valid["ret_8d"].abs().ge(20)
        | valid["mfe_8d"].ge(25)
        | valid["mae_8d"].le(-20)
    ].head(sample_size)
    sample = pd.concat([random_sample, event_sample]).drop_duplicates(["trade_date", "ts_code"])

    trade_dates = sorted(clean["trade_date"].astype(str).unique())
    all_cache_dates = sorted(path.stem for path in (cache_dir / "daily").glob("*.parquet"))
    date_position = {date: index for index, date in enumerate(all_cache_dates)}
    required_dates: set[str] = set()
    sample_dates: dict[str, list[str]] = {}
    for date in sample["trade_date"].astype(str).unique():
        position = date_position.get(date)
        if position is None:
            continue
        future_dates = all_cache_dates[position + 1 : position + 1 + max(HORIZONS)]
        sample_dates[date] = future_dates
        required_dates.update(future_dates)

    daily = _load_daily_path(cache_dir, sorted(required_dates))
    grouped = {(code, date): group for (code, date), group in daily.groupby(["ts_code", "trade_date"])}
    errors: list[dict[str, object]] = []
    checked = 0
    raw_endpoint_divergences = 0

    for row in sample.itertuples(index=False):
        future_dates = sample_dates.get(str(row.trade_date), [])
        path_rows = []
        for date in future_dates:
            group = grouped.get((str(row.ts_code), date))
            if group is None or group.empty:
                break
            path_rows.append(group.iloc[0])
        if len(path_rows) < max(HORIZONS):
            continue
        path = pd.DataFrame(path_rows).reset_index(drop=True)
        reconstructed = reconstruct_path(path)
        if not reconstructed:
            continue
        checked += 1
        field_errors = {
            field: abs(float(getattr(row, field)) - value)
            for field, value in reconstructed.items()
        }
        if max(field_errors.values(), default=0.0) > 1e-8:
            errors.append(
                {
                    "trade_date": str(row.trade_date),
                    "ts_code": str(row.ts_code),
                    "field_errors": field_errors,
                }
            )

        raw_ret_8d = (float(path.iloc[7]["close"]) / float(path.iloc[0]["open"]) - 1.0) * 100.0
        if abs(raw_ret_8d - reconstructed["ret_8d"]) > 0.05:
            raw_endpoint_divergences += 1

    return {
        "year": year,
        "trade_dates": len(trade_dates),
        "sampled": int(len(sample)),
        "checked": checked,
        "mismatch_count": len(errors),
        "max_absolute_error": max(
            (max(item["field_errors"].values()) for item in errors),
            default=0.0,
        ),
        "raw_endpoint_divergences": raw_endpoint_divergences,
        "mismatches": errors[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2016, 2022)))
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--clean-dir", type=Path, default=Path("data/research/clean_all_market"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/research/clean_return_label_audit_20260808.json"),
    )
    args = parser.parse_args()

    reports = [
        audit_year(year, args.clean_dir, args.cache_dir, args.sample_size, args.seed + year)
        for year in args.years
    ]
    summary = {
        "definition": "T日收盘锁定信号，T+1开盘买入，T+N收盘退出；pct_chg连接复权路径",
        "reports": reports,
        "passed": all(report["mismatch_count"] == 0 and report["checked"] > 0 for report in reports),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
