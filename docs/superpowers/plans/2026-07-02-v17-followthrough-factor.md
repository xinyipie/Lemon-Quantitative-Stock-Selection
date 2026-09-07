# v17 Followthrough Factor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a v17 short-line research profile and style gate that test whether v12-like coverage can be cleaned up with follow-through factors.

**Architecture:** Keep all strategy behavior inside `strategy_profiles.py`, following the existing `profile_vN` and `adaptive_quality_vN` pattern. Add focused unit tests in `tests/test_strategy_profiles.py`, then validate with offline backtests.

**Tech Stack:** Python, pandas, unittest, existing `backtest_v2.py` offline runner.

---

### Task 1: Tests

**Files:**
- Modify: `tests/test_strategy_profiles.py`

- [ ] **Step 1: Add availability tests**

Add assertions that `profile_v17_followthrough_factor` appears in `available_profiles()` and `adaptive_quality_v17` appears in `available_style_gates()`.

- [ ] **Step 2: Add gate behavior test**

Create a DataFrame with lane A, lane B, sideways noise, bear noise, overheated sector, volume spike, deep drawdown, and weak inflow rows. Assert that only lane A and lane B pass `apply_style_gate(..., "adaptive_quality_v17")`.

- [ ] **Step 3: Add scoring behavior test**

Compare a balanced follow-through setup against an overheated/noisy setup and assert v17 scores the balanced setup at least 20 points higher.

- [ ] **Step 4: Run red test**

Run `python -m unittest tests.test_strategy_profiles`. Expected before implementation: failures for missing profile/gate.

### Task 2: Strategy Profile

**Files:**
- Modify: `strategy_profiles.py`

- [ ] **Step 1: Register names**

Add `profile_v17_followthrough_factor` to `VALID_FACTOR_PROFILES` and `adaptive_quality_v17` to `VALID_STYLE_GATES`.

- [ ] **Step 2: Implement `adaptive_quality_v17`**

Inside `apply_style_gate`, include v17 in the adaptive gate tuple. Add lane A and lane B exactly as described in the spec, using `factor_wyckoff` as a numeric series.

- [ ] **Step 3: Implement `profile_v17_followthrough_factor`**

Build from `profile_v12_2026h1_guard`, reward the two lanes, reward controlled volume/drawdown and pattern/inflow confirmation, and penalize sideways, bear, hot sector/volume, deep drawdown, and excessive Wyckoff.

- [ ] **Step 4: Run green test**

Run `python -m unittest tests.test_strategy_profiles`. Expected: all tests pass.

### Task 3: Backtest Validation

**Files:**
- Read generated files under `backtest_results/`

- [ ] **Step 1: Run Top1 2025**

Run:

```powershell
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 1 --factor-profile profile_v17_followthrough_factor --style-gate adaptive_quality_v17
```

- [ ] **Step 2: Run Top1 2026H1**

Run:

```powershell
python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --no-timing --hold 8 --topn 1 --factor-profile profile_v17_followthrough_factor --style-gate adaptive_quality_v17
```

- [ ] **Step 3: Summarize acceptance metrics**

Report total trades, win rate, total return, avg MFE, avg MAE, avg window-end return, hit 3%, hit 5%, and whether the result is an improvement over v16's sample size.

