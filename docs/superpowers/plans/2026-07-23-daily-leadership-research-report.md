# Daily Leadership Research Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a twice-attempted daily A-share leadership report that aggregates every formal production signal source, writes a concise professional article without exposing internal software or strategy details, archives every edition, and supports date and keyword search.

**Architecture:** Persist a compact selection-run snapshot from `main.py`, then build one normalized internal fact snapshot from the existing signal database, market radar, news cache, dragon observation, and matured performance data. A two-pass writer receives only a public-safe projection; a deterministic validator gates publication into a versioned SQLite archive, while FastAPI serves the latest article and archive search. The 02:00 full update performs the primary attempt and the 08:30 radar update retries only when that publication date has no valid report.

**Tech Stack:** Python 3, pandas, SQLite/FTS5 with parameterized `LIKE` fallback, requests-compatible OpenAI API, FastAPI, Jinja2, unittest/pytest.

## Global Constraints

- The product remains a pure research and stock-selection tool; do not add order placement, position management, or trade execution.
- All Tushare access remains batched; no per-stock API loops may be introduced.
- All new code comments are in Chinese.
- Public report text must not expose software names, AI/Agent/model/database/cache/API terminology, strategy names, versions, profiles, internal state enums, parameters, weights, thresholds, raw scores, or filter logic.
- Public report text must not contain buy, sell, position-size, target-price, or return-guarantee instructions.
- Individual stocks may only come from the union of formal short-cycle observations, auxiliary short-cycle observations, active medium-term Watch/Elite observations, market-radar candidates, and visible dragon priority/caution observations.
- Empty, not-triggered, missing, and failed source states remain distinct; another source may not fill an empty formal source.
- Only matured samples enter return, win-rate, MFE, or MAE statistics.
- Every published number, stock, industry, event, and conclusion must be traceable to the internal fact snapshot.
- Each publication date has one current published report and an immutable version history.
- The 08:30 run retries only when the 02:00 report is missing or failed; it must not regenerate a successful report.
- Preserve the existing `daily_ai_brief.py` dashboard feature; the new leadership report is a separate publication path.
- Keep existing user worktree changes intact; stage and commit only files named by each task.

---

## File Structure

### New production files

- `daily_report/__init__.py` — package exports only.
- `daily_report/selection_snapshot.py` — serialize and persist the daily `run_daily_selection()` market/scan result, including empty and not-triggered states.
- `daily_report/store.py` — report archive schema, version history, generation jobs, publication, navigation, and search.
- `daily_report/facts.py` — aggregate and normalize formal production facts and merge duplicate stocks across sources.
- `daily_report/publication.py` — build the public-safe fact projection and validate final report structure, traceability, language, and redaction.
- `daily_report/writer.py` — two-pass analyst/editor prompts and JSON API parsing.
- `daily_report/service.py` — idempotent generation orchestration and failure recording.
- `daily_research_report.py` — command-line entry point for 02:00 generation, 08:30 retry, and manual regeneration.
- `web_app/services/report_service.py` — read-only presentation helpers for archive and detail pages.
- `web_app/templates/reports.html` — archive search page.
- `web_app/templates/report_detail.html` — one continuous leadership-report article.

### Modified production files

- `main.py:5863-5945` — persist the daily selection snapshot after formal pools and long-term lifecycle lists are resolved.
- `daily_web_update.py:246-430` — call the new report command at the end of full mode and retry at the end of radar mode.
- `daily_web_update.py:517-540` — add `--skip-daily-report` for controlled maintenance and tests.
- `web_app/app.py:6-60` — import report presentation helpers.
- `web_app/app.py:645-667` — add `/reports` routes before the stock explanation and long-term routes.
- `web_app/templates/base.html:22-30` — add the report archive navigation link.
- `web_app/static/app.css` — add restrained article/archive styling and responsive rules.
- `README.md` — document generation, retry, archive, and manual commands for maintainers.

### New and modified tests

- `tests/test_daily_report_selection_snapshot.py`
- `tests/test_daily_report_store.py`
- `tests/test_daily_report_facts.py`
- `tests/test_daily_report_publication.py`
- `tests/test_daily_report_writer.py`
- `tests/test_daily_report_service.py`
- `tests/test_daily_report_web.py`
- `tests/test_daily_report_end_to_end.py`
- `tests/test_daily_web_update.py`
- `tests/test_daily_web_update_modes.py`
- `tests/test_live_signal_persistence.py`
- `tests/test_web_app.py`

---

### Task 1: Persist a complete daily selection snapshot

**Files:**
- Create: `daily_report/__init__.py`
- Create: `daily_report/selection_snapshot.py`
- Modify: `main.py:5863-5945`
- Test: `tests/test_daily_report_selection_snapshot.py`
- Test: `tests/test_live_signal_persistence.py`

**Interfaces:**
- Consumes: the dictionary returned by `main.run_daily_selection()`, final `longterm_watch_pool`, final `longterm_elite_pool`, and `include_longterm`.
- Produces: `build_selection_snapshot(selection: dict, include_longterm: bool, longterm_watch_count: int, longterm_elite_count: int) -> dict`, `save_selection_snapshot(db_path: str | Path, snapshot: dict) -> None`, and `get_selection_snapshot(db_path: str | Path, trade_date: str) -> dict | None`.

- [ ] **Step 1: Write failing round-trip and empty-state tests**

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from daily_report.selection_snapshot import (
    build_selection_snapshot,
    get_selection_snapshot,
    save_selection_snapshot,
)


