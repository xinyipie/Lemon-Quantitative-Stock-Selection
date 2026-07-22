# Short Signal Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把短线复盘页改造成以今日决策和5日结果为核心的清晰工作台。

**Architecture:** 在 FastAPI 路由层生成结果视图计数和筛选结果，Jinja 模板负责信息分层，页面专属 CSS 负责桌面与移动布局。策略服务层和数据库结构保持不变。

**Tech Stack:** FastAPI、Jinja2、原生 CSS

## Global Constraints

- 不修改选股和评分逻辑。
- 默认展示已满5日样本。
- 明确区分实盘记录和历史回测。

---

### Task 1: 结果视图上下文

**Files:**
- Modify: `web_app/app.py`

**Interfaces:**
- Consumes: `list[dict]` 格式的已装饰短线信号。
- Produces: `_build_short_result_context(signals, view)` 返回筛选结果、激活视图和各类计数。

- [ ] 增加已完成、观察中、盈利、亏损、高回撤和全部筛选。
- [ ] 为每条结果生成直观收益结论与回撤标签。
- [ ] 将分页调整为每页30条。

### Task 2: 页面信息结构

**Files:**
- Modify: `web_app/templates/signals.html`

**Interfaces:**
- Consumes: `short_stats`、`result_view`、`result_counts` 和 `signals`。
- Produces: 今日决策区、可折叠实盘历史和7列结果表。

- [ ] 重排第一屏核心信息。
- [ ] 增加快捷结果筛选。
- [ ] 将冗长原因放入按需展开详情。

### Task 3: 响应式视觉

**Files:**
- Modify: `web_app/static/app.css`
- Modify: `web_app/templates/base.html`

**Interfaces:**
- Consumes: `.page-signals` 下的短线工作台类名。
- Produces: 无全页横向溢出的桌面布局和移动端降级布局。

- [ ] 增加短线专属卡片、筛选标签和结果表样式。
- [ ] 更新静态资源版本以避免浏览器旧缓存。
