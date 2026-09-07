# Ten Year OOS Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a defensible ten-year out-of-sample validation workflow for short-term stock-picking strategies.

**Architecture:** Keep the live stock-picking logic untouched. Add research-only scripts and docs that audit cache coverage, download missing historical data, run a fixed strategy matrix by explicit year ranges, and summarize annual robustness metrics.

**Tech Stack:** Python, pandas, existing `data_downloader.py`, existing `backtest_v2.py`, existing `strategy_profiles.py`, local parquet cache in `data/cache`.

---

## File Structure

- Modify: `docs/superpowers/specs/2026-07-03-ten-year-oos-validation-design.md`
  - Records the anti-overfitting validation design, current cache coverage, data risks, and acceptance criteria.
- Create: `research/ten_year_cache_audit.py`
  - Reads local parquet cache directories and writes a per-year coverage report.
- Create: `research/ten_year_strategy_matrix.py`
  - Runs a fixed list of existing strategy profiles across explicit year ranges and writes a summary CSV.
- Modify: `docs/EXPERIMENT_LOG.md`
  - Adds a dated note that strategy research has shifted from per-year tuning to walk-forward validation.

## Task 1: Cache Coverage Audit Script

**Files:**
- Create: `research/ten_year_cache_audit.py`

- [ ] **Step 1: Write the script**

```python
from __future__ import annotations

import argparse
import collections
from pathlib import Path

import pandas as pd


DATASETS = ("daily", "daily_basic", "moneyflow", "index_daily")


def collect_dates(cache_dir: Path, dataset: str) -> list[str]:
    folder = cache_dir / dataset
    if not folder.exists():
        return []
    return sorted(path.stem for path in folder.glob("*.parquet") if len(path.stem) == 8)


def build_rows(cache_dir: Path) -> list[dict]:
    rows = []
    for dataset in DATASETS:
        dates = collect_dates(cache_dir, dataset)
        counts = collections.Counter(date[:4] for date in dates)
        for year in sorted(counts):
            rows.append(
                {
                    "dataset": dataset,
                    "year": year,
                    "trading_days": counts[year],
                    "first_date": min(date for date in dates if date.startswith(year)),
                    "last_date": max(date for date in dates if date.startswith(year)),
                }
            )
        if not dates:
            rows.append(
                {
                    "dataset": dataset,
                    "year": "",
                    "trading_days": 0,
                    "first_date": "",
                    "last_date": "",
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit local ten-year cache coverage.")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--output", default="backtest_results/ten_year_cache_coverage.csv")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    rows = build_rows(cache_dir)
    df = pd.DataFrame(rows)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False, encoding="utf-8-sig")
    print(df.to_string(index=False))
    print(f"saved: {output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the audit**

Run: `python research/ten_year_cache_audit.py`

Expected: CSV saved to `backtest_results/ten_year_cache_coverage.csv`, showing 2023-2026 coverage and 2016-2022 gaps.

## Task 2: Historical Data Download

**Files:**
- Use: `data_downloader.py`

- [x] **Progress 2026-07-03: staged stock-core download started**

Completed with `--core-only` first, because historical `index_daily` is much slower and should be handled separately:

- 2026 late gap: `python data_downloader.py --start 20260626 --end 20260630 --market-core`
- 2016 stock core: `python data_downloader.py --start 20160101 --end 20161231 --core-only`
- 2017 stock core: `python data_downloader.py --start 20170101 --end 20171231 --core-only`
- 2018 stock core: `python data_downloader.py --start 20180101 --end 20181231 --core-only`
- 2019 stock core: `python data_downloader.py --start 20190101 --end 20191231 --core-only`
- 2020 stock core: `python data_downloader.py --start 20200101 --end 20201231 --core-only`
- 2021 stock core: `python data_downloader.py --start 20210101 --end 20211231 --core-only`

Coverage audit after these runs:

- `daily` / `daily_basic` / `moneyflow`: 2016, 2017, 2018, 2019, 2020, 2021 are complete.
- 2026 `index_daily` now reaches 20260630.
- Historical `index_daily` for 2016-2021 is still incomplete and should be downloaded or optimized separately before using market-regime/industry-index-dependent conclusions.
- Remaining stock-core gaps for the ten-year plan: 2022.

- [ ] **Step 1: Download missing core market data**

Run: `python data_downloader.py --start 20160101 --end 20221231 --market-core`

Expected: `data/cache/daily`, `data/cache/daily_basic`, `data/cache/moneyflow`, and `data/cache/index_daily` gain complete trading-day files for 2016-2022.

- [ ] **Step 2: Fill late 2026 index gap**

Run: `python data_downloader.py --start 20260626 --end 20260630 --market-core`

Expected: `data/cache/index_daily` extends to 20260630 if the upstream source has those dates.

- [ ] **Step 3: Re-run coverage audit**

Run: `python research/ten_year_cache_audit.py`

Expected: 2016-2022 annual rows appear for all four datasets, and 2026 index coverage is no longer behind daily coverage.

## Task 3: Strategy Matrix Runner

**Files:**
- Create: `research/ten_year_strategy_matrix.py`

- [ ] **Step 1: Implement fixed strategy matrix runner**

```python
from __future__ import annotations

