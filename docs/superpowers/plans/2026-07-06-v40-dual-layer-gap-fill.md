# v40 Dual Layer Gap Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-only v40 short-line consensus profile that keeps v35/v39 quality while adding a gap-fill lane targeting roughly 50-80 ten-year trades.

**Architecture:** Add `v40` as a consensus profile in `strategy_profiles.py`. `v40` first returns the existing v35 primary lane; only when v35 is empty for the date does it build a v29-style consensus candidate set and apply a conservative low-MAE gap-fill guard. Backtest and report generation continue to use existing `backtest_v2.py` and matrix tooling.

**Tech Stack:** Python, pandas, unittest, existing offline `backtest_v2.py`, existing research scripts under `research/`.

---

## File Structure

- Modify: `strategy_profiles.py`
  - Add `v40` to `VALID_CONSENSUS_PROFILES`.
  - Add helper `_apply_consensus_gap_fill_guard`.
  - Add helper `_build_v40_dual_layer_gap_fill`.
  - Route `build_consensus_candidates(... consensus_profile="v40")` through the dual-layer helper.
- Modify: `tests/test_strategy_profiles.py`
  - Add unit tests proving v40 prefers v35 primary candidates and only uses gap-fill candidates when primary is empty.
  - Add unit test proving v40 rejects single-vote or high-risk gap-fill candidates.
- Optional modify: `research/ten_year_strategy_matrix.py`
  - If the script has a hard-coded `STRATEGIES` list, add a v40 comparison row.
  - If it already accepts ad hoc strategies, skip this file.
- Create: `docs/TEN_YEAR_V40_DUAL_LAYER_GAP_FILL_20260706.md`
  - Summarize validation results after matrix execution.

---

### Task 1: Add v40 Behavior Tests

**Files:**
- Modify: `tests/test_strategy_profiles.py`

- [ ] **Step 1: Add imports if missing**

Ensure the existing import from `strategy_profiles` includes:

```python
from strategy_profiles import (
    apply_live_short_postprocess,
    build_consensus_candidates,
    normalize_consensus_profile,
)
```

If `build_consensus_candidates` is already imported, only add `normalize_consensus_profile`.

- [ ] **Step 2: Add a local row helper in `StyleGateTest`**

Add this helper method inside the same test class that already tests consensus behavior:

```python
    def _v40_row(self, code: str, **overrides):
        row = {
            "code": code,
            "ts_code": f"{code}.SZ",
            "score": 80.0,
            "market_style": "weak_momentum",
            "macro_mode": "active",
            "regime": "BULL_TREND",
            "market_index_change": 0.3,
            "limit_up_count": 85,
            "limit_down_count": 2,
            "limit_up_down_ratio": 20.0,
            "sector_ma10_ratio": 78.0,
            "change": 3.0,
            "volume_ratio": 2.0,
            "drawdown_from_high": 5.0,
            "factor_volume_ratio": 70.0,
            "factor_drawdown": 60.0,
            "factor_inflow": 99.0,
            "factor_turnover": 55.0,
            "factor_sector": 40.0,
            "factor_pattern": 65.0,
            "factor_counter_trend": 50.0,
            "factor_wyckoff": 68.0,
            "factor_accel": 50.0,
        }
        row.update(overrides)
        return row
```

- [ ] **Step 3: Add normalization test**

Add:

```python
    def test_v40_consensus_profile_is_registered(self):
        self.assertEqual(
            normalize_consensus_profile("v40"),
            "v40",
        )
```

- [ ] **Step 4: Add primary lane test**

Add:

```python
    def test_v40_prefers_v35_primary_lane_when_available(self):
        df = pd.DataFrame(
            [
                self._v40_row("000001", factor_pattern=65.0, factor_sector=35.0),
                self._v40_row("000002", factor_pattern=20.0, factor_sector=70.0),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v40", min_votes=2)

        self.assertGreaterEqual(len(result), 1)
        self.assertEqual("primary_v35", result.iloc[0]["consensus_layer"])
        self.assertEqual("v40", result.iloc[0]["consensus_profile"])
```

