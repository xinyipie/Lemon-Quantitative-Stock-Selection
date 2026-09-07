# 十年历史策略第一档审计（2026-07-04）

## 目标

把已经跑过的历史版本和 v29-v39 共识版本放到同一把尺子下比较，先做“第一档”强策略筛选。这里不新增策略规则，只做证据层沉淀，避免继续被单一年份的漂亮结果带偏。

输入矩阵来自 `backtest_results/ten_year_strategy_matrix_*.csv`，输出：

- `reports/historical_strategy_audit_first_tier_20260704.csv`
- `reports/historical_strategy_audit_first_tier_20260704.md`
- `reports/historical_strategy_audit_first_tier_20260704.json`

本次合并后覆盖 29 个策略版本、255 条年度矩阵记录。

## 档位规则

- `main_candidate`：交易数达到主线门槛、活跃年份没有亏损、十年总收益为正、2025+2026H1 近端收益为正，且近端胜率和 3% 命中率不低于 70%。
- `high_confidence`：交易数低于主线门槛，但至少 4 个活跃年份，且收益、近端胜率、3% 命中率都干净。
- `watch_only`：总收益或近端收益还可以，但样本、胜率、年份稳定性或亏损年份不够主线资格。
- `reject`：总收益/近端收益为负，或防守年份表现明显不合格。

## 第一档榜单

| 排名 | 档位 | 策略 | 交易数 | 加权胜率 | 总收益 | 近端胜率 | 近端收益 | 3%命中 | 5%命中 | MAE | 最差年 | 分数 |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | main_candidate | `v35_consensus_cautious_high_pattern_top1_hold3` | 26 | 92.31% | +185.44% | 90.00% | +158.06% | 96.15% | 73.08% | -1.81% | +3.95% | 361.24 |
| 2 | main_candidate | `v34_consensus_cautious_down_friction_top1_hold3` | 24 | 91.67% | +180.98% | 89.47% | +154.01% | 95.83% | 75.00% | -1.87% | +3.95% | 357.34 |
| 3 | main_candidate | `v39_consensus_strong_rank_top1_hold3` | 23 | 95.65% | +165.73% | 94.12% | +138.35% | 100.00% | 73.91% | -1.61% | +3.95% | 356.73 |
| 4 | main_candidate | `v38_consensus_rank_protected_rerank_top1_hold3` | 23 | 95.65% | +170.54% | 94.45% | +143.76% | 95.65% | 69.57% | -1.70% | +11.21% | 347.16 |
| 5 | main_candidate | `v37_consensus_quality_rerank_top1_hold3` | 24 | 91.67% | +178.86% | 94.73% | +159.65% | 91.67% | 62.50% | -1.72% | +3.64% | 344.90 |
| 6 | main_candidate | `v39_consensus_strong_rank_top2_hold3` | 23 | 95.65% | +72.83% | 94.12% | +59.27% | 100.00% | 73.91% | -1.61% | +1.97% | 310.94 |
| 7 | main_candidate | `v35_consensus_cautious_high_pattern_top2_hold3` | 39 | 76.92% | +77.99% | 73.33% | +61.20% | 79.49% | 64.10% | -2.30% | +1.97% | 279.20 |
| 8 | main_candidate | `v34_consensus_cautious_down_friction_top2_hold3` | 37 | 75.68% | +75.92% | 72.41% | +59.32% | 78.38% | 64.86% | -2.36% | +1.97% | 274.61 |
| 9 | main_candidate | `v38_consensus_rank_protected_rerank_top2_hold3` | 38 | 76.32% | +76.02% | 73.33% | +61.20% | 78.95% | 63.16% | -2.36% | +2.78% | 266.04 |
| 10 | main_candidate | `v37_consensus_quality_rerank_top2_hold3` | 38 | 76.32% | +74.32% | 73.33% | +59.50% | 78.95% | 60.53% | -2.32% | +2.78% | 264.82 |
| 11 | main_candidate | `v36_consensus_snapshot_top_rule_top2_hold3` | 25 | 80.00% | +56.12% | 73.69% | +39.39% | 84.00% | 72.00% | -2.12% | +4.69% | 258.23 |
| 12 | high_confidence | `v36_consensus_snapshot_top_rule_top1_hold3` | 17 | 94.12% | +117.49% | 92.31% | +95.88% | 94.12% | 76.47% | -1.74% | +9.39% | 306.18 |

## 结论

当前第一档主线不是 v19/v27/v33，也不是交易最多的 v9，而是 v35 Top1。

v35 Top1 的核心优点是：交易数达到可用下限，十年活跃年份无亏损，2025+2026H1 近端收益和胜率都强，同时 3 日命中率很高。它比 v39 多 3 笔交易、总收益高约 19.71 个百分点；代价是胜率和 MAE 略差一点。

v39 Top1 更适合作为“宁可少推、别推坑”的高置信档：加权胜率 95.65%，3% 命中率 100%，MAE 更低，但交易数和总收益低于 v35。后续如果要上线双档，建议：

- 收益主线：`v35_consensus_cautious_high_pattern_top1_hold3`
- 高置信少推：`v39_consensus_strong_rank_top1_hold3`

v33/v30 这类版本虽然总收益不差，但因为存在亏损活跃年份，暂时只能观察，不能放进第一档主线。

## 下一步

第一档完成后，后续优化不应继续盲目新增小规则。更稳的方向是从 v35 与 v39 的差异样本里找可解释条件：v35 多出来但赚钱的票能不能被保留，v35 多出来但亏钱的票是否有跨年稳定风险特征。如果这个差异找不到稳定规律，就保留 v35/v39 双档，而不是继续为了少数样本过拟合。
