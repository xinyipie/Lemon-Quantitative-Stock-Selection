from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CACHE_DAILY = ROOT / "data" / "cache" / "daily"
REPORTS = ROOT / "reports"


@dataclass(frozen=True)
class EntryRule:
    name: str
    wait_days: int = 0
    pullback_pct: float | None = None
    trigger_window: int = 3


ENTRY_RULES = [
    EntryRule("direct_T1_open", wait_days=0),
    EntryRule("wait_T2_open", wait_days=1),
    EntryRule("wait_T3_open", wait_days=2),
    EntryRule("wait_T5_open", wait_days=4),
    EntryRule("pullback_1pct_3d", pullback_pct=1.0),
    EntryRule("pullback_2pct_3d", pullback_pct=2.0),
    EntryRule("pullback_3pct_3d", pullback_pct=3.0),
]


def _normalise_date(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace("-", "")[:8]


def _available_dates() -> list[str]:
    return sorted(p.stem for p in CACHE_DAILY.glob("*.parquet"))


def _next_trade_date(date: str, dates: list[str]) -> str:
    for d in dates:
        if d > date:
            return d
    return ""


def load_samples() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    inputs = [
        ("v35_top1", REPORTS / "v35_top1_annual_aggregate_trades_20260704.csv"),
        ("v39_top1", REPORTS / "v39_top1_annual_aggregate_trades_20260704.csv"),
        ("stage3_candidates", REPORTS / "stage3_candidate_consensus_topn_selected.csv"),
    ]
    dates = _available_dates()

    for sample_name, path in inputs:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df["sample"] = sample_name
        if "buy_date" not in df.columns:
            df["buy_date"] = df["select_date"].map(lambda x: _next_trade_date(_normalise_date(x), dates))
        keep = [
            "sample",
            "select_date",
            "buy_date",
            "ts_code",
            "ret_5d",
            "mfe_pct",
            "mae_pct",
            "hit_3pct",
            "hit_5pct",
            "factor_pattern",
            "macro_mode",
            "regime",
            "operation_mode",
        ]
        for col in keep:
            if col not in df.columns:
                df[col] = pd.NA
        frames.append(df[keep])

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    out["select_date"] = out["select_date"].map(_normalise_date)
    out["buy_date"] = out["buy_date"].map(_normalise_date)
    out = out[out["ts_code"].notna() & out["buy_date"].ne("")]
    return out.drop_duplicates(["sample", "select_date", "buy_date", "ts_code"]).reset_index(drop=True)


def load_daily_subset(samples: pd.DataFrame, extra_days: int = 16) -> pd.DataFrame:
    dates = _available_dates()
    min_date = samples["buy_date"].min()
    max_date = samples["buy_date"].max()
    end_idx = min(len(dates) - 1, dates.index(max_date) + extra_days) if max_date in dates else len(dates) - 1
    start_idx = max(0, dates.index(min_date) - 1) if min_date in dates else 0
    date_window = dates[start_idx : end_idx + 1]
    codes = set(samples["ts_code"].astype(str))

    frames: list[pd.DataFrame] = []
    for date in date_window:
        path = CACHE_DAILY / f"{date}.parquet"
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path, columns=["ts_code", "trade_date", "open", "high", "low", "close"])
        except Exception:
            try:
                df = pd.read_parquet(path)
            except Exception:
                continue
            required = ["ts_code", "open", "high", "low", "close"]
            if any(col not in df.columns for col in required):
                continue
            if "trade_date" not in df.columns:
                df = df.copy()
                df["trade_date"] = date
            df = df[["ts_code", "trade_date", "open", "high", "low", "close"]]
        df = df[df["ts_code"].isin(codes)]
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    daily = pd.concat(frames, ignore_index=True)
    daily["trade_date"] = daily["trade_date"].astype(str).str.replace("-", "").str[:8]
    return daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _future_path(code_df: pd.DataFrame, buy_date: str, max_len: int = 12) -> pd.DataFrame:
    idx = code_df.index[code_df["trade_date"] >= buy_date]
    if len(idx) == 0:
        return pd.DataFrame()
    pos = code_df.index.get_loc(idx[0])
    return code_df.iloc[pos : pos + max_len].reset_index(drop=True)


