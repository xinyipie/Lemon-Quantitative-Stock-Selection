# Nightly Strategy Research Automation Plan

## Goal

Create a conservative unattended research workflow that starts from the `codex/strategy-research` branch, runs existing read-only strategy diagnostics, writes a nightly report, and avoids blocking on ordinary confirmations while the user is away.

## Scope

- Add a runner under `research/` that orchestrates existing research scripts.
- Add docs that explain the no-confirmation rule and morning review flow.
- Create a recurring Codex automation for 20:00 local time.
- Do not modify official strategy defaults or `main.py`.
- Do not add trading execution or broker integration.

## Steps

1. Add a focused unit test for branch safety and report generation.
2. Implement `research/nightly_strategy_runner.py`.
3. Add protocol docs for unattended operation.
4. Run related tests and a smoke command.
5. Create the daily 20:00 automation.
6. Commit and push the research-branch changes.

## Verification

- `python -m unittest tests.test_nightly_strategy_runner`
- `python -m py_compile research/nightly_strategy_runner.py`
- Optional smoke: `python research/nightly_strategy_runner.py --until 08:00`

