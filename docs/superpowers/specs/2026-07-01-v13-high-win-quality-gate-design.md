# v13 High Win Quality Gate Design

## Goal

Find a short-term stock selection strategy that uses `TopN=1` or `TopN=2`, reaches at least 70% win rate on both 2025 full-year backtest and 2026 first-half backtest, and keeps both periods profitable.

## Strategy Shape

The strategy is intentionally selective but does not cap the number of trades. It starts from the stronger historical baseline, `profile_v9_sector_quality_guard` with `adaptive_quality_v6`, then adds a harder quality gate aimed at the user's requirement: selected stocks should rise over the next three to five days.

`TopN=1` is the default validation mode. `TopN=2` is allowed only when the second candidate passes the same strict quality gate; the system must never lower the gate just to fill a second slot.

## Quality Gate

The first implementation will introduce:

- `profile_v13_high_win_quality_gate`
- `adaptive_quality_v13`

The quality gate favors candidates with strong structure, clear inflow, controlled pullback, and non-overheated volume:

- `factor_pattern >= 63`
- `factor_inflow >= 70`
- `drawdown_from_high <= 7`
- `1.3 <= volume_ratio <= 3.0`
- `change <= 5.0`

Weak or unstable styles get stricter treatment. `sideways`, `bear`, `short_only`, and override-like environments must pass stronger quality thresholds or remain empty. If no candidate passes, the strategy returns no pick for that day.

## Validation

Backtest commands:

- `python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --factor-profile profile_v13_high_win_quality_gate --style-gate adaptive_quality_v13 --topn 1 --short-filter-profile baseline`
- `python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --factor-profile profile_v13_high_win_quality_gate --style-gate adaptive_quality_v13 --topn 1 --short-filter-profile baseline`
- repeat both with `--topn 2`

The work stops only when one validated combination satisfies:

- 2025 win rate >= 70%
- 2026 H1 win rate >= 70%
- 2025 total return > 0
- 2026 H1 total return > 0

If the first v13 pass misses, thresholds will be iterated in small steps. The preferred adjustment order is to tighten weak-market gates first, then tune volume and drawdown bands, and only then consider score weighting changes.