def _simulate_rule(path: pd.DataFrame, rule: EntryRule, hold_days: int = 5) -> dict | None:
    if len(path) <= rule.wait_days:
        return None

    base_open = float(path.iloc[0]["open"])
    if rule.pullback_pct is None:
        entry_idx = rule.wait_days
        entry_price = float(path.iloc[entry_idx]["open"])
    else:
        trigger = base_open * (1 - rule.pullback_pct / 100)
        entry_idx = None
        for i in range(min(rule.trigger_window, len(path))):
            if float(path.iloc[i]["low"]) <= trigger:
                entry_idx = i
                entry_price = trigger
                break
        if entry_idx is None:
            return None

    exit_idx = min(entry_idx + hold_days - 1, len(path) - 1)
    after_entry = path.iloc[entry_idx : exit_idx + 1]
    exit_close = float(path.iloc[exit_idx]["close"])
    ret = (exit_close / entry_price - 1) * 100
    mfe = (after_entry["high"].max() / entry_price - 1) * 100
    mae = (after_entry["low"].min() / entry_price - 1) * 100
    return {
        "rule": rule.name,
        "entry_date": path.iloc[entry_idx]["trade_date"],
        "entry_price": entry_price,
        "exit_date": path.iloc[exit_idx]["trade_date"],
        "ret_5d_from_entry": ret,
        "mfe_from_entry": mfe,
        "mae_from_entry": mae,
        "hit_3pct_from_entry": mfe >= 3,
        "win_from_entry": ret > 0,
        "entered": True,
    }


