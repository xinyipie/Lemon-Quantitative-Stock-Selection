"""龙头快钱模块辅助数据采集。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from research.limit_pool_collector import _load_cached_trade_dates, _normalize_ts_code


LHB_COLUMNS = [
    "trade_date",
    "ts_code",
    "name",
    "lhb_net_buy",
    "lhb_buy_amount",
    "lhb_sell_amount",
    "lhb_turnover",
    "lhb_reason",
]

HOT_COLUMNS = ["trade_date", "ts_code", "hot_rank", "new_fans_ratio", "loyal_fans_ratio"]


def collect_dragon_aux_range(
    start_date: str,
    end_date: str,
    output_root: str | Path = "data_research",
    trade_dates: list[str] | None = None,
    ak_module: Any | None = None,
    sleep_seconds: float = 0.3,
) -> dict:
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    dates = _trade_dates_in_range(start, end, trade_dates)
    root = Path(output_root) / "dragon_aux"
    ak = ak_module or _load_akshare()
    dt_dir = root / "dt_pool"
    sub_new_dir = root / "sub_new_pool"
    lhb_dir = root / "lhb_detail"
    for directory in (dt_dir, sub_new_dir, lhb_dir):
        directory.mkdir(parents=True, exist_ok=True)
    rows = {"dt_pool": 0, "sub_new_pool": 0, "lhb_detail": 0}
    errors: list[str] = []
    for idx, trade_date in enumerate(dates, start=1):
        try:
            dt = ak.stock_zt_pool_dtgc_em(date=trade_date)
            dt_norm = normalize_aux_pool_frame(dt, source="dt_pool", trade_date=trade_date)
            dt_norm.to_parquet(dt_dir / f"{trade_date}.parquet", index=False)
            rows["dt_pool"] += len(dt_norm)
        except Exception as exc:
            errors.append(f"dt_pool {trade_date}: {exc}")
        try:
            sub_new = ak.stock_zt_pool_sub_new_em(date=trade_date)
            sub_new_norm = normalize_aux_pool_frame(sub_new, source="sub_new_pool", trade_date=trade_date)
            sub_new_norm.to_parquet(sub_new_dir / f"{trade_date}.parquet", index=False)
            rows["sub_new_pool"] += len(sub_new_norm)
        except Exception as exc:
            errors.append(f"sub_new_pool {trade_date}: {exc}")
        if sleep_seconds > 0 and idx < len(dates):
            time.sleep(sleep_seconds)
    try:
        lhb = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        lhb_norm = normalize_lhb_detail(lhb)
        if not lhb_norm.empty:
            for trade_date, frame in lhb_norm.groupby("trade_date"):
                frame.to_parquet(lhb_dir / f"{trade_date}.parquet", index=False)
        rows["lhb_detail"] += len(lhb_norm)
    except Exception as exc:
        errors.append(f"lhb_detail {start}-{end}: {exc}")
    return {
        "start_date": start,
        "end_date": end,
        "total_days": len(dates),
        "rows": rows,
        "errors": errors,
    }


def normalize_aux_pool_frame(raw: pd.DataFrame | None, source: str, trade_date: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["trade_date", "source", "ts_code", "name", "pct_chg", "industry"])
    work = raw.copy()
    result = pd.DataFrame()
    result["trade_date"] = [_normalize_date(trade_date)] * len(work)
    result["source"] = source
    result["ts_code"] = _pick(work, ("代码", "股票代码", "证券代码", "ts_code", "code")).map(_normalize_ts_code)
    result["name"] = _pick(work, ("名称", "股票简称", "证券简称", "name")).fillna("").astype(str)
    result["pct_chg"] = pd.to_numeric(_pick(work, ("涨跌幅", "涨幅", "pct_chg", "change")), errors="coerce")
    result["industry"] = _pick(work, ("所属行业", "行业", "industry")).fillna("").astype(str)
    return result


def normalize_lhb_detail(raw: pd.DataFrame | None) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=LHB_COLUMNS)
    work = raw.copy()
    result = pd.DataFrame()
    result["trade_date"] = _pick(work, ("上榜日", "trade_date", "日期")).map(_normalize_date)
    result["ts_code"] = _pick(work, ("代码", "股票代码", "证券代码", "ts_code", "code")).map(_normalize_ts_code)
    result["name"] = _pick(work, ("名称", "股票简称", "证券简称", "name")).fillna("").astype(str)
    result["lhb_net_buy"] = pd.to_numeric(_pick(work, ("龙虎榜净买额", "净买额", "net_buy")), errors="coerce").fillna(0)
    result["lhb_buy_amount"] = pd.to_numeric(_pick(work, ("龙虎榜买入额", "买入额", "buy_amount")), errors="coerce").fillna(0)
    result["lhb_sell_amount"] = pd.to_numeric(_pick(work, ("龙虎榜卖出额", "卖出额", "sell_amount")), errors="coerce").fillna(0)
    result["lhb_turnover"] = pd.to_numeric(_pick(work, ("龙虎榜成交额", "成交额", "turnover")), errors="coerce").fillna(0)
    result["lhb_reason"] = _pick(work, ("上榜原因", "原因", "lhb_reason")).fillna("").astype(str)
    result = result.dropna(subset=["trade_date", "ts_code"])
    return result[LHB_COLUMNS].reset_index(drop=True)


def normalize_hot_rank_detail(raw: pd.DataFrame | None, ts_code: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=HOT_COLUMNS)
    work = raw.copy()
    result = pd.DataFrame()
    result["trade_date"] = _pick(work, ("时间", "日期", "trade_date")).map(_normalize_date)
    result["ts_code"] = _normalize_ts_code(ts_code)
    result["hot_rank"] = pd.to_numeric(_pick(work, ("排名", "rank", "hot_rank")), errors="coerce")
    result["new_fans_ratio"] = pd.to_numeric(_pick(work, ("新晋粉丝", "new_fans_ratio")), errors="coerce")
    result["loyal_fans_ratio"] = pd.to_numeric(_pick(work, ("铁杆粉丝", "loyal_fans_ratio")), errors="coerce")
    result = result.dropna(subset=["trade_date", "hot_rank"])
    return result[HOT_COLUMNS].reset_index(drop=True)


def _pick(frame: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series:
    columns = {str(column).strip(): column for column in frame.columns}
    for alias in aliases:
        if alias in columns:
            return frame[columns[alias]]
    for alias in aliases:
        for text, original in columns.items():
            if alias and alias in text:
                return frame[original]
    return pd.Series([None] * len(frame), index=frame.index)


def _trade_dates_in_range(start: str, end: str, trade_dates: list[str] | None = None) -> list[str]:
    dates = trade_dates if trade_dates is not None else _load_cached_trade_dates()
    normalized = sorted(date for date in (_normalize_date(item) for item in (dates or [])) if start <= date <= end)
    if normalized:
        return normalized
    return pd.bdate_range(start=start, end=end).strftime("%Y%m%d").tolist()


def _normalize_date(value: object) -> str:
    text = str(value or "").strip().replace("-", "")[:8]
    return text if len(text) == 8 and text.isdigit() else ""


def _load_akshare():
    import akshare as ak

    return ak


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集龙头快钱辅助研究数据。")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-root", default="data_research")
    parser.add_argument("--sleep", type=float, default=0.3)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result = collect_dragon_aux_range(args.start, args.end, args.output_root, sleep_seconds=args.sleep)
    print(
        f"dragon aux collected {result['start_date']}~{result['end_date']} "
        f"days={result['total_days']} rows={result['rows']} errors={len(result['errors'])}"
    )
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