class DailySelectionSnapshotTest(unittest.TestCase):
    def test_round_trip_preserves_empty_and_not_triggered_states(self):
        selection = {
            "trade_date": "20260722",
            "market_state": "caution",
            "market_style": "sideways",
            "macro_mode": "cautious",
            "regime": "BEAR_TREND",
            "regime_data": {"price_vs_ma60_pct": -3.2, "ma60_slope_pct": -0.04},
            "operation_mode": "stop",
            "sentiment_data": {"limit_up_count": 31, "limit_down_count": 9, "sentiment": "偏弱"},
            "stock_pool": pd.DataFrame(),
            "short_observe_pool": pd.DataFrame(),
            "longterm_pool": pd.DataFrame(),
        }
        snapshot = build_selection_snapshot(selection, True, 0, 0)
        self.assertEqual(snapshot["short_scan"]["status"], "completed_empty")
        self.assertEqual(snapshot["longterm_scan"]["status"], "not_triggered")
        self.assertEqual(snapshot["market"]["regime"], "BEAR_TREND")

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "signals.db"
            save_selection_snapshot(db, snapshot)
            self.assertEqual(get_selection_snapshot(db, "20260722"), snapshot)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m unittest tests.test_daily_report_selection_snapshot -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'daily_report'`.

- [ ] **Step 3: Implement serialization and SQLite persistence**

Create `daily_report/__init__.py` with an empty module docstring, then create `daily_report/selection_snapshot.py` with these exact public functions and schema:

```python
"""保存每日正式扫描的市场与空池状态。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


ALLOWED_LONGTERM_REGIMES = {"BULL_TREND", "BULL_PULLBACK"}


def build_selection_snapshot(
    selection: dict,
    include_longterm: bool,
    longterm_watch_count: int,
    longterm_elite_count: int,
) -> dict:
    short_count = _frame_count(selection.get("stock_pool"))
    observe_count = _frame_count(selection.get("short_observe_pool"))
    longterm_raw_count = _frame_count(selection.get("longterm_pool"))
    regime = str(selection.get("regime") or "")
    if not include_longterm:
        longterm_status = "disabled"
    elif regime not in ALLOWED_LONGTERM_REGIMES:
        longterm_status = "not_triggered"
    elif longterm_raw_count:
        longterm_status = "completed_with_results"
    else:
        longterm_status = "completed_empty"
    return {
        "trade_date": str(selection.get("trade_date") or "").replace("-", "")[:8],
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "market": {
            "market_state": selection.get("market_state"),
            "market_style": selection.get("market_style"),
            "macro_mode": selection.get("macro_mode"),
            "regime": regime,
            "regime_data": _json_safe(selection.get("regime_data") or {}),
            "operation_mode": selection.get("operation_mode"),
            "sentiment": _json_safe(selection.get("sentiment_data") or {}),
        },
        "short_scan": {
            "status": "completed_with_results" if short_count else "completed_empty",
            "formal_count": short_count,
            "observe_count": observe_count,
        },
        "longterm_scan": {
            "status": longterm_status,
            "raw_count": longterm_raw_count,
            "watch_count": int(longterm_watch_count),
            "elite_count": int(longterm_elite_count),
        },
    }


def save_selection_snapshot(db_path: str | Path, snapshot: dict) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table if not exists daily_selection_snapshots (
                trade_date text primary key,
                created_at text not null,
                snapshot_json text not null
            )
            """
        )
        conn.execute(
            """
            insert into daily_selection_snapshots(trade_date, created_at, snapshot_json)
            values (?, ?, ?)
            on conflict(trade_date) do update set
                created_at = excluded.created_at,
                snapshot_json = excluded.snapshot_json
            """,
            (
                snapshot["trade_date"],
                snapshot["created_at"],
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_selection_snapshot(db_path: str | Path, trade_date: str) -> dict | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "select snapshot_json from daily_selection_snapshots where trade_date = ?",
            (str(trade_date).replace("-", "")[:8],),
        ).fetchone()
        return json.loads(row[0]) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _frame_count(value) -> int:
    return int(len(value)) if value is not None else 0


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value
```

- [ ] **Step 4: Persist the snapshot from `main.main()`**

After long-term watch/elite lists and cooldown are resolved, add a small helper call in `main.py`; keep the import local so backtests do not import the report package:

```python
def _persist_daily_selection_snapshot(
    selection: dict,
    include_longterm: bool,
    longterm_watch: pd.DataFrame,
    longterm_elite: pd.DataFrame,
    db_path=DEFAULT_DB_PATH,
) -> None:
    from daily_report.selection_snapshot import build_selection_snapshot, save_selection_snapshot

    snapshot = build_selection_snapshot(
        selection,
        include_longterm=include_longterm,
        longterm_watch_count=len(longterm_watch) if longterm_watch is not None else 0,
        longterm_elite_count=len(longterm_elite) if longterm_elite is not None else 0,
    )
    save_selection_snapshot(db_path, snapshot)
```

Call it immediately before `shared_ai_context` is built:

```python
    _persist_daily_selection_snapshot(
        sel,
        include_longterm=include_longterm,
        longterm_watch=longterm_watch_pool,
        longterm_elite=longterm_elite_pool,
    )
```

Extend `tests/test_live_signal_persistence.py` to patch `daily_report.selection_snapshot.save_selection_snapshot` and assert it receives a `completed_empty` snapshot when both DataFrames are empty.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_daily_report_selection_snapshot tests.test_live_signal_persistence -v`

Expected: PASS.

- [ ] **Step 6: Commit the snapshot boundary**

```bash
git add daily_report/__init__.py daily_report/selection_snapshot.py main.py tests/test_daily_report_selection_snapshot.py tests/test_live_signal_persistence.py
git commit -m "feat: persist daily selection snapshots"
```

---

### Task 2: Add versioned report storage, jobs, and search

**Files:**
- Create: `daily_report/store.py`
- Test: `tests/test_daily_report_store.py`

**Interfaces:**
- Consumes: SQLite path, publication date, market date, input hash, validated document, plain text, and searchable keywords.
- Produces: `begin_generation(db_path, report_date, slot, retry_if_missing=False, force=False) -> bool`, `finish_generation(db_path, report_date, status, error) -> None`, `publish_report(...) -> int`, `get_report(...) -> dict | None`, `get_latest_report(...) -> dict | None`, `get_adjacent_report_dates(...) -> tuple[str | None, str | None]`, and `search_reports(...) -> list[dict]`.

- [ ] **Step 1: Write failing archive, version, retry, and search tests**

```python
class DailyReportStoreTest(unittest.TestCase):
    def version_count(self, report_date):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "select count(*) from daily_report_versions where report_date = ?",
                (report_date,),
            ).fetchone()[0]
        finally:
            conn.close()

    def test_publish_keeps_versions_and_searches_current_text(self):
        self.assertTrue(begin_generation(self.db, "20260723", "night"))
        first_id = publish_report(
            self.db,
            report_date="20260723",
            market_date="20260722",
            title="缩量分化延续",
            document={"title": "缩量分化延续", "sections": []},
            body_text="半导体方向扩散不足，贵州茅台仅作风险样本。",
            keywords=["半导体", "贵州茅台", "600519.SH"],
            input_hash="hash-1",
            data_cutoff="2026-07-22 15:00:00",
            news_cutoff="2026-07-23 02:00:00",
        )
        finish_generation(self.db, "20260723", "published", "")
        second_id = publish_report(
            self.db,
            report_date="20260723",
            market_date="20260722",
            title="缩量分化仍待修复",
            document={"title": "缩量分化仍待修复", "sections": []},
            body_text="半导体方向仍未形成行业扩散。",
            keywords=["半导体"],
            input_hash="hash-2",
            data_cutoff="2026-07-22 15:00:00",
            news_cutoff="2026-07-23 08:30:00",
        )
        self.assertGreater(second_id, first_id)
        self.assertEqual(get_report(self.db, "20260723")["title"], "缩量分化仍待修复")
        self.assertEqual(search_reports(self.db, query="半导体")[0]["report_date"], "20260723")
        self.assertEqual(self.version_count("20260723"), 2)

    def test_retry_gate_skips_published_date_and_reopens_failed_date(self):
        self.assertTrue(begin_generation(self.db, "20260723", "night"))
        finish_generation(self.db, "20260723", "failed", "writer timeout")
        self.assertTrue(begin_generation(self.db, "20260723", "morning", retry_if_missing=True))
        finish_generation(self.db, "20260723", "published", "")
        self.assertFalse(begin_generation(self.db, "20260723", "morning", retry_if_missing=True))
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_daily_report_store -v`

Expected: FAIL because `daily_report.store` does not exist.

- [ ] **Step 3: Implement the archive schema and atomic publication**

Create these tables in `_init_schema(conn)`:

```sql
create table if not exists daily_reports (
    id integer primary key autoincrement,
    report_date text not null unique,
    market_date text not null,
    title text not null,
    document_json text not null,
    body_text text not null,
    keywords_json text not null,
    input_hash text not null,
    data_cutoff text not null,
    news_cutoff text not null,
    version_id integer not null,
    published_at text not null,
    updated_at text not null
);

create table if not exists daily_report_versions (
    id integer primary key autoincrement,
    report_date text not null,
    market_date text not null,
    title text not null,
    document_json text not null,
    body_text text not null,
    keywords_json text not null,
    input_hash text not null,
    data_cutoff text not null,
    news_cutoff text not null,
    created_at text not null
);

create table if not exists daily_report_jobs (
    report_date text primary key,
    status text not null,
    slot text not null,
    attempt_count integer not null default 0,
    last_error text not null default '',
    started_at text not null,
    updated_at text not null
);
```

Implement publication in one transaction: insert a version, upsert `daily_reports` to the new version, then refresh the FTS row. `_init_fts(conn)` must catch `sqlite3.OperationalError` and return `False`; `search_reports()` uses `MATCH` when available and a parameterized `LIKE` query otherwise. Use `BEGIN IMMEDIATE` in `begin_generation()` and reject a non-stale `running` row or any `published` row when `retry_if_missing=True`. Treat a `running` row older than 45 minutes as stale and allow a new attempt.

- [ ] **Step 4: Implement safe search and navigation**

Normalize dates with `re.sub(r"\D", "", value)[:8]`. Build the fallback query using parameters only:

```python
where = ["1 = 1"]
params: list[str] = []
if start:
    where.append("report_date >= ?")
    params.append(_date_key(start))
if end:
    where.append("report_date <= ?")
    params.append(_date_key(end))
if query:
    token = f"%{str(query).strip()}%"
    where.append("(title like ? or body_text like ? or keywords_json like ?)")
    params.extend([token, token, token])
```

`get_adjacent_report_dates()` returns the nearest earlier and later published dates. Search results include `report_date`, `market_date`, `title`, `snippet`, and `published_at`, never `document_json`, job errors, or internal versions.

- [ ] **Step 5: Run focused tests**

Run: `python -m unittest tests.test_daily_report_store -v`

Expected: PASS with both FTS5 and forced fallback test cases.

- [ ] **Step 6: Commit storage**

```bash
git add daily_report/store.py tests/test_daily_report_store.py
git commit -m "feat: add daily report archive"
```

---

### Task 3: Build the complete internal fact snapshot

**Files:**
- Create: `daily_report/facts.py`
- Test: `tests/test_daily_report_facts.py`

**Interfaces:**
- Consumes: report date, effective market date, signal/history database paths, saved selection snapshot, and existing read-only service functions.
- Produces: `build_daily_report_facts(report_date: str, market_date: str, signal_db: str | Path, history_db: str | Path, now: datetime | None = None, sources: FactSources | None = None) -> dict`.

- [ ] **Step 1: Write failing union, conflict, and empty-state tests**

Define a `FactSources` fixture whose callables return:

- formal short: `000001.SZ`, score 81;
- auxiliary short: `000002.SZ`;
- active medium-term: `000001.SZ`, so it must merge with formal short;
- radar: `000001.SZ` and `600519.SH`;
- dragon priority: `000001.SZ` with a hot-stage risk;
- selection snapshot: short `completed_with_results`, medium term `completed_with_results`;
- matured short performance: two closed samples;
- medium-term audit: one completed run.

Assert:

```python
facts = build_daily_report_facts(
    "20260723",
    "20260722",
    signal_db,
    history_db,
    sources=fake_sources,
)
self.assertEqual(len(facts["observations"]), 3)
pingan = next(item for item in facts["observations"] if item["ts_code"] == "000001.SZ")
self.assertEqual(
    set(pingan["sources"]),
    {"short_formal", "longterm_active", "market_radar", "dragon_priority"},
)
self.assertTrue(pingan["conflicts"])
self.assertEqual(facts["source_status"]["short_formal"]["state"], "available")
self.assertTrue(facts["completeness"]["can_publish"])
```

Add a second test with empty formal pools, radar-only stocks, and `longterm_scan.status == "not_triggered"`; assert radar stocks remain tagged only as radar and formal counts stay zero.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_daily_report_facts -v`

Expected: FAIL because `daily_report.facts` does not exist.

- [ ] **Step 3: Implement `FactSources` and default adapters**

Use a dataclass of callables so unit tests never require the real 1.7 GB history database:

```python
@dataclass
class FactSources:
    selection_snapshot: Callable[[str | Path, str], dict | None]
    recent_signals: Callable[..., list[dict]]
    active_longterm: Callable[[str | Path], list[dict]]
    signal_runs: Callable[..., list[dict]]
    longterm_runs: Callable[..., list[dict]]
    longterm_events: Callable[..., list[dict]]
    longterm_audit_summary: Callable[..., dict]
    sector_radar: Callable[..., dict]
    concept_news: Callable[..., dict]
    radar_decision: Callable[[dict, dict], dict]
    dragon_observation: Callable[..., dict]
    short_performance: Callable[[list[dict], int], dict]
```

`default_fact_sources()` imports the existing functions lazily from `daily_report.selection_snapshot`, `web_app.services.signal_service`, `web_app.services.sector_service`, and `web_app.services.dragon_service`.

- [ ] **Step 4: Implement normalized source collection**

Collect only the target market date for daily signals:

```python
short_formal = sources.recent_signals(
    signal_db,
    history_db=history_db,
    limit=50,
    source="live",
    mode="short",
    start=market_date,
    end=market_date,
)
short_observe = sources.recent_signals(
    signal_db,
    history_db=history_db,
    limit=20,
    source="live_observe",
    mode="short",
    start=market_date,
    end=market_date,
)
```

Build the radar and dragon data using `end_date=market_date`. Dragon inputs are limited to `display_groups.priority` and `display_groups.caution`; `research` and hidden buckets may contribute only aggregate risk context. Active long-term items retain their lifecycle dates, current state, score history, and last reason.

- [ ] **Step 5: Implement cross-source merge without fake composite scores**

Normalize stock codes, then merge into this structure:

```python
{
    "ts_code": "000001.SZ",
    "name": "平安银行",
    "industry": "银行",
    "sources": ["short_formal", "longterm_active"],
    "source_evidence": {
        "short_formal": {"rank": 1, "score": 81, "reason": "..."},
        "longterm_active": {"latest_score": 79, "days_in_pool": 4},
    },
    "resonance": [],
    "conflicts": [],
    "risks": [],
    "validation": [],
}
```

Never create `combined_score`. Add resonance when two or more independent source families agree. Add conflict when an observation belongs to a risky industry, dragon marks fragile/late behavior, radar labels it overheated/lagging, or formal and contextual evidence point in opposite directions.

- [ ] **Step 6: Build completeness and matured-performance blocks**

`completeness.can_publish` is `True` only when:

- a saved selection snapshot exists for `market_date`;
- its `trade_date` equals `market_date`;
- short and medium-term scan states are one of `completed_with_results`, `completed_empty`, `not_triggered`, or `disabled`;
- market facts exist.

News, radar, dragon, and historical audit gaps reduce `confidence_cap` or add a warning but do not convert missing data to negative evidence. Use recent `backtest_ic_short` signals and `summarize_short_signal_performance()` for closed short samples. Use `get_longterm_audit_summary()` only for imported completed periods.

Assign stable evidence IDs such as `market:regime`, `sector:电子:heat`, `stock:000001.SZ:short_formal`, and `performance:short:recent`; store their values in `evidence_index`.

- [ ] **Step 7: Run focused tests**

Run: `python -m unittest tests.test_daily_report_facts -v`

Expected: PASS.

- [ ] **Step 8: Commit facts**

```bash
git add daily_report/facts.py tests/test_daily_report_facts.py
git commit -m "feat: aggregate daily report facts"
```

---

### Task 4: Add public projection and deterministic publication gates

**Files:**
- Create: `daily_report/publication.py`
- Test: `tests/test_daily_report_publication.py`

**Interfaces:**
- Consumes: internal fact snapshot and writer document.
- Produces: `build_public_facts(facts: dict) -> dict`, `validate_report(document: dict, facts: dict, public_facts: dict) -> list[str]`, `report_to_plain_text(document: dict) -> str`, and `extract_search_keywords(document: dict, public_facts: dict) -> list[str]`.

- [ ] **Step 1: Write failing redaction and traceability tests**

Test that `build_public_facts()` removes `regime`, `profile`, `score`, `source_evidence`, model metadata, and internal source keys while retaining safe market descriptions, public stock identity, industry, observable facts, conflict, risk, and evidence IDs.

Test these invalid documents:

```python
invalid_internal = {
    "title": "v18模型给出强推荐",
    "sections": [{"key": "core_judgement", "heading": "核心判断", "paragraphs": [
        {"text": "BEAR_TREND下模型评分82分。", "evidence_ids": ["market:regime"], "entity_refs": []}
    ]}],
    "keywords": ["v18"],
}
self.assertTrue(validate_report(invalid_internal, facts, public_facts))

invalid_hallucination = valid_document()
invalid_hallucination["sections"][0]["paragraphs"][0] = {
    "text": "不存在的公司上涨18.7%。",
    "evidence_ids": ["missing:evidence"],
    "entity_refs": ["stock:999999.SZ"],
}
self.assertIn("unknown evidence id: missing:evidence", validate_report(invalid_hallucination, facts, public_facts))
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_daily_report_publication -v`

Expected: FAIL because `daily_report.publication` does not exist.

- [ ] **Step 3: Implement the public-safe projection**

Map internal states to business language before the writer sees them:

```python
SCAN_STATE_TEXT = {
    "completed_with_results": "已形成新增观察",
    "completed_empty": "暂未发现高置信度标的",
    "not_triggered": "当前市场环境未满足观察条件",
    "disabled": "本期不纳入该周期观察",
}
```

Do not copy entire internal dictionaries. Construct a new payload using an allowlist. Keep `evidence_id`, public stock name/code, industry, observable returns/volume/stage facts, evidence gaps, risks, and validation conditions. Replace source keys with safe labels such as `短周期观察`, `中期观察`, `行业与个股交叉验证`, and `活跃度观察`.

- [ ] **Step 4: Implement strict report validation**

Require exactly these section keys in order:

```python
REQUIRED_SECTIONS = (
    "core_judgement",
    "market_context",
    "focus",
    "performance_risk",
    "watch_points",
)
```

Use case-insensitive banned patterns covering `AI`, `Agent`, `模型`, `软件`, `数据库`, `缓存`, `API`, `profile`, `v\d+`, internal enums, `score`, `评分`, `阈值`, `权重`, `买入`, `卖出`, `仓位`, `目标价`, `稳赚`, and `必涨`. Reject filler phrases including `作为一个`, `根据输入JSON`, `综合来看`, `值得注意的是`, and `需要指出的是`.

For every paragraph:

- require one or more `evidence_ids` that exist in `facts.evidence_index`;
- require every `entity_ref` to exist in `public_facts.allowed_entity_refs`;
- reject six-digit stock codes not present in the allowed stock set;
- collect Arabic numeric tokens and reject any not present in the referenced evidence values or allowed date/cutoff metadata;
- for focus paragraphs that mention a stock, require at least one risk, conflict, evidence-gap, validation, or invalidation reference.

Reject titles shorter than 12 or longer than 24 visible characters after whitespace removal, and reject marketing words `重磅`, `爆发`, `必看`, `翻倍`, and `暴涨`.

- [ ] **Step 5: Implement plain text and keyword extraction**

`report_to_plain_text()` joins the title, headings, and paragraphs without HTML. `extract_search_keywords()` accepts only entities, industries, event titles, risk labels, and explicit writer keywords already present in the public facts; it removes banned/internal tokens and returns at most 40 unique terms.

- [ ] **Step 6: Run focused tests**

Run: `python -m unittest tests.test_daily_report_publication -v`

Expected: PASS.

- [ ] **Step 7: Commit publication gates**

```bash
git add daily_report/publication.py tests/test_daily_report_publication.py
git commit -m "feat: validate public daily reports"
```

---

### Task 5: Implement the two-pass high-density writer

**Files:**
- Create: `daily_report/writer.py`
- Test: `tests/test_daily_report_writer.py`

**Interfaces:**
- Consumes: public-safe facts, `config.AI_CONFIG`, and an injectable HTTP `post` callable.
- Produces: `generate_report_document(public_facts: dict, ai_config: dict | None = None, post: Callable | None = None) -> dict | None`.

- [ ] **Step 1: Write failing two-call and parse tests**

Use a fake `post` that records both requests. The first response returns an analyst draft with judgements and evidence IDs. The second returns the final five-section document. Assert:

- exactly two calls occur;
- the second user prompt contains the draft but no internal source names;
- output title and sections parse correctly;
- malformed JSON, timeouts, and missing API key return `None`.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_daily_report_writer -v`

Expected: FAIL because `daily_report.writer` does not exist.

- [ ] **Step 3: Implement strict JSON API calling**

Implement `_call_json(prompt, system, config, post, max_tokens)` using the existing OpenAI-compatible payload shape. Use temperature `0.1`, timeout from config, and at most two attempts. Strip Markdown fences, parse the outer JSON object, and return `None` on request, HTTP, response-shape, or JSON errors. Never log prompts or API keys.

- [ ] **Step 4: Implement the analyst prompt**

The analyst system prompt must state:

```text
你是A股研究组的内部分析员。只使用输入事实和evidence_id工作。
找出最重要的市场矛盾、跨来源印证、冲突、证据缺口和已成熟表现。
空结果必须保持原来源状态，不能用其他来源补位。
不得创造股票、行业、事件、数字或因果关系。只返回合法JSON。
```

Require this output schema:

```json
{
  "judgements": [
    {"text": "内部判断", "confidence": "高/中/低", "evidence_ids": ["id"]}
  ],
  "focus_entities": ["stock:000001.SZ"],
  "conflicts": [{"text": "分歧", "evidence_ids": ["id"]}],
  "watch_questions": [{"text": "验证问题", "evidence_ids": ["id"]}]
}
```

- [ ] **Step 5: Implement the editor prompt**

The editor receives only public facts and the analyst draft. Its system prompt must require natural, concise Chinese; evidence-first reasoning; no implementation language; no investment instructions; no filler; and no minimum word count. Require this exact structural contract:

```json
{
  "title": "12至24字事实型标题",
  "sections": [
    {
      "key": "core_judgement",
      "heading": "核心判断",
      "paragraphs": [
        {"text": "自然段", "evidence_ids": ["id"], "entity_refs": ["stock:000001.SZ"], "risk_refs": ["id"]}
      ]
    }
  ],
  "keywords": ["行业或股票关键词"]
}
```

The prompt explicitly lists all five required keys and tells the editor to omit a stock rather than write a one-sided positive paragraph.

- [ ] **Step 6: Run focused tests**

Run: `python -m unittest tests.test_daily_report_writer -v`

Expected: PASS.

- [ ] **Step 7: Commit writer**

```bash
git add daily_report/writer.py tests/test_daily_report_writer.py
git commit -m "feat: write high-density daily reports"
```

---

### Task 6: Orchestrate generation, validation, publication, and CLI retries

**Files:**
- Create: `daily_report/service.py`
- Create: `daily_research_report.py`
- Test: `tests/test_daily_report_service.py`

**Interfaces:**
- Consumes: report/market dates, database paths, writer, facts builder, and store.
- Produces: `generate_daily_report(...) -> dict` with status `published`, `skipped`, or `failed`; CLI flags `--report-date`, `--market-date`, `--signal-db`, `--history-db`, `--slot`, `--retry-if-missing`, and `--force`.

- [ ] **Step 1: Write failing success, failure, and retry tests**

Test these flows using temporary databases and injected functions:

1. Valid facts + valid document publishes and returns `{"status": "published"}`.
2. Facts with `can_publish=False` records failure and leaves `daily_reports` empty.
3. Writer returns `None` and leaves the last valid report unchanged.
4. Validator returns errors and saves no public report.
5. `retry_if_missing=True` skips an existing published date without calling facts or writer.
6. Same date with `force=True` creates a new version.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_daily_report_service -v`

Expected: FAIL because `daily_report.service` does not exist.

- [ ] **Step 3: Implement orchestration with no template fallback**

Implement this control flow:

```python
def generate_daily_report(
    report_date: str,
    market_date: str,
    signal_db: str | Path,
    history_db: str | Path,
    slot: str = "manual",
    retry_if_missing: bool = False,
    force: bool = False,
    facts_builder=build_daily_report_facts,
    writer=generate_report_document,
) -> dict:
    if not begin_generation(signal_db, report_date, slot, retry_if_missing, force):
        return {"status": "skipped", "report_date": report_date, "reason": "already_published_or_running"}
    try:
        facts = facts_builder(report_date, market_date, signal_db, history_db)
        if not facts.get("completeness", {}).get("can_publish"):
            raise ReportGenerationError("critical facts incomplete")
        public_facts = build_public_facts(facts)
        document = writer(public_facts)
        if not document:
            raise ReportGenerationError("writer returned no valid document")
        errors = validate_report(document, facts, public_facts)
        if errors:
            raise ReportGenerationError("; ".join(errors[:8]))
        body_text = report_to_plain_text(document)
        keywords = extract_search_keywords(document, public_facts)
        version_id = publish_report(
            signal_db,
            report_date=report_date,
            market_date=market_date,
            title=document["title"],
            document=document,
            body_text=body_text,
            keywords=keywords,
            input_hash=facts["input_hash"],
            data_cutoff=facts["cutoffs"]["data"],
            news_cutoff=facts["cutoffs"]["news"],
        )
        finish_generation(signal_db, report_date, "published", "")
        return {"status": "published", "report_date": report_date, "version_id": version_id}
    except Exception as exc:
        finish_generation(signal_db, report_date, "failed", str(exc)[:500])
        return {"status": "failed", "report_date": report_date, "reason": str(exc)[:200]}
```

Compute `facts.input_hash` from canonical JSON with sorted keys. Do not publish a fallback document.

- [ ] **Step 4: Implement the CLI without breaking the parent update**

`daily_research_report.py` resolves the default report date with `ZoneInfo("Asia/Shanghai")`. If `--market-date` is omitted, call `latest_history_trade_date(history_db)`. Print one JSON status line and exit `0` for `published`, `skipped`, and recorded `failed` outcomes so a report API outage does not mark the entire market-data update failed. Exit `2` only for invalid CLI arguments or an unreadable database path.

- [ ] **Step 5: Run focused tests and CLI smoke help**

Run: `python -m unittest tests.test_daily_report_service -v`

Expected: PASS.

Run: `python daily_research_report.py --help`

Expected: exit `0` and list all seven CLI flags.

- [ ] **Step 6: Commit orchestration**

```bash
git add daily_report/service.py daily_research_report.py tests/test_daily_report_service.py
git commit -m "feat: orchestrate daily report publication"
```

---

### Task 7: Integrate 02:00 primary generation and 08:30 retry

**Files:**
- Modify: `daily_web_update.py:246-430`
- Modify: `daily_web_update.py:463-540`
- Test: `tests/test_daily_web_update.py`
- Test: `tests/test_daily_web_update_modes.py`

**Interfaces:**
- Consumes: the CLI from Task 6 and existing `full`/`radar` modes.
- Produces: one full-mode primary command after all audits and one radar-mode retry command after radar refresh.

- [ ] **Step 1: Write failing command-order tests**

Add a full-mode test that captures `run_command()` calls and asserts:

```python
report_index = next(i for i, text in enumerate(command_texts) if "daily_research_report.py" in text)
outcome_index = next(i for i, text in enumerate(command_texts) if "short_signal_outcome_refresher.py" in text)
longterm_indexes = [i for i, text in enumerate(command_texts) if "longterm_history_importer.py" in text]
self.assertGreater(report_index, outcome_index)
self.assertGreater(report_index, max(longterm_indexes))
self.assertIn("--slot night", command_texts[report_index])
self.assertNotIn("--retry-if-missing", command_texts[report_index])
```

Add a radar-mode test asserting the command follows `refresh_market_radar_snapshot()` and contains `--slot morning --retry-if-missing`. Add skip-flag and dry-run assertions.

- [ ] **Step 2: Run focused tests and verify ordering failures**

Run: `python -m unittest tests.test_daily_web_update tests.test_daily_web_update_modes -v`

Expected: FAIL because the new command is absent.

- [ ] **Step 3: Add the report command helper**

```python
def _generate_leadership_report(
    py: str,
    args: argparse.Namespace,
    report_date: str,
    market_date: str,
    slot: str,
    retry_if_missing: bool,
) -> None:
    if getattr(args, "skip_daily_report", False):
        return
    command = [
        py,
        "daily_research_report.py",
        "--report-date", report_date,
        "--market-date", market_date,
        "--signal-db", str(args.signal_db),
        "--history-db", str(args.history_db),
        "--slot", slot,
    ]
    if retry_if_missing:
        command.append("--retry-if-missing")
    run_command(command, args.dry_run)
```

- [ ] **Step 4: Place both calls at the correct terminal points**

In `radar` mode, call the helper after `refresh_market_radar_snapshot()` and before the completion message, using `today_text()` as report date, `effective_end` as market date, slot `morning`, and retry `True`.

In `full` mode, call it after the short outcome refresh and the entire long-term audit/import loop, immediately before `Web 数据同步流程完成`, using slot `night` and retry `False`.

Do not call the leadership report in `daily`, `dragon`, or `fast` modes. Keep `_generate_daily_ai_brief()` in its existing path.

- [ ] **Step 5: Add the maintenance flag**

Add:

```python
parser.add_argument("--skip-daily-report", action="store_true", help="跳过领导版市场研究日报生成")
```

Update every test `Namespace` fixture with `skip_daily_report=False` unless that test explicitly covers the skip path.

- [ ] **Step 6: Run scheduler tests**

Run: `python -m unittest tests.test_daily_web_update tests.test_daily_web_update_modes -v`

Expected: PASS.

- [ ] **Step 7: Commit scheduler integration**

```bash
git add daily_web_update.py tests/test_daily_web_update.py tests/test_daily_web_update_modes.py
git commit -m "feat: schedule daily report retries"
```

---

### Task 8: Add archive search and continuous article pages

**Files:**
- Create: `web_app/services/report_service.py`
- Create: `web_app/templates/reports.html`
- Create: `web_app/templates/report_detail.html`
- Modify: `web_app/app.py:6-60`
- Modify: `web_app/app.py:645-667`
- Modify: `web_app/templates/base.html:22-30`
- Modify: `web_app/static/app.css`
- Test: `tests/test_daily_report_web.py`
- Test: `tests/test_web_app.py`

**Interfaces:**
- Consumes: read-only functions from `daily_report.store`.
- Produces: `build_report_archive_context(...) -> dict`, `build_report_detail_context(...) -> dict`, `GET /reports`, and `GET /reports/{report_date}`.

- [ ] **Step 1: Write failing web tests**

Seed a temporary report database, patch the app-level report DB constant, and assert:

- `/reports?q=半导体&start=20260701&end=20260731` returns the matching title and date;
- `/reports/20260723` renders one `<article>` with all five sections;
- detail page shows report date, market date, data cutoff, and message cutoff;
- previous/next links use existing published dates;
- unknown dates return 404;
- page source contains none of `AI`, `Agent`, `profile`, `BEAR_TREND`, `评分`, `数据库`, or `模型`;
- all paragraphs are autoescaped and no report text is rendered with Jinja `safe`.

- [ ] **Step 2: Run and verify route failures**

Run: `python -m unittest tests.test_daily_report_web tests.test_web_app -v`

Expected: FAIL with `/reports` returning 404.

- [ ] **Step 3: Implement read-only presentation helpers**

```python
def build_report_archive_context(db_path, query="", start="", end="") -> dict:
    return {
        "query": str(query or "").strip(),
        "start": normalize_date_input(start),
        "end": normalize_date_input(end),
        "items": search_reports(db_path, query=query, start=start, end=end, limit=100),
    }


def build_report_detail_context(db_path, report_date: str) -> dict | None:
    report = get_report(db_path, report_date)
    if not report:
        return None
    previous_date, next_date = get_adjacent_report_dates(db_path, report_date)
    return {"report": report, "previous_date": previous_date, "next_date": next_date}
```

- [ ] **Step 4: Add FastAPI routes**

Import `HTTPException` and add:

```python
@app.get("/reports")
def report_archive(request: Request, q: str = "", start: str = "", end: str = ""):
    context = build_report_archive_context(DEFAULT_SIGNAL_DB_PATH, q, start, end)
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"request": request, "active_nav": "reports", **context},
    )


