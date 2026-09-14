# 日报与市场专栏优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 修复行情更新、日报发布和专栏数据解释的可靠性问题。

**Architecture:** 复用现有下载、事实构建、质检、SQLite 发布和 Jinja 页面。公共时效判断供日报与更新任务使用；证据作为文章内可选快照保存，旧数据兼容。

**Tech Stack:** Python、pandas、PyArrow、SQLite、FastAPI、Jinja、pytest。

**Spec:** `docs/superpowers/specs/2026-09-14-information-reliability-design.md`

## Global Constraints

- 纯选股工具，严禁新增自动下单、仓位管理或交易执行代码。
- Tushare 按市场或代码批量调用，不逐股循环请求。
- 新增代码注释使用中文；沿用 HTTP 中转与当前正式策略。
- 不删除历史报告/缓存，不以未来数据回填历史证据。
- 测试报告只陈述实际执行结果；生产补数和多年回测单独标记。

## Task 1：股票主数据类型修复（O01）

文件：`data_downloader.py`、`tests/test_data_integrity_remediation.py` 或专门回归文件。

接口：`download_stock_basic(pro, force=False)` 保持不变；保存前统一已知文本字段、symbol 六位代码与日期表示，标准化 incoming 和部分下载时合并的 existing。

- [x] 以字符串 `000001`、浮点 `2.0`、缺失 symbol 及退市记录构造失败回归，实际读写 Parquet。
- [x] 运行测试确认原实现失败，再增加局部标准化函数；无效 ts_code 不覆盖缓存。
- [x] 运行 `python -m pytest tests/test_data_integrity_remediation.py tests/test_data_downloader_trade_dates.py` 与新回归。

## Task 2：日报发布与证据合同（O03、O04、O05）

文件：`daily_report/service.py`、`publication.py`、`writer.py`、`facts.py` 及对应测试。

接口：保留 `generate_daily_report` 参数；保存的 document 新增公开 `evidence_snapshot`，证据键沿用段落 evidence_ids，包含 label、有限公开摘要、source_url、published_at，不向页面泄露原始 payload。

- [x] 将“跳过校验直接发布”旧测试改为拒绝；新增修订成功、修订失败后合格降级、畸形段落、危险链接回归。
- [x] 调用 `validate_report(document, facts, public_facts)`，错误传给一次 reviser，降级稿也校验，失败保持旧文章。
- [x] 历史绩效保留来源/区间/样本/限制，提示词与确定性稿不能推断当前市场；数值显示适度舍入。
- [x] 保存当前文章使用的公开证据快照，禁止重新查询后用今天数据替代。
- [x] 运行 `python -m pytest tests/test_daily_report_service.py tests/test_daily_report_publication.py tests/test_daily_report_facts.py tests/test_daily_report_writer.py tests/test_daily_report_output.py`。

## Task 3：交易日时效与更新状态（O02、O06）

文件：公共时效模块、`daily_report/service.py` 或事实构建入口、`daily_web_update.py`、对应测试。

接口：新增可注入日期/日历的纯判断函数，输出 expected_date、actual_date、status、reason；日报构建与更新命令共享。

- [x] 新增过期、周末、节假日、缺失日历、未收盘日测试，使用临时日历不联网。
- [x] 在调用 AI 之前检查日报所需前一交易日；缺日历或过期直接返回明确失败。
- [x] 更新流程结束前核验实际交易日，过期不得打印成功；历史指定日期以指定目标核验。
- [x] 运行 `python -m pytest tests/test_daily_web_update.py tests/test_daily_web_update_modes.py tests/test_scheduled_update.py` 与时效回归。

## Task 4：日报与专栏阅读体验（O05、O07、O08）

文件：`web_app/templates/report_detail.html`、`reports.html`、`sectors.html`、`web_app/services/report_service.py`、`web_app/static/app.css` 及页面测试。

- [x] 为新版文章来源展开、旧文无快照、历史数据提示增加页面回归。
- [x] 依据区展示安全来源、时间、证据说明；数据日期突出，旧报告不再只显示 AI 品牌强调。
- [x] 明确日报/雷达/策略/龙头的分工，次级内容折叠；保留导航和历史阅读。
- [x] 本地真实浏览器验证日报导航、依据展开、雷达导航和窄屏；运行页面回归。

## Task 5：集成验证与交付记录

- [x] 检查全部 diff，按设计做独立代码审查并处理发现。
- [x] 运行 `python -m pytest` 和 `node --test tests/js/*.test.cjs`（环境可用时）。
- [x] 更新本计划勾选与实测结果、修改总览；准确列出生产部署/补数状态。

## 执行记录

- 2026-09-14：计划建立。策略收益研究单独列为后续事项；本轮完成 O01—O08 工程范围，不以历史收益作为验收。

- 2026-09-14：Task 1—4 已实施，定向与全套回归通过，浏览器已验收。Task 5 复审完成（66 项针对测试通过，无新增阻塞），生产部署/补数未执行；详细证据见 `docs/audits/2026-09-14-information-reliability.md`。
- 决定：在当前独立功能分支原位工作，不复制体量较大的研究数据；保留用户原工作目录，所有修改可由 Git 审查。
- 决定：盘中更新采用上海时间18点前允许前一交易日的保守到数门槛；报告至少要求报告日前一交易日，同日已取得的行情仍可使用。
- 补充 O06：浏览器发现缺日期被判为日期对齐，已修复并补 `tests/test_radar_alignment_missing.py`。

- 2026-09-14 上线追加：最终服务器版本 c89ffcd，11个入口通过，真实股票主数据5901条保存成功；日行情补数未执行。详情见上线记录。
