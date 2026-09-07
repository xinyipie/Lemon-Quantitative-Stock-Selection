from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


KEY_COLUMNS = ["select_date", "ts_code"]
NUMERIC_COLUMNS = [
    "profit_after_fee",
    "profit_pct",
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
    "hit_3pct",
    "hit_5pct",
    "factor_sector",
    "factor_pattern",
    "factor_wyckoff",
    "factor_inflow",
    "factor_drawdown",
    "volume_ratio",
    "drawdown_from_high",
    "limit_up_count",
    "limit_down_count",
    "sector_ma10_ratio",
    "consensus_votes",
    "consensus_avg_rank",
    "consensus_avg_score",
    "consensus_score",
]
SHOW_COLUMNS = [
    "select_date",
    "ts_code",
    "name",
    "profit_after_fee",
    "mfe_pct",
    "mae_pct",
    "hit_3pct",
    "hit_5pct",
    "exit_reason",
    "market_style",
    "macro_mode",
    "factor_sector",
    "factor_pattern",
    "factor_wyckoff",
    "volume_ratio",
    "drawdown_from_high",
    "limit_up_count",
    "limit_down_count",
    "sector_ma10_ratio",
    "consensus_avg_rank",
    "consensus_score",
]
FACTOR_COLUMNS = [
    "factor_sector",
    "factor_pattern",
    "factor_wyckoff",
    "factor_inflow",
    "factor_drawdown",
    "volume_ratio",
    "drawdown_from_high",
    "limit_up_count",
    "limit_down_count",
    "sector_ma10_ratio",
    "consensus_avg_rank",
    "consensus_score",
]


def load_trades(path: str | Path) -> pd.DataFrame:
    return normalize_trades(pd.read_csv(path, encoding="utf-8-sig"))


