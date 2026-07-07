# 短线 T1/T3 观察层落地记录（2026-07-07）

## 目标

在不替换现有线上正式短线策略的前提下，给每日短线候选增加一层可复盘标签：

- `T1_BUY_CANDIDATE`：当前强度、形态、板块共振较完整，属于原策略正式候选里的即时观察对象。
- `T3_WAIT_CONFIRM`：形态和板块条件较好，但当前强度尚未完全确认，重点观察推荐后约 3 个交易日是否企稳。
- `NO_BUY_OBSERVE_ONLY`：只记录，不作为买入建议。

这版只做观察、记录和日报展示，不生成自动下单、自动交易或仓位执行代码。

## 规则来源

结合此前实验结论：

- `strong_T1` 适合保留为正式强候选观察口径。
- T3 确认优于机械 T5：T3 更接近“先跌几天再企稳”的修复路径。
- 延迟确认规则不能直接上线替换，需要先通过真实推荐日后的 T+1/T+3/T+5 表现做走查，避免过拟合。

## 当前实现

新增函数：

- `classify_short_entry_timing(stock_pool, trade_date)`
- `_short_entry_observation_reason(row, layer)`
- `_save_short_observation_log(trade_date, observation_pool)`

新增输出字段：

- `observation_date`
- `recommendation_layer`
- `entry_timing`
- `observation_action`
- `observation_reason`
- `observation_version`

落盘位置：

- 每日快照：`reports/live_observation/short_observation_YYYYMMDD.csv`
- 累积日志：`reports/live_observation/short_observation_log.csv`

日报展示：

- 每个短线 Top 候选新增「T1/T3观察层」小节。
- 明确标注“观察层只用于复盘验证，不是自动交易指令”。

## v1 判定

T1：

- `score >= 60`
- `factor_pattern >= 60`
- `factor_sector >= 30`
- `limit_down_count <= 4`
- `market_style in momentum / weak_momentum / sideways / 空`

T3：

- 不满足 T1
- `factor_pattern >= 50`
- `factor_sector >= 30`
- `sector_ma10_ratio >= 70`
- `limit_down_count <= 6`
- `macro_mode in active / cautious / 空`

其他：

- `NO_BUY_OBSERVE_ONLY`

## 下一步验证

1. 每天保留正式候选和观察层标签。
2. 用真实行情补齐每条记录的 T+1/T+3/T+5 最大涨幅、最大回撤、收盘收益。
3. 分组比较：
   - T1 当前买入是否优于整体短线候选。
   - T3 延迟确认是否能提升胜率和收益。
   - `NO_BUY_OBSERVE_ONLY` 是否确实低质，若反而表现好，回头修正规则。
4. 连续观察一段时间后，再决定是否把 T1/T3 规则变成正式筛选门，而不是现在就替换线上策略。

