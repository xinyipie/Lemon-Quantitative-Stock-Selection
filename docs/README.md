# 文档入口

更新时间：2026-06-03

这个目录用于保存策略研究、版本治理和实验结论。新一轮工作先读下面三个文件即可，不需要从完整流水账里重新找线索。

## 当前必读

1. [CURRENT_BASELINE.md](CURRENT_BASELINE.md)
   - 当前短线定板版本。
   - 为什么选择 `profile_v4_adaptive_quality_v6 + baseline exit + fixed Top3`。
   - 买卖点后续如何用于选股工具。

2. [STRATEGY_RESEARCH_PLAN.md](STRATEGY_RESEARCH_PLAN.md)
   - 下一阶段研究路线。
   - 当前不再主攻卖点和推荐数量，转向短线因子优化。

3. [EXPERIMENT_INDEX.md](EXPERIMENT_INDEX.md)
   - 历史实验导航。
   - 快速查 `profile_v3/v4/v5/v6`、`weak_only/adaptive_quality`、TopN、出场实验 v1/v2 的结论。

## 证据流水

- [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md)：完整实验记录，保留全部证据链。
- [VERSION_CONTROL.md](VERSION_CONTROL.md)：每次实验一个提交的版本控制约定。
- [PROJECT_TAKEOVER.md](PROJECT_TAKEOVER.md)：项目早期接手备忘，部分结论已被当前基准更新。

## 约定

- 新实验先写进 `EXPERIMENT_LOG.md`，关键结论再同步到 `CURRENT_BASELINE.md` 或 `STRATEGY_RESEARCH_PLAN.md`。
- 回测产物默认不进 Git，结果写进文档。
- 下一阶段固定卖点为 `baseline exit`，避免把选股因子和卖点优化混在一起。