@app.get("/reports/{report_date}")
def report_detail(request: Request, report_date: str):
    context = build_report_detail_context(DEFAULT_SIGNAL_DB_PATH, report_date)
    if context is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return templates.TemplateResponse(
        request,
        "report_detail.html",
        {"request": request, "active_nav": "reports", **context},
    )
```

- [ ] **Step 5: Build simple templates**

`reports.html` contains one GET form with `q`, `start`, and `end`, followed by a semantic list of date, title, market date, and escaped snippet.

`report_detail.html` contains:

```html
<article class="research-report">
  <header class="research-report__header">
    <p class="eyebrow">A股市场研究日报</p>
    <h1>{{ report.title }}</h1>
    <p class="report-meta">报告日期：{{ report.report_date|fmt_date }} · 行情截至：{{ report.market_date|fmt_date }}</p>
    <p class="report-meta">数据截至：{{ report.data_cutoff }} · 消息截至：{{ report.news_cutoff }}</p>
  </header>
  {% for section in report.document.sections %}
  <section class="research-report__section" id="{{ section.key }}">
    <h2>{{ section.heading }}</h2>
    {% for paragraph in section.paragraphs %}<p>{{ paragraph.text }}</p>{% endfor %}
  </section>
  {% endfor %}
  <footer>本文基于公开市场数据进行研究整理，仅供内部研究参考。</footer>
