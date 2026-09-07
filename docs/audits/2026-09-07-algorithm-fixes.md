# 根目录算法审查修复映射（2026-09-07）

## 范围与验证口径

本次修复对应 `2026-09-07-live-strategy-review.md` 的 LS-01 至 LS-14，以及
`2026-09-07-root-auxiliary-review.md` 中有可复现证据的 RA 缺陷。修改限于根目录策略、
回测、统计和市场消息诊断模块；没有修改 `web_app/**`、`research/**`、部署文件或自动下单代码。

验证使用内存 DataFrame、临时文件和注入的假数据源。没有请求外部 API，没有运行多年回测、
模型训练或参数搜索。因此本报告确认的是时序、公式、数据契约和失败语义已修复，不代表历史收益已重新验证。

## 实盘策略与回测问题

| 编号 | 状态 | 修复后的行为 | 主要回归测试 |
|---|---|---|---|
| LS-01 | 已修复 | 指数行情缺失、样本不足或异常时返回 `DATA_UNAVAILABLE`/`data_unavailable`，仓位乘数为 0；应用市场门控的主流程停止选股。 | `test_market_regime_fails_closed_when_benchmark_is_missing`；`test_short_term_market_risk_fails_closed_when_an_index_is_missing` |
| LS-02 | 已修复 | 日内可成交止盈先于依赖收盘价的时间止损、弱收盘和动态到期退出；不再用更晚的收盘信息覆盖已发生的止盈。 | `test_intraday_take_profit_precedes_close_based_time_stop` |
| LS-03 | 已修复 | 已持有股票在涨停日可以按目标价卖出，不再依赖次日开盘；封死跌停的卖出等待逻辑保留。 | `test_limit_up_does_not_delay_a_shareholder_sell`；`test_limit_up_take_profit_executes_before_later_limit_down` |
| LS-04 | 已修复 | 批量 IC 按模式选择评分列：短线使用 `short_score`，长线使用 `longterm_score`；缺列或常数列按单实验记录 IC 不可用并继续批任务。 | `test_batch_ic_uses_mode_specific_nonconstant_score`；`test_batch_records_constant_score_as_ic_unavailable` |
| LS-05 | 已修复 | `use_market_timing=False` 会传入共享选股流程并跳过市场准入；短线和长线后置门控也使用同一开关。无择时分支统一用 `effective_multiplier` 计算 TopN，原始仓位乘数为 0 时不会再次清空纯因子候选。 | `test_backtest_passes_market_gate_choice_into_shared_selector`；`test_short_no_timing_keeps_candidates_when_regime_multiplier_is_zero`；`test_longterm_no_timing_does_not_reject_candidates_after_selection` |
| LS-06 | 已修复 | 批量回测显式区分 `official` 与 `pure-factor`。正式模式复用当前短线 profile、开盘过滤、持有期和长线最大持仓；纯因子模式显式关闭择时。 | `test_batch_official_mode_uses_live_profiles_and_execution_gates` |
| LS-07 | 已修复 | 胜负、胜率、平均盈亏、盈亏比、最大连亏和单笔极值统一按 `profit_after_fee`；毛收益另以 `gross_*` 字段展示。 | `test_performance_classification_uses_net_returns` |
| LS-08 | 已修复 | 长线观察压缩的 `lookback_days` 按真实日期差取窗，不再把稀疏扫描批次当作连续天数。 | `test_live_compression_lookback_is_calendar_days_not_scan_count` |
| LS-09 | 已修复 | 止损风险改为 `(close-stop)/close*100`，以入场价作为风险分母，所有复用该项的 profile 同步生效。 | `test_stop_risk_uses_entry_price_as_denominator` |
| LS-10 | 已修复 | 同一报告期存在多次公告时，先按 `ann_date` 选择截至评估日的最新版本，再进行跨报告期比较。 | `test_financial_versions_keep_latest_announcement_per_period` |
| LS-11 | 已修复 | 长线成交记录写入真实 `max_positions`；暴露审计优先使用该字段，缺失时必须显式提供参数，不再从已使用槽位推断容量。 | `test_longterm_exposure_requires_real_slot_count`；`test_longterm_exposure_refuses_to_infer_capacity_from_used_slots` |
| LS-12 | 已修复 | 观察名单年龄按实际日期运算，跨月和跨年不再用整数日期相减。 | `test_watchlist_age_uses_real_date_arithmetic` |
| LS-13 | 已修复 | IC 工具拒绝用已实现 `profit` 充当预测分数；没有有效评分列时明确报不可用，批处理跳过该文件并继续。 | `test_ic_refuses_realized_profit_as_a_score` |
| LS-14 | 已修复 | 缺少基准收益时输出“基准缺失”并保留超额收益为空，不再把绝对收益伪装成超额收益标签。 | `test_excess_winner_labels_are_unavailable_without_benchmark` |

