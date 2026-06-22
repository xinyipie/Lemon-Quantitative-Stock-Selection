# Nightly Research Protocol

## Branch And Scope

- Required branch: `codex/strategy-research`.
- Official short baseline remains: `profile_v4_adaptive_quality_v9_sector_quality_guard + baseline exit + Top3`.
- Current longterm research baseline remains: `longterm_quality_lifecycle_v18_market_sync`.
- Do not change `main.py` default online strategy.
- Do not delete historical experiment assets.
- Do not create automatic trading, broker, or order execution code.

## Autonomy Rules

- Do not ask the user for routine confirmations during the night.
- Make conservative assumptions when a choice is low-risk and reversible.
- Skip destructive or ambiguous actions and write the blocker into the nightly report.
- If external data or Git authentication fails, continue with local diagnostics and record the failure.
- Prefer diagnostic tools, factor stability checks, and pool-quality analysis before proposing a new profile.

## Research Standards

Every candidate strategy note must include:

- Logic changed.
- Trading or financial rationale.
- Market regimes where it should work or fail.
- Overfitting risk.
- Cross-period validation status.
- Recommendation: abandon, keep observing, or enter next validation.

## Stop Rule

At or before the configured deadline, write a concise summary under:

```text
reports/research/nightly/YYYYMMDD/
```

If no mature candidate exists, say so directly. A clean “no upgrade” result is valid research.