def build_event_rows(samples: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_by_code = {code: part.reset_index(drop=True) for code, part in daily.groupby("ts_code")}
    path_rows: list[dict] = []
    rule_rows: list[dict] = []

    for row in samples.itertuples(index=False):
        code_df = daily_by_code.get(str(row.ts_code))
        if code_df is None:
            continue
        path = _future_path(code_df, str(row.buy_date))
        if len(path) < 5:
            continue

        base_open = float(path.iloc[0]["open"])
        first3_low_pct = (path.iloc[:3]["low"].min() / base_open - 1) * 100
        first3_close_min_pct = (path.iloc[:3]["close"].min() / base_open - 1) * 100
        day5_high_pct = (path.iloc[:5]["high"].max() / base_open - 1) * 100
        day5_close_pct = (path.iloc[4]["close"] / base_open - 1) * 100
        day3_close_pct = (path.iloc[2]["close"] / base_open - 1) * 100 if len(path) >= 3 else pd.NA
        dip_then_rise_1_3 = first3_low_pct <= -1 and day5_high_pct >= 3
        dip_then_rise_2_3 = first3_low_pct <= -2 and day5_high_pct >= 3
        dip_then_rise_2_5 = first3_low_pct <= -2 and day5_high_pct >= 5

        base = row._asdict()
        path_rows.append(
            {
                **base,
                "base_open": base_open,
                "first3_low_pct": first3_low_pct,
                "first3_close_min_pct": first3_close_min_pct,
                "day3_close_pct": day3_close_pct,
                "day5_high_pct": day5_high_pct,
                "day5_close_pct": day5_close_pct,
                "dip_then_rise_1_3": dip_then_rise_1_3,
                "dip_then_rise_2_3": dip_then_rise_2_3,
                "dip_then_rise_2_5": dip_then_rise_2_5,
            }
        )

        for rule in ENTRY_RULES:
            result = _simulate_rule(path, rule)
            if result is None:
                continue
            rule_rows.append({**base, **result})

    return pd.DataFrame(path_rows), pd.DataFrame(rule_rows)


def _summary_bool_rate(s: pd.Series) -> float:
    return float(s.mean() * 100) if len(s) else 0.0


def summarise_paths(paths: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for sample, g in paths.groupby("sample"):
        rows.append(
            {
                "sample": sample,
                "events": len(g),
                "day5_win_rate": _summary_bool_rate(g["day5_close_pct"] > 0),
                "avg_day5_close_pct": g["day5_close_pct"].mean(),
                "avg_first3_low_pct": g["first3_low_pct"].mean(),
                "dip1_hit3_rate": _summary_bool_rate(g["dip_then_rise_1_3"]),
                "dip2_hit3_rate": _summary_bool_rate(g["dip_then_rise_2_3"]),
                "dip2_hit5_rate": _summary_bool_rate(g["dip_then_rise_2_5"]),
                "dip2_count": int((g["first3_low_pct"] <= -2).sum()),
                "dip2_day5_win_rate": _summary_bool_rate(g.loc[g["first3_low_pct"] <= -2, "day5_close_pct"] > 0),
                "no_dip2_day5_win_rate": _summary_bool_rate(g.loc[g["first3_low_pct"] > -2, "day5_close_pct"] > 0),
            }
        )
    return pd.DataFrame(rows)


def summarise_rules(rules: pd.DataFrame, total_events: pd.Series) -> pd.DataFrame:
    rows: list[dict] = []
    for (sample, rule), g in rules.groupby(["sample", "rule"]):
        total = int(total_events.get(sample, len(g)))
        rows.append(
            {
                "sample": sample,
                "rule": rule,
                "entered_trades": len(g),
                "entry_rate": len(g) / total * 100 if total else 0,
                "win_rate": _summary_bool_rate(g["win_from_entry"]),
                "avg_ret_5d": g["ret_5d_from_entry"].mean(),
                "total_ret_5d": g["ret_5d_from_entry"].sum(),
                "avg_mfe": g["mfe_from_entry"].mean(),
                "avg_mae": g["mae_from_entry"].mean(),
                "hit3_rate": _summary_bool_rate(g["hit_3pct_from_entry"]),
            }
        )
    return pd.DataFrame(rows).sort_values(["sample", "total_ret_5d"], ascending=[True, False])


def write_markdown(path_summary: pd.DataFrame, rule_summary: pd.DataFrame, output: Path) -> None:
    lines = [
        "# 延迟/回撤入场路径审计（2026-07-06）",
        "",
        "目标：验证“正式推荐后先跌几天、再开始涨”是否可以作为短线入场时点优化，而不是改选股本身。",
        "",
        "口径：以推荐后的 T+1 开盘为基准，复原后续日线 open/high/low/close；比较直接买、等待 T+2/T+3 开盘、以及 1%/2%/3% 回撤触发入场。收益均为入场后 5 个交易日收盘收益。",
        "",
        "## 路径现象",
        "",
        path_summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 入场规则对比",
        "",
        rule_summary.to_markdown(index=False, floatfmt=".2f"),
        "",
        "## 初步结论",
        "",
        "- 如果强策略样本中等待入场提升不明显，说明 v35/v39 这类信号更像“买点已经很紧”，乱等可能错过涨幅。",
        "- 如果大样本中回撤触发显著提高胜率但 entry_rate 下降，说明它更适合作为扩容层的入场过滤，而不是替代强策略。",
        "- 下一步应把该规则放进独立回测：只在空窗日或弱信号日等待回撤触发，强策略仍保持 T+1 买入口径。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    samples = load_samples()
    if samples.empty:
        raise SystemExit("No samples found")
    daily = load_daily_subset(samples)
    if daily.empty:
        raise SystemExit("No daily data found")

    paths, rules = build_event_rows(samples, daily)
    path_summary = summarise_paths(paths)
    rule_summary = summarise_rules(rules, paths.groupby("sample").size())

    paths_out = REPORTS / "delayed_entry_path_events_20260706.csv"
    rules_out = REPORTS / "delayed_entry_rule_events_20260706.csv"
    path_summary_out = REPORTS / "delayed_entry_path_summary_20260706.csv"
    rule_summary_out = REPORTS / "delayed_entry_rule_summary_20260706.csv"
    doc_out = ROOT / "docs" / "DELAYED_ENTRY_PATH_AUDIT_20260706.md"

    paths.to_csv(paths_out, index=False, encoding="utf-8-sig")
    rules.to_csv(rules_out, index=False, encoding="utf-8-sig")
    path_summary.to_csv(path_summary_out, index=False, encoding="utf-8-sig")
    rule_summary.to_csv(rule_summary_out, index=False, encoding="utf-8-sig")
    write_markdown(path_summary, rule_summary, doc_out)

    print(path_summary.to_string(index=False))
    print()
    print(rule_summary.to_string(index=False))
    print()
    print(f"wrote {doc_out}")


if __name__ == "__main__":
    main()
