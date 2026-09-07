# Daily Report Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the scheduled daily report publishable when DeepSeek output violates deterministic numeric traceability.

**Architecture:** The service first attempts the existing DeepSeek draft and repair flow. If no validated AI document remains, it builds a deterministic document from `public_facts`, validates that document through the same gate, and publishes it with `generation_mode=data_fallback`.

**Tech Stack:** Python, unittest, SQLite report store.

## Global Constraints

- Do not relax `validate_report()`.
- Do not publish or render a rejected AI draft.
- Never use facts outside the current report run's approved public facts.

---

### Task 1: Prove validated fallback publication

**Files:**
- Modify: `tests/test_daily_report_service.py`
- Modify: `daily_report/service.py`

**Interfaces:**
- Consumes: `fallback_builder(public_facts) -> dict | None`
- Produces: `generate_daily_report(...)["status"] == "published"` when an invalid AI draft has a valid deterministic fallback.

- [ ] **Step 1: Write the failing test**

```python
def test_invalid_ai_document_publishes_validated_deterministic_fallback(self):
    result = self.generate(
        writer=lambda public: _document("bad"),
        fallback_builder=build_deterministic_report_document,
    )
    self.assertEqual(result["status"], "published")
    self.assertEqual(get_report(self.signal_db, "20260723")["document"]["generation_mode"], "data_fallback")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_daily_report_service.DailyReportServiceTest.test_invalid_ai_document_publishes_validated_deterministic_fallback`

Expected: `failed` is returned because the service does not yet call the fallback builder.

- [ ] **Step 3: Implement the minimal fallback branch**

```python
if errors or not document:
    fallback = fallback_builder(public_facts)
    fallback_errors = validate_report(fallback, facts, public_facts) if fallback else ["fallback unavailable"]
    if not fallback_errors:
        document = fallback
```

- [ ] **Step 4: Run the focused service tests**

Run: `python -m unittest tests.test_daily_report_service`

Expected: all service tests pass, including incomplete-facts and invalid-fallback safety cases.

### Task 2: Use the fallback in production scheduling

**Files:**
- Modify: `daily_report/service.py`
- Test: `tests/test_daily_report_service.py`

**Interfaces:**
- Consumes: `build_deterministic_report_document(public_facts)`
- Produces: a default fallback when `generate_daily_report()` is called from `daily_research_report.py`.

- [ ] **Step 1: Write a failing test for the production default**

```python
result = generate_daily_report(..., writer=lambda public: _document("bad"))
self.assertEqual(result["status"], "published")
```

- [ ] **Step 2: Verify the test fails before the default is wired**

Run: `python -m unittest tests.test_daily_report_service.DailyReportServiceTest.test_default_fallback_publishes_after_invalid_ai_document`

Expected: `failed` is returned.

- [ ] **Step 3: Set the service default to the deterministic builder**

```python
fallback_builder=build_deterministic_report_document
```

- [ ] **Step 4: Run focused tests and scheduled-update contract test**

Run: `python -m unittest tests.test_daily_report_service tests.test_scheduled_update`

Expected: all tests pass.

### Task 3: Deploy and recover today\'s report

**Files:**
- Deploy: `daily_report/service.py`

- [ ] **Step 1: Push the validated revision and update `/opt/stock` without touching runtime databases**

Run: `git push origin main`, then `git pull --ff-only origin main` on the server and restart `stock-web`.

- [ ] **Step 2: Generate the missing 2026-08-17 report through the normal CLI**

Run: `python daily_research_report.py --report-date 20260817 --market-date 20260814 --slot manual --force`

- [ ] **Step 3: Verify status and the published report record**

Run: inspect `data/daily_report_status.json`, `daily_report_update.log`, and `http://127.0.0.1:8000/reports/20260817`.

Expected: report status is published and no unsupported numeric text is present.
