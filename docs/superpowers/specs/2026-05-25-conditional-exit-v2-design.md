# Conditional Exit V2 Design

## Context

The current short-strategy baseline is `profile_v4_adaptive_quality + baseline exit`.
Full-year 2025 validation rejected global exit tightening: `exit_v1_mid_lock` and
`exit_v1_profit_guard` improved some local exit cases but reduced or failed to improve
the overall portfolio result.

Attribution on the 2025 baseline trades showed that bad trailing-stop samples differ
from good take-profit samples mainly on weaker structure and path quality:

- lower `factor_pattern`
- lower `factor_wyckoff`
- lower `factor_volume_ratio`
- more extreme `factor_drawdown`
- deeper MAE

This supports conditional exit management instead of another global parameter change.

## Goal

Add an experimental exit profile named `exit_v2_conditional_lock`.

The profile should preserve the baseline exit behavior for normal and strong names,
and only tighten the trailing lock for high-risk names that have already produced
meaningful upside but show weak structure or poor path quality.

This is also designed to become a future live holding-risk hint. The system should not
assume automatic trading execution. In live use, the same rule can produce messages
such as "higher sell-risk, tighten manual watch" for the user's own decision process.

## Non-Goals

- Do not replace the main baseline exit by default.
- Do not change `profile_v4_adaptive_quality` factor scoring.
- Do not add automatic live sell execution.
- Do not tune only to Q1 results.

## Proposed Rule

Start from baseline short exit parameters:

- fallback stop: `-7.0%`
- fallback profit: `15.0%`
- trailing stop: `7.0%`
- trailing activation: `3.0%`

When a trade has meaningful profit potential and a weak-quality risk signature, use a
tighter conditional trailing stop for that trade only.

Initial risk signature:

- `factor_pattern < 58`, or
- `factor_wyckoff < 62`, or
- `factor_volume_ratio < 58`, or
- `factor_drawdown > 90`, or
- `drawdown_from_high > 8` with weak pattern

Initial activation idea:

- only apply the tighter lock after current profit or MFE reaches at least `6%`
- conditional trailing width starts at `4.5%` to `5.0%`

The exact thresholds are intentionally conservative and must be verified against both
2026Q1 and full-year 2025.

## Code Shape

- Add optional conditional exit parameters to `BacktestV2`.
- Keep default behavior identical when conditional exit is disabled.
- Add `exit_v2_conditional_lock` to `test.py` as an experiment profile.
- Record conditional-exit metadata in trade output if practical, so attribution can
  compare triggered and non-triggered trades.
- Keep future live-hint reuse in mind, but do not build the live hint UI in this step.

## Validation

Required smoke:

```text
python -m py_compile backtest_v2.py test.py
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20250102 --end 20250110 --label smoke_exit_v2
```

User-run validation:

```text
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20260101 --end 20260420 --label 2026Q1_exit_v2
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20250101 --end 20251231 --label 2025_exit_v2_confirm
```

Promotion criteria:

- Q1 does not deteriorate materially.
- 2025 total return and Sharpe are not worse than baseline.
- max drawdown does not increase materially.
- high-MFE losers, big givebacks, or average giveback improve enough to justify the
  extra rule complexity.

If full-year 2025 deteriorates, keep baseline exit and only reuse the attribution logic
later as a live holding-risk warning.
