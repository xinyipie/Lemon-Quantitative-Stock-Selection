# 混合延迟确认实验（2026-07-06）

## 研究假设

强信号（v35/v39 Top1）保持 T+1 开盘直接买；只有没有强信号的日期，才允许扩容层候选进入，并测试 T+2/T+3 延迟确认。该实验只研究选股/入场时点，不生成任何自动交易代码。

## 总览

| strategy                                     |   trades |   win_rate |   total_ret |   avg_ret |   hit3_rate |   avg_mae |   positive_years |   loss_years |
|:---------------------------------------------|---------:|-----------:|------------:|----------:|------------:|----------:|-----------------:|-------------:|
| hybrid_dynamic_T1_T3_T5_by_ticket            |       69 |      75.36 |      167.17 |      2.42 |       72.46 |     -2.27 |                9 |            1 |
| hybrid_strong_plus_wait_T3                   |       93 |      66.67 |      151.72 |      1.63 |       68.82 |     -2.63 |                9 |            1 |
| hybrid_strong_plus_wait_T2_no_preentry_break |       72 |      63.89 |      147.31 |      2.05 |       68.06 |     -2.46 |                8 |            1 |
| hybrid_strong_plus_wait_T3_no_preentry_break |       62 |      74.19 |      143.74 |      2.32 |       74.19 |     -2.27 |                9 |            1 |
| strong_direct_only                           |       28 |      96.43 |      129.55 |      4.63 |       89.29 |     -1.58 |                5 |            0 |

## 年度拆分

| strategy                                     | year   |   trades |   win_rate |   total_ret |   avg_ret |   hit3_rate |   avg_mae |   positive_years |   loss_years |
|:---------------------------------------------|:-------|---------:|-----------:|------------:|----------:|------------:|----------:|-----------------:|-------------:|
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2016   |       10 |      60.00 |       13.53 |      1.35 |       80.00 |     -2.74 |                1 |            0 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2017   |       10 |      60.00 |        7.10 |      0.71 |       50.00 |     -2.54 |                1 |            0 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2018   |        1 |     100.00 |        1.21 |      1.21 |      100.00 |     -0.74 |                1 |            0 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2019   |       11 |      63.64 |        3.26 |      0.30 |       63.64 |     -3.62 |                1 |            0 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2020   |        2 |     100.00 |       19.85 |      9.93 |       50.00 |     -1.27 |                1 |            0 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2021   |        3 |      66.67 |       -0.15 |     -0.05 |       33.33 |     -2.95 |                0 |            1 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2023   |        7 |      57.14 |       12.03 |      1.72 |       57.14 |     -1.89 |                1 |            0 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2024   |        3 |     100.00 |        6.92 |      2.31 |      100.00 |     -1.47 |                1 |            0 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2025   |       18 |      94.44 |       76.30 |      4.24 |       88.89 |     -1.67 |                1 |            0 |
| hybrid_dynamic_T1_T3_T5_by_ticket            | 2026H1 |        4 |     100.00 |       27.09 |      6.77 |      100.00 |     -0.96 |                1 |            0 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2016   |       10 |      50.00 |        9.73 |      0.97 |       60.00 |     -2.70 |                1 |            0 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2017   |       10 |      40.00 |       11.53 |      1.15 |       70.00 |     -2.15 |                1 |            0 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2019   |       12 |      41.67 |        6.28 |      0.52 |       58.33 |     -3.16 |                1 |            0 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2020   |        3 |      66.67 |       17.98 |      5.99 |       66.67 |     -2.03 |                1 |            0 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2021   |        2 |     100.00 |        1.34 |      0.67 |       50.00 |     -2.94 |                1 |            0 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2023   |        6 |      66.67 |       -0.56 |     -0.09 |       50.00 |     -2.53 |                0 |            1 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2024   |        4 |      75.00 |        1.94 |      0.49 |       75.00 |     -3.30 |                1 |            0 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2025   |       19 |      89.47 |       73.45 |      3.87 |       84.21 |     -1.77 |                1 |            0 |
| hybrid_strong_plus_wait_T2_no_preentry_break | 2026H1 |        6 |      66.67 |       25.61 |      4.27 |       66.67 |     -2.76 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2016   |       15 |      60.00 |       22.54 |      1.50 |       80.00 |     -2.39 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2017   |       11 |      63.64 |       10.24 |      0.93 |       54.55 |     -2.42 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2018   |        1 |     100.00 |        1.21 |      1.21 |      100.00 |     -0.74 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2019   |       12 |      58.33 |        6.45 |      0.54 |       66.67 |     -3.56 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2020   |        3 |      66.67 |       19.85 |      6.62 |       66.67 |     -1.34 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2021   |        5 |      60.00 |        4.24 |      0.85 |       60.00 |     -2.81 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2023   |       10 |      40.00 |       -4.78 |     -0.48 |       40.00 |     -3.09 |                0 |            1 |
| hybrid_strong_plus_wait_T3                   | 2024   |        6 |      66.67 |        0.96 |      0.16 |       83.33 |     -2.97 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2025   |       22 |      81.82 |       70.65 |      3.21 |       77.27 |     -1.96 |                1 |            0 |
| hybrid_strong_plus_wait_T3                   | 2026H1 |        8 |      87.50 |       20.37 |      2.55 |       75.00 |     -3.52 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2016   |        9 |      55.56 |        8.36 |      0.93 |       77.78 |     -2.74 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2017   |        9 |      55.56 |        0.38 |      0.04 |       44.44 |     -2.43 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2018   |        1 |     100.00 |        1.21 |      1.21 |      100.00 |     -0.74 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2019   |       10 |      50.00 |       -2.13 |     -0.21 |       60.00 |     -3.87 |                0 |            1 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2020   |        2 |     100.00 |       19.85 |      9.93 |       50.00 |     -1.27 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2021   |        2 |     100.00 |        1.34 |      0.67 |       50.00 |     -2.94 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2023   |        4 |      50.00 |        4.41 |      1.10 |       75.00 |     -2.04 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2024   |        3 |     100.00 |        6.92 |      2.31 |      100.00 |     -1.47 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2025   |       18 |      94.44 |       76.30 |      4.24 |       88.89 |     -1.67 |                1 |            0 |
| hybrid_strong_plus_wait_T3_no_preentry_break | 2026H1 |        4 |     100.00 |       27.09 |      6.77 |      100.00 |     -0.96 |                1 |            0 |
| strong_direct_only                           | 2020   |        1 |     100.00 |       17.89 |     17.89 |      100.00 |      0.00 |                1 |            0 |
| strong_direct_only                           | 2021   |        2 |     100.00 |        1.34 |      0.67 |       50.00 |     -2.94 |                1 |            0 |
| strong_direct_only                           | 2024   |        3 |     100.00 |        6.92 |      2.31 |      100.00 |     -1.47 |                1 |            0 |
| strong_direct_only                           | 2025   |       18 |      94.44 |       76.30 |      4.24 |       88.89 |     -1.67 |                1 |            0 |
| strong_direct_only                           | 2026H1 |        4 |     100.00 |       27.09 |      6.77 |      100.00 |     -0.96 |                1 |            0 |

## 解读

- 若 `hybrid_strong_plus_wait_T3` 笔数明显增加但胜率被拉低，说明扩容层还需要质量门，不宜直接补票。
- 若 `no_preentry_break` 版本胜率更高但笔数过少，说明入场前不破位可以当作确认因子，但不能单独解决交易数。
- 该结果仍属于历史研究，不能直接上线；下一步应放入完整十年回测引擎，复用真实退出规则和年度分段。
