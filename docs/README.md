# 文档入口

更新时间：2026-09-07

这个目录用于保存运行说明、策略研究、版本治理和验收记录。当前状态以最新代码修改总览和配置为准，旧实验文档保留当时的结论，不作为修复后的新收益证据。

## 当前必读

- [2026-09-07 修改总览](audits/2026-09-07-change-summary.md)：当前行情地址、短线/长线配置、前后端及算法修改、部署版本和验证边界。
- [原行情服务恢复](audits/2026-09-07-legacy-relay-restoration.md)：实际中转为 `http://14.nat0.cn:32817`，真实接口查询已验证成功。

1. [CURRENT_BASELINE.md](CURRENT_BASELINE.md)
   - 当前短线定板版本。
   - 当前 v9 评分、v39 强推荐与 best_balance 观察层，以及保留的历史选型依据。
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
