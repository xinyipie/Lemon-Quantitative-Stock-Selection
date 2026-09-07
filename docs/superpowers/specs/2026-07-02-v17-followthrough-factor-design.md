# v17 Followthrough Factor Design

## Goal

Build a short-line research profile that increases trade coverage versus v16 while staying focused on the user's core requirement: selected stocks should have a high chance of rising in the next 3-5 trading days.

## Context

The v16 gate produced clean but sparse signals. The useful evidence from prior experiments points back to the v12 family: v12 had materially better 2026H1 coverage and positive return, but admitted too many noisy momentum and sideways candidates. v17 therefore starts from the v12 coverage idea and adds a follow-through confirmation layer instead of loosening v16.

## Factor Lessons Used

- `weak_momentum` and selective `momentum` candidates are more useful than broad sideways candidates for 2026H1.
- `factor_sector` is useful as confirmation but should not be treated as "higher is always better".
- Controlled volume and controlled drawdown matter more than raw score.
- `factor_wyckoff` can become a heat/noise warning when it is too high.
- Final validation must include `hit_3pct_rate`, `hit_5pct_rate`, `avg_mfe_pct`, `avg_mae_pct`, and `avg_window_end_pct`, not only realized trade win rate.

## Strategy Shape

Add:

- `profile_v17_followthrough_factor`
- `adaptive_quality_v17`

The gate keeps two interpretable lanes:

Lane A, high-confirmation follow-through:

- `market_style in ("weak_momentum", "momentum")`
- `factor_pattern >= 60`
- `factor_inflow >= 90`
- `factor_sector >= 35`
- `drawdown_from_high <= 7`
- `volume_ratio <= 2.8`
- `change <= 5`
- `factor_wyckoff <= 70`

Lane B, balanced not-overheated follow-through:

- `market_style in ("weak_momentum", "momentum")`
- `factor_pattern >= 60`
- `factor_inflow >= 70`
- `35 <= factor_sector <= 85`
- `drawdown_from_high <= 6`
- `volume_ratio <= 2.5`
- `change <= 5`
- `factor_wyckoff <= 80`

Bear and sideways candidates are excluded in the first v17 pass. This is intentional: the 2026H1 evidence shows weak-momentum/momentum carried the better follow-through profile, while sideways added many false repairs.

## Validation

Run Top1 first:

```powershell
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 1 --factor-profile profile_v17_followthrough_factor --style-gate adaptive_quality_v17
python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --no-timing --hold 8 --topn 1 --factor-profile profile_v17_followthrough_factor --style-gate adaptive_quality_v17
```

Then run Top2 only as a diagnostic if Top1 is promising:

```powershell
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 2 --factor-profile profile_v17_followthrough_factor --style-gate adaptive_quality_v17
python backtest_v2.py --mode short --offline --start 20260101 --end 20260630 --no-timing --hold 8 --topn 2 --factor-profile profile_v17_followthrough_factor --style-gate adaptive_quality_v17
```

Acceptance targets:

- 2025 and 2026H1 total return must both be positive.
- 2026H1 should improve trade count materially versus v16.
- Prefer realized win rate near or above 70%, but reject any result that reaches it only through tiny sample size.
- Prefer `hit_3pct_rate >= 75%` and `hit_5pct_rate >= 60%`.
- `avg_window_end_pct` should stay positive.
- `avg_mae_pct` should not materially worsen versus the v12/v15 coverage baselines.