import argparse
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
    {"name": "v9_top1_hold8", "factor": "profile_v9_sector_quality_guard", "gate": "adaptive_quality_v6", "hold": 8, "topn": 1},
    {"name": "v9_top3_hold8", "factor": "profile_v9_sector_quality_guard", "gate": "adaptive_quality_v6", "hold": 8, "topn": 3},
    {"name": "v19_top1_hold3", "factor": "profile_v19_calm_followthrough", "gate": "adaptive_quality_v19", "hold": 3, "topn": 1},
    {"name": "v23_top1_hold3", "factor": "profile_v23_cautious_window", "gate": "adaptive_quality_v23", "hold": 3, "topn": 1},
    {"name": "v25_top1_hold3", "factor": "profile_v19_calm_followthrough", "gate": "adaptive_quality_v25", "hold": 3, "topn": 1},
    {"name": "v27_top1_hold3", "factor": "profile_v21_sector_calm_followthrough", "gate": "adaptive_quality_v27", "hold": 3, "topn": 1},
    {"name": "v28_top1_hold3", "factor": "profile_v21_sector_calm_followthrough", "gate": "adaptive_quality_v28", "hold": 3, "topn": 1},
]


def latest_metrics(before: set[Path]) -> Path | None:
    files = set(Path("backtest_results").glob("metrics_*.json"))
    new_files = sorted(files - before, key=lambda path: path.stat().st_mtime)
    return new_files[-1] if new_files else None


def run_one(strategy: dict, label: str, start: str, end: str) -> dict:
    before = set(Path("backtest_results").glob("metrics_*.json"))
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
    ]
    completed = subprocess.run(cmd, text=True)
    metrics_path = latest_metrics(before)
    row = {
        "strategy": strategy["name"],
        "period": label,
        "start": start,
        "end": end,
        "returncode": completed.returncode,
        "metrics_file": str(metrics_path) if metrics_path else "",
    }
    if metrics_path:
        with metrics_path.open("r", encoding="utf-8") as fh:
            metrics = json.load(fh)
        for key in (
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
        ):
            row[key] = metrics.get(key)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fixed ten-year short strategy matrix.")
    parser.add_argument("--output-dir", default="backtest_results")
    parser.add_argument("--only-period", action="append", default=[])
    parser.add_argument("--only-strategy", action="append", default=[])
    args = parser.parse_args()

    periods = [item for item in PERIODS if not args.only_period or item[0] in args.only_period]
    strategies = [item for item in STRATEGIES if not args.only_strategy or item["name"] in args.only_strategy]

    rows = []
    for strategy in strategies:
        for label, start, end in periods:
            rows.append(run_one(strategy, label, start, end))

    output = Path(args.output_dir) / f"ten_year_strategy_matrix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    pd.DataFrame(rows).to_csv(output, index=False, encoding="utf-8-sig")
    print(f"saved: {output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test one known slice**

Run: `python research/ten_year_strategy_matrix.py --only-period 2025 --only-strategy v19_top1_hold3`

Expected: one-row CSV with v19 2025 metrics near the known result: 22 trades, 72.73% win rate, 109.57% return.

- [ ] **Step 3: Run the full matrix after data is complete**

Run: `python research/ten_year_strategy_matrix.py`

Expected: CSV containing 7 strategies times 11 periods, with failed or no-trade periods visible instead of silently ignored.

## Task 4: Experiment Log Update

**Files:**
- Modify: `docs/EXPERIMENT_LOG.md`

- [ ] **Step 1: Add the 2026-07-03 research pivot note**

Append this section:

```markdown
## 2026-07-03 十年样本外验证切换

我们停止用 2025/2026 的漂亮结果继续反向调参。后续短线策略研究改为 walk-forward 样本外验证：2016-2019 用于发现规律，2020-2021 用于第一轮验证，2022-2024 用于压力测试，2025-2026H1 封存为最终验收。

当前缓存主要覆盖 2023-2026H1，不是连续十年数据。下一步先补齐 2016-2022 核心行情缓存，再对 v9、v19、v23、v25、v27、v28 做统一年度矩阵回测。策略进入线上前必须解释最差年份、交易数、回撤和连续亏损，不能只看单年收益最高。
```

- [ ] **Step 2: Verify docs mention the pivot**

Run: `rg "十年样本外验证|walk-forward|2016-2019" docs`

Expected: output includes this plan, the design spec, and `docs/EXPERIMENT_LOG.md`.

## Task 5: Verification

**Files:**
- Test: `research/ten_year_cache_audit.py`
- Test: `research/ten_year_strategy_matrix.py`

- [ ] **Step 1: Run syntax checks**

Run: `python -m py_compile research/ten_year_cache_audit.py research/ten_year_strategy_matrix.py`

Expected: exit code 0.

- [ ] **Step 2: Run cache audit**

Run: `python research/ten_year_cache_audit.py`

Expected: coverage CSV is written and printed.

- [ ] **Step 3: Run one strategy matrix smoke test**

Run: `python research/ten_year_strategy_matrix.py --only-period 2025 --only-strategy v19_top1_hold3`

Expected: one matrix CSV is written; v19 2025 result matches the known backtest order of magnitude.

## Progress 2026-07-03: Data Foundation Filled

- Completed 2022 stock core with `python data_downloader.py --start 20220101 --end 20221231 --core-only`.
- Added `research/fill_index_daily_range.py` for fast index cache backfill.
- Rebuilt 2016-2026H1 `index_daily` using `index_daily` for market indices and `sw_daily` for Shenwan industry indices:
  `python research/fill_index_daily_range.py --start 20160101 --end 20260630 --force --pause 1.0`.
- Coverage audit now shows `daily` / `daily_basic` / `moneyflow` / `index_daily` present for 2016-2026H1.
- Index row-quality audit: 2016-2025 every trading-day file has at least 20 rows; 2026H1 has 116/122 such files. The 6 zero-row dates are also zero-row in stock core tables, so they are calendar shell/non-trading dates rather than index-only gaps.
