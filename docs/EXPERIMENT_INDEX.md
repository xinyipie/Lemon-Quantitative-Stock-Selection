# 实验索引

更新时间：2026-05-25

完整实验证据在 [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md)。本文件只保留导航和当前结论。

## 当前定板

| 项目 | 结论 |
|---|---|
| 主基准 | `profile_v4_adaptive_quality + baseline exit` |
| 实盘配置 | `SHORT_LIVE_FACTOR_PROFILE=profile_v4`，`SHORT_LIVE_STYLE_GATE=adaptive_quality` |
| 出场规则 | 保留 baseline，不升级 v1/v2 出场实验 |
| 下一阶段 | 固定卖点，优化选股质量 |

## 历史阶段

### 1. 项目接手与基线考古

目标：确认历史最优不是当前 HEAD v10.0，而是 v8/v4.1 一带的三风格短线骨架。

关键结论：

- 历史早期最优线索：2025 全年 +30.85%，178 笔。
- Git 版本控制建立较晚，不能直接信任 tag 名称。
- 需要用文档、回测产物和 2.0 备份交叉还原。

### 2. 重建基准 v1

结果：

| 区间 | 笔数 | 胜率 | 总收益 | 最大回撤 |
|---|---:|---:|---:|---:|
| 2025 全年 | 251 | 35.86% | -7.79% | 32.43% |
| 2026Q1 | 48 | 20.83% | -20.44% | 23.09% |

结论：没有复现历史最佳，评分方向或高权重因子存在问题。

### 3. 评分方向与路径质量实验

做过：

- `score_desc` vs `score_asc`
- `diagnostic_v1`
- `profile_v2`
- `profile_v3`

关键结论：

- 简单反向总分不稳健。
- 只看 5/10/20 日 IC 不够，短线更应看 MFE、MAE、窗口期末收益。
- `profile_v3` 证明路径质量方向有效，但 Q1 仍被 `sideways` 拖累。

### 4. 弱市防守与风格门控

做过：

- `profile_v4`
- `profile_v5`
- `weak_only`
- `weak_or_cautious_sideways`
- `adaptive_quality`

关键结果：

| 场景 | 2026Q1 | 2025全年 | 结论 |
|---|---:|---:|---|
| profile_v4 | -20.70% | +16.75% | 全年改善，Q1 不够防守 |
| profile_v4_weak_only | +1.93% | +6.50% | Q1 防守好，全年太保守 |
| profile_v4_adaptive_quality | +1.93% | +48.87% | 当前主基准 |

核心解释：

- Q1 中低质量 `active + sideways` 亏损严重。
- 2025 全年高质量 `active + sideways` 是主要收益来源。
- `adaptive_quality` 保留好的一边，过滤坏的一边。

### 5. 出场实验

做过：

- `exit_v1_tight_lock`
- `exit_v1_mid_lock`
- `exit_v1_profit_guard`
- `exit_v2_conditional_lock`

关键结果：

| 出场版本 | 2026Q1 | 2025全年 | 结论 |
|---|---:|---:|---|
| baseline | +1.93% | +48.87% | 当前默认 |
| exit_v1_mid_lock | +2.29% | +26.68% | 全年退化 |
| exit_v1_profit_guard | +2.76% | +46.18% | 接近但仍略差 |
| exit_v2_conditional_lock | +1.40% | +34.12% | 全年明显退化 |

结论：继续调卖点容易过拟合。后续固定 baseline exit。

## 下一轮实验

实验名：

```text
factor_quality_attribution_v1
```

目标：

- 不先改策略。
- 先分析当前主基准中赚钱票和亏钱票的因子差异。
- 分区间看 2025 全年和 2026Q1。
- 分风格看 `active + sideways` 和 `weak_momentum`。

优先观察字段：

- `factor_pattern`
- `factor_wyckoff`
- `factor_volume_ratio`
- `factor_inflow`
- `factor_sector`
- `factor_drawdown`
- `drawdown_from_high`
- `market_style`
- `macro_mode`
- `track_type`
