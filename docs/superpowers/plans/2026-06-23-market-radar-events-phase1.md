# Market Radar Events Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend event-standardization layer for Market Radar v2 using existing `news_sector_*.json` cache payloads.

**Architecture:** Create a small `market_radar` package with pure functions that turn cached AI/news payloads into standardized event dictionaries and a summary. Keep `web_app/services/sector_service.py` as the Web compatibility layer and add `events` / `event_summary` to `build_concept_news_radar()` without changing strategy logic.

**Tech Stack:** Python standard library, `unittest`, existing JSON cache format, existing FastAPI/Jinja service tests.

---

### Task 1: Standard Event Builder

**Files:**
- Create: `market_radar/__init__.py`
- Create: `market_radar/events.py`
- Test: `tests/test_market_radar_events.py`

- [ ] **Step 1: Write failing tests**

Create tests that call `build_events_from_news_payload(payload)` and assert:
- duplicate AI items with the same news title merge into one event,
- raw source URL/provider is preserved,
- broad industry mappings are marked low confidence,
- materiality/source/duration fields are present.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_market_radar_events`

Expected: import failure for `market_radar.events`.

- [ ] **Step 3: Implement minimal event builder**

Implement pure functions:
- `build_events_from_news_payload(payload, limit=20) -> list[dict]`
- `build_event_summary(events) -> dict`

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_market_radar_events`

Expected: OK.

### Task 2: Web Service Integration

**Files:**
- Modify: `web_app/services/sector_service.py`
- Modify: `tests/test_sector_web.py`

- [ ] **Step 1: Write failing service test**

Extend a cache-backed test to assert `build_concept_news_radar()` returns:
- `events`,
- `event_summary`,
- event titles, materiality, source URL, and verification points.

- [ ] **Step 2: Verify test fails**

Run: `python -m unittest tests.test_sector_web`

Expected: missing `events` / `event_summary`.

- [ ] **Step 3: Integrate event builder**

Import event builder in `sector_service.py`, generate events from the selected news cache payload, and keep the old `news` / `concepts` response shape intact.

- [ ] **Step 4: Verify service tests pass**

Run: `python -m unittest tests.test_sector_web tests.test_market_radar_events`

Expected: OK.

### Task 3: Regression

**Files:**
- No production file changes unless tests expose a compatibility issue.

- [ ] **Step 1: Run Web and radar regression**

Run:
`python -m unittest tests.test_data_downloader_trade_dates tests.test_daily_web_update tests.test_update_service tests.test_web_app tests.test_web_services tests.test_explanation_service tests.test_sector_web tests.test_market_radar_events`

Expected: OK.
