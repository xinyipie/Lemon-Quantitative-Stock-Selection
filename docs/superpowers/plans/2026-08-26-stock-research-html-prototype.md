# Stock Research HTML Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, interactive HTML prototype that reorganizes the stock research project into five clear workflows while preserving every useful existing capability and removing duplicate presentation.

**Architecture:** Create a dependency-free single-page prototype under `prototype/stock-research/`. `index.html` provides semantic views and controls, `app.css` owns the restrained “朴素研究表” visual system, and `app.js` owns local demo data, state switching, filtering, tabs, and detail rendering. Production FastAPI, Jinja templates, databases, and update jobs remain untouched.

**Tech Stack:** HTML5, CSS3, browser-native JavaScript, pytest static-contract tests, Codex in-app Browser visual verification.

**Spec:** `docs/superpowers/specs/2026-08-26-stock-research-html-prototype-design.md`

## Global Constraints

- Desktop Web first at 1440×1024; remain readable and operable at 1024px width.
- Use native HTML, CSS, and JavaScript only; no framework, package install, build tool, CDN, webfont, or external asset.
- Store all prototype code under `prototype/stock-research/` and do not modify `web_app/templates`, `web_app/static`, FastAPI routes, databases, or production update scripts.
- Use only fields supported by the spec's data contract. Do not show short-portfolio maximum drawdown, short CSI300 excess return, undefined profit/loss ratio, a data-completeness score, or nonexistent 20/60/120-day statistics.
- Preserve three demo states: `empty`, `signal`, and `stale`.
- Keep formal short signals, observation candidates, and market-radar directions visibly distinct.
- All new code comments are in Chinese.
- Do not add order entry, buy/sell actions, position sizing, portfolio management, or automated execution.

---

### Task 1: Prototype Shell and Navigation Contract

**Files:**
- Create: `prototype/stock-research/index.html`
- Create: `prototype/stock-research/app.css`
- Create: `prototype/stock-research/app.js`
- Create: `tests/test_stock_research_prototype.py`

**Interfaces:**
- Consumes: none.
- Produces: five view containers with IDs `view-today`, `view-strategy`, `view-market`, `view-stock`, `view-system`; navigation buttons with `data-view`; JavaScript function `showView(viewName: string): void`.

- [ ] **Step 1: Write the failing shell contract test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype" / "stock-research"


def read(name: str) -> str:
    return (PROTOTYPE / name).read_text(encoding="utf-8")


def test_prototype_shell_has_five_workflows_and_local_assets():
    html = read("index.html")
    assert 'href="app.css"' in html
    assert 'src="app.js"' in html
    for view in ("today", "strategy", "market", "stock", "system"):
        assert f'id="view-{view}"' in html
        assert f'data-view="{view}"' in html
    assert "今日" in html
    assert "策略复盘" in html
    assert "市场观察" in html
    assert "个股研究" in html
    assert "系统状态" in html
