# v40 Dual Layer Gap Fill Design

## Background

The ten-year short-line audit found a clean high-confidence lane but not yet a complete short-line strategy:

- `v35_consensus_cautious_high_pattern_top1_hold3`: 26 trades, 92.31% win rate, +185.44% total return, 0 loss years.
- `v39_consensus_strong_rank_top1_hold3`: 23 trades, 95.65% win rate, +165.73% total return, 0 loss years.
- `v35 Top2`: 39 trades, but win rate drops to 76.92% and return drops to +77.99%.
- `v19 Top1`: 107 trades and +232.93% total return, but only 56.08% win rate with 6 loss years.
- `v9 Top1`: 238 trades, but only 39.92% win rate and too many poor recommendations.

The user requirement is not simply more trades. The strategy should recommend stocks that are likely to rise in the next 3-5 days, avoid low-quality names, remain profitable across years, and reduce the long empty windows of the v35/v39 high-confidence lane.

## Goal

Design a research-only `v40_dual_layer_gap_fill_50_80_trades` strategy.

The target is to raise the ten-year trade count from the current 23-26 range to roughly 50-80 trades, with 40-60 trades acceptable if quality remains materially better. The strategy must not chase daily recommendations. If the available candidates are weak, it should stay empty.

## Non-Goals

- Do not change the live default strategy.
- Do not add any order execution, position automation, or trading API behavior.
- Do not optimize for one year only.
- Do not promote a rule only because it improves 2025 or 2026H1.
- Do not allow single-version candidates to enter the gap-fill lane directly.

## Strategy Shape

v40 is a two-layer short-line framework.

### Layer 1: Primary High-Confidence Lane

Layer 1 keeps the current first-tier strategy unchanged:

- Yield-oriented primary lane: `v35 Top1`.
- High-confidence sparse lane: `v39 Top1`.

For the research profile, `v35 Top1` is the default primary lane because it has the highest first-tier total return. `v39 Top1` remains the stricter comparison lane.

When Layer 1 has candidates on a selection date, v40 should use Layer 1 and should not add lower-confidence names just to increase count.

### Layer 2: Gap-Fill Lane

Layer 2 runs only when Layer 1 has no candidate on a selection date.

Layer 2 candidates must satisfy all base conditions:

- Consensus membership: candidate appears in at least two historical strong routes.
- Candidate is not `single_only`.
- Candidate has a low drawdown path profile in the available evidence, using MAE-oriented gates from the consensus research.
- Candidate has plausible 3-day or 5-day upside evidence, prioritizing MFE and hit-rate behavior over long-hold recovery.
- Candidate passes weak-window defense for 2022/2023-like environments.

The intended source evidence is the existing consensus snapshot and stage2 simulation:

- `consensus_2plus_low_mae_shape`: 29 trades, 75.86% win rate, +132.80% total return, 89.66% 3% hit rate, 72.41% 5% hit rate.
- `single_only`: 25 trades, 40.00% win rate, -0.81% total return, weak-window garbage source.

Layer 2 should be conservative enough that it expands coverage without becoming v19 or v9 again.

## Candidate Ranking

Layer 2 ranking should be deterministic and explainable:

1. Higher consensus vote count.
2. Better consensus average rank.
3. Lower expected MAE or stronger low-MAE shape.
4. Better 3-day MFE / 3% hit evidence.
5. Market heat is acceptable but not overloaded.
6. Lower reliance on unstable factors such as raw volume ratio, high pattern score, or high sector heat.

Factors known to be unstable should not receive global positive weight:

- `volume_ratio` and `factor_volume_ratio`: direction changed between 2025 and 2026Q1.
- High `factor_pattern`: not reliably positive and can select fragile names.
- High `factor_sector`: not globally positive; lower sector position was more stable in factor stability research.

## Weak-Window Defense

The gap-fill lane must explicitly defend against the known weak windows:

- 2022: avoid forcing trades in defensive conditions.
- 2023: avoid consensus candidates that only show 3-day pop potential but fail 5-day profit and MAE control.

Weak-window defense may use already available market context columns:

- `market_style`
- `macro_mode`
- `regime`
- `market_index_change`
- `sector_ma10_ratio`
- `limit_up_count`
- `limit_down_count`
- `limit_up_down_ratio`

The design prefers no trade over a low-quality gap-fill trade.

## Validation Plan

The implementation must produce a full ten-year matrix for 2016-2026H1 and at least these comparison rows:

- `v35_consensus_cautious_high_pattern_top1_hold3`
- `v39_consensus_strong_rank_top1_hold3`
- `v35_consensus_cautious_high_pattern_top2_hold3`
- `v19_top1_hold3`
- `v9_top1_hold8`
- `v40_dual_layer_gap_fill_50_80_trades`

The validation report must include:

- Total trades.
- Active years.
- Positive years.
- Loss years.
- Weighted win rate.
- Total return.
- 2025 win rate and return.
- 2026H1 win rate and return.
- 3% hit rate.
- 5% hit rate.
- Average MAE.
- Weak-window 2022/2023 detail.
- Difference samples showing which trades came from Layer 1 and which from Layer 2.

## Promotion Criteria

v40 is considered useful only if it satisfies these conditions:

- Ten-year trades are preferably 50-80, acceptable 40-60 if quality is strong.
- Total return remains positive and competitive with first-tier strategies.
- Loss years remain 0 or are limited to very small drawdowns that are explicitly explained.
- 2025 full-year win rate is near or above 70%.
- 2026H1 win rate is near or above 70%.
- 3% hit rate remains high enough to support the user's 3-5 day rise requirement.
- Layer 2 trades do not dominate the result; they supplement Layer 1 rather than replace it.

## Failure Criteria

v40 should be rejected or redesigned if any of these happen:

- Trade count increases mainly by reintroducing `single_only` behavior.
- 2022 or 2023 becomes materially negative.
- 2025 or 2026H1 drops far below the 70% win-rate target.
- The strategy depends on a small one-year exception.
- Top2-style expansion causes win rate and return to collapse.
- The result is not materially better than simply using v35/v39 as a high-confidence sparse lane.

## Implementation Boundary

The first implementation should be research-only:

- Add tests around the layer-selection behavior.
- Add a strategy profile or research helper that can replay Layer 1 and Layer 2.
- Run the ten-year matrix offline.
- Write a result document under `docs/`.
- Do not change `SHORT_LIVE_CONSENSUS_PROFILE` default.

Live integration can be considered only after the research report proves the profile is useful.