</article>
```

Do not display evidence IDs, source tags, internal keywords, versions, job state, or errors.

- [ ] **Step 6: Add restrained CSS and navigation**

Add a `市场日报` navigation link. Style `.research-report` with a readable `max-width: 860px`, generous paragraph line-height, restrained borders, and no dashboard cards. Add `.report-archive` rules and a single-column mobile layout. Extend the all-page usability test with `page-reports`.

- [ ] **Step 7: Run web tests**

Run: `python -m unittest tests.test_daily_report_web tests.test_web_app -v`

Expected: PASS.

- [ ] **Step 8: Commit web archive**

```bash
git add web_app/services/report_service.py web_app/templates/reports.html web_app/templates/report_detail.html web_app/app.py web_app/templates/base.html web_app/static/app.css tests/test_daily_report_web.py tests/test_web_app.py
git commit -m "feat: add searchable report archive"
```

---

### Task 9: Add end-to-end publication coverage and maintainer documentation

**Files:**
- Create: `tests/test_daily_report_end_to_end.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: all tasks above with fake data sources and fake HTTP responses.
- Produces: a deterministic end-to-end acceptance test and operator commands.

- [ ] **Step 1: Write the end-to-end test**

Use temporary signal/history databases, save an empty formal scan snapshot, provide one radar candidate and one dragon conflict through injected `FactSources`, and return valid analyst/editor JSON from a fake HTTP client. Execute `generate_daily_report()`, then assert:

