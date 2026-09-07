# Market Radar Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除空白、重复卡片和模板化新闻内容。

**Architecture:** 服务层生成只读规则方向；模板自适应折叠；个股证据按代码并入板块候选表。

**Tech Stack:** Python, FastAPI, Jinja2, CSS

## Global Constraints

- 规则方向不进入量化评分。
- 新闻时效规则保持不变。
- 桌面高密度，移动端单列。

### Task 1: 新闻差异化
- [ ] 修改 `web_app/services/sector_service.py` 生成方向、摘要和类别。

### Task 2: 页面压缩
- [ ] 修改 `web_app/templates/sectors.html` 与 `web_app/static/app.css` 折叠空栏目。

### Task 3: 合并个股证据
- [ ] 将 `brief.stock_watchlist` 按代码并入板块候选表。

