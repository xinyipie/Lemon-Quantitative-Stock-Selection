from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


PERIODS = [
    ("2016", "20160101", "20161231"),
    ("2017", "20170101", "20171231"),
    ("2018", "20180101", "20181231"),
    ("2019", "20190101", "20191231"),
    ("2020", "20200101", "20201231"),
    ("2021", "20210101", "20211231"),
    ("2022", "20220101", "20221231"),
    ("2023", "20230101", "20231231"),
    ("2024", "20240101", "20241231"),
    ("2025", "20250101", "20251231"),
    ("2026H1", "20260101", "20260630"),
]


STRATEGIES = [
    {
        "name": "v9_top1_hold8",
        "factor": "profile_v9_sector_quality_guard",
        "gate": "adaptive_quality_v6",
        "hold": 8,
        "topn": 1,
    },
    {
        "name": "v9_top3_hold8",
        "factor": "profile_v9_sector_quality_guard",
        "gate": "adaptive_quality_v6",
        "hold": 8,
        "topn": 3,
    },
    {
        "name": "v19_top1_hold3",
        "factor": "profile_v19_calm_followthrough",
        "gate": "adaptive_quality_v19",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v23_top1_hold3",
        "factor": "profile_v23_cautious_window",
        "gate": "adaptive_quality_v23",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v25_top1_hold3",
        "factor": "profile_v19_calm_followthrough",
        "gate": "adaptive_quality_v25",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v27_top1_hold3",
        "factor": "profile_v21_sector_calm_followthrough",
        "gate": "adaptive_quality_v27",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v28_top1_hold3",
        "factor": "profile_v21_sector_calm_followthrough",
        "gate": "adaptive_quality_v28",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v29_consensus_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v29",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v29_consensus_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v29",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v30_consensus_heat_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v30",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v30_consensus_heat_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v30",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v31_consensus_layered_heat_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v31",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v31_consensus_layered_heat_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v31",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v32_consensus_moderate_heat_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v32",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v32_consensus_moderate_heat_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v32",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v33_consensus_dual_lane_breadth_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v33",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v33_consensus_dual_lane_breadth_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v33",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v34_consensus_cautious_down_friction_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v34",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v34_consensus_cautious_down_friction_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v34",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v35_consensus_cautious_high_pattern_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v35",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v35_consensus_cautious_high_pattern_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v35",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v36_consensus_snapshot_top_rule_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v36",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v36_consensus_snapshot_top_rule_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v36",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v37_consensus_quality_rerank_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v37",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v37_consensus_quality_rerank_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v37",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v38_consensus_rank_protected_rerank_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v38",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v38_consensus_rank_protected_rerank_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v38",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v39_consensus_strong_rank_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v39",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v39_consensus_strong_rank_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v39",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v40_dual_layer_gap_fill_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v40",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v40_dual_layer_gap_fill_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v40",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v41_strict_pattern_breadth_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v41",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v41_strict_pattern_breadth_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v41",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v42_pattern_breadth_rerank_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v42",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v42_pattern_breadth_rerank_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v42",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v43_cautious_rank_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v43",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v43_cautious_rank_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v43",
        "hold": 3,
        "topn": 2,
    },
    {
        "name": "v44_pattern_down_top1_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v44",
        "hold": 3,
        "topn": 1,
    },
    {
        "name": "v44_pattern_down_top2_hold3",
        "factor": "original",
        "gate": "none",
        "consensus": "v44",
        "hold": 3,
        "topn": 2,
    },
]


METRIC_KEYS = (
    "total_trades",
    "win_rate",
    "total_return_pct",
    "max_drawdown_pct",
    "avg_profit_after_fee",
    "max_consecutive_loss",
    "avg_mfe_pct",
    "avg_mae_pct",
    "hit_3pct_rate",
    "hit_5pct_rate",
)


def run_one(strategy: dict, label: str, start: str, end: str, metrics_dir: Path) -> dict:
    print(f"running: {strategy['name']} {label} [{start} ~ {end}]", flush=True)
    metrics_path = metrics_dir / f"{strategy['name']}_{label}.json"
    cmd = [
        sys.executable,
        "backtest_v2.py",
        "--mode",
        "short",
        "--offline",
        "--start",
        start,
        "--end",
        end,
        "--no-timing",
        "--hold",
        str(strategy["hold"]),
        "--topn",
        str(strategy["topn"]),
        "--factor-profile",
        strategy["factor"],
        "--style-gate",
        strategy["gate"],
        "--metrics-output",
        str(metrics_path),
    ]
    if strategy.get("consensus", "none") != "none":
        cmd.extend(["--consensus-profile", strategy["consensus"]])
    completed = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    row = {
        "strategy": strategy["name"],
        "period": label,
        "start": start,
        "end": end,
        "returncode": completed.returncode,
        "metrics_file": str(metrics_path) if metrics_path.exists() else "",
    }
    if metrics_path.exists():
        with metrics_path.open("r", encoding="utf-8") as fh:
            metrics = json.load(fh)
        for key in METRIC_KEYS:
            row[key] = metrics.get(key)
    elif completed.returncode == 0:
        for key in METRIC_KEYS:
            row[key] = 0
    print(f"done: {strategy['name']} {label} rc={completed.returncode}", flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fixed ten-year short strategy matrix.")
    parser.add_argument("--output-dir", default="backtest_results")
    parser.add_argument("--only-period", action="append", default=[])
    parser.add_argument("--only-strategy", action="append", default=[])
    parser.add_argument("--jobs", type=int, default=1, help="并发回测进程数，默认1")
    args = parser.parse_args()

    periods = [item for item in PERIODS if not args.only_period or item[0] in args.only_period]
    strategies = [item for item in STRATEGIES if not args.only_strategy or item["name"] in args.only_strategy]

    output_dir = Path(args.output_dir)
    run_tag = datetime.now().strftime('%Y%m%d_%H%M%S')
    metrics_dir = output_dir / "matrix_metrics" / run_tag
    metrics_dir.mkdir(parents=True, exist_ok=True)

    tasks = [
        (strategy, label, start, end)
        for strategy in strategies
        for label, start, end in periods
    ]
    rows = []
    jobs = max(1, args.jobs)
    if jobs == 1:
        for strategy, label, start, end in tasks:
            rows.append(run_one(strategy, label, start, end, metrics_dir))
    else:
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = [
                executor.submit(run_one, strategy, label, start, end, metrics_dir)
                for strategy, label, start, end in tasks
            ]
            for idx, future in enumerate(as_completed(futures), start=1):
                rows.append(future.result())
                print(f"progress: {idx}/{len(futures)}", flush=True)

    order = {}
    idx = 0
    for strategy in strategies:
        for label, _, _ in periods:
            order[(strategy["name"], label)] = idx
            idx += 1
    rows = sorted(rows, key=lambda row: order.get((row["strategy"], row["period"]), 10**9))

    output = output_dir / f"ten_year_strategy_matrix_{run_tag}.csv"
    pd.DataFrame(rows).to_csv(output, index=False, encoding="utf-8-sig")
    print(f"saved: {output}")


if __name__ == "__main__":
    main()
