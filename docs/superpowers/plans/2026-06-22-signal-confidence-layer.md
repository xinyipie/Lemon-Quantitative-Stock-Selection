# Signal Confidence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable confidence layer so users can distinguish strong, watch, weak, and currently excluded signals without changing official strategies.

**Architecture:** The confidence layer is computed in `web_app/services/signal_service.py` after existing quality/risk enrichment. Templates render the new fields as compact tags and tooltips, while AI fallback explanations include the same facts so generated copy stays grounded.

**Tech Stack:** Python, SQLite-backed signal service, Jinja templates, unittest.

---

### Task 1: Signal Confidence Fields

**Files:**
- Modify: `web_app/services/signal_service.py`
- Test: `tests/test_web_services.py`

- [ ] **Step 1: Write failing tests**

Add tests that create strong, weak, and current-risk-blocked signal records, then assert `confidence_label`, `confidence_tone`, and `confidence_summary`.

- [ ] **Step 2: Implement confidence enrichment**

Add helper functions that classify signals as `强信号`, `可观察`, `弱信号`, or `风险排除` using existing score, outcome, process, MAE, and current risk fields.

- [ ] **Step 3: Verify tests**

Run: `python -m unittest tests.test_web_services`

### Task 2: Render Confidence in Web Pages

**Files:**
- Modify: `web_app/templates/dashboard.html`
- Modify: `web_app/templates/signals.html`
- Modify: `web_app/templates/stock_detail.html`
- Modify: `web_app/static/app.css`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Write failing render assertions**

Assert the short signal pages include `可信度` and at least one confidence label.

- [ ] **Step 2: Add confidence tags**

Show the confidence tag near each signal's existing review tags. Use a tooltip for detailed evidence.

- [ ] **Step 3: Verify page tests**

Run: `python -m unittest tests.test_web_app`

### Task 3: AI Fallback Explanation Uses Confidence

**Files:**
- Modify: `web_app/services/explanation_service.py`
- Test: `tests/test_explanation_service.py`

- [ ] **Step 1: Write failing explanation test**

Assert fallback explanations include the confidence label and confidence evidence when the signal provides it.

- [ ] **Step 2: Include confidence facts**

Use `confidence_label` and `confidence_summary` in the fallback summary and risk/positive lists.

- [ ] **Step 3: Verify explanation tests**

Run: `python -m unittest tests.test_explanation_service`

### Task 4: Final Verification

**Files:**
- No additional files.

- [ ] **Step 1: Run focused tests**

Run: `python -m unittest tests.test_web_services tests.test_web_app tests.test_explanation_service`

- [ ] **Step 2: Compile changed Python files**

Run: `python -m py_compile web_app\services\signal_service.py web_app\services\explanation_service.py tests\test_web_services.py tests\test_web_app.py tests\test_explanation_service.py`

- [ ] **Step 3: Browser check**

Open `/`, `/signals`, and `/stock/000001` to confirm confidence tags display without crowding the tables.
