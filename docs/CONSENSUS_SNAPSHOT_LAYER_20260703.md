# 共识候选池快照层记录

## 目的

v30/v31 的正式矩阵验证说明：继续手工调一个阈值，然后完整跑十年日级选股，效率太低。

本轮新增一个可复用的候选池快照层，把 v19/v25/v27 三条历史强线的 IC 候选池重新门控后合并，后续规则搜索可以直接读快照，而不是每个规则都重跑 `backtest_v2.py`。

## 新增脚本

`research/consensus_snapshot_builder.py`

默认输入：

```bash
reports/stage1_metric_ic_map_v19_v25_v27.csv
```

默认输出：

```bash
reports/consensus_snapshot_v19_v25_v27.csv
reports/consensus_snapshot_v19_v25_v27.json
```

本轮实际生成：

```bash
python research\consensus_snapshot_builder.py --input-map reports\stage1_metric_ic_map_v19_v25_v27.csv --output reports\consensus_snapshot_v19_v25_v27_20260703.csv
```

输出摘要：

```json
{
  "rows": 203,
  "dates": 134,
  "periods": ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026H1"],
  "vote_counts": {"1": 32, "2": 66, "3": 105}
}
```

## 快照口径

脚本不会直接合并原始 `ic_short` 文件，因为历史文档已经确认这些文件并不等于最终门控池。

正确流程是：

1. 从 `stage1_metric_ic_map_v19_v25_v27.csv` 找到每个强版本、每个年份的 `ic_short` 文件。
2. 按版本重新应用对应的评分和门控：
   - v19：`profile_v19_calm_followthrough` + `adaptive_quality_v19`
   - v25：`profile_v19_calm_followthrough` + `adaptive_quality_v25`
   - v27：`profile_v21_sector_calm_followthrough` + `adaptive_quality_v27`
3. 按 `period + select_date + ts_code` 聚合：
   - `consensus_votes`
   - `consensus_avg_rank`
   - `consensus_avg_score`
   - `consensus_profiles`
   - `consensus_score`
4. 保留可用于规则搜索的事前字段：
   - 市场热度：`limit_up_count`、`limit_down_count`、`limit_up_down_ratio`
   - 板块广度：`sector_ma10_ratio`
   - 入场状态：`change`、`volume_ratio`、`drawdown_from_high`
   - 个股因子：`factor_*`
5. 保留用于快速评估的结果字段：
   - `ret_3d`
   - `ret_5d`
   - `mfe_pct`
   - `mae_pct`

## 快速一致性检查

用快照近似评估 v29/v30/v31 的候选层表现，指标为固定 5 日收益，不替代正式回测。

| 规则 | 样本 | 日期 | 5日胜率 | 5日收益合计 | MFE | MAE | 近期样本 | 近期胜率 | 近期收益 | 2016收益 | 2023收益 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| snapshot_v29_top1 | 114 | 114 | 51.75% | +140.29% | +6.83% | -3.90% | 44 | 61.36% | +151.50% | -13.05% | -12.42% |
| snapshot_v29_top2 | 152 | 114 | 53.29% | +182.64% | +6.82% | -4.00% | 62 | 59.68% | +184.63% | -18.07% | -6.72% |
| snapshot_v30_top1 | 40 | 40 | 57.50% | +89.24% | +7.34% | -3.41% | 26 | 57.69% | +63.56% | +1.98% | +0.00% |
| snapshot_v30_top2 | 55 | 40 | 60.00% | +155.55% | +7.67% | -3.29% | 38 | 57.89% | +105.93% | +1.98% | +0.00% |
| snapshot_v31_top1 | 54 | 54 | 53.70% | +72.47% | +6.26% | -3.31% | 34 | 55.88% | +51.75% | +0.00% | -5.20% |
| snapshot_v31_top2 | 70 | 54 | 55.71% | +120.06% | +6.65% | -3.37% | 46 | 56.52% | +93.26% | +0.00% | -5.20% |

解释：
- 快照层和正式回测方向一致：v31 放宽后质量下降，2023 风险重新出现。
- v30 的防守更好，但覆盖率偏低。
- v29 覆盖更好，但 2016/2023 明显亏损。
- 固定 5 日收益低估了正式回测中退出规则的影响，不能直接当上线依据。

## 下一步

基于快照层写系统规则搜索脚本，而不是继续手工试 v32：

1. 输入：`reports/consensus_snapshot_v19_v25_v27_20260703.csv`
2. 枚举规则：
   - `consensus_votes` 下限
   - `limit_up_count` 分层
   - `sector_ma10_ratio` 分层
   - `change`、`volume_ratio`、`drawdown_from_high`
   - `factor_sector`、`factor_pattern`、`factor_wyckoff`
3. 排名目标：
   - 2025/2026H1 胜率和收益不能掉太多。
   - 2016/2022/2023 的亏损要显著小于 v29。
   - 交易数不能低于 v30 太多。
   - 平均 MAE 要下降。
4. 只有快照层进入候选的规则，才接入正式 `consensus_profile` 并跑完整矩阵。

当前状态：
- v19/v27 仍是强基准。
- v30 是强确认层。
- v31 是失败分支。
- 快照层已经可用，下一步进入系统规则搜索。