- [ ] **Step 5: Add gap-fill fallback test**

Add:

```python
    def test_v40_uses_gap_fill_when_primary_lane_is_empty(self):
        df = pd.DataFrame(
            [
                self._v40_row(
                    "000001",
                    macro_mode="cautious",
                    limit_down_count=10,
                    factor_pattern=50.0,
                ),
                self._v40_row(
                    "000002",
                    macro_mode="active",
                    limit_down_count=2,
                    factor_pattern=30.0,
                    factor_sector=35.0,
                    volume_ratio=2.0,
                    drawdown_from_high=4.5,
                    factor_wyckoff=68.0,
                ),
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v40", min_votes=2)

        self.assertGreaterEqual(len(result), 1)
        self.assertEqual("gap_fill", result.iloc[0]["consensus_layer"])
        self.assertIn("gap_fill_score", result.columns)
        self.assertEqual("v40", result.iloc[0]["consensus_profile"])
```

- [ ] **Step 6: Add gap-fill rejection test**

Add:

```python
    def test_v40_gap_fill_rejects_high_risk_candidates(self):
        df = pd.DataFrame(
            [
                self._v40_row(
                    "000001",
                    macro_mode="cautious",
                    limit_down_count=10,
                    factor_pattern=50.0,
                    volume_ratio=3.4,
                    drawdown_from_high=9.0,
                    factor_wyckoff=45.0,
                )
            ]
        )

        result = build_consensus_candidates(df, consensus_profile="v40", min_votes=2)

        self.assertEqual(0, len(result))
```

- [ ] **Step 7: Run the new tests and verify they fail**

Run:

```bash
python tests\test_strategy_profiles.py
```

Expected: FAIL because `v40` is not registered and `consensus_layer` is not implemented.

---

### Task 2: Implement v40 Consensus Profile

**Files:**
- Modify: `strategy_profiles.py`

- [ ] **Step 1: Register v40**

Add `"v40"` to `VALID_CONSENSUS_PROFILES` after `"v39"`:

```python
    "v39",
    "v40",
)
```

Add `v40` to `CONSENSUS_PROFILE_CONFIGS` using the same three strong routes:

```python
    "v40": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
```

- [ ] **Step 2: Add `_apply_consensus_gap_fill_guard`**

Insert after `_apply_consensus_strong_rank_guard`:

