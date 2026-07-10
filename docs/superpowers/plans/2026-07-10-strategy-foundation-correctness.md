# Strategy Foundation Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make official backtests comparable with live strategy output and remove the largest data-timing and portfolio-accounting distortions.

**Architecture:** Centralize official profile resolution, complete the long-term financial universe before selection, enforce announcement-date filtering through one helper, and rebuild portfolio acceptance/equity around bounded slots and daily mark-to-market prices. Existing research profiles remain available through explicit arguments.

**Tech Stack:** Python 3, pandas, pytest, existing `main.py`, `backtest_v2.py`, `config.py`, and `strategy_profiles.py`.

## Global Constraints

- 纯选股工具，严禁生成自动下单、仓位管理或交易执行代码。
- 所有 Tushare 请求必须批量，严禁逐股循环调用接口。
- 所有新增代码注释使用中文。
- 选股逻辑继续由 `main.py` 供回测和实盘复用。
- 生产代码修改必须先有会因缺失行为而失败的测试。
- 不修改用户现有未跟踪研究文件。

---

### Task 1: Official strategy profile contract

**Files:**
- Modify: `config.py`
- Modify: `main.py`
- Modify: `backtest_v2.py`
- Test: `tests/test_strategy_profile_contract.py`

**Interfaces:**
- Produces: `get_official_short_profile() -> dict[str, str]`
- Produces: `get_official_longterm_profile() -> str`
- Consumes: `SHORT_LIVE_FACTOR_PROFILE`, `SHORT_LIVE_STYLE_GATE`, `SHORT_LIVE_CONSENSUS_PROFILE`, `LONGTERM_LIVE_PROFILE`

- [ ] **Step 1: Write failing tests** asserting official resolvers match config and CLI defaults use those values.
- [ ] **Step 2: Run** `python -m pytest tests/test_strategy_profile_contract.py -q` and confirm failure because resolvers/defaults do not exist.
- [ ] **Step 3: Implement minimal resolvers and official CLI defaults**, preserving explicit research arguments.
- [ ] **Step 4: Run** `python -m pytest tests/test_strategy_profile_contract.py tests/test_strategy_profiles.py -q` and confirm pass.

### Task 2: Complete long-term wide-pool financial coverage

**Files:**
- Modify: `main.py`
- Test: `tests/test_longterm_financial_coverage.py`

**Interfaces:**
- Produces: `_merge_longterm_financial_data(stocks: pd.DataFrame, existing: dict, trade_date: str) -> dict`
- Consumes: `get_financial_data_batch(codes, trade_date)` once for missing codes only.

- [ ] **Step 1: Write failing tests** proving missing wide-pool codes are fetched in one batch and existing records are retained.
- [ ] **Step 2: Run** `python -m pytest tests/test_longterm_financial_coverage.py -q` and confirm failure because the helper is absent.
- [ ] **Step 3: Implement the helper** and pass its merged result into `select_longterm_pool`.
- [ ] **Step 4: Run** `python -m pytest tests/test_longterm_financial_coverage.py tests/test_longterm_profit_growth.py -q` and confirm pass.

### Task 3: Fail-closed financial announcement timing

**Files:**
- Modify: `main.py`
- Test: `tests/test_financial_point_in_time.py`

**Interfaces:**
- Produces: `FinancialDataQualityError(ValueError)`
- Produces: `_filter_announced_rows(df: pd.DataFrame, trade_date: str, dataset_name: str) -> pd.DataFrame`

- [ ] **Step 1: Write failing tests** for a missing `ann_date`, invalid dates, future announcements, and valid same-day announcements.
- [ ] **Step 2: Run** `python -m pytest tests/test_financial_point_in_time.py -q` and confirm failure because historical missing dates are currently accepted.
- [ ] **Step 3: Implement strict filtering** and use it in both financial batch functions.
- [ ] **Step 4: Run** `python -m pytest tests/test_financial_point_in_time.py tests/test_longterm_profit_growth.py -q` and confirm pass.

### Task 4: Bounded portfolio slots and daily mark-to-market equity

**Files:**
- Modify: `backtest_v2.py`
- Test: `tests/test_backtest_portfolio_accounting.py`
- Modify: `tests/test_longterm_portfolio_framework.py`

**Interfaces:**
- Produces: `BacktestV2.max_positions: int`
- Produces: `_filter_selected_items_for_portfolio(...) -> list[dict]` with bounded slots and duplicate rejection.
- Produces: `_build_mark_to_market_equity(all_trades, price_cache) -> pd.DataFrame`

- [ ] **Step 1: Write failing tests** for cross-day slot saturation, duplicate rejection, and an unrealized drawdown appearing before exit.
- [ ] **Step 2: Run** `python -m pytest tests/test_backtest_portfolio_accounting.py -q` and confirm the current unbounded/exit-only behavior fails.
- [ ] **Step 3: Implement bounded slots and daily mark-to-market equity** without changing signal generation or exit rules.
- [ ] **Step 4: Run** `python -m pytest tests/test_backtest_portfolio_accounting.py tests/test_longterm_portfolio_framework.py tests/test_conditional_exit.py -q` and confirm pass.

### Task 5: Regression verification

**Files:**
- No production changes.

**Interfaces:**
- Consumes all tasks above.
- Produces fresh verification evidence.

- [ ] **Step 1: Run focused suite** `python -m pytest tests/test_strategy_profile_contract.py tests/test_longterm_financial_coverage.py tests/test_financial_point_in_time.py tests/test_backtest_portfolio_accounting.py tests/test_longterm_portfolio_framework.py tests/test_longterm_profit_growth.py tests/test_strategy_profiles.py tests/test_conditional_exit.py -q`.
- [ ] **Step 2: Run full suite** `python -m pytest -q`.
- [ ] **Step 3: Inspect** `git diff --check` and `git diff --stat`.
- [ ] **Step 4: Compare requirements** against `docs/superpowers/specs/2026-07-10-strategy-foundation-correctness-design.md` and report any deferred execution-model work explicitly.
