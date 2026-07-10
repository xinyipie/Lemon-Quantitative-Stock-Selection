# Full Web UI Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the existing FastAPI/Jinja research console into a responsive, decision-first, paginated and semantically accurate interface without changing strategy logic or adding trading execution.

**Architecture:** Keep all existing URLs and the server-rendered Jinja stack. Add a small UI service for pagination and display labels, extend history data with chart-ready points, persist the expensive Market Radar payload, and reshape templates around shared shell, table and section-navigation patterns.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite, standard-library pickle/JSON helpers, HTML/CSS, inline SVG, unittest.

## Global Constraints

- Do not introduce React, Vue, Bootstrap, Tailwind, external CDNs, or new runtime dependencies.
- Do not add automatic ordering, position management, or trade execution.
- Do not change stock-selection thresholds or backtest logic.
- All new code comments must be Chinese.
- Preserve existing URLs and server runtime databases.
- Short-signal pages use 50 rows per page from the existing 300-row filtered cap.
- Long-term audit pages use 50 rows per page from the existing 1000-row filtered cap.

---

### Task 1: Shared UI primitives and pagination contract

**Files:**
- Create: `web_app/services/ui_service.py`
- Create: `tests/test_web_ui_overhaul.py`
- Modify: `web_app/app.py`

**Interfaces:**
- Produces: `paginate_items(items: list[dict], page: int | str, page_size: int = 50) -> tuple[list[dict], dict]`
- Produces: `normalize_date_input(value: str) -> str`
- Produces: `display_source_label(value: str) -> str`
- Produces: Jinja filters `fmt_optional`, `fmt_date_input`, and `display_source_label`

- [ ] **Step 1: Write failing helper tests**

```python
from web_app.services.ui_service import paginate_items, normalize_date_input, display_source_label

def test_paginate_items_clamps_invalid_and_overflow_pages():
    items = [{"id": index} for index in range(105)]
    page_items, info = paginate_items(items, page=99, page_size=50)
    assert [item["id"] for item in page_items] == list(range(100, 105))
    assert info == {"page": 3, "page_size": 50, "total": 105, "total_pages": 3, "start_index": 101, "end_index": 105}

def test_ui_labels_and_date_normalization_are_user_facing():
    assert normalize_date_input("2026-07-09") == "20260709"
    assert display_source_label("fallback") == "规则解释"
    assert display_source_label("short_v9_final") == "v9 底层评分"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_web_ui_overhaul -v`
Expected: import failure because `web_app.services.ui_service` does not exist.

- [ ] **Step 3: Implement the minimal UI service**

```python
def paginate_items(items, page, page_size=50):
    values = list(items or [])
    total = len(values)
    total_pages = max(1, (total + page_size - 1) // page_size)
    try:
        current = int(page)
    except (TypeError, ValueError):
        current = 1
    current = min(max(current, 1), total_pages)
    start = (current - 1) * page_size
    selected = values[start : start + page_size]
    return selected, {
        "page": current,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "start_index": start + 1 if selected else 0,
        "end_index": start + len(selected),
    }
```

Register the three filters in `web_app/app.py` after the existing `fmt_date` filter.

- [ ] **Step 4: Run helper tests and verify GREEN**

Run: `python -m unittest tests.test_web_ui_overhaul -v`
Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit the helper contract**

```bash
git add web_app/services/ui_service.py web_app/app.py tests/test_web_ui_overhaul.py
git commit -m "Add shared web UI helpers"
```

---

### Task 2: Responsive application shell and accessible shared components

**Files:**
- Modify: `tests/test_web_app.py`
- Modify: `web_app/templates/base.html`
- Modify: `web_app/templates/partials/update_status_panel.html`
- Modify: `web_app/static/app.css`

**Interfaces:**
- Consumes: Jinja filters registered in Task 1
- Produces: `.app-shell`, `.mobile-nav-toggle`, `.table-shell`, `.page-section-nav`, `.pagination`, `.sr-only`

- [ ] **Step 1: Add failing shell assertions**

