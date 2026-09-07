# Walkforward Linear Ranker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建并运行一个仅用信号日信息的低自由度短线候选二级排序研究。

**Architecture:** 从全市场三引擎交易明细恢复每日去重候选及引擎成员特征，按日构造横截面百分位；使用扩展窗口岭回归产生 2019-2021 走样本外预测并选择固定参数，随后一次性验证 2022-2024，最后只观察 2025-2026H1。

**Tech Stack:** Python 3、pandas、numpy、pytest。

## Global Constraints

- 禁止未来收益进入特征。
- 交易成本固定为 0.25 个百分点。
- 不修改正式策略，不调用 AI 和新闻。
- 验证期不得参与参数选择。

---

### Task 1: 数据准备与无泄漏特征

**Files:**
- Create: `research/walkforward_linear_ranker.py`
- Test: `tests/test_walkforward_linear_ranker.py`

- [ ] 实现候选去重、引擎成员透视、按日横截面百分位和阶段标签。
- [ ] 用测试确认任何未来收益字段都不在特征列表中。

### Task 2: 加权岭回归与候选选择

**Files:**
- Modify: `research/walkforward_linear_ranker.py`
- Test: `tests/test_walkforward_linear_ranker.py`

- [ ] 实现每日等权的岭回归、预测、TopN 和弃权阈值。
- [ ] 用合成样本确认模型方向、TopN 和弃权行为。

### Task 3: 走样本外选择、验收和报告

**Files:**
- Modify: `research/walkforward_linear_ranker.py`
- Test: `tests/test_walkforward_linear_ranker.py`

- [ ] 生成 2019-2021 扩展窗口预测，只用该区间选择参数。
- [ ] 固定参数后生成验证、近期观察、年度和扰动指标。
- [ ] 输出 Markdown 与 CSV，并单列 2026-04-22 光迅科技排名。
