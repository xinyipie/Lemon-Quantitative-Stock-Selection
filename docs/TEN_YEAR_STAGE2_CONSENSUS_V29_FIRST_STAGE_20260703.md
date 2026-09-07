# v29 共识门第一档实现记录

## 范围

- 新增 research-only 参数：`python backtest_v2.py --mode short --consensus-profile v29 ...`
- 默认值仍为 `none`，不影响线上 `main.py` 和既有回测命令。
- v29 采用三条历史强路线投票：v19、v25、v27；候选股至少命中 2 条才允许进入 TopN。
- 已加入矩阵策略：`v29_consensus_top1_hold3`、`v29_consensus_top2_hold3`。

## Smoke

命令：

```bash
python backtest_v2.py --mode short --offline --start 20260101 --end 20260131 --no-timing --hold 3 --topn 1 --consensus-profile v29 --metrics-output reports\smoke_v29_consensus_202601.json
```

结果：

| 指标 | 数值 |
|---|---:|
| 交易数 | 2 |
| 胜率 | 100.0% |
| 总收益 | +16.58% |
| 平均费后收益 | +7.99% |
| 最大回撤 | 0.00% |
| 平均 MFE | +13.85% |
| 平均 MAE | -0.85% |
| Hit3 | 100.0% |
| Hit5 | 100.0% |

## 注意

这只是入口验证，不代表策略结论。下一步必须跑 2016~2026H1 的 Top1/Top2 全矩阵，确认它不是只在 2026 年 1 月这个窗口表现好。