```

- [ ] **Step 2: Run the shell test and verify it fails**

Run: `python -m pytest tests/test_stock_research_prototype.py::test_prototype_shell_has_five_workflows_and_local_assets -v`

Expected: FAIL because `prototype/stock-research/index.html` does not exist.

- [ ] **Step 3: Create the semantic HTML shell**

Create `index.html` with this structural contract:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>策略研究助手 · HTML原型</title>
  <link rel="stylesheet" href="app.css">
</head>
<body>
  <a class="skip-link" href="#main-content">跳到主要内容</a>
  <header class="topbar">
    <a class="brand" href="#today" data-view="today">策略研究助手</a>
    <nav aria-label="主导航">
      <button type="button" data-view="today" aria-current="page">今日</button>
      <button type="button" data-view="strategy">策略复盘</button>
      <button type="button" data-view="market">市场观察</button>
      <button type="button" data-view="stock">个股研究</button>
      <button type="button" data-view="system">系统状态</button>
    </nav>
    <form id="global-search" role="search">
      <label class="sr-only" for="global-search-input">股票代码或名称</label>
      <input id="global-search-input" placeholder="股票代码或名称">
      <button type="submit">搜索</button>
    </form>
  </header>
  <main id="main-content">
    <section id="view-today" data-page-view></section>
    <section id="view-strategy" data-page-view hidden></section>
    <section id="view-market" data-page-view hidden></section>
    <section id="view-stock" data-page-view hidden></section>
    <section id="view-system" data-page-view hidden></section>
  </main>
  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Add minimal layout tokens and navigation behavior**

In `app.css`, define the plain visual foundation:

```css
:root {
  --bg: #f7f8fa;
  --surface: #fff;
  --ink: #17202a;
  --muted: #667085;
  --line: #d9e0e8;
  --blue: #2454d6;
  --green: #12805c;
  --red: #b42318;
  --amber: #ad6b00;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }
.topbar { min-height: 64px; display: grid; grid-template-columns: auto 1fr minmax(260px, 380px); align-items: center; gap: 28px; padding: 0 24px; background: var(--surface); border-bottom: 1px solid var(--line); }
.topbar nav { display: flex; gap: 8px; }
.topbar button, .topbar input { font: inherit; }
[data-page-view] { max-width: 1400px; margin: 0 auto; padding: 28px 24px 56px; }
[hidden] { display: none !important; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
```

In `app.js`, add the shared navigation contract:

```js
function showView(viewName) {
  document.querySelectorAll("[data-page-view]").forEach((view) => {
    view.hidden = view.id !== `view-${viewName}`;
  });
  document.querySelectorAll("[data-view]").forEach((control) => {
    const active = control.dataset.view === viewName;
    control.classList.toggle("is-active", active);
    if (control.tagName === "BUTTON") control.setAttribute("aria-current", active ? "page" : "false");
  });
  window.location.hash = viewName;
}

document.querySelectorAll("[data-view]").forEach((control) => {
  control.addEventListener("click", (event) => {
    event.preventDefault();
    showView(control.dataset.view);
  });
});
```

- [ ] **Step 5: Run the shell test**

Run: `python -m pytest tests/test_stock_research_prototype.py::test_prototype_shell_has_five_workflows_and_local_assets -v`

Expected: PASS.

- [ ] **Step 6: Commit the shell**

```bash
git add prototype/stock-research tests/test_stock_research_prototype.py
git commit -m "feat: scaffold stock research prototype"
```

---

### Task 2: Today View, Truthful Metrics, and Demo States

**Files:**
- Modify: `prototype/stock-research/index.html`
- Modify: `prototype/stock-research/app.css`
- Modify: `prototype/stock-research/app.js`
- Modify: `tests/test_stock_research_prototype.py`

**Interfaces:**
- Consumes: `showView(viewName)` from Task 1.
- Produces: constant `DEMO_STATES: Record<string, DemoState>`; functions `setDemoState(stateName: string): void`, `renderToday(state: DemoState): void`, and `toggleEvidence(): void`.

- [ ] **Step 1: Add failing tests for data honesty and three states**

```python
def test_today_view_uses_supported_metrics_and_three_states():
    html = read("index.html")
    js = read("app.js")
    for label in ("5日正收益率", "平均5日收益", "平均MFE", "平均MAE", "机会风险比"):
        assert label in html
    for state in ('empty:', 'signal:', 'stale:'):
        assert state in js
    for unsupported in ("最大回撤", "相对沪深300", "数据完整度"):
        assert unsupported not in html


def test_today_view_distinguishes_radar_from_pool_signals():
    html = read("index.html")
    assert "市场雷达观察，不等于入池推荐" in html
    assert 'id="today-evidence"' in html
    assert 'id="demo-state"' in html
```

- [ ] **Step 2: Run the new tests and verify failure**

Run: `python -m pytest tests/test_stock_research_prototype.py -v`

Expected: FAIL because the today content and demo-state model do not exist.

- [ ] **Step 3: Add the today document structure**

Populate `view-today` with these semantic regions:

```html
<div class="prototype-tools">
  <label for="demo-state">原型状态</label>
  <select id="demo-state">
    <option value="empty">空仓</option>
    <option value="signal">有信号</option>
    <option value="stale">数据滞后</option>
  </select>
</div>
<p class="date-line"><strong id="display-date">2026-08-26</strong>　数据截至 <span id="data-date">2026-08-25</span>　<span id="sync-label">行情与信号已同步</span></p>
<section class="decision-block" aria-labelledby="decision-title">
  <h1 id="decision-title">今日结论：不宜开新仓</h1>
  <p id="decision-reason">短线实盘无入池标的，长线 Elite / Watch 均为空；空仓也是策略结果。</p>
  <button type="button" class="text-button" id="evidence-toggle" aria-expanded="false">查看判断依据</button>
  <div id="today-evidence" hidden></div>
</section>
<div class="today-grid">
  <section aria-labelledby="watch-title"><h2 id="watch-title">今天重点看 <small>市场雷达观察，不等于入池推荐</small></h2><div id="watch-table"></div></section>
  <section aria-labelledby="stats-title"><h2 id="stats-title">策略近期表现 <small>本筛选窗口</small></h2><div id="strategy-stats"></div></section>
</div>
<section aria-labelledby="runtime-title"><h2 id="runtime-title">数据与运行状态</h2><div id="runtime-table"></div></section>
```

- [ ] **Step 4: Implement the exact demo-state data shape and renderer**

In `app.js`, define the shared shape and current realistic values:

```js
const DEMO_STATES = {
  empty: {
    conclusion: "今日结论：不宜开新仓",
    reason: "短线实盘无入池标的，长线 Elite / Watch 均为空；空仓也是策略结果。",
    tone: "caution",
    dataDate: "2026-08-25",
    stats: { sampleCount: 39, winRate: 38.5, avgRet5d: -2.47, avgMfe: 6.55, avgMae: -6.85, opportunityRisk: 0.95 },
    runtime: { market: "已更新", short: "已运行 / 0只", longterm: "已运行 / 0只", review: "最新样本 2026-07-03" }
  },
  signal: {
    conclusion: "今日结论：有可关注信号",
    reason: "短线正式层出现2只入池标的；仍需等待次日承接，不把入池等同买入。",
    tone: "ok",
    dataDate: "2026-08-25",
    stats: { sampleCount: 41, winRate: 41.5, avgRet5d: -1.82, avgMfe: 6.71, avgMae: -6.42, opportunityRisk: 1.05 },
    runtime: { market: "已更新", short: "已运行 / 2只", longterm: "已运行 / 1只", review: "最新样本 2026-07-03" }
  },
  stale: {
    conclusion: "今日结论：数据待更新",
    reason: "行情有效日落后，暂停生成当日判断；先完成数据同步。",
    tone: "warn",
    dataDate: "2026-08-21",
    stats: null,
    runtime: { market: "滞后4天", short: "未运行", longterm: "未运行", review: "最新样本 2026-07-03" }
  }
};

function renderToday(state) {
  document.querySelector("#decision-title").textContent = state.conclusion;
  document.querySelector("#decision-reason").textContent = state.reason;
  document.querySelector("#data-date").textContent = state.dataDate;
  document.querySelector("#strategy-stats").innerHTML = state.stats
    ? renderStatsTable(state.stats)
    : '<p class="empty-message">行情数据滞后，本窗口暂不计算策略表现。</p>';
  document.querySelector("#runtime-table").innerHTML = renderRuntimeTable(state);
  document.body.dataset.demoState = document.querySelector("#demo-state").value;
}

function setDemoState(stateName) {
  renderToday(DEMO_STATES[stateName] || DEMO_STATES.empty);
}
```

Implement `renderStatsTable`, `renderRuntimeTable`, and the market-radar observation table with escaped fixed strings. Use CSS classes `number-positive`, `number-negative`, and `status-warning`; do not infer investment instructions from colors.

```js
function renderStatsTable(stats) {
  const cells = [
    ["样本数（已完成）", stats.sampleCount, ""],
    ["5日正收益率", `${stats.winRate.toFixed(1)}%`, "number-positive"],
    ["平均5日收益", `${stats.avgRet5d > 0 ? "+" : ""}${stats.avgRet5d.toFixed(2)}%`, stats.avgRet5d >= 0 ? "number-positive" : "number-negative"],
    ["平均MFE", `+${stats.avgMfe.toFixed(2)}%`, "number-positive"],
    ["平均MAE", `${stats.avgMae.toFixed(2)}%`, "number-negative"],
    ["机会风险比", stats.opportunityRisk.toFixed(2), ""]
  ];
  return `<div class="table-scroll"><table><tbody><tr>${cells.map(([label]) => `<th scope="col">${label}</th>`).join("")}</tr><tr>${cells.map(([, value, tone]) => `<td class="metric-value ${tone}">${value}</td>`).join("")}</tr></tbody></table></div><p class="sample-warning">样本仅${stats.sampleCount}条，结论仍需积累。</p>`;
}

function renderRuntimeTable(state) {
  const rows = [
    ["行情库", state.dataDate, state.runtime.market],
    ["短线实盘", state.dataDate, state.runtime.short],
    ["长线扫描", state.dataDate, state.runtime.longterm],
    ["历史复盘", "2026-07-03", state.runtime.review]
  ];
  return `<div class="table-scroll"><table><thead><tr><th>模块</th><th>数据日期</th><th>状态</th></tr></thead><tbody>${rows.map((row) => `<tr>${row.map((value) => `<td>${value}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
```

- [ ] **Step 5: Wire evidence expansion, date controls, and state switching**

```js
document.querySelector("#demo-state").addEventListener("change", (event) => setDemoState(event.target.value));
document.querySelector("#evidence-toggle").addEventListener("click", () => {
  const panel = document.querySelector("#today-evidence");
  const expanded = panel.hidden;
  panel.hidden = !expanded;
  document.querySelector("#evidence-toggle").setAttribute("aria-expanded", String(expanded));
});
setDemoState("empty");
```

Add `近100日` and `自定义日期` controls. Custom dates update the displayed range and show “原型使用同结构模拟统计”; they must not invent a 20/60/120 preset.

- [ ] **Step 6: Run tests and verify all pass**

Run: `python -m pytest tests/test_stock_research_prototype.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the today workflow**

```bash
git add prototype/stock-research tests/test_stock_research_prototype.py
git commit -m "feat: add truthful daily decision prototype"
```

---

### Task 3: Strategy Review and Market Observation Workflows

**Files:**
- Modify: `prototype/stock-research/index.html`
- Modify: `prototype/stock-research/app.css`
- Modify: `prototype/stock-research/app.js`
- Modify: `tests/test_stock_research_prototype.py`

**Interfaces:**
- Consumes: shared navigation and fixed demo data from Tasks 1–2.
- Produces: `activateTab(group: string, tabName: string): void`, `filterShortSignals(): void`, `renderLongtermAudit(): void`, and `renderMarketPanel(tabName: string): void`.

- [ ] **Step 1: Add failing workflow coverage tests**

```python
def test_strategy_and_market_workflows_cover_existing_features():
    html = read("index.html")
    for label in ("短线复盘", "长线观察", "运行漏斗", "生命周期", "历史验证"):
        assert label in html
    for label in ("行业雷达", "热门龙头", "消息事件", "市场日报"):
        assert label in html
    assert 'data-tab-group="strategy"' in html
    assert 'data-tab-group="market"' in html
    assert 'id="short-filter-form"' in html
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest tests/test_stock_research_prototype.py::test_strategy_and_market_workflows_cover_existing_features -v`

Expected: FAIL because the consolidated workflows are not present.

- [ ] **Step 3: Build the strategy-review structure**

Add strategy tabs `short` and `longterm`. The short view contains strategy selector, result selector, start/end date, stock/industry query, current-window summary, 30-row-style compact table using 6 mock rows, and a detail disclosure. The long-term view contains current pool state, the four-stage run funnel, lifecycle events, and audit results with 10/40/80-day, MFE/MAE, benchmark, and excess-return fields.

Use this tab contract:

```html
<div class="tabs" role="tablist" aria-label="策略类型">
  <button role="tab" data-tab-group="strategy" data-tab="short" aria-selected="true">短线复盘</button>
  <button role="tab" data-tab-group="strategy" data-tab="longterm" aria-selected="false">长线观察</button>
</div>
<div data-tab-panel="strategy:short"></div>
<div data-tab-panel="strategy:longterm" hidden></div>
```

- [ ] **Step 4: Implement strategy filters and details**

```js
function filterShortSignals() {
  const form = new FormData(document.querySelector("#short-filter-form"));
  const query = String(form.get("q") || "").trim().toLowerCase();
  const result = String(form.get("result") || "all");
  const rows = SHORT_SIGNALS.filter((item) => {
    const queryMatch = !query || `${item.name} ${item.code} ${item.industry}`.toLowerCase().includes(query);
    const resultMatch = result === "all" || item.result === result;
    return queryMatch && resultMatch;
  });
  document.querySelector("#short-results").innerHTML = renderShortRows(rows);
}
```

Each short row must distinguish `正式策略`, `观察候选`, or `影子试运行`. Clicking “查看理由” opens an inline disclosure containing system reasons, confirmed outcome, MFE/MAE, and cached AI explanation state.

Define every `SHORT_SIGNALS` item with the same keys consumed by Tasks 3–4:

```js
const SHORT_SIGNALS = [
  { id: "20260703-605488", date: "2026-07-03", code: "605488.SH", name: "福莱新材", industry: "塑料", strategyLabel: "正式策略", result: "losing", score: 4.0, reason: "板块热度较好、量比活跃，但v9重排分偏低。", ret5d: -11.51, mfe: 2.51, mae: -15.86, explanationStatus: "已缓存 · 2026-08-25" },
  { id: "20260702-002594", date: "2026-07-02", code: "002594.SZ", name: "比亚迪", industry: "汽车整车", strategyLabel: "观察候选", result: "winning", score: 12.5, reason: "资金分较强、板块热度较好，形态仍需确认。", ret5d: 3.75, mfe: 6.23, mae: -0.16, explanationStatus: "待生成" },
  { id: "20260629-002891", date: "2026-06-29", code: "002891.SZ", name: "中宠股份", industry: "食品", strategyLabel: "影子试运行", result: "winning", score: 22.6, reason: "量比活跃，但重排分低于正式层阈值。", ret5d: 5.26, mfe: 6.45, mae: -1.45, explanationStatus: "已缓存 · 2026-08-24" }
];
```

- [ ] **Step 5: Build the market-observation tabs**

Add four accessible tabs and compact mock content:

- `行业雷达`: trend heat, news heat, resonance state, and confirmation condition.
- `热门龙头`: priority, cautious, and research-only groups with source date.
- `消息事件`: verified/unverified, positive/negative/neutral labels, source, timestamp, and verification points.
- `市场日报`: archive list and an inline readable detail view.

Use `activateTab(group, tabName)` for both strategy and market groups, and preserve `aria-selected`, `hidden`, and keyboard-focusable buttons.

```js
function activateTab(group, tabName) {
  document.querySelectorAll(`[data-tab-group="${group}"]`).forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.tab === tabName));
  });
  document.querySelectorAll(`[data-tab-panel^="${group}:"]`).forEach((panel) => {
    panel.hidden = panel.dataset.tabPanel !== `${group}:${tabName}`;
  });
}

document.querySelectorAll("[data-tab-group]").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tabGroup, button.dataset.tab));
});
```

- [ ] **Step 6: Run tests and manually exercise tabs**

Run: `python -m pytest tests/test_stock_research_prototype.py -v`

Expected: PASS.

Manual browser checks:

1. Open `index.html` through a local static server.
2. Switch between short/longterm without page reload.
3. Filter a stock by name and then reset.
4. Switch all four market tabs and open one report detail.
5. Confirm formal signals, observations, and radar directions never share the same label.

- [ ] **Step 7: Commit strategy and market workflows**

```bash
git add prototype/stock-research tests/test_stock_research_prototype.py
git commit -m "feat: consolidate strategy and market prototype views"
```

---

### Task 4: Stock Research and System Status Workflows

**Files:**
- Modify: `prototype/stock-research/index.html`
- Modify: `prototype/stock-research/app.css`
- Modify: `prototype/stock-research/app.js`
- Modify: `tests/test_stock_research_prototype.py`

**Interfaces:**
- Consumes: `showView`, shared tab renderer, and local demo state.
- Produces: `searchStock(query: string): void`, `renderStock(stock: StockRecord): void`, `renderSystemStatus(state: DemoState): void`, and `openSignalDetail(signalId: string): void`.

- [ ] **Step 1: Add failing stock/system tests**

```python
def test_stock_and_system_views_preserve_useful_capabilities():
    html = read("index.html")
    for label in ("价格趋势", "财务质量", "资金行为", "历史信号", "信号解释"):
        assert label in html
    for label in ("数据覆盖", "日常更新", "完整重算", "异常提示"):
        assert label in html
    assert 'id="stock-search-form"' in html
    assert 'id="signal-detail"' in html
