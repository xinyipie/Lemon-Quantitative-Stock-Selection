# Market Regime Conditioned Opportunity Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated research pipeline that tests whether existing short-term opportunity signals become stable when matched to predetermined market regimes and holding periods.

**Architecture:** Reuse the existing yearly all-market panel and ranking selector, attach the already calculated market regime to every signal-day candidate, summarize fixed-horizon net returns by split, and freeze ranking direction from the training period before evaluating validation. The module writes research artifacts only and never imports into the live selection path.

**Tech Stack:** Python 3.14, pandas, numpy, pytest, local Parquet cache.

## Global Constraints

- No future data may enter market state, profile filtering, or ranking.
- Training is 2016-2021, validation is 2022-2024, recent observation is 2025-2026H1.
- T+1 open entry and 0.30% round-trip cost are fixed.
- Formal strategy files and production configuration remain unchanged.
- New code comments are in Chinese.

---

### Task 1: Regime policy and metric helpers

**Files:**
- Create: `research/regime_conditioned_opportunity_research.py`
- Test: `tests/test_regime_conditioned_opportunity_research.py`

**Interfaces:**
- Produces: `normalize_regime(series) -> Series`, `regime_holding_days(regime) -> int | None`, and `summarize_regime_rankings(selected, cost_pct=0.30) -> DataFrame`.

- [ ] Write tests that prove known regimes retain their identity, unknown regimes are explicit, BEAR_TREND is disabled, and each active regime uses its predetermined holding period.
- [ ] Run `pytest tests/test_regime_conditioned_opportunity_research.py -q` and observe failure because the module does not exist.
- [ ] Implement the minimal helpers and summary metrics.
- [ ] Run the focused test and confirm it passes.

### Task 2: Training-only direction selection and validation gate

**Files:**
- Modify: `research/regime_conditioned_opportunity_research.py`
- Test: `tests/test_regime_conditioned_opportunity_research.py`

**Interfaces:**
- Produces: `choose_training_directions(metrics) -> DataFrame` and `apply_validation_gate(chosen) -> DataFrame`.

- [ ] Add tests proving direction is chosen only from training rows and the validation gate requires positive training stability plus validation metrics and unconditional-baseline improvement.
- [ ] Run the focused tests and observe the expected missing-function failures.
- [ ] Implement deterministic tie-breaking and all acceptance thresholds from the design.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Full historical research and artifacts

**Files:**
- Modify: `research/regime_conditioned_opportunity_research.py`
- Create at runtime: `reports/research/regime_conditioned_opportunity_20260807.md`
- Create at runtime: `reports/research/regime_conditioned_opportunity_metrics_20260807.csv`
- Create at runtime: `reports/research/regime_conditioned_opportunity_chosen_20260807.csv`
- Create at runtime: `reports/research/regime_conditioned_opportunity_coverage_20260807.csv`

**Interfaces:**
- Consumes: `build_year_panel`, `assign_feature_bins`, `select_ranked_candidates`, frozen profiles, and rank specifications.
- Produces: reproducible research tables and a human-readable conclusion.

- [ ] Load each year with sufficient prehistory and preserve the existing T+1 entry filters.
- [ ] Rank active-regime candidates, compute fixed regime-specific returns, and build unconditional profile/factor baselines.
- [ ] Freeze direction on training data, evaluate validation and recent observation, and write all artifacts.
- [ ] Run the full 2016-2026H1 research command and record pass/fail counts without changing production strategy.