## 根目录辅助模块问题

| 编号 | 状态 | 修复后的行为 | 主要回归测试 |
|---|---|---|---|
| RA-01 | 已修复 | 事件研究按主板、创业板/科创板、北交所及 ST 名称采用对应涨停阈值；历史行业和名称必须来自评估日精确 `stock_basic_history/YYYYMMDD.parquet` 快照。 | `test_event_study_uses_board_specific_limit_thresholds`；`test_event_study_requires_exact_historical_industry_snapshot` |
| RA-02 | 已修复确定缺陷；方法限制已披露 | 缓存损坏和样本不足显式失败；输出改为描述性事件统计，不再宣称已经证明可交易效应。对照组、盘口成交、费用和聚类显著性仍未实现，因此结果只能用于提出假设。 | RA-01 的时点测试及事件输入失败分支 |
| RA-03 | 已修复 | `analyze_trades.py` 可安全导入；按结果文件实际修改时间选择匹配实验，并正确映射 metrics JSON 与 trades CSV；收益优先使用扣费字段。 | `test_analyze_trades_selects_latest_matching_result`；`test_analyze_trades_maps_metrics_json_to_trades_csv` |
| RA-04 | 已修复 | 规则所需字段缺失时保持未知而非填 0 命中；候选键重复或交易缺少净收益字段时拒绝汇总。 | `test_rule_with_missing_required_fields_is_not_a_hit`；`test_rule_summary_rejects_duplicate_candidate_keys_and_missing_net_returns` |
| RA-05 | 已修复 | 历史板块诊断要求评估日精确证券主数据快照；股票行情必须与共同截面日一致，停牌旧行不混入当日截面。 | `test_sector_heat_rejects_stale_stock_rows_and_marks_missing_inputs`；`test_sector_history_uses_exact_basic_snapshot` |
| RA-06 | 已修复 | 缺行情基础指标、资金流或基准时仍允许诊断分数输出，但附带 `data_quality`、原因和数据日期，使缺失值与真实 0 可区分；未改变原有评分尺度。 | `test_sector_heat_marks_missing_benchmark_and_market_inputs_as_degraded` |
| RA-07 | 已修复 | 旧新闻接口回退也按评估日和 `days` 过滤；情绪分析去重标题，过滤未来、过期和不可解析日期，并返回使用数及降级原因。 | `test_old_news_fallback_filters_outside_requested_window`；`test_news_sentiment_deduplicates_titles_and_reports_bad_dates` |
| RA-08 | 已修复 | AI 行业加分仅接受已知行业；市场决策层再次校验行业集合并从校验后的加分重算总分，未知行业不能覆盖下跌市场模式。 | `test_sector_boosts_drop_unknown_ai_industries`；`test_market_decision_cannot_be_overridden_by_unknown_industry` |
| RA-09 | 已修复确定缺陷；方法口径已披露 | THS 概念事件按评估日和最大年龄过滤；主流程总是传评估日。独立诊断未传日期时以数据自身最新日为观察日。文档明确 `heat` 是当批横截面相对热度。 | `test_ths_concept_fallback_drops_stale_events`；既有 `test_concept_heat_provider.py` |
| RA-10 | 方法语义已明确 | 保留原有“新闻只对下跌状态提供正向政策覆盖”的不对称策略，不擅自改变策略方向；模块说明已明确该行为。RA-07/08 的时效和行业输入缺陷已单独修复。 | 行业覆盖验证测试 |
| RA-11 | 无生产修复 | `debug_guard.py`、`debug_guard2.py` 保持手工调试脚本分类，本次未运行。 | 不适用 |
| RA-12 | 无生产修复 | `test.py`、`test_timing.py` 保持实验/烟测驱动分类，输出不作为独立 holdout 证据，本次未运行。 | 不适用 |

## 验证结果与边界

- 专属算法与相关根目录回归：最终命令和通过数量记录在本次任务完成消息中。
- 所有修改文件执行 Python 语法编译检查；同时执行 `git diff --check` 检查补丁格式。
- 曾运行一次 `python -m pytest tests -q`，当时结果为 `967 passed, 22 skipped, 9 failed`。其中五项位于并行修改的 `research/**`，三项位于本任务明确不修改的 `web_app/**`；本范围内剩余的一项概念日期兼容失败已修复并单独回归通过。根任务仍需在并行变更收敛后执行最终全量测试。
- 未验证真实数据供应商响应格式、新闻延迟、集合竞价成交率、滑点及修复后的多年收益。任何上线收益结论仍需冻结配置后的新样本或合规的样本外验证。