```

- [ ] **Step 2: Run the test and verify failure**

Run: `python -m pytest tests/test_stock_research_prototype.py::test_stock_and_system_views_preserve_useful_capabilities -v`

Expected: FAIL because the detail structures are missing.

- [ ] **Step 3: Implement stock search and explicit missing fields**

Define two local stock records, one complete and one intentionally incomplete:

```js
const STOCKS = [
  { code: "000001.SZ", name: "平安银行", latestClose: 11.59, ret10d: 2.93, ret40d: 15.32, ret80d: 1.13, roe: 2.65, netprofitYoy: 3.03, debtToAssets: 90.98, netMainFlow: 10321.90, turnover: 0.51, volumeRatio: 0.91, missing: ["PE(TTM)", "PB", "总市值"] },
  { code: "600519.SH", name: "贵州茅台", latestClose: 1468.00, ret10d: -1.20, ret40d: 4.10, ret80d: 8.30, roe: 31.20, netprofitYoy: 12.40, debtToAssets: 18.50, netMainFlow: null, turnover: 0.24, volumeRatio: 0.76, missing: ["主力净流入"] }
];

function searchStock(query) {
  const normalized = query.trim().toLowerCase();
  const stock = STOCKS.find((item) => `${item.code} ${item.name}`.toLowerCase().includes(normalized));
  document.querySelector("#stock-search-error").textContent = stock ? "" : "未找到股票，请输入代码或中文名。";
  if (stock) renderStock(stock);
}
```

Render missing fields by name: `缺少：PE(TTM)、PB、总市值`; never use only “数据不足”. Use a plain CSS line placeholder for the prototype trend plot only if it is built from CSS borders; do not create a decorative fake chart. A compact 120-day SVG-free table of date/close/MA20/MA60 sample rows is acceptable and preferred.

- [ ] **Step 4: Implement history detail and AI explanation as a disclosure**

Add a dialog-like inline `<section id="signal-detail" hidden>` with close button, strategy identity, selection date, score, reasons, subsequent 5-day result, MFE/MAE, confirmation conditions, invalidation conditions, and explanation timestamp. `openSignalDetail(signalId)` must open an existing record only and must not generate new AI content.

```js
function openSignalDetail(signalId) {
  const signal = SHORT_SIGNALS.find((item) => item.id === signalId);
  if (!signal) return;
  const panel = document.querySelector("#signal-detail");
  panel.innerHTML = `<div class="detail-head"><h3>${signal.name} · ${signal.strategyLabel}</h3><button type="button" id="close-signal-detail">关闭</button></div><dl><dt>入选日期</dt><dd>${signal.date}</dd><dt>系统理由</dt><dd>${signal.reason}</dd><dt>5日结果</dt><dd>${signal.ret5d}%</dd><dt>MFE / MAE</dt><dd>${signal.mfe}% / ${signal.mae}%</dd><dt>AI解释</dt><dd>${signal.explanationStatus}</dd></dl>`;
  panel.hidden = false;
  document.querySelector("#close-signal-detail").addEventListener("click", () => { panel.hidden = true; });
}
```

- [ ] **Step 5: Implement system status without duplicating daily content**

Render data coverage rows for `stock_daily`, `stock_daily_basic`, `stock_moneyflow`, `index_daily`, `stock_basic`, `fina_indicator`, and `income`. Put “日常更新” and “完整重算” only in this view. Prototype buttons show a confirmation-free local status message such as “原型演示：未调用生产更新任务”; they must not call any endpoint.

```js
function renderSystemStatus(state) {
  const warning = state === DEMO_STATES.stale ? "行情日期落后，请先运行日常更新。" : "各核心日期已同步。";
  document.querySelector("#system-summary").textContent = warning;
}

