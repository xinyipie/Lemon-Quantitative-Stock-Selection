# v16 Window Confidence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and evaluate a v16 short-line research profile focused on 3-5 day forward window quality.

**Architecture:** Extend the existing `strategy_profiles.py` registry, style gate, and factor scoring switch with a small v16 profile. Reuse the current backtest runner and unit test file; no trading execution or exit logic changes.

**Tech Stack:** Python, pandas, unittest, existing offline `backtest_v2.py` runner.

---

### Task 1: Add Failing Tests

**Files:**
- Modify: `tests/test_strategy_profiles.py`

- [ ] **Step 1: Add availability tests**

Add tests asserting `adaptive_quality_v16` and `profile_v16_window_confidence` appear in the exported registries.

- [ ] **Step 2: Add gate behavior test**

Add a test where v16 keeps a strong sector lane and a stricter weak-momentum lane, while filtering low-sector weak momentum, 9-12% drawdown, hot entries, and volume spikes.

- [ ] **Step 3: Add scoring behavior test**

Add a test asserting v16 scores a confirmed weak-momentum continuation setup at least 20 points above a v15-style relaxed weak-momentum candidate.

- [ ] **Step 4: Run tests and verify RED**

Run:

```powershell
python -m unittest tests.test_strategy_profiles
```

Expected: tests fail because v16 is not registered or implemented yet.

### Task 2: Implement v16 Profile and Gate

**Files:**
- Modify: `strategy_profiles.py`

- [ ] **Step 1: Register names**

Add `profile_v16_window_confidence` to `VALID_FACTOR_PROFILES` and `adaptive_quality_v16` to `VALID_STYLE_GATES`.

- [ ] **Step 2: Implement gate**

Inside `apply_style_gate`, include `adaptive_quality_v16` in the adaptive branch and add a dedicated v16 mask before the legacy adaptive logic.

- [ ] **Step 3: Implement score**

Inside `factor_profile_score`, add `profile_v16_window_confidence` after v15. Base it on `profile_v14_sector_pattern_gate`, then add bonuses and penalties for sector continuation, confirmed weak-momentum continuation, calm entry, controlled volume, and the 9-12% drawdown risk bucket.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_strategy_profiles
```

Expected: all tests pass.

### Task 3: Backtest and Summarize

**Files:**
- Read generated `backtest_results/metrics_*.json`
- Read generated `backtest_results/trades_*.csv` if needed

- [ ] **Step 1: Run Top1 2025**

```powershell
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 1 --factor-profile profile_v16_window_confidence --style-gate adaptive_quality_v16
```

- [ ] **Step 2: Run Top1 2026H1**

```powershell
python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --no-timing --hold 8 --topn 1 --factor-profile profile_v16_window_confidence --style-gate adaptive_quality_v16
```

- [ ] **Step 3: Run Top2 2025**

```powershell
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 2 --factor-profile profile_v16_window_confidence --style-gate adaptive_quality_v16
```

- [ ] **Step 4: Run Top2 2026H1**

```powershell
python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --no-timing --hold 8 --topn 2 --factor-profile profile_v16_window_confidence --style-gate adaptive_quality_v16
```

- [ ] **Step 5: Summarize metrics**

Report trades, win rate, total return, `hit_3pct_rate`, `hit_5pct_rate`, `avg_mfe_pct`, `avg_mae_pct`, and `avg_window_end_pct`. Judge v16 primarily by 3-5 day window quality.