def normalize_trades(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in KEY_COLUMNS:
        if col not in out.columns:
            raise ValueError(f"missing required column: {col}")
    out["select_date"] = pd.to_numeric(out["select_date"], errors="coerce").fillna(0).astype(int)
    out["ts_code"] = out["ts_code"].fillna("").astype(str)
    for col in NUMERIC_COLUMNS:
        if col in out.columns:
            if out[col].dtype == bool:
                out[col] = out[col].astype(float)
            else:
                out[col] = pd.to_numeric(out[col], errors="coerce")
    if "profit_after_fee" not in out.columns:
        if "profit_pct" not in out.columns:
            raise ValueError("missing return column: profit_after_fee or profit_pct")
        out["profit_after_fee"] = out["profit_pct"]
    if "hit_3pct" not in out.columns:
        out["hit_3pct"] = out.get("mfe_pct", pd.Series(0.0, index=out.index)) >= 3.0
    if "hit_5pct" not in out.columns:
        out["hit_5pct"] = out.get("mfe_pct", pd.Series(0.0, index=out.index)) >= 5.0
    return out


def build_delta_audit(
    base: pd.DataFrame,
    compare: pd.DataFrame,
    base_label: str = "base",
    compare_label: str = "compare",
) -> dict:
    base_df = normalize_trades(base)
    compare_df = normalize_trades(compare)
    base_keys = _key_frame(base_df)
    compare_keys = _key_frame(compare_df)
    common_keys = base_keys.merge(compare_keys, on=KEY_COLUMNS, how="inner")

    base_only = _anti_join(base_df, compare_keys)
    compare_only = _anti_join(compare_df, base_keys)
    common_base = base_df.merge(common_keys, on=KEY_COLUMNS, how="inner")
    common_compare = compare_df.merge(common_keys, on=KEY_COLUMNS, how="inner")

    summary = [
        _summary_row("common", common_base),
        _summary_row(f"{base_label}_only", base_only),
        _summary_row(f"{compare_label}_only", compare_only),
        _summary_row(base_label, base_df),
        _summary_row(compare_label, compare_df),
    ]
    factor_delta = _factor_delta(base_only, compare_only, base_label, compare_label)
    return {
        "base_label": base_label,
        "compare_label": compare_label,
        "summary": summary,
        "factor_delta": factor_delta,
        "base_only": _sort_trades(base_only),
        "compare_only": _sort_trades(compare_only),
        "common_base": _sort_trades(common_base),
        "common_compare": _sort_trades(common_compare),
    }


def write_delta_audit(
    base_path: str | Path,
    compare_path: str | Path,
    output: str | Path,
    base_label: str = "base",
    compare_label: str = "compare",
) -> dict:
    result = build_delta_audit(
        load_trades(base_path),
        load_trades(compare_path),
        base_label=base_label,
        compare_label=compare_label,
    )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    detail = _detail_frame(result, base_label, compare_label)
    detail.to_csv(output, index=False, encoding="utf-8-sig")

    summary = {
        "base_label": base_label,
        "compare_label": compare_label,
        "base_path": str(base_path),
        "compare_path": str(compare_path),
        "output": str(output),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": result["summary"],
        "factor_delta": result["factor_delta"],
    }
    output.with_suffix(".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output.with_suffix(".md").write_text(_format_markdown(result, summary), encoding="utf-8")
    return summary


def _key_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df[KEY_COLUMNS].drop_duplicates().copy()


def _anti_join(left: pd.DataFrame, right_keys: pd.DataFrame) -> pd.DataFrame:
    merged = left.merge(right_keys.assign(_in_right=True), on=KEY_COLUMNS, how="left")
    return merged[merged["_in_right"].isna()].drop(columns=["_in_right"]).copy()


def _summary_row(bucket: str, df: pd.DataFrame) -> dict:
    trades = len(df)
    ret = pd.to_numeric(df.get("profit_after_fee", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    hit3 = _bool_rate(df.get("hit_3pct", pd.Series(dtype=bool)))
    hit5 = _bool_rate(df.get("hit_5pct", pd.Series(dtype=bool)))
    return {
        "bucket": bucket,
        "trades": int(trades),
        "wins": int((ret > 0).sum()),
        "losses": int((ret <= 0).sum()) if trades else 0,
        "win_rate": round(float((ret > 0).mean() * 100.0), 2) if trades else 0.0,
        "total_profit_after_fee": round(float(ret.sum()), 2),
        "avg_profit_after_fee": round(float(ret.mean()), 2) if trades else 0.0,
        "avg_mfe_pct": _mean(df, "mfe_pct"),
        "avg_mae_pct": _mean(df, "mae_pct"),
        "hit_3pct_rate": hit3,
        "hit_5pct_rate": hit5,
    }


def _factor_delta(base_only: pd.DataFrame, compare_only: pd.DataFrame, base_label: str, compare_label: str) -> list[dict]:
    rows = []
    for col in FACTOR_COLUMNS:
        if col not in base_only.columns and col not in compare_only.columns:
            continue
        base_avg = _mean(base_only, col)
        compare_avg = _mean(compare_only, col)
        rows.append(
            {
                "factor": col,
                f"{base_label}_only_avg": base_avg,
                f"{compare_label}_only_avg": compare_avg,
                "diff": round(base_avg - compare_avg, 2),
            }
        )
    return sorted(rows, key=lambda item: abs(item["diff"]), reverse=True)


def _detail_frame(result: dict, base_label: str, compare_label: str) -> pd.DataFrame:
    frames = []
    for bucket, key in (
        (f"{base_label}_only", "base_only"),
        (f"{compare_label}_only", "compare_only"),
        ("common_base", "common_base"),
        ("common_compare", "common_compare"),
    ):
        df = result[key].copy()
        if df.empty:
            continue
        cols = [col for col in SHOW_COLUMNS if col in df.columns]
        part = df[cols].copy()
        part.insert(0, "bucket", bucket)
        frames.append(part)
    if not frames:
        return pd.DataFrame(columns=["bucket"] + SHOW_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def _format_markdown(result: dict, summary: dict) -> str:
    lines = [
        "# 策略差异样本审计",
        "",
        f"- 基准：`{summary['base_label']}`",
        f"- 对比：`{summary['compare_label']}`",
        f"- 基准文件：`{summary['base_path']}`",
        f"- 对比文件：`{summary['compare_path']}`",
        "",
        "## 样本贡献",
        "",
        "| 分组 | 交易数 | 胜率 | 收益合计 | 平均收益 | MFE | MAE | 3%命中 | 5%命中 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["summary"]:
        lines.append(
            "| {bucket} | {trades} | {win:.2f}% | {total:+.2f}% | {avg:+.2f}% | {mfe:+.2f}% | {mae:+.2f}% | {hit3:.2f}% | {hit5:.2f}% |".format(
                bucket=row["bucket"],
                trades=row["trades"],
                win=row["win_rate"],
                total=row["total_profit_after_fee"],
                avg=row["avg_profit_after_fee"],
                mfe=row["avg_mfe_pct"],
                mae=row["avg_mae_pct"],
                hit3=row["hit_3pct_rate"],
                hit5=row["hit_5pct_rate"],
            )
        )

    lines.extend(["", "## 独有样本因子差异", ""])
    if result["factor_delta"]:
        base_label = summary["base_label"]
        compare_label = summary["compare_label"]
        lines.append(f"| 因子 | {base_label}独有均值 | {compare_label}独有均值 | 差异 |")
        lines.append("|---|---:|---:|---:|")
        for row in result["factor_delta"][:12]:
            lines.append(
                "| {factor} | {base:.2f} | {compare:.2f} | {diff:+.2f} |".format(
                    factor=row["factor"],
                    base=row[f"{base_label}_only_avg"],
                    compare=row[f"{compare_label}_only_avg"],
                    diff=row["diff"],
                )
            )
    else:
        lines.append("没有独有样本可比较。")

    lines.extend(["", "## 基准独有样本", ""])
    lines.append(_sample_table(result["base_only"]))
    lines.extend(["", "## 对比独有样本", ""])
    lines.append(_sample_table(result["compare_only"]))
    return "\n".join(lines) + "\n"


def _sample_table(df: pd.DataFrame, limit: int = 30) -> str:
    if df.empty:
        return "无。"
    cols = [col for col in SHOW_COLUMNS if col in df.columns]
    show = df[cols].head(limit).copy()
    return show.to_markdown(index=False)


def _sort_trades(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(KEY_COLUMNS).reset_index(drop=True)


def _mean(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    values = pd.to_numeric(df[col], errors="coerce").dropna()
    if values.empty:
        return 0.0
    return round(float(values.mean()), 2)


def _bool_rate(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    if series.dtype == bool:
        values = series
    elif pd.api.types.is_numeric_dtype(series):
        values = pd.to_numeric(series, errors="coerce").fillna(0.0) > 0
    else:
        text = series.astype(str).str.lower()
        values = text.isin(("true", "1", "1.0", "yes"))
    return round(float(values.mean() * 100.0), 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two strategy trade CSV files.")
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--compare", required=True, type=Path)
    parser.add_argument("--base-label", default="base")
    parser.add_argument("--compare-label", default="compare")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = write_delta_audit(
        args.base,
        args.compare,
        args.output,
        base_label=args.base_label,
        compare_label=args.compare_label,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