document.querySelectorAll("[data-prototype-update]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#update-demo-message").textContent = "原型演示：未调用生产更新任务。";
  });
});
```

- [ ] **Step 6: Run tests and exercise search/error paths**

Run: `python -m pytest tests/test_stock_research_prototype.py -v`

Expected: PASS.

Manual checks:

1. Search `000001`, `平安银行`, and an invalid symbol.
2. Confirm invalid input is retained and error text is visible.
3. Open and close one signal detail using mouse and keyboard.
4. Switch demo state to stale and confirm system status explains the lag.
5. Click both update buttons and confirm no network request or production mutation occurs.

- [ ] **Step 7: Commit stock and system workflows**

```bash
git add prototype/stock-research tests/test_stock_research_prototype.py
git commit -m "feat: add stock research and system prototype views"
```

---

### Task 5: Responsive, Accessibility, and Visual Verification

**Files:**
- Modify: `prototype/stock-research/app.css`
- Modify: `prototype/stock-research/index.html`
- Modify: `prototype/stock-research/app.js`
- Modify: `tests/test_stock_research_prototype.py`

**Interfaces:**
- Consumes: completed prototype from Tasks 1–4.
- Produces: verified desktop prototype with no horizontal overflow at 1440px and 1024px; keyboard-visible focus; final screenshots for empty, signal, and stale states.

- [ ] **Step 1: Add failing structural accessibility tests**

```python
def test_prototype_has_accessible_controls_and_no_production_calls():
    html = read("index.html")
    js = read("app.js")
    assert 'class="skip-link"' in html
    assert 'aria-label="主导航"' in html
    assert 'aria-expanded="false"' in html
    assert 'role="tablist"' in html
    assert "fetch(" not in js
    assert "XMLHttpRequest" not in js
    assert "/update/run" not in js