- status is `published`;
- one current report and one version exist;
- formal short and medium-term counts remain zero;
- the radar/dragon stock appears as an independent observation, not as a formal result;
- the public body contains the stock basis and risk;
- the public body contains none of the internal banned terms;
- keyword and date search find the report;
- a morning retry returns `skipped` and makes no HTTP call.

- [ ] **Step 2: Run the end-to-end test and fix only integration mismatches**

Run: `python -m unittest tests.test_daily_report_end_to_end -v`

Expected: PASS. If it fails, adjust interface mismatches in the owning module; do not weaken publication validation to make the fixture pass.

- [ ] **Step 3: Document operator commands**

Add a concise README section containing:

```bash
# 手动生成当天日报
python daily_research_report.py --report-date 20260723 --market-date 20260722 --slot manual

# 仅在当天尚无有效报告时补生成
python daily_research_report.py --report-date 20260723 --market-date 20260722 --slot morning --retry-if-missing

# 强制生成修订版
python daily_research_report.py --report-date 20260723 --market-date 20260722 --slot manual --force
```

Document `/reports`, the 02:00 primary attempt, the 08:30 retry, and the rule that a failed attempt never overwrites the last valid report. This is maintainer documentation and may use internal implementation names; those names remain forbidden only in the public report pages and indexed report content.