```python
def test_dashboard_has_accessible_responsive_shell(self):
    response = self.client.get("/")
    self.assertEqual(response.status_code, 200)
    self.assertIn('aria-label="主导航"', response.text)
    self.assertIn('aria-controls="primary-navigation"', response.text)
    self.assertIn('class="mobile-nav-toggle"', response.text)
    self.assertIn('data-confirm-message=', response.text)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_web_app.WebAppTest.test_dashboard_has_accessible_responsive_shell -v`
Expected: failure because the mobile navigation and confirmation attribute are absent.

- [ ] **Step 3: Implement the shared shell**

Update `base.html` to include a semantic navigation label, mobile toggle button, stable `primary-navigation` id, new CSS version `20260710-ui-overhaul`, and a small script that toggles `aria-expanded`. Extend the existing form script to call `window.confirm()` only when `data-confirm-message` exists.

Wrap all long tables through template changes in later tasks; define the shared style now. Add visible keyboard focus, sticky desktop sidebar, `auto-fit` status strips, responsive spacing at 1080px/720px, and definitions for previously missing `page-header`, `panel-title`, `panel-title-row`, and `success-tag`.

- [ ] **Step 4: Verify shell tests and existing update tests**

Run: `python -m unittest tests.test_web_app -v`
Expected: all dashboard/update tests pass.

- [ ] **Step 5: Commit shared shell**

```bash
git add tests/test_web_app.py web_app/templates/base.html web_app/templates/partials/update_status_panel.html web_app/static/app.css
git commit -m "Build responsive research console shell"
```

---

### Task 3: Decision-first dashboard, paginated short review, and actionable database status

**Files:**
- Modify: `tests/test_web_app.py`
- Modify: `web_app/app.py`
- Modify: `web_app/templates/dashboard.html`
- Modify: `web_app/templates/signals.html`
- Modify: `web_app/templates/db_status.html`
- Modify: `web_app/static/app.css`

**Interfaces:**
- Consumes: `paginate_items()` and `normalize_date_input()` from Task 1
- Produces: `/signals?page=N` context keys `all_signals`, `signals`, `page_info`
- Produces: dashboard context key `has_today_candidates: bool`

- [ ] **Step 1: Add failing route/template tests**

```python
def test_signals_page_paginates_and_preserves_filters(self):
    response = self.client.get("/signals?page=2&start=2026-01-01&industry=银行")
    self.assertEqual(response.status_code, 200)
    self.assertIn("第 2 /", response.text)
    self.assertIn('type="date"', response.text)
    self.assertIn('class="table-shell"', response.text)

def test_db_page_offers_web_sync_and_advanced_cli_details(self):
    response = self.client.get("/db")
    self.assertIn('action="/update/run?mode=daily"', response.text)
    self.assertIn("高级操作", response.text)
    self.assertNotIn("页面只读，不会自动拉取数据", response.text)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_web_app -v`
Expected: pagination, date-input, table-shell, and database-action assertions fail.

- [ ] **Step 3: Implement route pagination and page hierarchy**

Normalize incoming dates before querying. Fetch the existing capped signal set into `all_signals`, compute statistics from that set, and pass only `paginate_items(all_signals, page, 50)[0]` to the table. Build query-string pagination links that preserve `q`, `start`, `end`, and `industry`.

Move the dashboard decision zone directly below freshness status. When both recommendation cards contain zero candidates, show one consolidated no-action hero and move the two verbose empty cards into a collapsed detail section. Add `data-confirm-message="完整重算通常需要 5-30 分钟，确认开始？"` to the full update form.

Replace database CLI-first copy with the standard update panel and move commands into `<details>`.

- [ ] **Step 4: Run route tests and verify GREEN**

Run: `python -m unittest tests.test_web_app tests.test_web_services -v`
Expected: all tests pass.

- [ ] **Step 5: Commit dashboard and review pages**