```

- [ ] **Step 2: Run the test and verify any missing contract fails**

Run: `python -m pytest tests/test_stock_research_prototype.py::test_prototype_has_accessible_controls_and_no_production_calls -v`

Expected: FAIL until all specified semantics and network exclusions are present.

- [ ] **Step 3: Add responsive and focus styles**

```css
:focus-visible { outline: 3px solid rgba(36, 84, 214, .35); outline-offset: 2px; }
.skip-link { position: fixed; left: 16px; top: -80px; z-index: 20; background: #fff; padding: 8px 12px; border: 1px solid var(--blue); }
.skip-link:focus { top: 12px; }
@media (max-width: 1100px) {
  .topbar { grid-template-columns: 1fr; gap: 10px; padding: 12px 18px; }
  .topbar nav { overflow-x: auto; }
  .today-grid { grid-template-columns: 1fr; }
  .table-scroll { overflow-x: auto; }
}
```

Ensure every wide table is inside `.table-scroll`, buttons are at least 36px tall, muted text meets a visually reasonable contrast level, and no body-level horizontal scrollbar appears.

- [ ] **Step 4: Start a local static server and inspect the prototype**

Run: `python -m http.server 8765 --directory prototype/stock-research`

Expected: server listens on port 8765 and `index.html` loads without console errors.

Use the in-app Browser to capture and inspect:

1. 1440×1024, empty state, today view.
2. 1440×1024, signal state, short-strategy detail open.
3. 1440×1024, stale state, system view.
4. 1024×768, today view with no horizontal page overflow.
5. Keyboard navigation through top nav, tabs, evidence disclosure, filters, stock search, and signal detail.

- [ ] **Step 5: Compare against the selected plain visual target and correct mismatches**

Place the selected generated mock and the 1440×1024 prototype screenshot in one visual comparison. Correct only visible mismatches that affect the approved direction: typography scale, excessive card styling, unnecessary icons, crowded spacing, table alignment, red/green misuse, borders, and overflow. Repeat the screenshot once after corrections.

- [ ] **Step 6: Run final verification**

Run: `python -m pytest tests/test_stock_research_prototype.py -v`

Expected: all prototype contract tests PASS.

Run: `git diff --check -- prototype/stock-research tests/test_stock_research_prototype.py`

Expected: no whitespace errors.

- [ ] **Step 7: Commit verified prototype**

```bash
git add prototype/stock-research tests/test_stock_research_prototype.py
git commit -m "feat: finish verified stock research html prototype"
```
