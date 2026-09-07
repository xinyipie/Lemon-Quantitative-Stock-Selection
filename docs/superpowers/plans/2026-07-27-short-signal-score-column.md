# Short Signal Score Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在短线历史结果中紧邻股票信息展示基础策略分和 v9 风控复评分，并通过弹层集中呈现规则理由与已有 AI 判断。

**Architecture:** 直接复用 `signals` 页面已有的 `item.factors`、`item.score`、`item.recommend_reason`、`item.score_explain` 和 `item.ai_view`。模板使用原生 HTML `dialog` 提供弹层交互，样式集中放在现有 `app.css`，不新增后端接口、不请求模型、不改变评分算法。

**Tech Stack:** FastAPI、Jinja2、原生 HTML dialog、CSS。

## Global Constraints

- 只调整短线历史结果展示，不改变评分、排序、筛选和量化结果。
- 基础策略分缺失时显示“暂无”，不得显示伪造的 0 分。
- AI 判断只复用已有结果，不因打开弹层新增 DeepSeek 调用。
- 保持表格总列数不变，移动端沿用横向滚动。
- 不执行测试、浏览器验证或线上部署，除非用户明确授权。

---

### Task 1: 重组短线历史评分信息

**Files:**
- Modify: `web_app/templates/signals.html:139-195`
- Modify: `web_app/static/app.css:4556-4641`
- Modify: `web_app/templates/base.html:7`

**Interfaces:**
- Consumes: `item.factors.original_score`、`item.factors.score_base`、`item.score`、`item.score_explain`、`item.recommend_reason`、`item.current_risk_reason`、`item.ai_view`
- Produces: `.short-score-cell`、`.score-reason-trigger`、`.score-reason-dialog` 及对应的紧凑评分列和详情弹层

- [ ] **Step 1: 调整表头与行内容**

  在“股票 / 信号日”后增加“评分”，移除股票单元格中的旧评分行；基础分按 `original_score`、`score_base` 顺序回退，v9 分读取 `item.score`。

- [ ] **Step 2: 合并重复详情**

  删除最右侧“依据与详情”列，将 `recommend_reason`、`score_explain`、风险原因和 `partials/ai_observation.html` 放入评分列触发的原生 `dialog`；空结果行继续使用 11 列。

- [ ] **Step 3: 完成紧凑排版和弹层样式**

  重新分配 11 列宽度；评分列采用两行数值和一行链接；弹层限制为视口内可滚动，支持关闭按钮、Escape 和点击遮罩关闭。

- [ ] **Step 4: 更新静态资源版本**

  将 `base.html` 中 `app.css` 查询版本更新为 `20260727-short-score-v1`，避免浏览器继续使用旧样式缓存。