```bash
git add tests/test_web_app.py web_app/app.py web_app/templates/dashboard.html web_app/templates/signals.html web_app/templates/db_status.html web_app/static/app.css
git commit -m "Refocus dashboard and paginate short review"
```

---

### Task 4: Long-term and dragon page information architecture

**Files:**
- Modify: `tests/test_web_app.py`
- Modify: `tests/test_dragon_web.py`
- Modify: `web_app/app.py`
- Modify: `web_app/templates/longterm_pool.html`
- Modify: `web_app/templates/dragon_leaders.html`
- Modify: `web_app/static/app.css`

**Interfaces:**
- Consumes: `paginate_items()` from Task 1
- Produces: `/longterm?page=N` context keys `all_audit_samples`, `audit_samples`, `page_info`
- Produces: three anchor targets `current-pool`, `lifecycle`, `history-audit`

- [ ] **Step 1: Add failing long-term and dragon tests**

```python
def test_longterm_page_has_section_navigation_and_pagination(self):
    response = self.client.get("/longterm?page=2")
    self.assertIn('href="#current-pool"', response.text)
    self.assertIn('href="#lifecycle"', response.text)
    self.assertIn('href="#history-audit"', response.text)
    self.assertIn('class="pagination"', response.text)

def test_dragon_page_uses_expandable_overflow_instead_of_scroll_columns(self):
    response = self.client.get("/dragon")
    self.assertIn("查看更多候选", response.text)
    self.assertIn('class="panel-title-row"', response.text)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_web_app tests.test_dragon_web -v`
Expected: missing section navigation, pagination, and expandable overflow.

- [ ] **Step 3: Implement long-page structure**

Paginate the already capped long-term audit list at 50 rows. Add anchor navigation and place complete run logs plus historical detail tables in `<details>` blocks. Preserve current pool and lifecycle summaries outside pagination.

Render the first three dragon cards in each group directly and put the remaining cards inside `<details class="dragon-more">`. Remove fixed-height per-column scrolling in CSS.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m unittest tests.test_web_app tests.test_dragon_web -v`
Expected: all tests pass.

- [ ] **Step 5: Commit long-page improvements**

```bash
git add tests/test_web_app.py tests/test_dragon_web.py web_app/app.py web_app/templates/longterm_pool.html web_app/templates/dragon_leaders.html web_app/static/app.css
git commit -m "Restructure longterm and dragon pages"
```

---

### Task 5: Persisted Market Radar payload and section navigation

**Files:**
- Modify: `tests/test_sector_web.py`
- Modify: `web_app/app.py`
- Modify: `daily_web_update.py`
- Modify: `web_app/templates/sectors.html`
- Modify: `web_app/static/app.css`

**Interfaces:**
- Produces: `load_sector_page_cache(path: Path, key: tuple) -> dict | None`
- Produces: `save_sector_page_cache(path: Path, key: tuple, payload: dict) -> None`
- Consumes: existing `refresh_market_radar_snapshot()` update flow
- Produces cache file: `data/web_sector_page_cache.pkl` (runtime-only, never committed)

- [ ] **Step 1: Add failing cache and GET-purity tests**

```python
def test_sector_page_uses_persisted_payload_after_memory_cache_clear(self):
    with TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "radar.pkl"
        payload = {"radar": {"end_date": "20260709"}, "concept_news": {}, "decision": {}, "strategy_overlap": {}}
        save_sector_page_cache(cache_path, ("latest",), payload)
        self.assertEqual(load_sector_page_cache(cache_path, ("latest",))["radar"]["end_date"], "20260709")

def test_sector_get_does_not_write_market_snapshot(self):
    with patch("web_app.app.save_market_radar_snapshot") as save_snapshot:
        response = self.client.get("/sectors")
        self.assertEqual(response.status_code, 200)
        save_snapshot.assert_not_called()
