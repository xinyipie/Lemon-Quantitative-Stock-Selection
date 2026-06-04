# 策略研究路线

更新时间：2026-06-04

## 当前状态

短线主线已经定板，不再继续小幅调参：

```text
scenario: profile_v4_adaptive_quality_v9_sector_quality_guard
factor_profile: profile_v9_sector_quality_guard
style_gate: adaptive_quality_v6
exit_profile: baseline
TopN: 固定 Top3
score_order: desc
```

v6 保留为进攻型历史基准，默认实盘使用 v9。

## 为什么短线封版

跨区间结果显示，v9 在 2024 和 2026Q1 这类波动环境更稳，2025 主升市仅小幅落后 v6：

| 区间 | v6 | v9 | 判断 |
|---|---:|---:|---|
| 2024H1 | -14.79% | -14.79% | 持平，v9 IC 更好 |
| 2024H2 | +8.56% | +9.55% | v9 小胜 |
| 2024全年 | -7.50% | -6.65% | v9 小胜 |
| 2025全年 | +61.01% | +60.49% | v9 小输 |
| 2026Q1 | +1.93% | +4.99% | v9 明显胜 |

后续短线只做维护和输出体验优化，不再新增 v9.1 之类的小样本规则。

## 下一阶段：波段策略

波段策略目前不是定板状态，且先发现了回测组合口径问题。核心问题是：

- 当前波段回测每天都可能新开 Top3，旧持仓不占用新开仓名额；
- 净值按每笔 `1/top_n` 固定权重计算，持仓重叠后名义暴露可能远超100%；
- `longterm_score` 是否真的能区分赢家和输家；
- 评分分布是否仍然偏窄或门槛过硬；
- 赢家/输家在行业 RS、资金流、财务、入场质量上的差异不清楚；
- 当前回测交易 CSV 缺少波段候选池五维因子明细，无法分析“没买到的好票”。

## 第一阶段目标（已开始落地）

先审计和修正回测组合口径，不直接拿旧备份收益当结论。

1. 已用现有 `trades_*.csv` 审计同时持仓、重复开仓和名义暴露。
2. 已定义可实盘执行的波段组合口径：最大同时持仓、禁止同一股票持有期重复开仓、单笔按最大持仓数分配组合权重。
3. 已在 `backtest_v2.py` 实现 `--max-positions`，默认 `15`。
4. 已让波段回测输出 `ic_longterm_*.csv` 候选池质量文件，包含五维评分、回撤位置、行业 RS 等字段。
5. 下一步用当前 v4.1 和 legacy_raw_score_v1 在新组合口径下重跑三段。
6. 再判断是否需要做候选池因子归因或权重实验。

新增工具：

```text
python longterm_trade_diagnostics.py --trades backtest_results/trades_longterm_全段_20260421_184335.csv --output reports/longterm_trade_diagnostics_all.md --title 波段全段交易诊断
python longterm_backtest_audit.py --trades backtest_results/trades_20260604_133234.csv --output reports/longterm_backtest_audit_2025_legacy_raw_v1.md --title "波段2025 legacy原始评分回测审计"
```

旧版评分复刻实验：

```text
python backtest_v2.py --mode longterm --offline --start 20240701 --end 20241231 --longterm-profile zscore_v4_1 --max-positions 15
python backtest_v2.py --mode longterm --offline --start 20250101 --end 20251231 --longterm-profile zscore_v4_1 --max-positions 15
python backtest_v2.py --mode longterm --offline --start 20260101 --end 20260420 --longterm-profile zscore_v4_1 --max-positions 15
python backtest_v2.py --mode longterm --offline --start 20240701 --end 20241231 --longterm-profile legacy_raw_score_v1 --max-positions 15
python backtest_v2.py --mode longterm --offline --start 20250101 --end 20251231 --longterm-profile legacy_raw_score_v1 --max-positions 15
python backtest_v2.py --mode longterm --offline --start 20260101 --end 20260420 --longterm-profile legacy_raw_score_v1 --max-positions 15
```

当前审计结论详见：

```text
docs/LONGTERM_BACKTEST_AUDIT.md
```

## 第二阶段目标

补充波段候选池诊断 CSV，类似短线 `ic_short_*.csv`，至少包含：

| 字段 | 用途 |
|---|---|
| `select_date` / `ts_code` | 按选股日复盘候选 |
| `longterm_score` | 评分有效性 |
| `score_momentum` | 动量贡献 |
| `score_flow` | 资金流贡献 |
| `score_rs` | 行业 RS 贡献 |
| `score_fin` | 财务贡献 |
| `score_entry` | 入场质量贡献 |
| `drawdown_from_high` | 回调位置 |
| `industry_rs` | 行业强度 |
| `forward_20d/40d/60d` 或路径指标 | 后续表现 |

只有拿到候选池明细后，才做波段 v5 权重实验。

## 实验原则

- 不和短线混跑，波段单独评估。
- 先固定当前波段 v4.1 作为基准。
- 优先看胜率、总收益、最大回撤、平均持有天数、退出原因。
- IC 作为辅助，不能只凭 IC 改权重。
- 一次只改一个主要变量。
