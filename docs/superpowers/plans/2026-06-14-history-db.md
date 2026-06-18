# History Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a SQLite historical facts database from existing `data/cache` parquet files for future Web pages, stock inspection, and signal performance review.

**Architecture:** Keep `stock_signals.db` as the signal/watch-pool state database. Add a separate `stock_history.db` for immutable market facts imported from parquet. The first version only imports reusable raw facts and leaves derived Web display tables for later.

**Tech Stack:** Python standard library `sqlite3`, `pathlib`, `argparse`, `unittest`, plus existing `pandas` parquet support.

---

### Task 1: History Store Schema

**Files:**
- Create: `history_store.py`
- Test: `tests/test_history_store.py`

- [ ] **Step 1: Write failing schema tests**

Create tests that instantiate `HistoryStore` with a temporary SQLite path and verify tables/indexes exist for `stock_daily`, `stock_daily_basic`, `stock_moneyflow`, `index_daily`, `stock_basic`, `fina_indicator`, and `income`.

- [ ] **Step 2: Implement schema**

Create `HistoryStore.init_schema()` with explicit primary/unique keys and query-friendly indexes.

- [ ] **Step 3: Verify schema tests pass**

Run: `python -m unittest tests.test_history_store`

### Task 2: Data Upsert

**Files:**
- Modify: `history_store.py`
- Test: `tests/test_history_store.py`

- [ ] **Step 1: Write failing upsert tests**

Test that repeated imports of the same `(trade_date, ts_code)` row replace values instead of duplicating rows.

- [ ] **Step 2: Implement dataframe upsert helpers**

Add `upsert_dataframe(table, df)` and table-specific column selection to keep imports tolerant of missing optional columns.

- [ ] **Step 3: Verify upsert tests pass**

Run: `python -m unittest tests.test_history_store`

### Task 3: Parquet Import CLI

**Files:**
- Create: `history_db_importer.py`
- Test: `tests/test_history_db_importer.py`

- [ ] **Step 1: Write failing importer tests**

Create temporary parquet fixtures under `cache/daily`, `cache/daily_basic`, and static parquet files, then assert CLI helper imports only the requested date range.

- [ ] **Step 2: Implement importer**

Add `import_history_cache(cache_dir, db_path, start, end, tables, force)` and CLI args. Default tables import all supported datasets.

- [ ] **Step 3: Verify importer tests pass**

Run: `python -m unittest tests.test_history_store tests.test_history_db_importer`

### Task 4: Documentation and Real Import Command

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add command examples**

Document `python history_db_importer.py --cache-dir data/cache --db data/stock_history.db`.

- [ ] **Step 2: Run syntax and targeted tests**

Run:
`python -m unittest tests.test_history_store tests.test_history_db_importer`
`python -m py_compile history_store.py history_db_importer.py`

- [ ] **Step 3: Ask user to run full import**

Provide the full command because importing all parquet files can take time and produce a local database artifact.
