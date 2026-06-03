# 当前短线基准

更新时间：2026-06-03

## 定板版本

当前短线主基准定为：

```text
选股评分：profile_v4
风格门控：adaptive_quality_v6
出场规则：baseline exit
排序方向：desc
```

对应代码配置：

```text
SHORT_LIVE_FACTOR_PROFILE = "profile_v4"
SHORT_LIVE_STYLE_GATE = "adaptive_quality_v6"
SHORT_LIVE_SCORE_ORDER = "desc"
```

回测入口：

```text
python test.py --scenario profile_v4_adaptive_quality_v6 --exit-profile baseline
```

## 为什么定板

这版是目前跨 2024H2、2025 全年和 2026Q1 后最均衡的短线默认候选。

| 版本 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality_v6 | 2024H2 | 20 | 40.00% | +8.56% | -4.58% | - | +0.835 |
| score_desc 老基准 | 2026Q1 | 48 | 20.83% | -20.44% | -21.28% | 23.09% | -2.524 |
| profile_v4_adaptive_quality_v6 | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 |
| score_desc 老基准 | 2025全年 | 251 | 35.06% | -10.99% | -32.18% | 32.61% | -0.258 |
| profile_v4_adaptive_quality_v6 | 2025全年 | 154 | 45.45% | +61.01% | +39.82% | 20.72% | +1.740 |

核心结论：

- `weak_only` 是 Q1 防守有效线索，但全年常开会过度降频，2025 全年只有 +6.50%。
- `active + sideways` 是 2025 全年主要收益来源，但在 Q1 的低质量样本会亏损严重。
- `adaptive_quality_v6` 将两者结合：压力环境下接近 `weak_only`，正常环境保留高质量 `active + sideways`，并额外过滤“高分 + 放量过冲 + 板块偏弱”的追高风险。

## 出场规则结论

出场规则定为 `baseline exit`：

```text
fallback_stop = -7.0%
fallback_profit = 15.0%
trailing_stop = 7.0%
trailing_activate = 3.0%
```

已经验证过的出场实验：

| 出场版本 | 2026Q1 | 2025全年 | 结论 |
|---|---|---|---|
| baseline | +1.93%，回撤 3.84% | +48.87%，回撤 20.72% | 当前默认 |
| exit_v1_mid_lock | Q1 更好 | 全年退化到 +26.68%，回撤升至 27.01% | 不升级 |
| exit_v1_profit_guard | Q1 更好 | 全年略差到 +46.18%，回撤更高 | 不升级 |
| exit_v2_conditional_lock | Q1 收益降到 +1.40% | 全年退化到 +34.12% | 不升级 |

结论：卖点优化已进入边际收益低、过拟合风险高的阶段。后续实验固定 `baseline exit`，把卖点作为统一裁判。

## 买卖点后续怎么用

后续不再把卖点作为主战场，但它仍然有两个用途：

1. 回测裁判  
   所有选股因子实验统一使用 `baseline exit`，这样结果变化主要来自选股质量。

2. 实盘提示  
   在持仓分析或自选股分析里展示风险信息，例如技术止损、目标价、高 MFE 回吐风险、弱结构盯盘提示。系统仍然只是辅助决策，不做自动交易。

## 下一阶段目标

从“调卖点”切换到“提高选股质量”。

下一步实验先做归因，不马上改因子：

```text
factor_quality_attribution_v1
```

目标：

- 比较 2025 全年赚钱票 vs 亏钱票。
- 比较 2026Q1 赚钱票 vs 亏钱票。
- 分别观察 `active + sideways` 和 `weak_momentum`。
- 找出第一批最值得调整的选股因子。
