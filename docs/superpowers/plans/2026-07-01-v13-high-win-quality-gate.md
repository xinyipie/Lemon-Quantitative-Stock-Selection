# v13 High Win Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and iterate a v13 short-term profile and style gate until a `TopN=1` or `TopN=2` backtest reaches >=70% win rate on both 2025 and 2026 H1 with positive returns.

**Architecture:** Keep the change inside `strategy_profiles.py`, following existing profile and style-gate extension points. Use `tests/test_strategy_profiles.py` to lock availability and gate behavior, then validate with offline backtests.

**Tech Stack:** Python, pandas, unittest, existing `backtest_v2.py` offline engine.

---

### Task 1: Register v13 profile and gate

**Files:**
- Modify: `strategy_profiles.py`
- Test: `tests/test_strategy_profiles.py`

- [ ] **Step 1: Write failing availability tests**

Add tests asserting `profile_v13_high_win_quality_gate` and `adaptive_quality_v13` are available.

- [ ] **Step 2: Run availability tests to verify failure**

Run: `python -m unittest tests.test_strategy_profiles`
Expected: FAIL because v13 names are not registered.

- [ ] **Step 3: Register names**

Add `profile_v13_high_win_quality_gate` to `VALID_FACTOR_PROFILES` and `adaptive_quality_v13` to `VALID_STYLE_GATES`.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_strategy_profiles`
Expected: PASS for availability.

### Task 2: Add hard high-win style gate

**Files:**
- Modify: `strategy_profiles.py`
- Test: `tests/test_strategy_profiles.py`

- [ ] **Step 1: Write failing gate tests**

Add tests proving `adaptive_quality_v13` keeps a high-quality candidate and filters low pattern, low inflow, high drawdown, and overheated volume candidates.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_strategy_profiles`
Expected: FAIL because `adaptive_quality_v13` does not yet implement the hard gate.

- [ ] **Step 3: Implement minimal gate**

Inside `apply_style_gate`, make `adaptive_quality_v13` require:

- `factor_pattern >= 63`
- `factor_inflow >= 70`
- `drawdown_from_high <= 7`
- `1.3 <= volume_ratio <= 3.0`
- `change <= 5.0`
- reject `market_style == "bear"`

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_strategy_profiles`
Expected: PASS.

### Task 3: Add v13 score profile

**Files:**
- Modify: `strategy_profiles.py`
- Test: `tests/test_strategy_profiles.py`

- [ ] **Step 1: Write failing score tests**

Add tests proving v13 scores a high-quality candidate at least 20 points above a superficially high-scoring low-quality candidate.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_strategy_profiles`
Expected: FAIL because `profile_v13_high_win_quality_gate` falls back to original behavior.

- [ ] **Step 3: Implement minimal score**

Base v13 on `profile_v9_sector_quality_guard`, then boost candidates with strong pattern, inflow, controlled drawdown, and controlled volume. Penalize low pattern, low inflow, high drawdown, overheated volume, negative day change, and `sideways` or `bear` styles.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_strategy_profiles`
Expected: PASS.

### Task 4: Backtest and iterate thresholds

**Files:**
- Modify only if thresholds need tuning: `strategy_profiles.py`
- Test: `tests/test_strategy_profiles.py`

- [ ] **Step 1: Run 2025 Top1 backtest**

Run: `python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --factor-profile profile_v13_high_win_quality_gate --style-gate adaptive_quality_v13 --topn 1 --short-filter-profile baseline`

- [ ] **Step 2: Run 2026 H1 Top1 backtest**

Run: `python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --factor-profile profile_v13_high_win_quality_gate --style-gate adaptive_quality_v13 --topn 1 --short-filter-profile baseline`

- [ ] **Step 3: Run Top2 if Top1 misses trade coverage or return**

Repeat both commands with `--topn 2`.

- [ ] **Step 4: Iterate**

If either period has win rate below 70% or return <= 0, adjust one threshold at a time, run unit tests, and re-run both periods. Prefer tightening weak-market gates before loosening any core quality threshold.

- [ ] **Step 5: Stop condition**

Stop when one `TopN=1` or `TopN=2` combination reaches both win-rate targets and both return targets. Record the exact command and metrics file.
