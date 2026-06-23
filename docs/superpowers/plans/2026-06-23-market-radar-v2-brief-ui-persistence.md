# Market Radar v2 Brief UI Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Research Brief aggregation layer, render Market Radar v2 sections on `/sectors`, and persist daily radar review snapshots.

**Architecture:** Keep existing strategy and selection logic untouched. Add pure `market_radar/brief.py` for aggregating existing event/thesis/stock/review outputs, add `market_radar/store.py` for SQLite snapshot upsert/read, and wire both through `web_app/services/sector_service.py` and `web_app/app.py`. Upgrade the existing sectors template in place so old heat tables remain available below the v2 research workspace.

**Tech Stack:** Python standard library, SQLite, FastAPI/Jinja templates, existing CSS, `unittest`.

---

### Task 1: Research Brief Aggregation

**Files:**
- Create: `market_radar/brief.py`
- Test: `tests/test_market_radar_brief.py`
- Modify: `web_app/services/sector_service.py`
- Modify: `tests/test_sector_web.py`

- [ ] **Step 1: Write failing tests**

Add tests for `build_research_brief(decision, concept_news, radar, strategy_overlap=None)` asserting it returns `headline`, `mainlines`, `event_watchlist`, `sector_theses`, `stock_watchlist`, `risk_board`, `verification_checklist`, and `data_quality`.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_market_radar_brief`

Expected: import failure for `market_radar.brief`.

- [ ] **Step 3: Implement minimal brief builder**

Create a pure function that composes the existing v2 fields without fetching data.

- [ ] **Step 4: Wire service output**

Add `research_brief` to `build_market_radar_decision()` and cover it in `tests.test_sector_web`.

### Task 2: Radar Snapshot Persistence

**Files:**
- Create: `market_radar/store.py`
- Test: `tests/test_market_radar_store.py`
- Modify: `web_app/app.py`
- Modify: `tests/test_web_app.py` or `tests/test_sector_web.py`

- [ ] **Step 1: Write failing tests**

Test SQLite table creation, upsert by `radar_date`, read latest snapshot, and JSON round-trip.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_market_radar_store`

Expected: import failure for `market_radar.store`.

- [ ] **Step 3: Implement minimal store**

Implement `save_market_radar_snapshot(db_path, radar_date, brief, decision)` and `get_latest_market_radar_snapshot(db_path)`.

- [ ] **Step 4: Wire `/sectors`**

After `research_brief` is built, save a snapshot into `DEFAULT_SIGNAL_DB_PATH` and pass `latest_radar_snapshot` to the template. Failures should not break page rendering.

### Task 3: Frontend v2 Sections

**Files:**
- Modify: `web_app/templates/sectors.html`
- Modify: `web_app/static/app.css`
- Test: `tests/test_sector_web.py`

- [ ] **Step 1: Write failing render test**

Assert `/sectors` HTML contains stable section markers:
- `market-radar-v2-brief`
- `event-watchlist-panel`
- `sector-thesis-panel`
- `stock-evidence-panel`
- `review-loop-panel`

- [ ] **Step 2: Verify test fails**

Run: `python -m unittest tests.test_sector_web.SectorWebTest.test_sector_page_renders_market_radar_v2_sections`

Expected: missing marker strings.

- [ ] **Step 3: Add template sections**

Render the brief above existing detail panels, with compact cards and no trading/execution wording.

- [ ] **Step 4: Add CSS**

Use dense dashboard styling, small cards, stable grids, and responsive layout.

### Task 4: Regression and Real Data Check

**Files:**
- No production changes unless verification reveals issues.

- [ ] **Step 1: Run focused tests**

Run:
`python -m unittest tests.test_market_radar_events tests.test_market_radar_sector_thesis tests.test_market_radar_stock_evidence tests.test_market_radar_review_loop tests.test_market_radar_brief tests.test_market_radar_store tests.test_sector_web`

- [ ] **Step 2: Run full related regression**

Run:
`python -m unittest tests.test_data_downloader_trade_dates tests.test_daily_web_update tests.test_update_service tests.test_web_app tests.test_web_services tests.test_explanation_service tests.test_sector_web tests.test_market_radar_events tests.test_market_radar_sector_thesis tests.test_market_radar_stock_evidence tests.test_market_radar_review_loop tests.test_market_radar_brief tests.test_market_radar_store`

- [ ] **Step 3: Real cache smoke check**

Build `/sectors` data for `20260622`, print brief headline, counts, latest snapshot date, and top watch points.
