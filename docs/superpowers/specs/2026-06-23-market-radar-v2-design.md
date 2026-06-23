# Market Radar v2 后端设计

## 目标

市场雷达 v2 面向“盘前研究 + 收盘复盘”，后置盘中实时监控。它不是自动交易模块，也不生成下单、仓位或交易执行建议。目标是把现有“行业热度看板”升级为“事件驱动研究台”：像金融机构研究员或交易所新闻研究员一样，先判断新闻事件的真实性、重要性和行业映射，再看市场是否用量价和资金给出验证，最后给出可追溯的行业与个股观察清单。

## 现状

现有后端主要由三部分组成：

- `sector_heat_diagnostics.py`：计算行业热度、阶段和板块内候选股。
- `web_app/services/sector_service.py`：聚合行业热度、新闻/概念缓存、策略信号共振，并装饰成 Web 展示字段。
- `news_analyzer.py` 与 `logs/cache/news_sector_*.json`：抓取概念热度、解析新闻到行业，缓存原始新闻、AI 映射和行业 boosts。

这些数据已经能支撑 v2。`news_sector_20260622.json` 里已有 `raw_news`、`items`、`boosts`、`news_value_score`、URL 和来源信息，但 Web 后端目前只使用了其中一部分。

## 设计原则

- 研究优先：先解释“为什么这个行业值得看”，再给观察动作。
- 可追溯：每个结论都能回到新闻、来源、行业映射、量价验证和风险点。
- 分层判断：新闻事件、行业 thesis、个股证据、策略共振分开计算，再汇总。
- 保守表达：标签使用“重点跟踪、观察池、等确认、仅复盘”等研究语言，不表达买卖指令。
- 可降级：没有新闻缓存时仍能用行业量价热度工作；没有指数/概念数据时必须标出低置信。

## 后端分层

### 1. Event Layer

把新闻从“行业加分”升级为标准事件对象。

字段建议：

- `event_id`：稳定哈希，来源于标题、发布时间、来源和事件类型。
- `title`：规范化标题。
- `event_type`：政策、监管、订单、业绩、价格、地缘、产业趋势、风险提示、资金市场。
- `impact`：positive、negative、mixed。
- `materiality`：A、B、C、D。
- `duration`：日内、1-3日、1-2周、中期。
- `novelty`：新事件、延续事件、重复炒作。
- `source_quality`：官方、交易所/监管、公司公告、主流财经、普通媒体、传闻。
- `mapped_industries`：行业映射列表。
- `mapping_confidence`：precise、medium、broad。
- `evidence_urls`：来源链接和来源名。
- `verification_points`：后续验证点。
- `invalidation_points`：证伪点。
- `risk_note`：最大误读风险。

Event Layer 可以先从 `news_sector_*.json` 的 `items` 和 `raw_news` 装饰生成，不急着改新闻抓取链路。

### 2. Sector Thesis Layer

每个行业生成一个研究判断，而不只是热度分。

输入：

- 行业量价热度：`heat_score`、阶段、超额收益、MA20 占比、放量扩散、涨停/过热比例。
- 新闻事件：A/B/C/D 事件、正负影响、映射置信、持续性。
- 概念热度：概念涨幅与热度。
- 数据状态：行业指数覆盖、新闻日期和行情日期是否对齐。

输出字段：

- `thesis_label`：主线共振、趋势主线、消息待验证、过热风险、退潮风险、无主线。
- `research_action`：可重点跟踪、先放观察池、等回踩确认、仅复盘、暂不参与。
- `conviction`：高、中、低。
- `event_score`：新闻事件分。
- `market_validation_score`：量价验证分。
- `risk_score`：过热、负面事件、泛化映射、数据错位等扣分。
- `thesis_score`：综合研究分。
- `summary`：一句话研究摘要。
- `evidence`：支撑项列表。
- `risks`：风险项列表。
- `verification_points`：下一步验证项。

### 3. Stock Evidence Layer

个股候选不再只看板块内排名，而是拆成证据。

输入：

- 原有板块候选评分：相对板块、10日收益、MA20、量能、资金、换手。
- 策略信号：短线 v9、长线 v18 是否入池。
- 事件映射：是否直接受益、间接受益、泛题材。
- 风险过滤：现行财务/风险排除、过热追高、板块退潮。

输出字段：