```python
def _apply_consensus_gap_fill_guard(df: pd.DataFrame) -> pd.DataFrame:
    """v40 gap-fill lane: keep low-MAE consensus candidates without heat overload."""
    required = {
        "consensus_votes",
        "consensus_avg_rank",
        "limit_up_count",
        "limit_down_count",
        "sector_ma10_ratio",
        "volume_ratio",
        "drawdown_from_high",
        "factor_wyckoff",
        "factor_sector",
        "factor_pattern",
        "change",
    }
    if df.empty or not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    out = df.copy()
    votes = pd.to_numeric(out["consensus_votes"], errors="coerce").fillna(0)
    avg_rank = pd.to_numeric(out["consensus_avg_rank"], errors="coerce").fillna(999)
    limit_up_count = pd.to_numeric(out["limit_up_count"], errors="coerce").fillna(0)
    limit_down_count = pd.to_numeric(out["limit_down_count"], errors="coerce").fillna(999)
    sector_ma10_ratio = pd.to_numeric(out["sector_ma10_ratio"], errors="coerce").fillna(50)
    volume_ratio = pd.to_numeric(out["volume_ratio"], errors="coerce").fillna(999)
    drawdown = pd.to_numeric(out["drawdown_from_high"], errors="coerce").fillna(999)
    wyckoff = pd.to_numeric(out["factor_wyckoff"], errors="coerce").fillna(0)
    sector = pd.to_numeric(out["factor_sector"], errors="coerce").fillna(100)
    pattern = pd.to_numeric(out["factor_pattern"], errors="coerce").fillna(0)
    change = pd.to_numeric(out["change"], errors="coerce").fillna(999)
    macro = out["macro_mode"].fillna("").astype(str) if "macro_mode" in out.columns else pd.Series("", index=out.index)

    low_mae_shape = (
        (votes >= 2)
        & (avg_rank <= 3.0)
        & volume_ratio.between(1.4, 2.8, inclusive="both")
        & drawdown.between(2.0, 7.0, inclusive="both")
        & wyckoff.between(60.0, 75.0, inclusive="both")
        & (change <= 4.5)
    )
    market_ok = (
        (limit_up_count >= 60)
        & (limit_down_count <= 15)
        & ~sector_ma10_ratio.between(46.0, 70.0, inclusive="both")
    )
    cautious_exception = (
        macro.eq("cautious")
        & (limit_down_count <= 4)
        & (pattern >= 60.0)
    )
    sector_not_overheated = sector <= 60.0
    accepted = low_mae_shape & sector_not_overheated & (market_ok | cautious_exception)
    out = out.loc[accepted].copy()
    if out.empty:
        return out

    out["gap_fill_score"] = (
        pd.to_numeric(out["consensus_votes"], errors="coerce").fillna(0) * 100.0
        - pd.to_numeric(out["consensus_avg_rank"], errors="coerce").fillna(999) * 8.0
        + (75.0 - pd.to_numeric(out["factor_wyckoff"], errors="coerce").fillna(0)).abs().rsub(15.0).fillna(0)
        + (60.0 - pd.to_numeric(out["factor_sector"], errors="coerce").fillna(100)).clip(lower=0.0) * 0.2
        - (pd.to_numeric(out["volume_ratio"], errors="coerce").fillna(2.0) - 2.0).abs() * 3.0
        - pd.to_numeric(out["limit_down_count"], errors="coerce").fillna(0).clip(lower=0.0, upper=20.0) * 0.3
    ).round(4)
    out["consensus_score"] = out["gap_fill_score"]
    return out
```

- [ ] **Step 3: Add `_build_v40_dual_layer_gap_fill`**

Insert after `_apply_consensus_gap_fill_guard`:

```python
def _build_v40_dual_layer_gap_fill(
    df: pd.DataFrame,
    min_votes: int,
    base_score_col: str,
) -> pd.DataFrame:
    primary = build_consensus_candidates(
        df,
        consensus_profile="v35",
        min_votes=min_votes,
        base_score_col=base_score_col,
    )
    if not primary.empty:
        out = primary.copy()
        out["consensus_profile"] = "v40"
        out["consensus_layer"] = "primary_v35"
        return out

    gap = build_consensus_candidates(
        df,
        consensus_profile="v29",
        min_votes=min_votes,
        base_score_col=base_score_col,
    )
    gap = _apply_consensus_gap_fill_guard(gap)
    if gap.empty:
        return gap
    gap = gap.copy()
    gap["consensus_profile"] = "v40"
    gap["consensus_layer"] = "gap_fill"
    return gap.sort_values(
        ["consensus_votes", "gap_fill_score", "consensus_avg_rank"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
```

- [ ] **Step 4: Route v40 before generic config handling**

At the start of `build_consensus_candidates`, after normalization and empty checks, add:

```python
    if consensus_profile == "v40":
        return _build_v40_dual_layer_gap_fill(
            df,
            min_votes=min_votes,
            base_score_col=base_score_col,
        )
```

Place this before `configs = CONSENSUS_PROFILE_CONFIGS.get(...)` so the helper can compose v35 and v29 without the generic path overwriting layer labels.

- [ ] **Step 5: Preserve layer metadata in backtest output**

In `backtest_v2.py`, extend both consensus metadata loops to include:

```python
                        'consensus_layer',
                        'gap_fill_score',
```

The final tuple should include:

