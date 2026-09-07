# v15 Dual-Lane Quality Gate Design

## Goal

Increase trade coverage versus v14 while keeping the short-strategy target anchored on high win rate: 2025 full year and 2026 H1 should both keep win rate at or above 70% and positive total return.

## Problem

v14 reached the win-rate target, but 2026 H1 only produced one trade. That is too thin to trust and has high overfitting risk. The next version should not simply loosen every threshold. It should add a second controlled lane that can admit more candidates without letting overheated or structurally weak setups through.

## Design

v15 keeps v14 as lane A:

- `factor_pattern >= 70`
- `factor_inflow >= 70`
- `factor_sector >= 65`
- `drawdown_from_high <= 5`
- `1.3 <= volume_ratio <= 2.8`
- `change <= 3`
- `market_style != bear`

v15 adds lane B for coverage:

- only `market_style == weak_momentum`
- `factor_pattern >= 76`
- `factor_inflow >= 80`
- `drawdown_from_high <= 5.5`
- `1.3 <= volume_ratio <= 2.6`
- `change <= 3`
- `factor_sector >= 35`

Lane B deliberately avoids broad sideways and bear candidates. It relaxes sector strength only when individual pattern and inflow are stronger than lane A.

## Validation

Run Top1 first:

- 2025 full year: `20250101` to `20251231`
- 2026 H1: `20260101` to `20260630`

Acceptance target:

- both periods win rate >= 70%
- both periods total return > 0
- preferred coverage: 2025 >= 10 trades and 2026 H1 >= 5 trades

If Top1 cannot reach acceptable coverage, test Top2 as a diagnostic only. Do not accept Top2 unless both periods still pass win-rate and return gates.
