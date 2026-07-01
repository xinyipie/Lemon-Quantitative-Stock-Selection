# Dragon Reliability Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an offline research script that validates whether the dragon leader observation labels have forward-return reliability.

**Architecture:** Add a focused research module under `research/` that reads historical limit-pool parquet files, rebuilds dragon labels with the existing scoring service, joins local daily bars, and writes event, summary, and markdown report artifacts. Keep it independent from the live stock-picking pipeline.

**Tech Stack:** Python, pandas, parquet files, unittest.

---

### Task 1: Factor Event Builder

**Files:**
- Create: `research/dragon_reliability_backtest.py`
- Test: `tests/test_dragon_reliability_backtest.py`

- [ ] Write failing tests for building forward-return events from two limit-pool dates and daily bars.
- [ ] Implement `DragonReliabilityConfig`, `load_limit_events`, `build_price_panel`, and `build_factor_events`.
- [ ] Verify tests pass with `python -m unittest tests.test_dragon_reliability_backtest -q`.

### Task 2: Summary and Verdict

**Files:**
- Modify: `research/dragon_reliability_backtest.py`
- Modify: `tests/test_dragon_reliability_backtest.py`

- [ ] Write failing tests for lifecycle/theme/bucket summaries and insufficient-sample verdicts.
- [ ] Implement grouped metrics, verdict logic, and markdown rendering.
- [ ] Verify tests pass with `python -m unittest tests.test_dragon_reliability_backtest -q`.

### Task 3: CLI and Artifacts

**Files:**
- Modify: `research/dragon_reliability_backtest.py`

- [ ] Add CLI arguments for date range, input directories, output directory, and minimum sample sizes.
- [ ] Write `dragon_factor_events.csv`, `dragon_factor_summary.csv`, and `dragon_reliability_<date>.md`.
- [ ] Run the script against current local data and report the generated artifact paths.