```python
                    for col in (
                        'consensus_votes',
                        'consensus_avg_rank',
                        'consensus_avg_score',
                        'consensus_profiles',
                        'consensus_score',
                        'consensus_layer',
                        'gap_fill_score',
                    ):
```

- [ ] **Step 6: Run tests**

Run:

```bash
python tests\test_strategy_profiles.py
python -m py_compile strategy_profiles.py backtest_v2.py
```

Expected: all tests pass and py_compile emits no output.

- [ ] **Step 7: Commit implementation**

Commit only implementation and test changes:

```bash
git add strategy_profiles.py backtest_v2.py tests/test_strategy_profiles.py
git commit -m "feat: add v40 dual layer gap fill profile"
```

---

### Task 3: Run Focused Smoke Backtests

**Files:**
- No code changes expected.
- Generated artifacts: `backtest_results/`, `reports/`.

- [ ] **Step 1: Confirm CLI accepts v40**

Run:

```bash
python backtest_v2.py --help
```

Expected: help text includes `--consensus-profile` or the existing equivalent flag. If the exact flag name differs, use the shown flag in the next steps.

- [ ] **Step 2: Run a short v40 smoke period**

Run the smallest already-used smoke window with v40 consensus:

```bash
python backtest_v2.py --mode short --offline --start 20250102 --end 20250110 --hold-days 3 --topn 1 --consensus-profile v40
```

Expected: process exits 0 and writes a `trades_*.csv` or empty-but-successful metrics output.

- [ ] **Step 3: Run comparison smoke for v35**

Run:

```bash
python backtest_v2.py --mode short --offline --start 20250102 --end 20250110 --hold-days 3 --topn 1 --consensus-profile v35
```

Expected: process exits 0. If v40 and v35 choose the same candidates in this window, that is acceptable because v40 only fills gaps.

- [ ] **Step 4: Inspect latest trades for v40 metadata**

Run:

```bash
python -c "import glob,pandas as pd; f=max(glob.glob('backtest_results/trades_*.csv')); df=pd.read_csv(f, encoding='utf-8-sig'); print(f); print([c for c in ['consensus_profile','consensus_layer','gap_fill_score'] if c in df.columns]); print(df.head().to_string(index=False))"
```

Expected: latest v40 trades include `consensus_profile`; if trades exist, `consensus_layer` is present.

---

### Task 4: Run Ten-Year v40 Matrix

**Files:**
- Optional modify: `research/ten_year_strategy_matrix.py`
- Generated: `backtest_results/ten_year_strategy_matrix_*.csv`
- Generated: `backtest_results/matrix_metrics/<stamp>/...json`

- [ ] **Step 1: Add v40 to matrix strategies if needed**

If `research/ten_year_strategy_matrix.py` has a `STRATEGIES` constant, add:

```python
{
    "label": "v40_dual_layer_gap_fill_50_80_trades",
    "factor_profile": "original",
    "style_gate": "none",
    "consensus_profile": "v40",
    "top_n": 1,
    "hold_days": 3,
}
```

Keep existing v35, v39, v35 Top2, v19, and v9 comparison entries.

- [ ] **Step 2: Run matrix**

Run:

```bash
python research\ten_year_strategy_matrix.py
```

Expected: process exits 0 and writes a new `backtest_results/ten_year_strategy_matrix_YYYYMMDD_HHMMSS.csv`.

- [ ] **Step 3: Build first-tier audit including v40**

Run:

```bash
python research\historical_strategy_audit.py --output reports\historical_strategy_audit_v40_20260706.csv --min-main-trades 20 --min-confidence-trades 10
```

Expected: process exits 0 and writes `.csv`, `.json`, and `.md` outputs.

- [ ] **Step 4: Extract v40 comparison table**

Run:

```bash
python -c "import pandas as pd; df=pd.read_csv('reports/historical_strategy_audit_v40_20260706.csv', encoding='utf-8-sig'); keep=df[df.strategy.astype(str).str.contains('v35|v39|v40|v19_top1|v9_top1', regex=True)]; cols=['strategy','total_trades','active_years','positive_years','loss_years','weighted_win_rate','total_return_pct','recent_win_rate','recent_return_pct','avg_hit_3pct_rate','avg_hit_5pct_rate','avg_mae_pct']; print(keep[cols].to_string(index=False))"
```