- [ ] **Step 4: Run the complete focused feature suite**

Run:

```bash
python -m unittest \
  tests.test_daily_report_selection_snapshot \
  tests.test_daily_report_store \
  tests.test_daily_report_facts \
  tests.test_daily_report_publication \
  tests.test_daily_report_writer \
  tests.test_daily_report_service \
  tests.test_daily_report_web \
  tests.test_daily_report_end_to_end \
  tests.test_daily_web_update \
  tests.test_daily_web_update_modes \
  tests.test_live_signal_persistence \
  tests.test_web_app -v
```

Expected: all tests PASS with no real API calls.

- [ ] **Step 5: Run compilation and broader regression checks**

Run:

```bash
python -m py_compile \
  daily_research_report.py \
  daily_report/selection_snapshot.py \
  daily_report/store.py \
  daily_report/facts.py \
  daily_report/publication.py \
  daily_report/writer.py \
  daily_report/service.py \
  web_app/services/report_service.py \
  web_app/app.py \
  daily_web_update.py \
  main.py
```

Expected: exit `0` with no output.

Run:

```bash
python -m unittest \
  tests.test_signal_store \
  tests.test_web_services \
  tests.test_sector_web \
  tests.test_dragon_web \
  tests.test_market_radar_store \
  tests.test_explanation_service \
  tests.test_update_service -v
```

