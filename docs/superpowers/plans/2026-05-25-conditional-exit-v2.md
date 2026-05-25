# Conditional Exit V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an experimental `exit_v2_conditional_lock` profile that tightens trailing stops only for weak-quality trades after meaningful upside.

**Architecture:** Keep baseline exit behavior unchanged unless a new conditional-lock flag is enabled. Add a small helper on `BacktestV2` to evaluate risk from existing factor fields, then let `test.py` pass the experimental flags through the current CLI path.

**Tech Stack:** Python, pandas, existing `backtest_v2.py` CLI, existing `test.py` experiment runner.

---

### Task 1: Add Red Test For Conditional Lock Helper

**Files:**
- Create: `tests/test_conditional_exit.py`
- Modify: none

- [x] **Step 1: Write the failing test**

```python
import pandas as pd

from backtest_v2 import BacktestV2


def make_backtest(enabled=True):
    bt = BacktestV2.__new__(BacktestV2)
    bt.conditional_lock_enabled = enabled
    bt.conditional_lock_activation_pct = 6.0
    bt.conditional_lock_trailing_pct = 4.8
    return bt


def test_conditional_lock_tightens_only_weak_quality_after_profit():
    bt = make_backtest()
    row = pd.Series(
        {
            "factor_pattern": 52,
            "factor_wyckoff": 58,
            "factor_volume_ratio": 55,
            "factor_drawdown": 94,
            "drawdown_from_high": 9,
        }
    )

    assert bt._conditional_trailing_pct(row, current_profit_pct=6.5, mfe_pct=7.0, base_trailing_pct=7.0) == 4.8


def test_conditional_lock_keeps_baseline_for_strong_quality():
    bt = make_backtest()
    row = pd.Series(
        {
            "factor_pattern": 70,
            "factor_wyckoff": 75,
            "factor_volume_ratio": 72,
            "factor_drawdown": 70,
            "drawdown_from_high": 3,
        }
    )

    assert bt._conditional_trailing_pct(row, current_profit_pct=8.0, mfe_pct=9.0, base_trailing_pct=7.0) == 7.0


def test_conditional_lock_keeps_baseline_before_activation():
    bt = make_backtest()
    row = pd.Series(
        {
            "factor_pattern": 52,
            "factor_wyckoff": 58,
            "factor_volume_ratio": 55,
            "factor_drawdown": 94,
            "drawdown_from_high": 9,
        }
    )

    assert bt._conditional_trailing_pct(row, current_profit_pct=3.5, mfe_pct=4.0, base_trailing_pct=7.0) == 7.0
```

- [x] **Step 2: Run test to verify it fails**

Run: `python tests\test_conditional_exit.py`
Expected: FAIL because `BacktestV2` has no `_conditional_trailing_pct`.

Actual: FAIL confirmed with `AttributeError: 'BacktestV2' object has no attribute '_conditional_trailing_pct'`.

### Task 2: Implement Conditional Lock In Backtest

**Files:**
- Modify: `backtest_v2.py`

- [x] **Step 1: Add constructor fields and helper**

Add optional constructor parameters:

```python
conditional_lock_enabled: bool = False,
conditional_lock_activation_pct: float = 6.0,
conditional_lock_trailing_pct: float = 4.8,
```

Store them on `self`, and add `_conditional_trailing_pct(row, current_profit_pct, mfe_pct, base_trailing_pct)`.

- [x] **Step 2: Apply helper during trailing-stop update**

In `_simulate_trade`, compute the current MFE from the current day's high/close and `buy_price`, then call the helper before computing `new_trailing`.

- [x] **Step 3: Run test to verify it passes**

Run: `python tests\test_conditional_exit.py`
Expected: PASS.

Actual: PASS, 3 tests.

### Task 3: Add CLI And Test Runner Profile

**Files:**
- Modify: `backtest_v2.py`
- Modify: `test.py`

- [x] **Step 1: Add CLI flags**

Add:

```text
--conditional-lock
--conditional-lock-activation
--conditional-lock-trailing
```

Pass them into `BacktestV2` for short mode.

- [x] **Step 2: Add test.py exit profile**

Add `exit_v2_conditional_lock` with:

```python
{
    "conditional_lock": True,
    "conditional_lock_activation": 6.0,
    "conditional_lock_trailing": 4.8,
}
```

Extend `build_exit_args` to emit the new CLI flags.

- [x] **Step 3: Run smoke**

Run:

```text
python -m py_compile backtest_v2.py test.py
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20250102 --end 20250110 --label smoke_exit_v2
```

Expected: command exits 0 and writes two result rows to `test_result.json`.

Actual: command exited 0 and wrote baseline plus `exit_v2_conditional_lock` rows to `test_result.json`.

### Task 4: Document And Commit

**Files:**
- Modify: `docs/EXPERIMENT_LOG.md`
- Modify: `docs/superpowers/plans/2026-05-25-conditional-exit-v2.md`

- [x] **Step 1: Add experiment-log entry**

Record what changed, the smoke command, and that Q1/full-year validation still needs user-run results.

- [x] **Step 2: Mark plan checkboxes complete**

Update this plan file as tasks are completed.

- [x] **Step 3: Commit**

Run:

```text
git add backtest_v2.py test.py tests/test_conditional_exit.py docs/EXPERIMENT_LOG.md docs/superpowers/plans/2026-05-25-conditional-exit-v2.md
git commit -m "backtest: add conditional exit lock"
```
