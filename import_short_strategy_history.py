"""将冻结的短线研究记录导入信号库，供影子策略历史展示。"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from signal_store import DEFAULT_DB_PATH, SignalRecord, SignalStore


PROFILE = "short_defensive_quality_reentry_v16"
SOURCE = "research_shadow"
DEFAULT_INPUT = Path(
    "reports/research/defensive_quality_reentry_v16_2019_2026_20260808_trades.csv"
)


def _optional_number(value):
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _factor_payload(row: pd.Series) -> dict:
    keys = (
        "entry_open",
        "ret_3d",
        "ret_5d",
        "ret_8d",
        "mfe_8d",
        "mae_8d",
        "rank_prediction",
        "prediction_margin",
        "flow_ratio_5d",
        "flow_positive_days_5d",
        "quality_momentum_score",
        "regime",
        "engine",
    )
    payload = {key: _optional_number(row.get(key)) for key in keys if key != "regime" and key != "engine"}
    payload["regime"] = str(row.get("regime") or "")
    payload["engine"] = str(row.get("engine") or "quality_momentum_reentry")
    payload["original_score"] = _optional_number(row.get("quality_momentum_score"))
    payload["mfe_pct"] = _optional_number(row.get("mfe_8d"))
    payload["mae_pct"] = _optional_number(row.get("mae_8d"))
    payload["factor_profile"] = PROFILE
    payload["strategy_role"] = "shadow"
    return payload


def import_history(input_path: str | Path = DEFAULT_INPUT, signal_db: str | Path = DEFAULT_DB_PATH) -> dict:
    """按交易日导入 v16 历史；重复执行不会改变正式策略记录。"""

    frame = pd.read_csv(input_path, dtype={"trade_date": str, "ts_code": str})
    if frame.empty:
        return {"days": 0, "signals": 0}
    frame["trade_date"] = frame["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
    store = SignalStore(signal_db)
    imported = 0
    try:
        for trade_date, group in frame.sort_values(["trade_date", "selected_rank"]).groupby("trade_date"):
            run_id = store.record_run(
                trade_date=trade_date,
                mode="short",
                profile=PROFILE,
                source=SOURCE,
                label="frozen_v16",
            )
            records = []
            for position, (_, row) in enumerate(group.iterrows(), start=1):
                records.append(
                    SignalRecord(
                        ts_code=str(row.get("ts_code") or ""),
                        name=str(row.get("name") or ""),
                        industry=str(row.get("industry") or ""),
                        rank=int(_optional_number(row.get("selected_rank")) or position),
                        score=(
                            _optional_number(row.get("prediction_margin")) * 100
                            if _optional_number(row.get("prediction_margin")) is not None
                            else _optional_number(row.get("rank_prediction"))
                        ),
                        pool_type="short_shadow",
                        reason=f"{row.get('regime') or '逆风环境'}下的质量动量与资金流共振",
                        factors=_factor_payload(row),
                    )
                )
            store.update_pool(run_id, trade_date, "short", PROFILE, records)
            imported += len(records)
    finally:
        store.close()
    return {"days": int(frame["trade_date"].nunique()), "signals": imported}


def main() -> None:
    parser = argparse.ArgumentParser(description="导入逆风修复 v16 冻结研究历史")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--signal-db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    print(import_history(args.input, args.signal_db))


if __name__ == "__main__":
    main()
