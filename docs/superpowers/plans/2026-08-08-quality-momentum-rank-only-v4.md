# Quality Momentum Rank-Only v4 Implementation Plan

> **For agentic workers:** Execute inline because this is an isolated research runner; do not modify production selection code.

**Goal:** Verify whether the frozen quality-momentum shallow-pullback candidate family remains stable when the cross-year absolute market gate is removed and only the already-registered prediction-margin abstention is retained.

**Architecture:** Reuse the frozen 2016-2024 candidate file and the existing yearly expanding Ridge ranker. Produce annual out-of-sample Top2 predictions once, then select daily Top1 only when its prediction lead exceeds `0.02`; neighboring `0.01` and `0.03` margins are diagnostics, not model-selection alternatives.

**Tech Stack:** Python, pandas, NumPy, existing research walk-forward and overlap portfolio utilities.

## Global Constraints

- Do not read 2025 or 2026 while developing or selecting this candidate.
- Use T+1 open and five-trading-day return already persisted by the frozen candidate builder.
- Base round-trip cost is `0.25%`; stress cost is `0.50%`.
- No production file, deployment configuration, or live score is modified.
- The main rule must pass before neighboring margins may count as robustness evidence.

### Task 1: Freeze the rank-only research contract

**Files:**
- Create: `reports/research/prereg_quality_momentum_reentry_rank_only_v4_2019_2024_20260808.json`
- Create: `research/quality_momentum_reentry_rank_only_v4_2019_2024.py`
- Test: `tests/test_quality_momentum_reentry_rank_only_v4_2019_2024.py`

- [ ] Persist the exact years, margin, costs, metrics, and rejection gates before execution.
- [ ] Build expanding-year Ridge predictions using only earlier years.
- [ ] Select only daily Top1 when Top1 minus Top2 prediction exceeds `0.02`.
- [ ] Reject days with fewer than two ranked candidates.

### Task 2: Run six-year and perturbation audits

**Files:**
- Create: `reports/research/quality_momentum_reentry_rank_only_v4_2019_2024_20260808.json`
- Create: `reports/research/quality_momentum_reentry_rank_only_v4_2019_2024_20260808_trades.csv`

- [ ] Measure 2019-2021 internal OOS and 2022-2024 independent validation.
- [ ] Run block bootstrap on validation trading days.
- [ ] Measure overlap-adjusted annual returns and maximum drawdown at both costs.
- [ ] Confirm neighboring margins `0.01` and `0.03` do not reverse validation results.
- [ ] Keep production unchanged regardless of outcome.