Expected: all tests PASS.

- [ ] **Step 6: Perform a no-network dry run of both scheduler paths**

Run:

```bash
python daily_web_update.py --mode full --end 20260722 --skip-download --skip-history-import --skip-main --skip-short-review --skip-longterm-audit --dry-run
python daily_web_update.py --mode radar --end 20260722 --skip-download --skip-history-import --dry-run
```

Expected: the first command prints one `daily_research_report.py ... --slot night` command at the end; the second prints one `daily_research_report.py ... --slot morning --retry-if-missing` command after the radar command.

- [ ] **Step 7: Commit acceptance coverage and documentation**

```bash
git add tests/test_daily_report_end_to_end.py README.md
git commit -m "test: verify daily report workflow"
```

---

## Final Review Checklist

- [ ] Every formal source listed in the design is present in `FactSources` and covered by at least one test.
- [ ] Empty and not-triggered states remain distinguishable through snapshot, facts, public projection, and final prose.
- [ ] No research experiment file under `research/` or `reports/` is read as a daily stock source.
- [ ] No public field includes strategy names, versions, profiles, enums, raw scores, thresholds, weights, technical errors, or AI/software terminology.
- [ ] The writer never receives internal-only fields.
- [ ] The validator rejects unknown evidence IDs, stock codes, numeric claims, internal terms, investment instructions, marketing titles, and one-sided stock paragraphs.
- [ ] A failed writer or validator attempt cannot overwrite a published report.
- [ ] The archive preserves revisions while search returns only current published versions.
- [ ] Search works by publication date, title/body keyword, stock name/code, industry, event, and risk term.
- [ ] Full mode generates only after dragon, radar, short outcome refresh, and long-term audit import.
- [ ] Radar mode retries only if the current publication date lacks a valid report.
- [ ] Existing dashboard daily brief and all existing read-only research pages still pass their tests.