Expected: table shows whether v40 reaches the 40-80 trade range while keeping recent win rate near or above 70%.

---

### Task 5: Write v40 Result Report

**Files:**
- Create: `docs/TEN_YEAR_V40_DUAL_LAYER_GAP_FILL_20260706.md`

- [ ] **Step 1: Collect matrix facts**

Run:

```bash
python -c "import pandas as pd,glob; f=max(glob.glob('backtest_results/ten_year_strategy_matrix_*.csv')); df=pd.read_csv(f, encoding='utf-8-sig'); print(f); print(df[df.strategy.astype(str).str.contains('v40|v35|v39|v19_top1|v9_top1', regex=True)].to_string(index=False))"
```

Expected: output contains v40 and comparison strategies.

- [ ] **Step 2: Create report**

Write `docs/TEN_YEAR_V40_DUAL_LAYER_GAP_FILL_20260706.md` with these sections:

```markdown
# v40 Dual Layer Gap Fill Ten-Year Validation

## Goal

State the completed v40 target: expand the v35/v39 23-26 trade high-confidence lane toward 50-80 trades, with 40-60 acceptable if quality remains strong, while prioritizing 3-5 day upside and avoiding low-quality recommendations.

## Result Summary

Fill this table with completed numbers from the matrix and audit output:

| Strategy | Trades | Active Years | Positive Years | Loss Years | Win Rate | Total Return | 2025+2026H1 Win | 2025+2026H1 Return | 3% Hit | 5% Hit | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

## Yearly Detail

Provide the completed v40 yearly table with trades, win rate, return, 3% hit, 5% hit, and MAE.

## Layer Contribution

Provide completed Layer 1 and Layer 2 trade counts, win rate, and return. If a run produced trades without layer metadata, rerun the validation after Task 2 Step 5.

## Weak-Year Audit

Provide completed 2022 and 2023 behavior: whether v40 traded, whether it lost money, and whether it respected the gap-fill defense.

## Conclusion

State one completed decision: accept v40, tune v40 further, or reject v40 and keep v35/v39 as sparse high-confidence lanes.
```

- [ ] **Step 3: Verify no placeholders remain**

Run:

```bash
python -c "from pathlib import Path; text=Path('docs/TEN_YEAR_V40_DUAL_LAYER_GAP_FILL_20260706.md').read_text(encoding='utf-8'); checks=['T'+'BD','PEND'+'ING','PLACE'+'HOLDER','State the completed','Fill this table','Provide the completed','State one completed']; bad=[c for c in checks if c in text]; print(bad); raise SystemExit(1 if bad else 0)"
```

Expected: no matches. Replace instructional text with actual results before committing.

- [ ] **Step 4: Commit report**

Commit report and any matrix-script change:

```bash
git add docs/TEN_YEAR_V40_DUAL_LAYER_GAP_FILL_20260706.md research/ten_year_strategy_matrix.py
git commit -m "docs: record v40 ten-year validation"
```

If `research/ten_year_strategy_matrix.py` was not changed, omit it from `git add`.

---

## Final Verification

- [ ] Run:

```bash
python tests\test_strategy_profiles.py
python -m py_compile strategy_profiles.py backtest_v2.py research\historical_strategy_audit.py
```

- [ ] Run:

```bash
git status --short
```

Expected: only unrelated pre-existing research files remain dirty or untracked. The v40 implementation, plan, and report are committed or clearly listed for user review.

- [ ] Final response must state:
  - v40 total trades.
  - v40 weighted win rate.
  - v40 total return.
  - 2025 and 2026H1 results.
  - Whether v40 met the 50-80 or 40-60 trade objective.
  - Whether it is better than v35/v39 sparse lanes.