```

- [ ] **Step 2: Run sector tests and verify RED**

Run: `python -m unittest tests.test_sector_web -v`
Expected: missing cache helpers and current GET snapshot-write assertion failure.

- [ ] **Step 3: Implement safe persisted cache**

Store a versioned object containing `version`, `key`, `created_at`, and `payload`; write atomically through a sibling temporary file and `Path.replace()`. Catch unpickling, I/O, version, and key mismatch errors and return `None`. `_get_sector_page_payload()` checks memory, then disk, then computes and saves. Remove `save_market_radar_snapshot()` from the GET builder.

After `daily_web_update.refresh_market_radar_snapshot()` builds radar, concept news, and decision, also build strategy overlap and save the page payload cache.

Add a sticky `.page-section-nav` with the seven approved section anchors and wrap secondary blocks in semantic sections/details without removing existing content.

- [ ] **Step 4: Run sector tests and verify GREEN**

Run: `python -m unittest tests.test_sector_web -v`
Expected: all sector tests pass, including updated snapshot expectations.

- [ ] **Step 5: Commit radar performance work**

```bash
git add tests/test_sector_web.py web_app/app.py daily_web_update.py web_app/templates/sectors.html web_app/static/app.css
git commit -m "Cache and reorganize market radar page"
```

---

### Task 6: Accurate stock values and inline trend chart

**Files:**
- Modify: `tests/test_history_tools.py`
- Modify: `tests/test_web_app.py`
- Modify: `stock_history_query.py`
- Modify: `web_app/services/history_service.py`
- Modify: `web_app/templates/stock_detail.html`
- Modify: `web_app/static/app.css`

**Interfaces:**
- Produces in stock detail: `price_history: list[{trade_date, close, ma20, ma60}]` with at most 120 ascending rows
- Produces: `build_stock_chart(price_history: list[dict], width: int = 900, height: int = 240) -> dict`
- Chart result: `{available, width, height, close_points, ma20_points, ma60_points, min_value, max_value}`

- [ ] **Step 1: Add failing history/chart tests**

```python
def test_stock_history_preserves_zero_and_builds_moving_averages(self):
    result = query_stock_history("000001", history_db=self.db_path, signal_db=None)
    assert result["price_history"]
    assert result["price_history"][-1]["close"] == 0
    assert result["price_history"][19]["ma20"] is not None

def test_stock_page_renders_inline_trend_chart_and_optional_values(self):
    response = self.client.get("/stock/000001")
    self.assertIn('class="stock-trend-chart"', response.text)
    self.assertIn("MA20", response.text)
    self.assertNotIn(">0.00 元<", response.text)  # 缺失收盘价不得伪装为零
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_history_tools tests.test_web_app -v`
Expected: `price_history` and chart markup are absent.

- [ ] **Step 3: Implement chart-ready data and rendering**

Increase the stock daily query to 120 rows, reverse to ascending order, calculate rolling MA20/MA60 only when enough valid closes exist, and return the series. `build_stock_chart()` converts available values to bounded SVG point strings without filling missing values.

Replace template `value or 0` and `value or '-'` expressions with the `fmt_optional` filter so `None` displays `-` and numeric zero remains visible. Render the chart with inline SVG polylines and an empty state when unavailable. Reduce the history table to core columns and move secondary review tags into an expandable cell.

- [ ] **Step 4: Run history and page tests and verify GREEN**

Run: `python -m unittest tests.test_history_tools tests.test_web_app -v`
Expected: all tests pass.

- [ ] **Step 5: Commit stock diagnostic improvements**

```bash
git add tests/test_history_tools.py tests/test_web_app.py stock_history_query.py web_app/services/history_service.py web_app/templates/stock_detail.html web_app/static/app.css
git commit -m "Improve stock diagnostics and trend display"
```

---

### Task 7: Explanation semantics and POST refresh flow

**Files:**
- Modify: `tests/test_explanation_service.py`
- Modify: `tests/test_web_app.py`
- Modify: `web_app/app.py`
- Modify: `web_app/services/explanation_service.py`
- Modify: `web_app/templates/signal_explanation.html`
- Modify: `web_app/static/app.css`

**Interfaces:**
- Produces: `sanitize_observation_copy(text: str) -> str`
- Produces: `POST /explain/signal/{trade_date}/{ts_code}/refresh`
- Consumes: `display_source_label()` from Task 1

- [ ] **Step 1: Add failing language and route tests**

```python
def test_fallback_explanation_uses_observation_only_language(self):
    doc = build_fallback_explanation(self.sample_signal)
    combined = " ".join([doc["summary"], doc["watch_plan"], doc["invalidation"]])
    self.assertNotIn("轻仓", combined)
    self.assertNotIn("考虑买入", combined)

