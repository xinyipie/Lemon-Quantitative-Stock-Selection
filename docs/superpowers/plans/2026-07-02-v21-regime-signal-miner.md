# v21 Regime Signal Miner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-only miner that finds simple regime/factor rule candidates for short-line stocks that rise within 3-5 trading days across 2024, 2025, and 2026H1.

**Architecture:** Add one standalone research script that reads existing trade CSV files, derives simple factor buckets, scores rule candidates by per-period stability, and writes Markdown/JSON reports. Keep live selection and backtest engine behavior unchanged.

**Tech Stack:** Python standard library, pandas, existing `backtest_results/trades_*.csv` artifacts, Markdown/JSON reports.

---

### Task 1: Add Signal Miner Tests

**Files:**
- Create: `tests/test_short_signal_factor_miner.py`
- Create later: `research/short_signal_factor_miner.py`

- [ ] **Step 1: Write a focused unit test for metrics**

```python
import pandas as pd

from research.short_signal_factor_miner import summarize_rule


def test_summarize_rule_computes_short_window_metrics():
    df = pd.DataFrame(
        [
            {"period": "2024", "profit_after_fee": 2.0, "mfe_pct": 5.0, "mae_pct": -1.0, "window_end_pct": 1.0, "hit_3pct": True, "hit_5pct": True},
            {"period": "2024", "profit_after_fee": -1.0, "mfe_pct": 3.2, "mae_pct": -3.0, "window_end_pct": -0.5, "hit_3pct": True, "hit_5pct": False},
            {"period": "2025", "profit_after_fee": 4.0, "mfe_pct": 8.0, "mae_pct": -0.8, "window_end_pct": 3.0, "hit_3pct": True, "hit_5pct": True},
        ]
    )

    summary = summarize_rule("demo", df)

    assert summary["sample_count"] == 3
    assert summary["period_count"] == 2
    assert summary["win_rate"] == 66.67
    assert summary["hit_3pct_rate"] == 100.0
    assert summary["hit_5pct_rate"] == 66.67
    assert summary["avg_mfe_pct"] == 5.4
    assert summary["avg_mae_pct"] == -1.6
```

- [ ] **Step 2: Write a focused unit test for rule generation**

```python
import pandas as pd

from research.short_signal_factor_miner import build_rule_candidates


def test_build_rule_candidates_includes_sector_and_regime_buckets():
    df = pd.DataFrame(
        [
            {"period": "2024", "market_style": "weak_momentum", "macro_mode": "active", "factor_sector": 30.0, "profit_after_fee": 1.0, "mfe_pct": 4.0, "mae_pct": -1.0, "window_end_pct": 1.0, "hit_3pct": True, "hit_5pct": False},
            {"period": "2025", "market_style": "weak_momentum", "macro_mode": "active", "factor_sector": 70.0, "profit_after_fee": -1.0, "mfe_pct": 2.0, "mae_pct": -4.0, "window_end_pct": -1.0, "hit_3pct": False, "hit_5pct": False},
        ]
    )

    rules = build_rule_candidates(df, min_samples=1)
    names = {item["rule"] for item in rules}

    assert "market_style=weak_momentum" in names
    assert "factor_sector<=45" in names
    assert "factor_sector>60" in names
    assert "market_style=weak_momentum & factor_sector<=45" in names
```

- [ ] **Step 3: Run tests and verify they fail before implementation**

Run: `python -m unittest tests.test_short_signal_factor_miner`

Expected: import failure because `research.short_signal_factor_miner` does not exist.

### Task 2: Implement Research Miner

**Files:**
- Create: `research/short_signal_factor_miner.py`

- [ ] **Step 1: Add imports, constants, and CSV loading**

Implement a script with:

```python
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_FILES = (
    "backtest_results/trades_20260702_160634.csv",
    "backtest_results/trades_20260702_142957.csv",
    "backtest_results/trades_20260702_142535.csv",
)
DEFAULT_OUTPUT = Path("reports") / "short_signal_factor_miner.md"
NUMERIC_COLUMNS = (
    "profit_after_fee",
    "mfe_pct",
    "mae_pct",
    "window_end_pct",
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_wyckoff",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
    "score_base",
)
```

Add `load_trade_frames(paths)` that reads files with `utf-8-sig`, adds a `period` label from `backtest_start/backtest_end` if available or from file name fallback, and normalizes bool/numeric columns.

