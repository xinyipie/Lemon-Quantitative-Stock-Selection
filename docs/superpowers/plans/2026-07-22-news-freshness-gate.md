# News Freshness Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce publish-time freshness before AI news mapping and market-radar event generation.

**Architecture:** Normalize provider or URL dates at the source boundary, reject stale and unknown dates, and sort retained records by publication time before value score.

**Tech Stack:** Python, pandas, unittest

## Global Constraints

- Collection time must never substitute for publication time.
- News older than five calendar days must not reach AI mapping.
- Unknown publication dates must not affect sector scores.

---

### Task 1: Strict freshness gate

**Files:**
- Modify: `news_source_provider.py`
- Modify: `market_context_snapshot.py`
- Test: `tests/test_news_freshness_gate.py`

**Interfaces:**
- Consumes: provider records containing title, publish_time and URL.
- Produces: normalized publication metadata and a maximum five-day news set.

- [ ] Add coverage for URL dates, stale dates, unknown dates and freshness-first sorting.
- [ ] Normalize publication dates before scoring and filtering.
- [ ] Reject stale and unknown dates before AI mapping.
- [ ] Regenerate the latest market-radar snapshot on the server.
