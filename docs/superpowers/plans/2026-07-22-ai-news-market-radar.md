# AI News Market Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cached AI news brief to Market Radar that recommends validated sectors and existing quantitative candidate stocks without changing quantitative scores.

**Architecture:** A focused `market_radar.ai_news_brief` module compacts current news and radar facts, fingerprints the input, calls the existing DeepSeek-compatible client, validates the structured result against server-side allowlists, and stores a dated JSON cache. The scheduled radar refresh generates the cache; page requests only load and render it.

**Tech Stack:** Python 3, JSON file cache, existing DeepSeek-compatible API client, FastAPI/Jinja2, CSS.

## Global Constraints

- AI recommendations never modify sector heat, stock score, ranking, news boost, or concept boost.
- Recommended stocks must exist in the current `radar.candidates` collection.
- Only time-verified news and explicitly marked post-target news may enter the prompt.
- The page must remain usable when the API key is missing, the request fails, or JSON parsing fails.
- New code comments are Chinese.

---

### Task 1: Cached AI News Brief Generator

**Files:**
- Create: `market_radar/ai_news_brief.py`

**Interfaces:**
- Consumes: `radar: dict`, `concept_news: dict`, target date, cache directory, optional AI callable.
- Produces: `generate_ai_news_brief(...) -> dict` and `load_ai_news_brief(...) -> dict`.

- [ ] Build a compact input containing at most 30 news rows, 8 sectors, and 24 candidate stocks.
- [ ] Hash the normalized input and return the existing cache when the fingerprint matches.
- [ ] Request one structured JSON object containing summary, drivers, risks, sector focus, and stock focus.
- [ ] Parse fenced or plain JSON and validate all sectors/stocks against server-side allowlists.
- [ ] Preserve an existing valid cache on API or parsing failure and return an explicit unavailable status otherwise.

### Task 2: Scheduled Generation and Page Payload

**Files:**
- Modify: `daily_web_update.py`
- Modify: `web_app/app.py`

**Interfaces:**
- Consumes: Task 1 generator and loader.
- Produces: `ai_news_brief` in every Market Radar page payload.

- [ ] Generate or reuse the AI brief during `refresh_market_radar_snapshot` after radar/news facts are available.
- [ ] Include the generated brief in persisted latest and dated page caches.
- [ ] Load only the dated cache in ordinary `/sectors` requests; never call AI from a page request.
- [ ] Increment the page-cache version so old payloads cannot bypass the new field.

### Task 3: Market Radar UI

**Files:**
- Modify: `web_app/templates/sectors.html`
- Modify: `web_app/static/app.css`
- Modify: `web_app/templates/base.html`

**Interfaces:**
- Consumes: `ai_news_brief` from Task 2.
- Produces: A responsive AI message brief panel before Key Events.

- [ ] Render summary, target date, generated time, news count, and cache status.
- [ ] Render up to five sector cards with stance, confidence, evidence, validation, and invalidation.
- [ ] Render up to six stock cards with links to existing stock pages and explicit quantitative-candidate provenance.
- [ ] Render a compact honest fallback when no reliable AI result exists.
- [ ] Add responsive two-column desktop and one-column mobile styles, then bump the CSS asset version.

### Task 4: Deployment Verification

**Files:**
- Deploy the files modified in Tasks 1-3 to `/opt/stock`.

**Interfaces:**
- Consumes: completed local implementation.
- Produces: live Market Radar feature.

- [ ] Restart `stock-web` and confirm the service is active.
- [ ] Run the radar refresh once so the initial AI brief cache is generated.
- [ ] Open `/sectors` and verify no HTTP 500, no broken stock links, honest AI status, and no change to displayed quantitative scores.
