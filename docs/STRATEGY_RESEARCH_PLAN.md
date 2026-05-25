# 策略研究路线

更新时间：2026-05-25

目标：在当前短线主基准上继续提高选股质量，而不是继续调卖点。

## 当前主基准

短线主基准已经定板：

```text
profile_v4_adaptive_quality + baseline exit
```

代码含义：

- `factor_profile = profile_v4`
- `style_gate = adaptive_quality`
- `score_order = desc`
- 出场规则使用 baseline

验证结果：

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|
| score_desc 老基准 | 2026Q1 | 48 | 20.83% | -20.44% | -21.28% | 23.09% | -2.524 |
| profile_v4_adaptive_quality | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 |
| score_desc 老基准 | 2025全年 | 251 | 35.06% | -10.99% | -32.18% | 32.61% | -0.258 |
| profile_v4_adaptive_quality | 2025全年 | 155 | 43.87% | +48.87% | +27.68% | 20.72% | +1.459 |

## 关键认知

### 1. `weak_only` 是防守线索，不是全年主线

`weak_only` 在 2026Q1 表现最好，说明压力市里只做 `weak_momentum` 是有效防守。

但它在 2025 全年只有 +6.50%，说明全年常开会错过大量可赚钱机会。

### 2. `active + sideways` 是全年收益主力，但需要质量过滤

2025 全年中，`active + sideways` 是重要正向来源。

2026Q1 中，亏损集中在低质量 `active + sideways`，共同特征包括：

- 形态分偏低。
- 板块热度偏高。
- 回撤更深。
- 量能冲但结构不强。

`adaptive_quality` 的价值就是：压力环境中过滤掉这类票，正常环境保留高质量 `active + sideways`。

### 3. 卖点先封版

已验证多个出场实验：

- `exit_v1_mid_lock`
- `exit_v1_profit_guard`
- `exit_v2_conditional_lock`

这些实验在 Q1 有局部改善，但 2025 全年均不能超过 baseline。后续固定 `baseline exit`，避免把选股因子和卖点混在一起。

## 下一阶段：选股质量归因

下一轮实验不先改因子，而是做归因分析：

```text
factor_quality_attribution_v1
```

目标：

1. 固定当前主基准。
2. 固定 baseline exit。
3. 分析赚钱票和亏钱票的因子差异。
4. 找出下一刀最值得改的选股因子。

## 分析对象

至少覆盖两个区间：

- 2025 全年：`20250101~20251231`
- 2026Q1：`20260101~20260420`

至少拆分两类风格：

- `active + sideways`
- `weak_momentum`

## 优先观察字段

| 字段 | 关注点 |
|---|---|
| `factor_pattern` | 形态质量是否能区分好坏票 |
| `factor_wyckoff` | Wyckoff 是否仍有正向价值，还是在部分风格中反向 |
| `factor_volume_ratio` | 量能是温和确认还是冲高风险 |
| `factor_inflow` | 资金流是否应从加分变为硬过滤或排名 |
| `factor_sector` | 板块补涨是否过热 |
| `factor_drawdown` | 回撤得分是否奖励了过深回调 |
| `drawdown_from_high` | 距前高回撤是否需要分段处理 |
| `market_style` | 哪些风格应保留或禁用 |
| `macro_mode` | active/cautious 环境下因子方向是否不同 |
| `track_type` | 补涨/回调路径是否有明显差异 |

## 实验原则

- 一次只改一个主要变量。
- 每次同时看 2025 全年和 2026Q1。
- 固定出场规则，不在同一轮实验里改卖点。
- 优先看总收益、最大回撤、胜率、MFE、MAE、窗口期末收益。
- IC 作为辅助，不作为唯一标准。

## 推荐下一步

1. 新增或扩展归因脚本，输出当前主基准的因子质量报告。
2. 用最新主基准的 `trades_*.csv` 与 `ic_short_*.csv` 做赚钱/亏钱对比。
3. 根据归因结果选择第一轮因子实验。
4. 第一轮因子实验优先从候选池过滤或风格门控开始，不优先做小权重微调。