- [ ] **Step 2: Add metrics summarization**

Implement `summarize_rule(rule: str, df: pd.DataFrame) -> dict` with rounded metrics:

```python
{
    "rule": rule,
    "sample_count": int(len(df)),
    "period_count": int(df["period"].nunique()),
    "win_rate": percent(profit_after_fee > 0),
    "total_profit_pct": sum(profit_after_fee),
    "avg_profit_pct": mean(profit_after_fee),
    "avg_mfe_pct": mean(mfe_pct),
    "avg_mae_pct": mean(mae_pct),
    "avg_window_end_pct": mean(window_end_pct),
    "hit_3pct_rate": percent(hit_3pct),
    "hit_5pct_rate": percent(hit_5pct),
    "hit_10pct_rate": percent(hit_10pct) if present,
    "periods": [...]
}
```

- [ ] **Step 3: Add simple rule candidate generation**

Implement `build_rule_candidates(df, min_samples=3)` using:

Categorical rules:

```python
market_style=<value>
macro_mode=<value>
market_style=<value> & macro_mode=<value>
```

Numeric bucket rules:

```python
factor_sector<=45
factor_sector>60
factor_pattern<=40
factor_pattern>70
factor_wyckoff between 60 and 75
volume_ratio between 1.4 and 2.8
drawdown_from_high<=7
change<=4.5
```

Combination rules:

```python
market_style=<value> & <numeric rule>
macro_mode=<value> & <numeric rule>
market_style=<value> & macro_mode=<value> & <numeric rule>
```

- [ ] **Step 4: Add candidate classification**

Classify summaries with:

```python
candidate:
  sample_count >= min_samples
  period_count >= 2
  hit_3pct_rate >= 70
  hit_5pct_rate >= 50
  avg_profit_pct > 0

fragile:
  sample_count >= min_samples
  hit_3pct_rate >= 70
  avg_profit_pct > 0
  but period_count < 2 or hit_5pct_rate < 50

reject:
  everything else
```

Sort by classification, period count, hit_3pct rate, hit_5pct rate, average profit, and lower absolute MAE.

- [ ] **Step 5: Add report formatting and CLI**

Implement:

```python
def build_signal_miner_report(files=DEFAULT_FILES, min_samples=3) -> dict
def write_signal_miner_report(files=DEFAULT_FILES, output=DEFAULT_OUTPUT, min_samples=3) -> dict
def parse_args()
def main()
```

The Markdown report should include:

- Research boundary.
- Input files.
- Top candidate table.
- Fragile table.
- Rejected pattern table.
- Interpretation section.

### Task 3: Verify and Run Initial Scan

**Files:**
- Modify only if tests reveal issues: `research/short_signal_factor_miner.py`
- Test: `tests/test_short_signal_factor_miner.py`

- [ ] **Step 1: Run unit tests**

Run: `python -m unittest tests.test_short_signal_factor_miner`

Expected: all tests pass.

- [ ] **Step 2: Run existing strategy profile tests**

Run: `python -m unittest tests.test_strategy_profiles`

Expected: all tests pass.

- [ ] **Step 3: Run miner on known v19 files**

Run:

```bash
python research/short_signal_factor_miner.py --output reports/short_signal_factor_miner.md --min-samples 3
```

Expected:

- `reports/short_signal_factor_miner.md` exists.
- `reports/short_signal_factor_miner.json` exists.
- Report includes 2024, 2025, and 2026H1 input files.

- [ ] **Step 4: Read top candidates**

Inspect the Markdown and JSON report. Capture:

- Best candidate rules.
- Rules that explain 2024 failure.
- Whether trade-level sample size is enough or candidate-level `ic_short` mining is required next.

### Task 4: Decide Next Experiment

**Files:**
- No code required unless Task 3 shows a clear stable rule.

- [ ] **Step 1: Compare candidates against objective**

Check whether any candidate has:

- Multiple periods represented.
- 3-day hit rate at or above 70%.
- 5-day hit rate at or above 50%.
- Positive average final profit.
- Enough samples to be more than a tiny artifact.

- [ ] **Step 2: Choose next path**

If stable candidates exist, design v21 profile/gate using those rules.

If stable candidates do not exist, expand miner from trade-level files to `ic_short_*.csv` candidate-level files so we can discover rules outside the actually selected trades.

