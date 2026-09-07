# 历史版本复盘与上线准备审计（2026-07-07）

## 上线标准

- 真实退出交易数 >= 80。
- 总胜率 >= 65%，总收益 >= 250%。
- 亏损年份 <= 1，最差年份收益 >= -5%。
- 活跃年份 >= 9，单一年份交易占比 <= 45%。
- 近年（2023, 2024, 2025, 2026H1）胜率 >= 60%。

## 候选审计 Top8

| candidate                          | status        |   trades |   win_rate |   total_ret |   positive_years |   loss_years |   worst_year |   active_years |   recent_win_rate |   max_year_trade_share | blockers     |
|:-----------------------------------|:--------------|---------:|-----------:|------------:|-----------------:|-------------:|-------------:|---------------:|------------------:|-----------------------:|:-------------|
| candidate_b_bear_heat_plus_weak_t5 | research_only |       87 |      66.67 |      328.65 |                6 |            3 |        -3.08 |              9 |             73.68 |                  39.08 | loss_years>1 |
| union_top_3                        | research_only |       87 |      66.67 |      328.65 |                6 |            3 |        -3.08 |              9 |             73.68 |                  39.08 | loss_years>1 |
| union_top_4                        | research_only |       87 |      66.67 |      328.65 |                6 |            3 |        -3.08 |              9 |             73.68 |                  39.08 | loss_years>1 |
| union_top_5                        | research_only |       87 |      66.67 |      328.65 |                6 |            3 |        -3.08 |              9 |             73.68 |                  39.08 | loss_years>1 |
| union_top_6                        | research_only |       87 |      66.67 |      328.65 |                6 |            3 |        -3.08 |              9 |             73.68 |                  39.08 | loss_years>1 |
| union_top_7                        | research_only |       87 |      66.67 |      328.65 |                6 |            3 |        -3.08 |              9 |             73.68 |                  39.08 | loss_years>1 |
| union_top_8                        | research_only |       87 |      66.67 |      328.65 |                6 |            3 |        -3.08 |              9 |             73.68 |                  39.08 | loss_years>1 |
| union_top_9                        | research_only |       87 |      66.67 |      328.65 |                6 |            3 |        -3.08 |              9 |             73.68 |                  39.08 | loss_years>1 |

## 现阶段结论

- 小样本强版本（v35/v39/v39 类）优点是命中率极高，缺点是十年总笔数太少，不能直接解决稳定推荐问题。
- v45 的 T5 扩展在样本级好看，但真实退出后扩展层胜率只有约 35%，说明延迟买入不能只看5日后路径，必须有买入前确认和市场层过滤。
- 今晚的并集候选已经越过 `65% + 80笔` 的研究门槛，但按更严格上线标准仍是 `research_only`，主要问题是年度覆盖、亏损年份和 2025 集中度。
- 更值得继续打磨的方向是 `weak_momentum + 板块广度/强度 + T5不破位`，而不是泛候选池或单纯推迟到 T7。

## 当前最优候选：candidate_b_bear_heat_plus_weak_t5

### 分层

| candidate                          | candidate_layer   |   trades |   win_rate |   total_ret |   avg_ret |   avg_hold_days |   positive_years |   loss_years |   worst_year |
|:-----------------------------------|:------------------|---------:|-----------:|------------:|----------:|----------------:|-----------------:|-------------:|-------------:|
| candidate_b_bear_heat_plus_weak_t5 | expansion         |       60 |      56.67 |      137.67 |      2.29 |            5.70 |                6 |            3 |       -11.09 |
| candidate_b_bear_heat_plus_weak_t5 | strong_T1         |       27 |      88.89 |      190.98 |      7.07 |            6.37 |                5 |            0 |         8.01 |

### 年度

| candidate                          | year   |   trades |   win_rate |   total_ret |   avg_ret |   avg_hold_days |   positive_years |   loss_years |   worst_year |
|:-----------------------------------|:-------|---------:|-----------:|------------:|----------:|----------------:|-----------------:|-------------:|-------------:|
| candidate_b_bear_heat_plus_weak_t5 | 2016   |        1 |     100.00 |        4.69 |      4.69 |            8.00 |                1 |            0 |         4.69 |
| candidate_b_bear_heat_plus_weak_t5 | 2017   |        7 |      42.86 |       -0.46 |     -0.07 |            5.43 |                0 |            1 |        -0.46 |
| candidate_b_bear_heat_plus_weak_t5 | 2020   |       10 |      30.00 |       -3.08 |     -0.31 |            5.00 |                0 |            1 |        -3.08 |
| candidate_b_bear_heat_plus_weak_t5 | 2021   |        9 |      77.78 |       36.15 |      4.02 |            6.22 |                1 |            0 |        36.15 |
| candidate_b_bear_heat_plus_weak_t5 | 2022   |        3 |      66.67 |        5.03 |      1.68 |            8.00 |                1 |            0 |         5.03 |
| candidate_b_bear_heat_plus_weak_t5 | 2023   |        1 |       0.00 |       -2.17 |     -2.17 |            5.00 |                0 |            1 |        -2.17 |
| candidate_b_bear_heat_plus_weak_t5 | 2024   |       14 |      64.29 |       25.76 |      1.84 |            5.43 |                1 |            0 |        25.76 |
| candidate_b_bear_heat_plus_weak_t5 | 2025   |       34 |      79.41 |      201.74 |      5.93 |            6.24 |                1 |            0 |       201.74 |
| candidate_b_bear_heat_plus_weak_t5 | 2026H1 |        8 |      75.00 |       60.99 |      7.62 |            5.62 |                1 |            0 |        60.99 |

### 亏损退出分布

| year   | exit_reason       |   losses |   total_ret |   avg_ret |
|:-------|:------------------|---------:|------------:|----------:|
| 2017   | time_stop_dynamic |        2 |       -6.24 |     -3.12 |
| 2017   | forced_close      |        1 |       -1.94 |     -1.94 |
| 2017   | hold_complete     |        1 |       -2.09 |     -2.09 |
| 2020   | time_stop_dynamic |        6 |      -18.68 |     -3.11 |
| 2020   | stop_loss         |        1 |       -7.36 |     -7.36 |
| 2021   | stop_loss         |        2 |      -14.72 |     -7.36 |
| 2022   | hold_complete     |        1 |       -5.69 |     -5.69 |
| 2023   | time_stop_dynamic |        1 |       -2.17 |     -2.17 |
| 2024   | time_stop_dynamic |        5 |      -29.39 |     -5.88 |
| 2025   | time_stop_dynamic |        4 |      -12.24 |     -3.06 |
| 2025   | stop_loss         |        1 |       -7.36 |     -7.36 |
| 2025   | trailing_stop     |        1 |       -2.89 |     -2.89 |
| 2025   | weak_close_exit   |        1 |       -0.07 |     -0.07 |
| 2026H1 | hold_complete     |        1 |       -0.89 |     -0.89 |
| 2026H1 | time_stop_dynamic |        1 |       -2.47 |     -2.47 |

## 下一步优化方向

1. 对 2020、2024、2016 的失败票做负样本共性过滤，优先减少弱年度损失。
2. 给扩展层增加年度稳健惩罚，不再只按总收益和总胜率排序。
3. 把候选策略做 walk-forward：用早期年份选规则，后续年份验证，压低过拟合风险。
4. 只有当候选从 `research_only` 变成 `ready`，才考虑写入线上正式版本。
