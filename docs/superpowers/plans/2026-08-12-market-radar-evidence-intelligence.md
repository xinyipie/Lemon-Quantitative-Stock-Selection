# Market Radar Evidence Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让全部来源可识别、日期有效且内容可读的新闻进入 AI 研判，并使最终结论可追溯到真实证据。

**Architecture:** 新增 `market_radar.evidence_pack` 作为新闻、概念、行业、候选股和运行质量的统一适配层。`ai_news_brief` 对证据分批做首轮价值研判，再将结构化结果与市场上下文汇总，继续使用现有缓存和页面读取接口。

**Tech Stack:** Python、JSON、现有 DeepSeek 兼容调用、现有市场雷达缓存。

## Global Constraints

- 不修改量化评分、候选排名或策略结果。
- 不新增交易、仓位或自动执行能力。
- 新闻准入只要求来源可识别、日期有效、内容可读。
- 不因缺少行业映射、原文链接或预判方向而丢弃新闻。
- 保持 `generate_ai_news_brief` 和页面缓存接口兼容。

---

### Task 1: 统一可信证据包

**Files:**
- Create: `market_radar/evidence_pack.py`

**Interfaces:**
- Produces: `build_evidence_pack(radar, concept_news, target_date, previous_brief=None) -> dict`
- Produces: `build_input_audit(pack) -> dict`

- [ ] 归一化新闻来源、发布时间、采集时间、正文摘要和原文链接。
- [ ] 只排除来源缺失、日期无效、内容不可读、明确过期和完全重复记录。
- [ ] 合并近似转载为事件组，并保留来源集合。
- [ ] 纳入概念题材、行业量价、量化候选、数据质量和上一轮研判。
- [ ] 输出稳定 `evidence_id` 与完整输入审计。

### Task 2: AI 两阶段研判

**Files:**
- Modify: `market_radar/ai_news_brief.py`

**Interfaces:**
- Consumes: `build_evidence_pack(...) -> dict`
- Produces: 保持 `generate_ai_news_brief(...) -> dict` 与 `load_ai_news_brief(...) -> dict`

- [ ] 将全部准入事件按固定批次发送给 AI 做逐条价值研判。
- [ ] 汇总首轮结果与概念、行业、候选和复盘上下文。
- [ ] 要求所有驱动、风险、板块和股票结论引用 `evidence_id`。
- [ ] 校验行业、股票和证据白名单，删除无事实引用的结论。
- [ ] 缓存首轮结果、证据目录和输入审计，保留原有失败降级。

### Task 3: 调度兼容与状态落盘

**Files:**
- Modify: `daily_web_update.py`

**Interfaces:**
- Consumes: 原有 `radar`、`concept_news` 和 `snapshot_date`
- Produces: 原有市场雷达 JSON，同时记录 AI 证据审计摘要

- [ ] 保持定时刷新调用顺序不变。
- [ ] 将 AI 证据审计摘要写入市场雷达快照，便于后续定位采集、过滤、映射或 AI 故障。
- [ ] 不改变页面模板和现有路由。
