# 全市场机会画像研究 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个无前视泄漏、可解释并带训练/验证/封存检验的全市场短线机会画像研究工具。

**Architecture:** 复用 `research/all_market_multi_engine_research.py` 的年度面板构造函数，在内存中同时生成正样本和固定抽样对照组。研究层使用预定义分箱与最多两个条件的组合，训练期发现候选，验证期和封存期只评估，不改正式策略。

**Tech Stack:** Python 3、pandas、numpy、pytest、本地 parquet 行情缓存。

## Global Constraints

- 所有新增代码注释使用中文。
- 所有行情均从 `data/cache` 批量读取，禁止逐股调用 Tushare。
- T 日观察、T+1 开盘成交，禁止使用未来字段构造画像。
- 只新增研究脚本、测试和报告，不修改线上正式策略。
- 不生成自动交易、仓位管理或交易执行代码。
- 未经用户明确要求不执行 git 提交。

---

### Task 1: 样本与分箱基础设施

**Files:**
- Create: `research/all_market_opportunity_archetypes.py`
- Create: `tests/test_all_market_opportunity_archetypes.py`

**Interfaces:**
- Consumes: `all_market_multi_engine_research.build_year_panel(...)`
- Produces: `assign_feature_bins(panel: pd.DataFrame) -> pd.DataFrame`
- Produces: `build_case_control_sample(panel: pd.DataFrame, controls_per_day: int = 80) -> pd.DataFrame`

- [ ] **Step 1: 编写分箱边界和固定抽样测试**

验证边界值只进入一个分箱、Top20机会全部保留、对照抽样不依赖未来收益排序且同一输入结果稳定。

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `pytest tests/test_all_market_opportunity_archetypes.py -q`

Expected: FAIL，因为研究模块尚不存在。

- [ ] **Step 3: 实现预定义分箱和确定性对照抽样**

分箱覆盖市场状态、趋势位置、短期状态、交易活跃度和行业强弱；对照组按 `trade_date|ts_code` 的稳定哈希排序取每日最多80只。

- [ ] **Step 4: 运行目标测试并确认通过**

Run: `pytest tests/test_all_market_opportunity_archetypes.py -q`

Expected: PASS。

### Task 2: 画像指标与候选发现

**Files:**
- Modify: `research/all_market_opportunity_archetypes.py`
- Modify: `tests/test_all_market_opportunity_archetypes.py`

**Interfaces:**
- Consumes: `build_case_control_sample(...)` 的带标签样本。
- Produces: `evaluate_profile(sample: pd.DataFrame, mask: pd.Series) -> dict`
- Produces: `discover_profiles(train: pd.DataFrame) -> list[dict]`
- Produces: `evaluate_across_splits(sample: pd.DataFrame, profiles: list[dict]) -> pd.DataFrame`

- [ ] **Step 1: 编写 lift、coverage、收益和验收规则测试**

使用人工构造的小样本验证分母口径、零样本安全返回、三个阶段必须同时通过以及组合条件最多两个。

- [ ] **Step 2: 运行测试并确认新增断言失败**

Run: `pytest tests/test_all_market_opportunity_archetypes.py -q`

Expected: FAIL，缺少指标和候选发现函数。

- [ ] **Step 3: 实现单维画像与两条件组合研究**

先保留训练期 lift 大于1且命中数不少于60的单维画像；再从方向互补的前20个单维画像生成两条件组合，禁止同一字段自组合。

- [ ] **Step 4: 实现分阶段评价与严格验收**

验收规则逐项输出布尔列，最终 `research_pass` 必须为所有条件的逻辑与。

- [ ] **Step 5: 运行目标测试并确认通过**

Run: `pytest tests/test_all_market_opportunity_archetypes.py -q`

Expected: PASS。

### Task 3: 完整历史运行与报告

**Files:**
- Modify: `research/all_market_opportunity_archetypes.py`
- Create: `reports/research/all_market_opportunity_archetypes_20260807.md`
- Create: `reports/research/all_market_opportunity_archetypes_metrics_20260807.csv`
- Create: `reports/research/all_market_opportunity_archetypes_candidates_20260807.csv`

**Interfaces:**
- Consumes: 本计划 Task 1、Task 2 的公共函数。
- Produces: `run_research(start: str, end: str, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]`
- Produces: `write_report(metrics: pd.DataFrame, candidates: pd.DataFrame, output: Path) -> None`

- [ ] **Step 1: 增加命令行入口与年度流式处理**

命令 `python research/all_market_opportunity_archetypes.py --start 20160101 --end 20260630` 必须按年度构建面板并立即压缩为案例对照样本，避免把十年全市场明细同时放入内存。

- [ ] **Step 2: 运行完整历史研究**

Run: `python research/all_market_opportunity_archetypes.py --start 20160101 --end 20260630`

Expected: 输出三个阶段的基础机会率、Top候选画像、通过验收数量和三个报告文件路径。

- [ ] **Step 3: 核对研究结论边界**

确认报告明确展示样本数、命中数、lift、coverage、收益、MFE/MAE、活跃日数以及每条验收失败原因；没有候选通过时必须如实输出“暂无可接入正式策略的画像”。

