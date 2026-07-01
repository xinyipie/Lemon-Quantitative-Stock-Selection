#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""涨停池数据补全工具。

该工具只服务研究分支：从 AkShare/东方财富低成本接口抓取涨停池、
炸板池、昨日涨停表现和强势股池，统一字段后写入研究数据目录。
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


SOURCE_SPECS = (
    ("zt_pool", "stock_zt_pool_em", "涨停池"),
    ("zbgc_pool", "stock_zt_pool_zbgc_em", "炸板池"),
    ("previous_pool", "stock_zt_pool_previous_em", "昨日涨停表现"),
    ("strong_pool", "stock_zt_pool_strong_em", "强势股池"),
)

STANDARD_COLUMNS = [
    "trade_date",
    "source",
    "ts_code",
    "name",
    "pct_chg",
    "amount",
    "float_mv",
    "turnover_rate",
    "seal_amount",
    "first_limit_time",
    "last_limit_time",
    "open_count",
    "limit_days",
    "limit_up_reason",
    "industry",
    "concept",
]

CORE_FIELDS = [
    "ts_code",
    "name",
    "first_limit_time",
    "seal_amount",
    "open_count",
    "limit_days",
    "limit_up_reason",
]

COLUMN_ALIASES = {
    "ts_code": ("代码", "股票代码", "证券代码", "code", "ts_code"),
    "name": ("名称", "股票简称", "证券简称", "name"),
    "pct_chg": ("涨跌幅", "涨幅", "最新涨跌幅", "change", "pct_chg"),
    "amount": ("成交额", "成交金额", "amount"),
    "float_mv": ("流通市值", "流通市场值", "float_mv"),
    "turnover_rate": ("换手率", "turnover_rate"),
    "seal_amount": ("封板资金", "封单资金", "封单金额", "封成比", "seal_amount"),
    "first_limit_time": ("首次封板时间", "首次涨停时间", "首封时间", "first_limit_time"),
    "last_limit_time": ("最后封板时间", "最后涨停时间", "最终封板时间", "last_limit_time"),
    "open_count": ("炸板次数", "开板次数", "open_count"),
    "limit_days": ("连板数", "几天几板", "连续涨停", "limit_days"),
    "limit_up_reason": ("涨停原因", "原因", "涨停原因类别", "limit_up_reason"),
    "industry": ("所属行业", "行业", "industry"),
    "concept": ("所属概念", "概念", "题材", "concept"),
}


def collect_limit_pool_for_date(
    trade_date: str,
    output_root: str | Path = "data_research",
    ak_module: Any | None = None,
) -> dict:
    """采集单日涨停池研究数据并写入 parquet 与质量报告。"""
    trade_date = _normalize_date(trade_date)
    root = Path(output_root)
    data_dir = root / "limit_pool"
    report_dir = root / "reports"
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    ak = ak_module or _load_akshare()
    frames: list[pd.DataFrame] = []
    source_counts: dict[str, int] = {}
    errors: list[str] = []
    for source, func_name, label in SOURCE_SPECS:
        try:
            func = getattr(ak, func_name)
            raw = func(date=trade_date)
            frame = normalize_limit_pool_frame(raw, source=source, trade_date=trade_date)
            frames.append(frame)
            source_counts[source] = len(frame)
        except Exception as exc:  # 研究采集不中断，错误写入质量报告
            source_counts[source] = 0
            errors.append(f"{label}({func_name}) failed: {exc}")

    combined = pd.concat(frames, ignore_index=True) if frames else _empty_frame()
    if not combined.empty:
        combined = combined.drop_duplicates(["trade_date", "source", "ts_code"], keep="first")
    data_path = data_dir / f"{trade_date}.parquet"
    combined.to_parquet(data_path, index=False)

    result = {
        "trade_date": trade_date,
        "ok": bool(len(combined) > 0 and not errors),
        "total_rows": int(len(combined)),
        "source_counts": source_counts,
        "missing_core_fields": missing_core_fields(combined),
        "data_path": str(data_path),
        "report_path": str(report_dir / f"limit_pool_data_quality_{trade_date}.md"),
        "errors": errors,
    }
    Path(result["report_path"]).write_text(format_quality_report(result), encoding="utf-8")
    return result


def collect_limit_pool_range(
    start_date: str,
    end_date: str,
    output_root: str | Path = "data_research",
    trade_dates: list[str] | None = None,
    ak_module: Any | None = None,
    sleep_seconds: float = 0.5,
) -> dict:
    """按交易日区间批量采集涨停池研究数据。"""
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    dates = _trade_dates_in_range(start, end, trade_dates)
    ak = ak_module or _load_akshare()
    results = []
    for idx, trade_date in enumerate(dates, start=1):
        result = collect_limit_pool_for_date(trade_date, output_root=output_root, ak_module=ak)
        results.append(result)
        if sleep_seconds > 0 and idx < len(dates):
            time.sleep(sleep_seconds)
    return {
        "start_date": start,
        "end_date": end,
        "total_days": len(dates),
        "non_empty_days": sum(1 for item in results if int(item.get("total_rows", 0) or 0) > 0),
        "ok_days": sum(1 for item in results if item.get("ok")),
        "total_rows": sum(int(item.get("total_rows", 0) or 0) for item in results),
        "results": results,
    }


