# 短线 v9 定板结论

更新日期：2026-06-04

## 结论

短线正式稳健基准定板为：

```text
scenario: profile_v4_adaptive_quality_v9_sector_quality_guard
factor_profile: profile_v9_sector_quality_guard
style_gate: adaptive_quality_v6
exit_profile: baseline
TopN: 固定 Top3
score_order: desc
```

实盘入口同步为：

```text
SHORT_LIVE_FACTOR_PROFILE = "profile_v9_sector_quality_guard"
SHORT_LIVE_STYLE_GATE = "adaptive_quality_v6"
SHORT_LIVE_SCORE_ORDER = "desc"
ENABLE_LONGTERM_LIVE = False
```

v6 保留为进攻型历史基准，可继续通过 `profile_v4_adaptive_quality_v6` 显式复跑。

## 对比结果

| 区间 | v6 | v9 | 判断 |
|---|---:|---:|---|
| 2024H1 | -14.79% | -14.79% | 持平，v9 IC 更好 |
| 2024H2 | +8.56% | +9.55% | v9 小胜 |
| 2024全年 | -7.50% | -6.65% | v9 小胜，胜率和夏普更好 |
| 2025全年 | +61.01% | +60.49% | v9 小输 |
| 2026Q1 | +1.93% | +4.99% | v9 明显胜 |

综合看，v9 牺牲了少量 2025 主升市进攻性，但在 2024 和 2026Q1 这种波动环境里表现更稳健。考虑未来实盘环境不一定持续类似 2025 主牛市，v9 更适合作为默认稳健基准。

## 为什么不做 v9.1

2025 v6 vs v9 的 trade diff 显示：

```text
v9 少买 5 笔：合计 -12.66%
v9 多买 4 笔：合计 -13.59%
替换差：-0.93%
```

v9 不是把赚钱票换没了，而是避开坏票后，替代票仍有少量质量问题。可疑样本包括结构极差、板块极低、放量过热或中深回撤的组合，但样本只有 4 笔，不足以支撑继续雕刻 v9.1。

因此本轮不再新增小样本保护规则，避免过拟合。

## 已归档实验

- v7 sector penalty：不升级，2025/2026Q1 没有稳定改善。
- v8 sector rank：板块信号有效，但 2024H2 回撤明显，不升级。
- v10 mid-deep drawdown guard：交易几乎不变，不升级。
- v11 mid-deep drawdown strict guard：仅边缘改善，不升级。

## 下一步

短线主线暂时定板，后续工作转向波段策略诊断：

- longterm_score 分布是否太窄；
- 赢家/输家在行业RS、财务、动量、回调位置上的差异；
- 高分低收益和低分高收益的错配样本；
- 是否需要重构波段评分权重或候选池过滤。
