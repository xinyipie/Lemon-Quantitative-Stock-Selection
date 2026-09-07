# v16 Window Confidence Layer Design

## Goal

Build a short-line research profile that prioritizes stocks likely to rise in the next 3-5 trading days. Total return remains important, but the first acceptance signal is window quality: `hit_3pct_rate`, `hit_5pct_rate`, `avg_mfe_pct`, `avg_window_end_pct`, and controlled `avg_mae_pct`.

## Context

The previous experiments show three repeated lessons:

- Top1 concentration can produce attractive win rates with too few trades, but it does not generalize across periods.
- Simple factor weighting and hard quality gates are unstable because individual factors flip by market style and time period.
- The most reusable structure is style-aware gating around the existing `adaptive_quality` family, with `baseline exit` left unchanged.

The v15 experiment confirmed this again: the strict lane was clean but sparse, while the relaxed weak-momentum lane added 2025 coverage and immediately weakened 2026H1 window quality.

## Strategy Shape

v16 keeps the implementation small and testable:

- Add `profile_v16_window_confidence` as a scoring profile.
- Add `adaptive_quality_v16` as the A-grade recommendation gate.
- Keep B-grade observation as score behavior rather than a separate output channel, because the current backtest runner only consumes ranked candidates.
- Do not change exit rules, position sizing, order execution, or live trading behavior.

## A-Grade Gate

The A-grade gate is the only part that can pass into recommendation backtests.

Common requirements:

- Reject bear style.
- Require calm entry: `change <= 3.0`.
- Require controlled volume: `1.35 <= volume_ratio <= 2.65`.
- Reject the 9-12% drawdown risk bucket.
- Require shallow pullback: `drawdown_from_high <= 5.0`.

Lane A, strong sector continuation:

- `factor_pattern >= 72`
- `factor_inflow >= 72`
- `factor_sector >= 68`

Lane B, weak-momentum continuation:

- `market_style == "weak_momentum"`
- `factor_pattern >= 82`
- `factor_inflow >= 84`
- `factor_sector >= 60`
- `drawdown_from_high <= 4.8`

Lane B is deliberately stricter than v15 because v15 showed that relaxed weak-momentum candidates can look good on shape and money flow while failing 2026H1 follow-through.

## Scoring

`profile_v16_window_confidence` builds on `profile_v14_sector_pattern_gate`, then adjusts toward window quality:

- Reward strong sector continuation and strong pattern.
- Reward calm entry and controlled volume.
- Penalize the 9-12% drawdown bucket.
- Penalize weak-momentum candidates unless they satisfy Lane B confirmation.
- Penalize sideways active candidates unless they also satisfy the strong sector lane.

The score is used only for ranking after the gate. It must not introduce trading execution behavior.

## Validation

Run unit tests first, then run these backtests:

```powershell
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 1 --factor-profile profile_v16_window_confidence --style-gate adaptive_quality_v16
python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --no-timing --hold 8 --topn 1 --factor-profile profile_v16_window_confidence --style-gate adaptive_quality_v16
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 2 --factor-profile profile_v16_window_confidence --style-gate adaptive_quality_v16
python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --no-timing --hold 8 --topn 2 --factor-profile profile_v16_window_confidence --style-gate adaptive_quality_v16
```

Acceptance focus:

- 2025 and 2026H1 should keep positive total return.
- Prefer `hit_3pct_rate >= 75%`.
- Prefer `hit_5pct_rate >= 60%`.
- `avg_window_end_pct` should be positive.
- `avg_mae_pct` should not materially worsen versus v15.
- Trade count should improve versus v14 if possible, but not by admitting low-confidence weak-momentum noise.

