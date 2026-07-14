# Dashboard Usability Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a coherent, responsive usability redesign across every user-facing dashboard page.

**Architecture:** Keep the existing FastAPI/Jinja content and business behavior unchanged. Add a tested page-specific CSS layer keyed by the existing `body.page-*` classes, then update the stylesheet cache key so production browsers load it immediately.

**Tech Stack:** FastAPI, Jinja2, CSS Grid/Flexbox, unittest/pytest

## Global Constraints

- Preserve the read-only research workflow and do not add trading execution behavior.
- Preserve all existing data and routes.
- Use existing HTML classes and `body.page-*` page identifiers.
- Keep layouts responsive at 1680px, 1080px, and 720px breakpoints.

---

### Task 1: Add layout regression coverage

**Files:**
- Modify: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `/static/app.css` and rendered page body classes.
- Produces: regression checks for the usability layer and cache key.

- [ ] Add a test that requests the stylesheet and asserts selectors exist for dashboard, signals, dragon, longterm, sectors, stock, db, and explanation pages.
- [ ] Run `python -m pytest tests/test_web_app.py -k usability -q` and confirm it fails because the new layer is absent.

### Task 2: Implement the shared and page-specific usability layer

**Files:**
- Modify: `web_app/static/app.css`
- Modify: `web_app/templates/base.html`

**Interfaces:**
- Consumes: existing page classes and component classes.
- Produces: responsive wide-screen layouts without changing route behavior.

- [ ] Add a named CSS section with shared panel hierarchy, wide-screen page grids, table scanning support, and mobile fallbacks.
- [ ] Change the stylesheet query version in `base.html` to `20260714-usability-redesign`.
- [ ] Run the focused usability test and confirm it passes.

### Task 3: Verify and deploy

**Files:**
- Test: `tests/test_web_app.py`
- Test: `tests/test_sector_web.py`
- Test: `tests/test_dragon_web.py`

**Interfaces:**
- Consumes: final templates and stylesheet.
- Produces: deployed production revision.

- [ ] Run `python -m pytest tests/test_web_app.py tests/test_sector_web.py tests/test_dragon_web.py -q` and require zero failures.
- [ ] Commit only the design, plan, CSS, base template, and regression test files.
- [ ] Push `main`, pull on `/opt/stock`, restart `stock-web`, and verify every primary route returns HTTP 200.
- [ ] Verify production HTML references `20260714-usability-redesign` and production CSS contains the usability layer marker.

