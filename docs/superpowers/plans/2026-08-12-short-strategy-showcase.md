# 短线多策略展示实施计划

## 目标

在不改变正式量化选股和评分的前提下，将短线页升级为“全部策略、稳健共振、均衡观察、逆风修复”四个可切换入口，并保留每套策略独立的历史记录。

## 实施边界

- 正式策略继续使用 `profile_v9_sector_quality_guard` 与 `short_v9_final`。
- 观察策略继续使用 `short_live_observe_best_balance`。
- 逆风修复使用冻结 v16 研究记录，来源标记为 `research_shadow`，不进入正式推荐。
- AI 只负责解释，不参与评分、排序和入池。

## 改动

1. `web_app/services/signal_service.py`
   - 建立统一策略目录和策略身份映射。
   - 为每条短线信号附加展示元数据。
   - 同日同股只在同一策略内部去重，跨策略独立保留。
   - 生成四张策略概览卡的样本数、5 日正收益率和平均收益。
2. `web_app/app.py`
   - `/signals` 接受 `strategy` 参数。
   - 聚合正式、观察和影子研究三类记录，再按策略筛选。
   - 保持状态筛选、关键词、日期和行业筛选兼容。
3. `web_app/templates/signals.html`
   - 四张概览卡桌面端同排。
   - 增加小尺寸策略入口，浅色选中态。
   - 筛选、翻页和结果状态切换保留当前策略。
4. `web_app/templates/partials/short_strategy_selector.html`
   - 独立承载策略概览和策略入口，避免主模板继续膨胀。
5. `import_short_strategy_history.py`
   - 将冻结 v16 CSV 幂等导入现有信号库。
6. `tests/test_short_strategy_showcase.py`
   - 覆盖策略映射、跨策略不合并、统计和模板交互标记。

## 验证

- 运行 `python -m unittest tests.test_short_strategy_showcase`。
- 运行现有 `tests.test_web_services`。
- 使用浏览器验证四个策略入口、筛选、翻页和移动端布局。
- 部署后验证线上 `/signals?strategy=all|steady|balance|repair`。
