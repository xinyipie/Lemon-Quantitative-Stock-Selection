# Market Radar Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce one freshness contract across every market-radar input so stale or unverifiable data cannot produce a current-day conclusion.

**Architecture:** Add a focused freshness module that classifies dates and timestamps, then apply it at the collection and service boundaries. The page receives explicit module statuses and renders degraded states instead of silently substituting old cache files or historical signals.

**Tech Stack:** Python, FastAPI/Jinja2, SQLite, JSON disk caches, existing CSS.

## Global Constraints

- Use Beijing time for all freshness decisions.
- News is fresh through 24 hours, aging through 48 hours, and stale after 48 hours.
- Unknown publication times never contribute to trading conclusions.
- Never substitute collection time for publication time.
- Never use a cache from another date as current-day data.
- Do not add order execution or position-management behavior.

---

### Task 1: Shared freshness contract

**Files:**
- Create: `market_radar/freshness.py`

**Interfaces:**
- Produces: `classify_news_time(value, now=None) -> dict`
- Produces: `classify_trade_date(value, target_date) -> dict`
- Produces: `build_market_freshness(radar, concept_news, strategy_overlap, now=None) -> dict`

- [ ] Implement timezone-aware parsing, status labels, eligibility flags and reasons.
- [ ] Keep all return values JSON/template-safe.

### Task 2: Collection hard gates

**Files:**
- Modify: `news_source_provider.py`
- Modify: `market_context_snapshot.py`

**Interfaces:**
- Consumes: `classify_news_time`
- Produces: cache payloads containing `generated_at`, verified news and separate `unverified_news`.

- [ ] Remove recency credit for unknown publication time.
- [ ] Enforce a 48-hour limit using hours instead of calendar-day differences.
- [ ] Keep unknown-time records out of AI mapping and sector boosts.
- [ ] Persist collection diagnostics without treating unverified records as catalysts.

### Task 3: Service-layer date alignment and degradation

**Files:**
- Modify: `web_app/services/sector_service.py`
- Modify: `web_app/app.py`

**Interfaces:**
- Consumes: shared freshness classifiers.
- Produces: `concept_news.freshness`, `strategy_overlap.freshness`, and top-level `freshness`.

- [ ] Stop news, concept and theme cache loaders from falling back to another date.
- [ ] Filter stale and unknown news before building groups, events and summaries.
- [ ] Disable signal-pool news fallback for current message radar.
- [ ] Require strategy signal date to equal radar date.
- [ ] Reject persisted page cache entries whose target date or generation age is invalid.
- [ ] Degrade the combined decision when core dates are mismatched or unavailable.

### Task 4: User-facing freshness status

**Files:**
- Modify: `web_app/templates/sectors.html`
- Modify: `web_app/static/app.css`

**Interfaces:**
- Consumes: top-level `freshness.modules`, `freshness.overall_status`, and item freshness metadata.

- [ ] Replace plain date labels with four status cards for market, news, concepts and strategy.
- [ ] Show publication time, age, collection time and verification status on news cards.
- [ ] Put unknown-time records in a non-decision “待核验” area.
- [ ] Show a blocking banner when market data is stale or dates are mismatched.

### Task 5: Incremental refresh entry point

**Files:**
- Modify: `daily_web_update.py`

**Interfaces:**
- Produces: a lightweight market-context refresh mode suitable for a 30-minute server schedule.

- [ ] Ensure radar mode rebuilds current market context before saving the snapshot.
- [ ] Print an explicit nonzero failure when market context refresh fails.
- [ ] Leave server scheduler installation as a deployment operation using the new radar command.
