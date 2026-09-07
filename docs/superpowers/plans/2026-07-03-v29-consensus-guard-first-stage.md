# V29 Consensus Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-stage research-only v29 consensus guard so the short backtest can test Top1/Top2 candidates admitted by at least two of the v19/v25/v27 virtual strategies.

**Architecture:** Add a reusable consensus builder in `strategy_profiles.py`, then route `backtest_v2.py` through it only when `--consensus-profile v29` is passed. Keep default live and backtest behavior unchanged, and add v29 Top1/Top2 entries to the ten-year matrix runner for validation.

**Tech Stack:** Python, pandas, unittest/pytest, existing offline `backtest_v2.py` and `research/ten_year_strategy_matrix.py`.

---

### Task 1: Consensus Builder

**Files:**
- Modify: `tests/test_strategy_profiles.py`
- Modify: `strategy_profiles.py`

- [ ] **Step 1: Write failing tests**

Add tests importing `build_consensus_candidates` and checking these behaviors:

```python
from strategy_profiles import build_consensus_candidates


def test_build_consensus_candidates_requires_two_votes(self):
    df = pd.DataFrame([...])
    result = build_consensus_candidates(df, min_votes=2)
    assert "two_vote" in result["code"].tolist()
    assert "single_vote" not in result["code"].tolist()
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/test_strategy_profiles.py -q`
Expected: import error for `build_consensus_candidates`.

- [ ] **Step 3: Implement builder**

Add `CONSENSUS_PROFILES`, `normalize_consensus_profile`, `available_consensus_profiles`, and `build_consensus_candidates` to `strategy_profiles.py`. The v29 config is exactly:

```python
("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19")
("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25")
("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27")
```

- [ ] **Step 4: Run tests GREEN**

Run: `python -m pytest tests/test_strategy_profiles.py -q`
Expected: all pass.

### Task 2: Backtest Research Hook

**Files:**
- Modify: `backtest_v2.py`

- [ ] **Step 1: Add constructor/CLI fields**

Add `consensus_profile: str = 'none'` to `BacktestV2.__init__`, normalize it, and expose `--consensus-profile` choices from `available_consensus_profiles()`.

- [ ] **Step 2: Route short candidate pool**

Inside short `_select_stocks_for_date`, after threshold filtering and before TopN selection, call `build_consensus_candidates(raw_candidate_rows, consensus_profile=self.consensus_profile, min_votes=2)` when profile is not `none`. Sort by `consensus_score` and retain IC pool metadata.

- [ ] **Step 3: Verify compile**

Run: `python -m py_compile backtest_v2.py strategy_profiles.py`
Expected: no output and exit code 0.

### Task 3: Matrix Entries

**Files:**
- Modify: `research/ten_year_strategy_matrix.py`

- [ ] **Step 1: Add v29 Top1/Top2 strategy rows**

Add strategies named `v29_consensus_top1_hold3` and `v29_consensus_top2_hold3` using `--consensus-profile v29`, `hold=3`, `topn=1/2`.

- [ ] **Step 2: Smoke test short period**

Run: `python research\ten_year_strategy_matrix.py --strategies v29_consensus_top1_hold3 --periods 2026H1 --jobs 1` if the script supports filtering; otherwise run one direct backtest command.
Expected: command completes and writes metrics JSON.

### Task 4: Documentation Note

**Files:**
- Modify: `docs/TEN_YEAR_STAGE2_CONSENSUS_20260703.md`

- [ ] **Step 1: Append first-stage implementation note**

Record that v29 is research-only, default disabled, and must be validated via Top1/Top2 full backtest before considering live switch.