def normalize_limit_pool_frame(raw: pd.DataFrame | None, source: str, trade_date: str) -> pd.DataFrame:
    """把不同 AkShare 接口字段统一成研究侧标准字段。"""
    if raw is None or raw.empty:
        return _empty_frame()

    work = raw.copy()
    result = pd.DataFrame()
    result["trade_date"] = [_normalize_date(trade_date)] * len(work)
    result["source"] = [source] * len(work)

    for standard, aliases in COLUMN_ALIASES.items():
        col = _pick_column(work, aliases)
        if col:
            result[standard] = work[col]
        else:
            result[standard] = ""

    result["ts_code"] = result["ts_code"].map(_normalize_ts_code)
    for col in ("pct_chg", "amount", "float_mv", "turnover_rate", "seal_amount", "open_count", "limit_days"):
        result[col] = pd.to_numeric(result[col], errors="coerce")
    for col in STANDARD_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    return result[STANDARD_COLUMNS]


def missing_core_fields(frame: pd.DataFrame) -> list[str]:
    """返回当前数据缺失严重的关键字段。"""
    if frame is None or frame.empty:
        return CORE_FIELDS[:]
    missing = []
    for col in CORE_FIELDS:
        if col not in frame.columns:
            missing.append(col)
            continue
        series = frame[col]
        empty_ratio = series.isna().mean() if pd.api.types.is_numeric_dtype(series) else series.astype(str).str.strip().eq("").mean()
        if empty_ratio >= 0.8:
            missing.append(col)
    return missing


def format_quality_report(result: dict) -> str:
    """格式化研究数据质量报告。"""
    lines = [
        "# 涨停池数据质量报告",
        "",
        f"- 日期：`{result.get('trade_date')}`",
        f"- 状态：`{'完成' if result.get('ok') else '需检查'}`",
        f"- 总记录数：`{result.get('total_rows', 0)}`",
        f"- 数据文件：`{result.get('data_path')}`",
        "",
        "## 来源覆盖",
    ]
    for source, count in (result.get("source_counts") or {}).items():
        lines.append(f"- `{source}`：{count} 条")

    lines.extend(["", "## 关键字段缺口"])
    missing = result.get("missing_core_fields") or []
    if missing:
        for field in missing:
            lines.append(f"- `{field}`")
    else:
        lines.append("- 无明显缺口")

    lines.extend(["", "## 采集错误"])
    errors = result.get("errors") or []
    if errors:
        for error in errors:
            lines.append(f"- {error}")
    else:
        lines.append("- 无")
    lines.append("")
    return "\n".join(lines)


def _load_akshare():
    import akshare as ak

    return ak


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def _pick_column(frame: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    columns = {str(col).strip(): col for col in frame.columns}
    for alias in aliases:
        if alias in columns:
            return columns[alias]
    for alias in aliases:
        for text, original in columns.items():
            if alias and alias in text:
                return original
    return None


def _normalize_ts_code(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "." in text:
        code, suffix = text.split(".", 1)
        return f"{code.zfill(6)}.{suffix.upper()}"
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 6:
        return text
    code = digits[-6:]
    suffix = "SH" if code.startswith(("6", "9")) else "BJ" if code.startswith(("8", "4")) else "SZ"
    return f"{code}.{suffix}"


def _normalize_date(value: str) -> str:
    text = str(value or "").strip().replace("-", "")
    if len(text) == 8 and text.isdigit():
        return text
    return datetime.strptime(str(value), "%Y-%m-%d").strftime("%Y%m%d")


def _trade_dates_in_range(start: str, end: str, trade_dates: list[str] | None = None) -> list[str]:
    if trade_dates is None:
        trade_dates = _load_cached_trade_dates()
    normalized = sorted(
        date
        for date in (_normalize_date(item) for item in (trade_dates or []))
        if start <= date <= end
    )
    if normalized:
        return normalized
    return pd.bdate_range(start=datetime.strptime(start, "%Y%m%d"), end=datetime.strptime(end, "%Y%m%d")).strftime("%Y%m%d").tolist()


def _load_cached_trade_dates(cache_path: str | Path = "data/cache/trade_cal.parquet") -> list[str]:
    path = Path(cache_path)
    if not path.exists():
        return []
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return []
    if frame.empty or "cal_date" not in frame.columns:
        return []
    if "is_open" in frame.columns:
        frame = frame[pd.to_numeric(frame["is_open"], errors="coerce").fillna(0).astype(int) == 1]
    return frame["cal_date"].astype(str).tolist()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集涨停池/炸板池等龙头雷达研究数据。")
    parser.add_argument("--date", help="交易日期，格式 YYYYMMDD")
    parser.add_argument("--start", help="开始交易日期，格式 YYYYMMDD")
    parser.add_argument("--end", help="结束交易日期，格式 YYYYMMDD")
    parser.add_argument("--output-root", default="data_research", help="研究数据输出根目录")
    parser.add_argument("--sleep", type=float, default=0.5, help="批量采集时每个交易日之间的暂停秒数")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.start or args.end:
        if not args.start or not args.end:
            raise SystemExit("--start 和 --end 必须同时提供")
        result = collect_limit_pool_range(args.start, args.end, output_root=args.output_root, sleep_seconds=args.sleep)
        print(
            f"采集完成：{result['start_date']}~{result['end_date']} "
            f"交易日 {result['total_days']} 天，非空 {result['non_empty_days']} 天，总记录 {result['total_rows']} 条"
        )
        return 0 if result["non_empty_days"] > 0 else 1
    if not args.date:
        raise SystemExit("请提供 --date 或 --start/--end")
    result = collect_limit_pool_for_date(args.date, output_root=args.output_root)
    print(format_quality_report(result))
    return 0 if result["total_rows"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
