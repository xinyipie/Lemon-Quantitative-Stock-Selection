# v29 Consensus Guard Design

## Objective

Create a research-only short strategy framework that uses agreement among the strongest existing short profiles to reduce garbage recommendations while preserving the 2025/2026H1 high-return behavior.

The target behavior is not "recommend every day." The target is to recommend fewer stocks when the setup is poor and prioritize stocks that have a high probability of moving up within the next 3-5 trading days.

## Evidence Base

Primary evidence:

- `backtest_results/ten_year_strategy_matrix_20260703_163316.csv`
- `reports/stage2_consensus_simulation.csv`
- `reports/stage3_gated_candidate_consensus_topn_simulation.csv`
- `docs/TEN_YEAR_STAGE1_MATRIX_20260703.md`
- `docs/TEN_YEAR_STAGE2_CONSENSUS_20260703.md`

Findings:

- v19/v25/v27 are the only current family worth promoting into a new framework.
- Single-version-only trades are the main source of garbage, especially in 2022-2024.
- Trade-detail consensus is strong in 2025/2026H1, but candidate-pool fixed 5-day returns show lower win rate than full trade simulation.
- Therefore v29 must be verified with the full `backtest_v2.py` trade simulator, not only with `ret_5d`.

## Proposed Strategy

Name:

- `profile_v29_consensus_guard`
- `adaptive_quality_v29_consensus_guard`

Research profiles:

- `profile_v19_calm_followthrough` + `adaptive_quality_v19`
- `profile_v19_calm_followthrough` + `adaptive_quality_v25`
- `profile_v21_sector_calm_followthrough` + `adaptive_quality_v27`

Admission:

- For each selection date, build three virtual candidate lists using the same raw `stock_pool`.
- A stock is admissible only if at least two of the three virtual lists admit it after their own score profile and style gate.
- A stock admitted by all three lists receives a consensus bonus.
- A stock admitted by only one list is rejected by default.

Ranking:

- Primary: consensus count descending.
- Secondary: average rank across admitting profiles ascending.
- Tertiary: average experiment score descending.
- Optional tie-breaker: recent-factor bonus only when the market window is active.

Recent-factor bonus:

- `factor_sector <= 45`
- `factor_pattern <= 40`
- `change <= 4.5`
- `macro_mode == active`

This bonus must not act as an independent admission rule. It can only rerank stocks already admitted by consensus.

Weak-window behavior:

- If no stock has two-profile consensus, recommend nothing.
- In 2022/2023-like weak windows, do not allow single-profile fallback.
- This is intentional. Empty recommendation days are better than pushing low-quality names.

TopN:

- Test both Top1 and Top2.
- Do not test Top3 until Top1/Top2 prove robust; previous evidence shows wider baskets dilute quality.

## Implementation Boundaries

Do not change default live behavior during research.

Allowed implementation:

- Add research profile/gate names.
- Add a contained consensus-selection helper that can be enabled only by explicit CLI/profile configuration.
- Add tests for the helper using small synthetic DataFrames.
- Add backtest matrix entries for v29 Top1 and Top2.

Not allowed:

- No automated order placement or execution logic.
- No default live profile switch.
- No future-looking MAE/MFE fields in admission logic.
- No use of `ret_5d`, `mfe_pct`, `mae_pct`, or `window_end_pct` as input factors.

## Verification Plan

Smoke:

- `python -m py_compile strategy_profiles.py backtest_v2.py`
- Unit tests for consensus helper.
- One short 2025 smoke run to confirm profile works.

Main validation:

- Run v29 Top1/Top2 across 2016-2026H1 with the same matrix periods used in Stage1.
- Compare against v19/v25/v27 and v9 baselines.

Required output:

- A matrix CSV in `backtest_results`.
- A research report in `docs/` or `reports/`.

Promotion criteria:

- 2025 full-year win rate should be near or above 70% with positive return.
- 2026H1 win rate should be near or above 70% with positive return.
- 2022-2024 should avoid large negative recommendation clusters, even if that means no recommendations.
- Ten-year total return must be positive.
- Single-profile-only trades must not dominate losses.

Failure criteria:

- If v29 fixed Top1/Top2 cannot beat v19/v25/v27 on both recent performance and weak-window loss control, it stays research-only.
- If gains come only from 2025/2026H1 while 2016/2017/2023 deteriorate sharply, treat it as overfit.

