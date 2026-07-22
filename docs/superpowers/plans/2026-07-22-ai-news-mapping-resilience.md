# AI News Mapping Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore market-radar events when DeepSeek returns recoverable transport or formatting variations.

**Architecture:** Keep the existing cache and event contracts. Harden only the API boundary and parser, then expose a safe diagnostic through the existing `ai_message` field.

**Tech Stack:** Python, requests, unittest

## Global Constraints

- Never log API keys or full provider responses.
- Unmapped raw news must not affect sector scores.
- Event generation continues to require a validated industry mapping.

---

### Task 1: Resilient AI boundary and parser

**Files:**
- Modify: `market_context_snapshot.py`
- Modify: `news_analyzer.py`
- Test: `tests/test_ai_news_resilience.py`

**Interfaces:**
- Consumes: `config.AI_CONFIG`, AI response text, raw news titles.
- Produces: `call_ai_api()`, `get_ai_news_diagnostic()`, validated mapping rows, safe `ai_message` details.

- [ ] Add failing coverage for wrapped JSON, invalid fields and one retry after timeout.
- [ ] Add two-attempt request handling with safe diagnostics.
- [ ] Parse arrays and common object wrappers without accepting invalid fields.
- [ ] Regenerate the latest market context snapshot and confirm mapped items feed the existing event layer.
