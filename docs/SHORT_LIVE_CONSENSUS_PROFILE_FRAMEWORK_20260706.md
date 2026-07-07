# 短线实盘双档框架（2026-07-06）

## 背景

十年第一档审计和 v35/v39 差异审计后，当前策略不适合继续为了少量样本硬做 v40。更稳的框架是保留两个可切换档位：

- 收益主线：`v35_consensus_cautious_high_pattern_top1_hold3`
- 高置信少推：`v39_consensus_strong_rank_top1_hold3`

本次只把共识档位接入实盘后处理入口，默认不切换线上策略。

## 配置方式

新增配置：

```python
SHORT_LIVE_CONSENSUS_PROFILE = "none"
```

可选值：

| 配置 | 含义 | 使用场景 |
|---|---|---|
| `none` | 保持当前 `SHORT_LIVE_FACTOR_PROFILE + SHORT_LIVE_STYLE_GATE` 路径 | 默认，不改变现在线上 |
| `v35` | 十年第一档收益主线 | 想提高收益弹性时 |
| `v39` | 高置信少推档 | 更在意少推坑票、3-5 日命中时 |

## 代码入口

新增函数：

- `strategy_profiles.apply_live_short_postprocess`

实盘入口：

- `main.run_daily_selection`

当 `SHORT_LIVE_CONSENSUS_PROFILE != "none"` 时，实盘候选会走 `build_consensus_candidates`，也就是和回测共用同一套 v35/v39 共识逻辑。默认 `none` 时仍走原来的 `apply_short_profile`，不改变当前线上行为。

## 当前建议

现在线上是否切换，需要单独决定：

- 保守上线：先把 `SHORT_LIVE_CONSENSUS_PROFILE` 设为 `v39`，观察实际每日是否经常空窗。
- 收益优先：设为 `v35`，对应十年第一档主线。
- 暂不切换：保持 `none`，只保留能力。

我的倾向：先用 `v39` 做高置信观察档，和当前线上推荐并排观察几天；如果空窗太多或错过明显收益，再切 `v35`。
