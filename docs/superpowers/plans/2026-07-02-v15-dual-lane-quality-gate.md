# v15 Dual-Lane Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a v15 short-strategy profile and style gate that increases coverage while preserving the 70% win-rate target on 2025 and 2026 H1 backtests.

**Architecture:** Extend the existing `strategy_profiles.py` profile/gate registry. Add tests in `tests/test_strategy_profiles.py` before production code. Verify with unit tests and offline backtests.

**Tech Stack:** Python, pandas, unittest, existing `backtest_v2.py` offline engine.

---

### Task 1: v15 tests

**Files:**
- Modify: `tests/test_strategy_profiles.py`

- [ ] Add tests that assert `adaptive_quality_v15` and `profile_v15_dual_lane_quality_gate` are available.
- [ ] Add a gate test showing v15 keeps v14 lane A and a weak-momentum lane B candidate, while rejecting bear, overheated, weak-pattern, weak-inflow, deep-drawdown, volume-spike, and weak-sector candidates.
- [ ] Add a scoring test showing v15 ranks the lane B candidate above a hotter low-sector noisy candidate.
- [ ] Run `python -m unittest tests.test_strategy_profiles` and confirm the v15 tests fail before production code is changed.

### Task 2: v15 implementation

**Files:**
- Modify: `strategy_profiles.py`

- [ ] Register `profile_v15_dual_lane_quality_gate`.
- [ ] Register `adaptive_quality_v15`.
- [ ] Implement `adaptive_quality_v15` as lane A OR lane B.
- [ ] Implement `profile_v15_dual_lane_quality_gate` as a small adjustment on top of v14/v13 scoring, rewarding lane A and controlled lane B while penalizing heat, weak sector, deep drawdown, and volume spikes.
- [ ] Run `python -m unittest tests.test_strategy_profiles` and confirm all tests pass.

### Task 3: backtest validation

**Files:**
- Output: `backtest_results/run_v15_top1_2025.log`
- Output: `backtest_results/run_v15_top1_2026h1.log`

- [ ] Run 2025 Top1 offline backtest.
- [ ] Run 2026 H1 Top1 offline backtest.
- [ ] Read the generated `metrics_*.json` files and verify win rate, total return, and trade count.
- [ ] If Top1 coverage is still too low, run Top2 as diagnostic and report it separately.
