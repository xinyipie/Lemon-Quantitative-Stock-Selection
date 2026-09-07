from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from broad_engine_factor_miner import _load_candidates, _predicates, _select
from live_readiness_optimizer import BASE_RULE, BASE_SCORE, BASE_TOPN, _build_base, _mask_for_names
from live_readiness_postmortem import _readiness, _recent_win_rate
from v45_engine_exit_backtest import _group_metrics, _metrics


REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
RESULTS_IN = REPORTS / "live_readiness_optimizer_20260707.csv"
SUMMARY_OUT = REPORTS / "live_ready_variant_compare_20260707.csv"
YEARLY_OUT = REPORTS / "live_ready_variant_compare_yearly_20260707.csv"
LAYER_OUT = REPORTS / "live_ready_variant_compare_layers_20260707.csv"
DOC_OUT = DOCS / "LIVE_READY_VARIANT_COMPARE_20260707.md"


def _variant_specs() -> list[dict]:
    results = pd.read_csv(RESULTS_IN, encoding="utf-8-sig")
    ready = results[results["status"].eq("ready")].copy()
    if ready.empty:
        return []
    picks = []
    selectors = [
        ("best_balance", ready.sort_values(["score"], ascending=False).head(1)),
        ("max_trades", ready.sort_values(["trades", "win_rate", "total_ret"], ascending=[False, False, False]).head(1)),
        ("max_return", ready.sort_values(["total_ret", "win_rate"], ascending=[False, False]).head(1)),
        ("best_win", ready.sort_values(["win_rate", "trades"], ascending=[False, False]).head(1)),
    ]
    seen = set()
    for name, frame in selectors:
        if frame.empty:
            continue
        row = frame.iloc[0]
        key = (row["addon_rule"], int(row["addon_topn"]), row["addon_score"])
        if key in seen:
            continue
        seen.add(key)
        picks.append(
            {
                "variant": name,
                "addon_rule": row["addon_rule"],
                "addon_topn": int(row["addon_topn"]),
                "addon_score": row["addon_score"],
            }
        )
    return picks


def build_compare() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df_raw = _load_candidates()
    predicate_map = {name: pred for name, pred in _predicates(df_raw)}
    df, _strong, base = _build_base(df_raw, predicate_map)
    base_pairs = set(zip(base["buy_date"].astype(str), base["ts_code"].astype(str)))

    summaries = []
    yearly_frames = []
    layer_frames = []
    for spec in _variant_specs():
        mask = _mask_for_names(df, str(spec["addon_rule"]).split(" & "), predicate_map)
        add = _select(df, mask, int(spec["addon_topn"]), str(spec["addon_score"]))
        add = add[
            ~add.apply(lambda row: (str(row.get("buy_date", "")), str(row.get("ts_code", ""))) in base_pairs, axis=1)
        ].copy()
        add["candidate_layer"] = "readiness_addon"
        trades = pd.concat([base, add], ignore_index=True, sort=False).drop_duplicates(["buy_date", "ts_code"], keep="first")
        trades["ret"] = pd.to_numeric(trades["ret"], errors="coerce").fillna(0.0)
        trades["win"] = trades["ret"] > 0
        metrics = _metrics(trades)
        status, blockers = _readiness(metrics, trades)
        summaries.append(
            {
                **spec,
                "status": status,
                "blockers": ";".join(blockers),
                "recent_win_rate": _recent_win_rate(trades),
                **metrics,
            }
        )
        yearly = _group_metrics(trades, "year").sort_values("year")
        yearly.insert(0, "variant", spec["variant"])
        yearly_frames.append(yearly)
        layers = _group_metrics(trades, "candidate_layer")
        layers.insert(0, "variant", spec["variant"])
        layer_frames.append(layers)

    return (
        pd.DataFrame(summaries),
        pd.concat(yearly_frames, ignore_index=True, sort=False) if yearly_frames else pd.DataFrame(),
        pd.concat(layer_frames, ignore_index=True, sort=False) if layer_frames else pd.DataFrame(),
    )


def _write_doc(summary: pd.DataFrame, yearly: pd.DataFrame, layers: pd.DataFrame) -> None:
    lines = [
        "# 可上线观察候选变体对比（2026-07-07）",
        "",
        "## 固定底座",
        "",
        f"- `strong_T1` + `{BASE_RULE}`，Top{BASE_TOPN}，`{BASE_SCORE}` 排序。",
        "",
        "## 变体汇总",
        "",
        summary.to_markdown(index=False, floatfmt=".2f") if not summary.empty else "无",
        "",
        "## 分层",
        "",
        layers.to_markdown(index=False, floatfmt=".2f") if not layers.empty else "无",
        "",
        "## 年度",
        "",
        yearly.to_markdown(index=False, floatfmt=".2f") if not yearly.empty else "无",
        "",
    ]
    DOC_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    summary, yearly, layers = build_compare()
    summary.to_csv(SUMMARY_OUT, index=False, encoding="utf-8-sig")
    yearly.to_csv(YEARLY_OUT, index=False, encoding="utf-8-sig")
    layers.to_csv(LAYER_OUT, index=False, encoding="utf-8-sig")
    _write_doc(summary, yearly, layers)
    print(summary.to_string(index=False))
    print()
    print(yearly.to_string(index=False))


if __name__ == "__main__":
    main()
