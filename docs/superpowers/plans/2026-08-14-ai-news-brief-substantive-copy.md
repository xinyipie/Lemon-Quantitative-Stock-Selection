# AI News Brief Substantive Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让市场雷达 AI 研判默认展示基于真实新闻与量价字段的有效内容，并支持展开查看完整证据。

**Architecture:** 在 `ai_news_brief.py` 中强化最终模型契约，并增加确定性的证据型兜底加工；在 `sectors.html` 中按事实、传导、校验、证据四层渲染。数据层保持既有量化评分和候选排序不变。

**Tech Stack:** Python、Jinja2、原有 DeepSeek 调用与 JSON 缓存。

## Global Constraints

- 不改变任何量化评分、排名或候选集合。
- 所有展示结论必须能追溯到 evidence_id。
- 不运行自动交易，不新增交易执行能力。
- 默认紧凑展示，完整证据按需展开。

---

### Task 1: 生成结构化研究文案

**Files:**
- Modify: `market_radar/ai_news_brief.py`

**Interfaces:**
- Consumes: `pack.events`、`pack.sectors`、`pack.stocks`、`event_assessments`
- Produces: `sector_focus[].impact_chain/market_check/evidence_details` 与 `stock_focus[].market_check/evidence_details`

- [ ] **Step 1:** 强化最终 AI 输出约束，要求事件事实、传导链和具体校验条件。
- [ ] **Step 2:** 增加证据明细和量价快照构造函数。
- [ ] **Step 3:** 对空白或通用文案应用事实型兜底，保留模型已有的高质量内容。

### Task 2: 紧凑展示与证据展开

**Files:**
- Modify: `web_app/templates/sectors.html`

**Interfaces:**
- Consumes: Task 1 生成的新增展示字段
- Produces: 默认精简卡片及原始证据展开区

- [ ] **Step 1:** 板块卡展示影响传导与当前量价校验。
- [ ] **Step 2:** 个股卡展示当前市场状态。
- [ ] **Step 3:** 板块和个股都提供完整证据展开区。

### Task 3: 上线刷新

**Files:**
- Deploy: `market_radar/ai_news_brief.py`
- Deploy: `web_app/templates/sectors.html`

**Interfaces:**
- Consumes: Task 1 与 Task 2 的文件
- Produces: 下一批次重新生成的线上 AI 消息面研判

- [ ] **Step 1:** 按项目文档上传两个文件并重启 `stock-web`。
- [ ] **Step 2:** 清理当日 AI 研判缓存并触发市场雷达更新。

