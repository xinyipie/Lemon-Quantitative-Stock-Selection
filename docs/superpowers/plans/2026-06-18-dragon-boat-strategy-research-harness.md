# Dragon Boat Strategy Research Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first non-invasive research harness for Dragon Boat strategy work: inventory existing v9/v18 evidence, generate a research overview report, and document how to continue experiments without changing live defaults.

**Architecture:** Keep all new research work outside the live strategy path. Add a focused script under `research/` that reads existing reports, CSVs, and optional SQLite signal data, then writes Markdown/JSON summaries under `reports/research/`. Do not modify `main.py` defaults, live profile constants, or Web routing behavior.

**Tech Stack:** Python standard library, pandas, sqlite3, Markdown reports, unittest.

---

### Task 1: Research Asset Inventory

**Files:**
- Create: `research/strategy_research_overview.py`
- Test: `tests/test_strategy_research_overview.py`
- Output: `reports/research/dragon_boat_research_overview.md`

- [ ] **Step 1: Write the failing test**

Create `tests/test_strategy_research_overview.py` with a temp directory containing:

```python
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research.strategy_research_overview import build_research_overview, write_research_overview


class StrategyResearchOverviewTest(unittest.TestCase):
    def test_build_research_overview_summarizes_short_and_long_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = root / "reports"
            backtests = root / "backtest_results"
            data = root / "data"
            reports.mkdir()
            backtests.mkdir()
            data.mkdir()

            pd.DataFrame(
                [
                    {"select_date": "20260601", "ts_code": "000001.SZ", "score": 60, "rank": 1, "ret_5d": 5.2, "mfe": 8.0, "mae": -3.0},
                    {"select_date": "20260602", "ts_code": "000002.SZ", "score": 48, "rank": 2, "ret_5d": -2.0, "mfe": 1.0, "mae": -6.0},
                ]
            ).to_csv(backtests / "ic_short_20260618_120000.csv", index=False)

            pd.DataFrame(
                [
                    {"period": "2025H2", "ts_code": "000001.SZ", "name": "Alpha", "ret_80d": 10.0, "win_80d": 1, "beat_index_80d": 1, "score": 66.0},
                    {"period": "2025H2", "ts_code": "000002.SZ", "name": "Beta", "ret_80d": -4.0, "win_80d": 0, "beat_index_80d": 0, "score": 42.0},
                ]
            ).to_csv(reports / "longterm_pool_quality_2025H2_v18_market_sync_full.csv", index=False)

            overview = build_research_overview(root=root)

        self.assertEqual(overview["short"]["latest_ic_file"], "ic_short_20260618_120000.csv")
        self.assertEqual(overview["short"]["sample_count"], 2)
        self.assertEqual(overview["longterm"]["period_count"], 1)
        self.assertAlmostEqual(overview["longterm"]["avg_ret_80d"], 3.0)

    def test_write_research_overview_creates_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "reports").mkdir()
            (root / "backtest_results").mkdir()
            output = root / "reports" / "research" / "overview.md"
            write_research_overview(root=root, output=output)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            text = output.read_text(encoding="utf-8")
            self.assertIn("端午策略研究总览", text)
            payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertIn("short", payload)
            self.assertIn("longterm", payload)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
python -m unittest tests.test_strategy_research_overview
```

Expected: fail because `research.strategy_research_overview` does not exist.

- [ ] **Step 3: Implement the minimal script**

Create `research/strategy_research_overview.py` with:

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


SHORT_BASELINE = "profile_v4_adaptive_quality_v9_sector_quality_guard + baseline exit + Top3"
LONGTERM_RESEARCH = "longterm_quality_lifecycle_v18_market_sync"


def build_research_overview(root: str | Path = ".") -> dict:
    root = Path(root)
    short = summarize_short_assets(root / "backtest_results")
    longterm = summarize_longterm_assets(root / "reports")
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "principles": {
            "short_live_baseline": SHORT_BASELINE,
            "longterm_research_profile": LONGTERM_RESEARCH,
            "live_defaults_changed": False,
            "auto_trading": False,
        },
        "short": short,
        "longterm": longterm,
        "next_questions": [
            "短线 v9 的分数、资金、板块、形态因子在不同区间是否稳定正相关？",
            "长线 v18 的问题主要来自股票池过宽、入池时点、市场同步过滤，还是出池规则？",
            "哪些候选策略只在单一区间有效，必须剔除为过拟合风险？",
        ],
    }
```

Then implement `summarize_short_assets`, `summarize_longterm_assets`, `write_research_overview`, `_write_markdown`, `parse_args`, and `main` with only read-only file access.

- [ ] **Step 4: Verify**

Run:

```powershell
python -m unittest tests.test_strategy_research_overview
python research/strategy_research_overview.py --output reports/research/dragon_boat_research_overview.md
```

Expected: tests pass and the report is generated.

### Task 2: Documentation Hook

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add research harness command**

Add one row in the research scripts section:

```markdown
| `research/strategy_research_overview.py` | 端午策略研究总览：汇总短线 v9、长线 v18 现有证据，不改变上线策略 | `python research/strategy_research_overview.py --output reports/research/dragon_boat_research_overview.md` |
```

- [ ] **Step 2: Verify docs mention the script**

Run:

```powershell
rg -n "strategy_research_overview|dragon_boat_research_overview" README.md
```

Expected: both terms appear.

### Task 3: Safety Verification

**Files:**
- Inspect: `config.py`
- Inspect: `main.py`
- Inspect: `daily_web_update.py`

- [ ] **Step 1: Verify live strategy constants are unchanged**

Run:

```powershell
rg -n "profile_v4_adaptive_quality_v9_sector_quality_guard|longterm_quality_lifecycle_v18_market_sync|SHORT_LIVE|LONGTERM_LIVE" config.py main.py daily_web_update.py
```

Expected: live defaults still point to short v9 and long v18.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m unittest tests.test_strategy_research_overview tests.test_runner_config
```

Expected: all tests pass.

