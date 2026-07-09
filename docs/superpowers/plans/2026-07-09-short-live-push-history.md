# Short Live Push History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the latest 30 real short live push records on `/signals`, clearly separating strong recommendations from observation candidates.

**Architecture:** Reuse the existing signal database read path. Add a service helper that reads `source in ("live", "live_observe")` with `mode = "short"`, decorates each row with a layer label, and pass the list into the existing `/signals` route and template.

**Tech Stack:** Python, SQLite, FastAPI/Jinja2, unittest.

## Global Constraints

- Display exactly the latest 30 real live push records by default.
- Include only `source in ("live", "live_observe")` and `mode = "short"`.
- Exclude `backtest_ic_short` from this history.
- Do not change the existing backtest review table or short performance statistics.
- Do not add auto-order, position-management, or trade-execution code.

---

### Task 1: Service Helper For Live Push History

**Files:**
- Modify: `web_app/services/signal_service.py`
- Test: `tests/test_web_services.py`

**Interfaces:**
- Produces: `get_short_live_push_history(signal_db: str | Path = DEFAULT_DB_PATH, history_db: str | Path | None = DEFAULT_HISTORY_DB_PATH, limit: int = 30) -> list[dict]`
- Produces decorated keys: `history_layer_label`, `history_layer_tone`, `history_reason`, `history_entry_timing`

- [ ] **Step 1: Write the failing test**

Add a test that creates one `live`, one `live_observe`, and one `backtest_ic_short` short signal. Assert the helper returns only the first two, with layer labels `强推荐` and `观察候选`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m unittest tests.test_web_services.WebServicesTest.test_short_live_push_history_includes_live_layers_and_excludes_backtest`

Expected: FAIL because `get_short_live_push_history` is not defined.

- [ ] **Step 3: Implement minimal service helper**

Implement `get_short_live_push_history` by calling `get_recent_signals(..., source=["live", "live_observe"], mode="short", limit=limit)`, then decorate each item. Strong label is used for `source == "live"`, observe label for `source == "live_observe"`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests.test_web_services.WebServicesTest.test_short_live_push_history_includes_live_layers_and_excludes_backtest`

Expected: PASS.

### Task 2: Signals Route And Template

**Files:**
- Modify: `web_app/app.py`
- Modify: `web_app/templates/signals.html`
- Modify: `web_app/static/app.css`

**Interfaces:**
- Consumes: `get_short_live_push_history(...) -> list[dict]`
- Produces template variable: `live_push_history`

- [ ] **Step 1: Route wiring**

Import `get_short_live_push_history` in `web_app/app.py`. In the `/signals` route, call it with `limit=30` and pass `live_push_history` into the template context.

- [ ] **Step 2: Template block**

In `web_app/templates/signals.html`, add a `短线实盘推送历史` panel after the strong and observation cards and before the filter form. Render a compact table with date, layer, stock, industry, score, entry timing, and reason. Empty state says `暂无实盘推送历史。`

- [ ] **Step 3: CSS polish**

Add compact classes for layer badges and reason text in `web_app/static/app.css`, reusing existing colors.

- [ ] **Step 4: Run route-related tests**

Run: `python -m unittest tests.test_web_services`

Expected: PASS.

### Task 3: Verification, Commit, Deploy

**Files:**
- Verify: all modified Python files

- [ ] **Step 1: Run focused tests**

Run: `python -m unittest tests.test_web_services`

Expected: PASS.

- [ ] **Step 2: Compile changed Python**

Run: `python -m py_compile web_app/app.py web_app/services/signal_service.py tests/test_web_services.py`

Expected: no output and exit code 0.

- [ ] **Step 3: Commit**

Stage only the plan and implementation files, then commit with message `Add short live push history panel`.

- [ ] **Step 4: Push and deploy**

Push `main`, then SSH to `/opt/stock`, run `git pull --ff-only origin main`, restart `stock-web`, and verify `/signals` returns HTTP 200.