- `stock_role`：领涨、跟随、补涨、掉队、过热。
- `event_relevance`：直接受益、间接受益、泛题材、无事件支撑。
- `market_behavior`：放量承接、缩量整理、追高、资金分歧、资金流出。
- `strategy_alignment`：短线共振、长线共振、仅板块候选、策略冲突。
- `research_action`：可重点跟踪、先放观察池、等回踩确认、仅复盘。
- `reason_cards`：量价、资金、事件、策略、风险五类证据。

### 4. Research Brief Layer

为页面和后续 AI 摘要输出稳定结构。

输出建议：

- `headline`：今日市场雷达一句话。
- `market_regime_note`：市场环境简述。
- `mainlines`：主线行业列表。
- `event_watchlist`：关键事件列表。
- `sector_theses`：行业研究卡片。
- `stock_watchlist`：个股观察清单。
- `risk_board`：风险板块和负面事件。
- `verification_checklist`：下一交易日要验证什么。
- `data_quality`：数据日期、指数覆盖、新闻覆盖、概念覆盖。

## 综合评分草案

行业综合研究分 `thesis_score`：

- 35% 市场验证：超额收益、MA20 扩散、放量扩散、资金流。
- 30% 事件质量：事件等级、来源质量、持续性、映射置信。
- 15% 策略共振：短线/长线是否在同一行业产生信号。
- 10% 新鲜度：新闻是否新、行情是否刚开始验证。
- 10% 风险扣分：过热、负面事件、泛化映射、数据错位。

动作口径：

- `可重点跟踪`：thesis_score 高，事件和量价至少一项强，风险不过热。
- `先放观察池`：有事件或量价线索，但验证不足。
- `等回踩确认`：热度强但位置偏高或追高风险明显。
- `仅复盘`：退潮、负面事件、策略冲突或数据低置信。
- `暂不参与`：负面事件强、退潮严重或数据缺口过大。

## 数据质量与审计

新增 `data_quality` 输出：

- `sector_date`、`news_date`、`concept_date`、`signal_date`。
- `aligned`：日期是否对齐。
- `index_coverage`：最新行业指数覆盖数量。
- `news_source_count`：原始新闻数量。
- `event_count`：有效事件数量。
- `low_confidence_reasons`：数据错位、新闻缓存缺失、映射泛化、指数覆盖不足等。

页面可以明确显示“结论高/中/低置信”，避免用户把低质量输入下的结论当真。

## 模块边界

建议保留现有文件，同时新增较小模块，避免 `sector_service.py` 继续膨胀：

- `market_radar/events.py`：新闻缓存到标准事件。
- `market_radar/sector_thesis.py`：行业研究分和动作。
- `market_radar/stock_evidence.py`：个股证据卡。
- `market_radar/brief.py`：聚合输出给 Web。
- `web_app/services/sector_service.py`：逐步变成兼容层和模板适配层。

第一阶段可以不移动旧代码，只新增纯函数并在 `sector_service.py` 调用。

## 分阶段实现

### Phase 1：事件标准化与研究摘要

- 从 `news_sector_*.json` 生成标准 `events`。
- 给新闻事件补 `source_quality`、`novelty`、`materiality`、`verification_points`。
- 在 `build_concept_news_radar()` 返回 `events` 和 `event_summary`。
- 页面先展示“关键事件研究卡”。

### Phase 2：行业 thesis

- 新增 `build_sector_theses()`，合并行业热度和事件。
- 生成 `thesis_score`、`conviction`、`research_action`、`evidence`、`risks`。
- 让 `build_market_radar_decision()` 改用 thesis 结果，而不是简单交集。

### Phase 3：个股证据卡

- 新增 `build_stock_evidence()`。
- 候选股按“事件相关性 + 量价承接 + 策略共振 + 风险”分解。
- 替换现有板块内候选股的单一评分展示。

### Phase 4：复盘闭环

- 收盘后记录事件是否被市场验证。
- 对事件等级、行业映射、个股候选做事后审计。
- 输出“昨日主线验证 / 失败原因 / 次日观察点”。

## 测试策略

- 单元测试标准事件生成：重复新闻合并、来源链接保留、泛化映射降置信。
- 单元测试 thesis：主线共振、消息待验证、过热风险、负面冲突。
- 单元测试个股证据：领涨/补涨/掉队、直接/间接受益、过热追高。
- 服务测试：旧 `build_sector_radar()` 和 `/sectors` 页面兼容。
- 数据质量测试：新闻日期和行情日期错位、指数覆盖不足时降置信。

## 非目标

- 不做自动下单。
- 不做仓位管理。
- 不把新闻事件直接转成买入建议。
- 不引入逐股 Tushare 请求。
- 不改变当前正式短线和长线策略参数。
