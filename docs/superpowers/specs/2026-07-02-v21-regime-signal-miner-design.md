# v21 Regime Signal Miner Design

## Context

The short-line experiments now show two different truths:

- `profile_v19_calm_followthrough` can reach high annual win rate in 2025 and 2026H1, but it fails the 2024 out-of-sample check.
- Older `profile_v9_sector_quality_guard` is not high win-rate either, but it often produces acceptable 3-5 day MFE/hit rates, which matches the user's practical goal: selected stocks should rise soon after recommendation.

The next step should not be another hand-tuned threshold profile. Existing reports show short-line factors are unstable across periods. `factor_sector`, `factor_pattern`, `factor_inflow`, `factor_wyckoff`, and `score` all change direction across regimes. A generalized strategy therefore needs a regime-aware research layer before any new live profile is considered.

## Goal

Build a research harness that mines cross-period short-line rule candidates for:

- High probability of rising within 3-5 trading days.
- Positive realized return after the current baseline exit.
- Acceptable sample count across 2024, 2025, and 2026H1.
- Explicit no-trade behavior when the market state has no stable edge.

This harness is research-only. It must not add automatic order placement, live trade execution, or portfolio automation.

## Design

### 1. Data Inputs

The first implementation reads existing `backtest_results/trades_*.csv` files because they already contain:

- Selection date, buy/sell dates, final profit, MFE/MAE, and 3/5/10 percent hit flags.
- Factor columns such as `factor_volume_ratio`, `factor_drawdown`, `factor_inflow`, `factor_turnover`, `factor_sector`, `factor_pattern`, `factor_wyckoff`, `change`, `volume_ratio`, `drawdown_from_high`, `turnover`, `market_style`, and `macro_mode`.
- Profile metadata, so we can compare v9/v19 or other generated runs without changing strategy code.

The first target files are the known v19 runs:

- `trades_20260702_160634.csv`: 2024 full-year v19 out-of-sample failure.
- `trades_20260702_142957.csv`: 2025 full-year v19 success.
- `trades_20260702_142535.csv`: 2026H1 v19 success.

The miner should accept additional explicit file paths, so future v9/v12/v15/v16 runs can be analyzed without code changes.

### 2. Rule Shape

Rules are intentionally simple and auditable:

- One categorical partition: `market_style`, `macro_mode`, or both.
- One or two numeric factor buckets, such as `factor_sector <= 45`, `factor_pattern <= 40`, `volume_ratio between 1.4 and 2.8`, or `drawdown_from_high <= 7`.
- Optional minimum sample threshold per period.

The first miner does not produce a live strategy. It ranks candidate rule buckets and labels them:

- `candidate`: passes aggregate quality but needs more checks.
- `fragile`: good aggregate result but weak period coverage or tiny sample.
- `reject`: poor return, low hit rate, or unstable across periods.

### 3. Metrics

For each rule and period, the report records:

- Sample count.
- Final win rate using `profit_after_fee > 0`.
- Total and average final profit.
- Average MFE and MAE.
- Average `window_end_pct`.
- `hit_3pct`, `hit_5pct`, and `hit_10pct` rates.

Aggregate scoring should reward:

- `hit_3pct >= 70%`.
- `hit_5pct >= 55%`.
- Positive final average profit.
- Lower MAE.
- Presence in multiple periods.

Aggregate scoring should penalize:

- Sample count below configured thresholds.
- Any period with clearly negative average profit and poor hit rate.
- Rules that only work in one year.

### 4. Output

The miner writes both:

- Markdown report: `reports/short_signal_factor_miner.md`.
- JSON artifact: `reports/short_signal_factor_miner.json`.

The Markdown report starts with the best candidates, followed by rejected patterns and a concise interpretation section. It must explicitly state that the report is research evidence only.

### 5. Next Strategy Direction

If the miner finds stable candidates, v21 should become a two-layer strategy:

- Regime gate: decide whether the day is tradable or should be no-recommendation.
- Signal lane: choose one of the stable short-window rules, not a single global factor profile.

If no stable candidates appear, the correct conclusion is no-trade in those regimes, not forcing recommendations.

## Success Criteria

The research harness is successful when it can:

- Read the known v19 2024/2025/2026H1 trade files.
- Produce ranked rule candidates with per-period metrics.
- Show why v19 fails in 2024 using factor/regime buckets.
- Identify at least one next experiment path or conclude that existing trade-level data is insufficient and candidate-level `ic_short` files must be used next.

The broader strategy goal is not complete until a later v21 or replacement strategy is backtested across 2024, 2025, and 2026H1 and verified against the user's high-win, high-short-window-rise objective.
