# Daily Report Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Preserve strict report accuracy while adding one constrained repair attempt, a deterministic safe fallback, and durable scheduled-task logs.

**Architecture:** `daily_report.service` orchestrates validation, repair, fallback, and publication. `daily_report.writer` owns AI repair and deterministic fallback construction. `update_worker` and `update_service` persist subprocess streams without changing dashboard status behavior.

**Tech Stack:** Python, SQLite, unittest, Bash, cron

## Global Constraints

- Keep the existing deterministic report validator unchanged.
- Never publish unsupported numeric claims.
- Preserve the previous valid report whenever all attempts fail.
- Do not change quantitative scores or trading logic.

### Task 1: Strict report repair and fallback

- [ ] Add tests for valid repair, deterministic fallback, and total failure.
- [ ] Implement one constrained repair attempt and deterministic fallback.
- [ ] Run `python -m unittest tests.test_daily_report_service -v`.

### Task 2: Durable scheduler logs

- [ ] Add worker and runner log assertions.
- [ ] Persist subprocess streams with start and finish markers.
- [ ] Run `python -m unittest tests.test_update_service tests.test_scheduled_update -v`.

### Task 3: Deploy and recover today's report

- [ ] Deploy application files and install both runner scripts.
- [ ] Restart `stock-web`.
- [ ] Force-generate the current report through the repaired strict pipeline.
- [ ] Confirm publication and website availability.
