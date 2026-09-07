# 2026-09-07 代码修改与当前运行说明

本说明覆盖从审查快照 `bf8bac1` 开始的修复，以及随后恢复原行情中转的变更。当前已部署的运行代码为 `b543b866d5213adfb484ae694afad54f569255eb`；之后的文档提交不代表运行代码再次部署。

## 当前配置

| 项目 | 当前值或行为 |
|---|---|
| 行情地址 | `http://14.nat0.cn:32817`，来自发布前代码及生产备份，经用户确认继续使用；`TUSHARE_HTTP_URL` 未设置或留空时使用该地址。 |
| 行情地址校验 | 原中转 HTTP 地址和服务方 HTTPS 地址可用；拒绝其他 HTTP 地址、URL 中的用户名密码、查询参数和片段。 |
| 凭据 | 行情使用 `TUSHARE_TOKEN`，当前 AI 使用 `DEEPSEEK_API_KEY`；真实值不写入仓库。 |
| 短线 | `profile_v9_sector_quality_guard` + `adaptive_quality_v6`，强推荐层 `v39`，观察层 `best_balance`。 |
| 长线 | 已启用 `longterm_quality_lifecycle_v18_market_sync` 观察池及 Elite 提醒。 |
| 网站 | `/stock/`；未配置 `STOCK_WEB_TOKEN` 时默认只读。恢复行情地址不会开放匿名网页写操作。 |
| 生产入口 | `stock-web` → `gateway:app`，Python 3.12。 |

## 修改了哪些代码

| 部分 | 主要文件 | 修改后的行为 |
|---|---|---|
| 行情配置与连接 | `config.py`、`main.py`、`.env.example` | 恢复实际原中转地址；初始化先校验地址，日志使用实际 HTTP/HTTPS 协议；中转 HTTP 错误明确抛出，不再被当成空数据。 |
| 下载与历史数据 | `data_downloader.py`、`local_data_proxy.py`、`daily_web_update.py` | 财务增量更新与历史版本合并，传递正确缓存目录；保存完整 L/D/P 基础信息快照；严格历史读取缺少对应快照时报错。补齐全新目录初始化及 pandas/Arrow 缺失日期兼容。 |
| 正式策略与风险门控 | `main.py`、`strategy_profiles.py`、`longterm_live_pipeline.py` | 基准行情缺失时停止依赖市场判断的选股；修正止损风险分母、财务同报告期版本选择、观察池跨月日期计算；关闭择时的实验分支真正跳过相关门控。 |
| 回测成交与统计 | `backtest_v2.py`、`batch_backtest.py`、`ic_analysis.py`、长线审计模块 | 开盘准入不读取当天收盘结果；用前一日已知移动止损，跳空按可实现价格；已有持仓可在涨停日卖出，封死跌停保留退出意图。净收益用于胜负统计，按模式选 IC 分数，正式与纯因子实验显式区分。 |
| 新闻与板块诊断 | `news_analyzer.py`、`market_analyzer.py`、`concept_heat_provider.py`、`sector_heat_diagnostics.py`、`rule_hit_diagnostics.py` | 过滤过期、未来和无法解析日期的新闻并去重；未知行业不能影响市场决策；缺数据与真实零值区分，历史板块使用当时快照。 |
| 研究算法与证据 | `research/research_integrity.py`、`no_future_signal_pipeline.py`、`all_market_multi_engine_research.py`、各 clean/walkforward 家族、`research_evidence_registry.py` | 训练标签必须在预测起点前结束；先锁定候选再判定 T+1 成交，不按未来收益替补；未成交不建仓，缺标签不编码为负类，停牌不虚构退出。已用于选参的样本、毛收益或重叠收益序列不能作为 ready/OOS 证明。 |
| 后端任务与访问控制 | `web_app/app.py`、`services/update_service.py`、`update_worker.py`、`explanation_service.py`、`market_radar/store.py` | 更新任务按模式保存状态，互斥执行并传递失败码；GET 解释读缓存，POST 才生成；未授权写入明确拒绝，缓存加锁并处理数据库忙状态。 |
| 页面交互 | `web_app/templates/**`、`static/app.css`、`services/ui_service.py`、`stock_history_query.py` | 修复指数/ETF 缺财务字段及空库 500；显式指数代码可查询，收盘线恢复；链接保留挂载前缀，错误提示不会被旧轮询覆盖；反向日期阻止提交，历史结论和旧统计明确标注。 |
| 发布与测试 | `gateway.py`、`deploy/gateway.py`、`deploy/stock-daily-full-retry`、`.gitattributes`、依赖文件、`pytest.ini`、`tests/**` | 兼容原 systemd 入口和两种原型路径；修正 full 重试判定；部署文件固定 LF；运行数据库移出 Git 但实际保留。补充合成回归、浏览器脚本测试及跨平台测试。 |

## 两个重要的前后变化示例

1. **防止未来信息影响研究**：高分股票次日不能买入时，旧流程可能先过滤它，再递补低分股票；现在先按信号日已知信息锁定 TopN，再记录是否成交。训练样本同样按真实标签结束日期隔离，不能跨入预测期。
2. **区分故障与有效空结果**：旧流程可能把接口失败、缺指数行情或缓存不完整解释成空候选甚至正常市场状态；现在关键依赖缺失会报错、停止判断或明确降级，页面也会显示原因。

## 验证与限制

以下是已经执行的验收记录，本次文档整理没有重新跑算法或生成收益结果：

- 全面修复后本地全量测试：997 passed、22 skipped；Node 页面脚本测试：5 passed。
- 初次上线的生产 Python 3.12 隔离测试：126 passed；11 个主要只读入口返回 200。
- 恢复原行情中转后：本地与生产相关测试各 40 passed、5 subtests passed；生产真实 `trade_cal` 查询成功。
- 实际 Chromium 验证了首页、股票/指数体检、短线筛选、长线翻页、雷达导航、日报、只读更新及解释失败提示。
- 未执行修复后的多年回测、全量模型训练或全量行情更新；接口连接成功不等于全部更新任务已成功跑完。
- 旧 clean store 缺少 `label_exit_date_3d/5d/8d` 时需重建。历史证券主数据和财务首次公告版本仍须有可验证来源；历史收益不会随代码更新自动变为有效的新结果。

逐项问题、文件范围与测试依据：

- [根目录算法修复](2026-09-07-algorithm-fixes.md)
- [研究脚本修复](2026-09-07-research-fixes.md)
- [浏览器问题修复](2026-09-07-browser-fixes.md)
- [发布验收](2026-09-07-release-validation.md)
- [原行情服务恢复](2026-09-07-legacy-relay-restoration.md)
