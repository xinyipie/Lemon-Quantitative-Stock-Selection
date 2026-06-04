# 当前短线基准

更新日期：2026-06-04

## 定板版本

当前短线正式稳健基准已经定板：

```text
选股评分：profile_v9_sector_quality_guard
风格门控：adaptive_quality_v6
出场规则：baseline exit
排序方向：desc
推荐容量：固定 Top3
实盘入口：默认只跑短线，波段暂时关闭
```

对应代码配置：

```text
SHORT_LIVE_FACTOR_PROFILE = "profile_v9_sector_quality_guard"
SHORT_LIVE_STYLE_GATE = "adaptive_quality_v6"
SHORT_LIVE_SCORE_ORDER = "desc"
ENABLE_LONGTERM_LIVE = False
```

回测入口：

```text
python test.py --scenario profile_v4_adaptive_quality_v9_sector_quality_guard --exit-profile baseline
```

实盘入口：

```text
python main.py
```

v6 保留为进攻型历史基准，可通过 `profile_v4_adaptive_quality_v6` 显式复跑。

## 为什么从 v6 切到 v9

v9 的含义是：在 v6 已验证的 `profile_v4 + adaptive_quality_v6` 基础上，加入轻量板块质量保护。它不是大幅改权重，而是让强板块在量能不过热时小幅上提，让弱板块且放量过热的候选小幅降权。

跨区间结果：

| 区间 | v6 | v9 | 判断 |
|---|---:|---:|---|
| 2024H1 | -14.79% | -14.79% | 持平，v9 IC 更好 |
| 2024H2 | +8.56% | +9.55% | v9 小胜 |
| 2024全年 | -7.50% | -6.65% | v9 小胜，胜率和夏普更好 |
| 2025全年 | +61.01% | +60.49% | v9 小输 |
| 2026Q1 | +1.93% | +4.99% | v9 明显胜 |

结论：

- v6 在 2025 主升市略强，保留为进攻型历史基准。
- v9 在 2024 和 2026Q1 这种波动环境中更稳健。
- 2025 v9 仅小幅落后，且没有发现大规模替换失真。
- 综合未来实盘环境不一定持续主牛市，v9 更适合作为默认稳健基准。

## 推荐容量结论

短线默认保持固定 `Top3`，不升级为固定 `Top5` 或 `Top8`。

TopN 容量实验：

| 区间 | Top3 | Top5 | Top8 | 结论 |
|---|---:|---:|---:|---|
| 2024H2 | +8.56% | +4.20% | +2.85% | Top3 最稳 |
| 2025全年 | +61.01% | +44.68% | +23.39% | Top3 明显最好 |
| 2026Q1 | +1.93% | +5.21% | +3.10% | Top5 局部更好 |

解释：

- `Top8` 三段均不占优，后排候选质量下降明显。
- `Top5` 在 2026Q1 有价值，但在 2024H2 和 2025 全年拖累收益。
- 当前不做动态扩容，避免增加复杂度和过拟合风险。
- 默认固定 `Top3`，后续因子实验仍以 Top3 作为统一裁判。

## 出场规则结论

出场规则固定为 `baseline exit`：

```text
fallback_stop = -7.0%
fallback_profit = 15.0%
trailing_stop = 7.0%
trailing_activate = 3.0%
```

已验证过的出场实验：

| 出场版本 | 2026Q1 | 2025全年 | 结论 |
|---|---|---|---|
| baseline | +1.93%，回撤 3.84% | +61.01%，回撤 20.72% | 默认裁判 |
| exit_v1_mid_lock | Q1 更好 | 全年退化到 +26.68%，回撤升至 27.01% | 不升级 |
| exit_v1_profit_guard | Q1 更好 | 全年略差到 +46.18%，回撤更高 | 不升级 |
| exit_v2_conditional_lock | Q1 收益降到 +1.40% | 全年退化到 +34.12% | 不升级 |

结论：卖点优化已经进入边际收益低、过拟合风险高的阶段。后续实验固定 `baseline exit`，把收益变化主要归因于选股质量。

## 已归档短线实验

- v7 sector penalty：不升级，2025/2026Q1 没有稳定改善。
- v8 sector rank：板块信号有效，但 2024H2 回撤明显，不升级。
- v10 mid-deep drawdown guard：交易几乎不变，不升级。
- v11 mid-deep drawdown strict guard：仅边缘改善，不升级。

## 下一阶段目标

短线主线暂时定板，下一步转向波段策略诊断：

- longterm_score 分布是否太窄；
- 赢家/输家在行业RS、财务、动量、回调位置上的差异；
- 高分低收益和低分高收益的错配样本；
- 是否需要重构波段评分权重或候选池过滤。