def test_explanation_refresh_is_post_and_uses_readable_labels(self):
    response = self.client.get("/explain/signal/20250214/000157.SZ")
    self.assertIn('method="post"', response.text.lower())
    self.assertIn("规则解释", response.text)
    self.assertNotIn("?refresh=true", response.text)
```

- [ ] **Step 2: Run explanation tests and verify RED**

Run: `python -m unittest tests.test_explanation_service tests.test_web_app -v`
Expected: GET refresh link and raw labels still appear.

- [ ] **Step 3: Implement readable, side-effect-safe explanations**

Sanitize generated fallback observation language and update the system prompt to prohibit position-sizing or buy-action wording. Add the POST route that calls `get_or_create_signal_explanation(..., force=True)` and redirects to the canonical GET page. Keep legacy `?refresh=true` behavior for compatibility but remove it from templates.

Split the page into “信号当时已知信息” and “事后验证” sections. Render source/profile using display labels and replace the raw refresh link with a form button.

- [ ] **Step 4: Run explanation and web tests and verify GREEN**

Run: `python -m unittest tests.test_explanation_service tests.test_web_app -v`
Expected: all tests pass.

- [ ] **Step 5: Commit explanation improvements**

```bash
git add tests/test_explanation_service.py tests/test_web_app.py web_app/app.py web_app/services/explanation_service.py web_app/templates/signal_explanation.html web_app/static/app.css
git commit -m "Clarify signal explanations and refresh flow"
```

---

### Task 8: Full verification, performance budget, merge and deploy

**Files:**
- Verify: all Python and template files changed above

**Interfaces:**
- Consumes: all prior task outputs
- Produces: verified branch ready for `main` and `/opt/stock`

- [ ] **Step 1: Run focused Web suites**

Run: `python -m unittest tests.test_web_ui_overhaul tests.test_web_app tests.test_web_services tests.test_sector_web tests.test_dragon_web tests.test_explanation_service tests.test_history_tools -v`
Expected: all focused tests pass.

- [ ] **Step 2: Run complete suite**

Run: `python -m pytest -q`
Expected: all tests pass with only previously known warnings.

- [ ] **Step 3: Compile changed Python**

Run: `python -m py_compile web_app/app.py web_app/services/ui_service.py web_app/services/history_service.py web_app/services/explanation_service.py stock_history_query.py daily_web_update.py`
Expected: no output and exit code 0.

- [ ] **Step 4: Measure local route budgets**

Start the Web app against the existing local databases and request all eight page types. Record HTTP status, HTML bytes, and response time. Verify `/signals` and `/longterm` are at least 40% smaller than the recorded baselines of 150494 and 88104 bytes, and a persisted-cache `/sectors` response is below 1 second.

- [ ] **Step 5: Confirm the branch is internally complete**

Run: `git diff --check && git status --short --branch`
Expected: no whitespace errors; only the user's pre-existing unrelated untracked research files remain outside the committed overhaul scope.

- [ ] **Step 6: Merge and push**

Fast-forward `codex/web-ui-overhaul` into `main`, push `origin main`, and confirm local `main`, `origin/main`, and `HEAD` match.

- [ ] **Step 7: Deploy and verify**

SSH with `tmp/codex_ops_20260626`, run `git pull --ff-only origin main`, restart `stock-web`, and verify `/`, `/db`, `/sectors`, `/stock/000001`, `/signals`, `/dragon`, `/longterm`, and a real explanation page all return HTTP 200. Preserve `/opt/stock/data/stock_signals.db`.
