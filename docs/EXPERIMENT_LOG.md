# 实验记录

> 原则：每个策略实验只改一个主要变量；代码、命令、结果、结论一起提交。

## 当前治理基线

- 提交：`d78c28b docs: add project takeover and strategy research plan`
- 当前策略代码：HEAD 为 v10.0 方向，但历史最优线索是 v8.0 / 1A。
- 当前问题：5 月 9 日后回测引擎口径变化，导致新旧结果不可直接比较。

## 实验模板

复制以下模板新增记录。

```text
## YYYY-MM-DD 实验名称

### 假设

要验证什么？为什么它可能有效？

### 改动

- 文件：
- 主要逻辑：
- 是否只改了一个变量：

### 回测命令

python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 3
python backtest_v2.py --mode short --offline --start 20260101 --end 20260420 --no-timing --hold 8 --topn 3

### 结果

| 区间 | 笔数 | 胜率 | 总收益 | Alpha | Sharpe | 最大回撤 | 备注 |
|---|---:|---:|---:|---:|---:|---:|---|
| 2025 全年 |  |  |  |  |  |  |  |
| 2026Q1 |  |  |  |  |  |  |  |

### 结论

- 保留 / 回退 / 调参再测：
- 原因：
- 下一步：

### Git

- commit：
- 结果文件：
```

## 待验证队列

1. 重建真实最优基线：2.0/4.1 三风格骨架 + v8 板块补涨 + 固定 TopN 回测口径。
2. 复现历史最优结果：2025 全年 178 笔，收益 +30.85%，Alpha +9.66%。
3. v8 基线 + 1A 弱市无龙头清零。
4. 补涨板块内资金流硬过滤。
5. 同行业最多 1 只的分散约束。

## 2026-05-21 基线考古：真实最优不是 Git 标签

### 背景

用户提醒：Git 版本控制建立较晚，`85a81ef` 虽命名为 v8.0，但不一定等于真实历史最优 v8.0。因此不直接 `git restore 85a81ef`，改为根据历史文档、2.0 备份和回测产物交叉还原基线。

### 证据

历史最优结果集中在以下文件：

| metrics | 区间 | 笔数 | 胜率 | 总收益 | Alpha | Sharpe |
|---|---|---:|---:|---:|---:|---:|
| `metrics_20260427_165609.json` | 2025 全年 | 178 | 39.89% | +30.85% | +9.66% | 1.062 |
| `metrics_20260427_195147.json` | 2025 全年 | 178 | 39.89% | +30.85% | +9.66% | 1.062 |
| `metrics_20260428_210953.json` | 2025 全年 | 178 | 39.89% | +30.85% | +9.66% | 1.062 |
| `metrics_20260428_214904.json` | 2025 全年 | 178 | 39.89% | +30.85% | +9.66% | 1.062 |
| `metrics_20260428_221626.json` | 2025 全年 | 178 | 39.89% | +30.85% | +9.66% | 1.062 |

对应日志特征：

- 短线过滤日志仍显示 `v4.1短线过滤明细`。
- 同一轮日志中已出现 `板块补涨Top3`。
- 说明真实最优不是纯 v4.1，也不是后来的 v10.0，而是“v4.1 三风格候选池/评分骨架 + v8 板块补涨信号”。

2.0 备份特征：

- `select_stock_pool()` 是三风格模式：`momentum / weak_momentum / sideways`。
- `kline_ok` 是硬过滤。
- `volume_ratio_score`、`inflow_score`、`sector_score`、`wyckoff_score` 仍在综合评分中。
- `backtest_v2.py` 使用 `effective_top_n = top_n × position_multiplier`，不是分数门槛无限买入。
- 净值权重使用固定 `1/top_n`，不是 `1/n_bought` 动态满仓。
- 存在同股票冷静期和连续亏损暂停。

当前 HEAD 特征：

- `select_stock_pool()` 已是 v10.0 三因子补涨模型。
- 资金流降级为过滤器。
- 候选池统一放宽。
- 回测口径已切为分数门槛和动态权重。
- 与历史最优结果不可直接比较。

### 结论

下一步不直接回滚 Git 标签。应新建一个明确的“考古重建基线”：

- 策略：以 2.0 备份 / v4.1 三风格骨架为主体。
- 因子：加入 v8 板块补涨分，但不使用 v10 三因子重构。
- 回测：恢复固定 TopN、固定仓位权重、冷静期/连续亏损暂停口径。
- 目标：先复现 2025 全年 `178 / 39.89% / +30.85% / Alpha +9.66%`，再开始优化。

## 2026-05-23 重建基准 v1：三风格骨架 + v8 单日补涨 + 固定 TopN

### 假设

历史正向版本可能来自 2.0/4.1 三风格短线骨架，叠加 v8 板块补涨分，并使用固定 TopN / 固定 `1/top_n` 权重。

### 改动

- `main.py`：短线候选池恢复 momentum / weak_momentum / sideways 三风格硬过滤；板块补涨使用 v8 单日分，不启用 1A 时序乘数。
- `backtest_v2.py`：短线回测恢复固定 TopN；净值权重恢复固定 `1/top_n`；新增 `include_longterm=False`，短线回测不再执行波段模块。
- `config.py`：短线状态机门槛回到更接近历史基线的 55/60/72/999，Override 门槛 80/65。

### 回测命令

```text
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 3
python backtest_v2.py --mode short --offline --start 20260101 --end 20260420 --no-timing --hold 8 --topn 3
```

### 结果

| 区间 | 笔数 | 胜率 | 总收益 | Alpha | Sharpe | 最大回撤 | IC |
|---|---:|---:|---:|---:|---:|---:|---|
| 2025 全年 | 251 | 35.86% | -7.79% | -28.98% | -0.155 | 32.43% | 5d -0.142 / 10d -0.094 / 20d -0.065 |
| 2026-01-01~2026-04-20 | 48 | 20.83% | -20.44% | -21.28% | -2.524 | 23.09% | 5d -0.099 / 10d -0.147 / 20d -0.028 |

### 结论

- 该重建 v1 没有复现历史最佳 `178 / 39.89% / +30.85%`，因此不能作为最优基准。
- 负 IC 跨 2025 和 2026Q1 同时出现，说明当前评分排序方向或若干高权重因子可能反向。
- 下一步优先做因子贡献/反向排序验证：固定交易口径不动，只比较 `score` 正序、分因子排序、去掉板块共振中位数过滤后的效果。

### 结果文件

- `backtest_results/metrics_20260523_131234.json`
- `backtest_results/ic_short_20260523_131234.csv`
- `backtest_results/metrics_20260523_131623.json`
- `backtest_results/ic_short_20260523_131623.csv`

## 2026-05-23 回测算法改进：信号窗口质量层

### 背景

当前目标不是完全复现真实钱包，而是检查算法选出的股票在买入后窗口内是否有足够好的可交易涨幅。因此回测需要保留原有交易出场统计，同时新增一个不受仓位叠加、净值记账影响的信号质量视角。

### 改动

- `backtest_v2.py`：新增信号窗口质量统计，按 T+1 开盘买入价计算持有窗口内的最大上涨 MFE、最大下探 MAE、最好/最差收盘收益、窗口期末收益。
- 新增触及 3% / 5% / 10% 的比例，以及止盈价和止损价同日都被触及的歧义天数。
- 预取行情窗口从 `hold_days + 1` 扩到 `hold_days + 4`，覆盖交易逻辑最多延长 3 天的情况。
- 控制台、`metrics_*.json`、`trades_*.csv` 均输出信号窗口质量字段。

### 验证

```text
python -m py_compile backtest_v2.py
python backtest_v2.py --mode short --offline --start 20250101 --end 20250131 --no-timing --hold 8 --topn 3
```

### 结果

2025-01 样本共 3 笔交易：平均 MFE +6.88%，中位 MFE +6.91%，平均 MAE -0.88%，窗口期末均值 +2.82%；触及 3% / 5% / 10% 比例为 100.0% / 100.0% / 0.0%，止盈止损同日歧义 0 次。

### 结论

后续评估因子时，不能只看净值曲线和总收益；应同时比较 MFE、MAE、窗口期末收益、触及 3/5/10% 比例和同日歧义。这样更贴近“选股信号是否抓到可交易波动”的目标。

## 2026-05-23 实验开关：验证评分方向是否反向

### 背景

新增信号窗口质量后，标准回测显示当前候选股并非完全没有上涨空间：2025 全年触及 3% / 5% 的比例约为 64.5% / 48.6%。但 IC 明显为负，且 2025 五分位统计中低分组的 5日、10日、20日收益均优于高分组，说明问题优先怀疑在评分排序方向或高权重因子方向，而不是单纯的卖点。

### 改动

- `backtest_v2.py`：新增 `--score-order desc|asc`，默认 `desc` 保持原逻辑；`asc` 用于在同一候选池中低分优先买入。
- `test.py`：标准批测改为同时跑 `score_desc` 和 `score_asc` 两个场景，各自覆盖 2026Q1 与 2025 全年，并汇总信号窗口质量指标。

### 使用

```text
python test.py
```

也可以单独跑：

```text
python backtest_v2.py --mode short --offline --start 20250101 --end 20251231 --no-timing --hold 8 --topn 3 --score-order asc
```

### 判定

如果 `score_asc` 在胜率、平均 MFE、窗口期末收益、IC 高低分差上明显好于 `score_desc`，下一步应拆解并反转/降权当前评分中的问题因子；如果 `score_asc` 只改善局部年份，则继续按市场状态或风格拆分因子。

### 首轮结果

`score_asc` 在 2025 全年明显优于 `score_desc`，但在 2026Q1 明显变差：

| 场景 | 区间 | 胜率 | 总收益 | 平均MFE | 平均MAE | 窗口期末 |
|---|---|---:|---:|---:|---:|---:|
| score_desc | 2026Q1 | 20.83% | -20.44% | +9.19% | -7.64% | -0.51% |
| score_asc | 2026Q1 | 18.00% | -32.91% | +6.86% | -7.95% | -2.84% |
| score_desc | 2025全年 | 35.06% | -10.99% | +6.85% | -5.47% | -0.27% |
| score_asc | 2025全年 | 38.91% | +9.80% | +8.05% | -5.18% | +1.47% |

结论：不能简单把总分永久反向。更可能是部分子因子在不同市场状态或风格下方向不稳定。下一步需要输出子因子明细并计算子因子 IC。

## 2026-05-23 实验设施：输出短线子因子明细

### 改动

- `main.py`：短线候选池输出 `factor_volume_ratio`、`factor_drawdown`、`factor_inflow`、`factor_turnover`、`factor_sector`、`factor_pattern`、`factor_counter_trend`、`factor_wyckoff`、`factor_accel`、`score_base`、`market_style`、`macro_mode`。
- `backtest_v2.py`：逐笔交易 CSV 和 IC 明细 CSV 均保留上述字段。
- `test.py`：在 `test_result.json` 中新增 `factor_ic_10d`，用于快速判断各子因子的 10 日 IC、p 值、高低分组收益差。

### 目的

下一轮不再只比较总分正反排序，而是直接定位哪些子因子该正向保留、反向使用或降权。

## 2026-05-23 实验开关：diagnostic_v1 子因子重排

### 观察

子因子 10 日 IC 显示，总分在 2025 全年与 2026Q1 均为负，但子因子方向不一致：

- 2026Q1：资金流、换手率相对更有效；sideways 中资金流/换手率高低分差较大；weak_momentum 中板块因子明显有效。
- 2025 全年：momentum 与 sideways 中原总分明显反向；pattern 在全年略正向；sector、turnover、wyckoff 多数偏拖累。
- 因此不能简单永久反向总分，需要一个只在回测层生效的实验评分。

### 改动

- `backtest_v2.py`：新增 `--factor-profile original|diagnostic_v1`。
- `diagnostic_v1` 不改 `main.py` 实盘选股逻辑，只在回测阶段根据已导出的子因子重新计算 `experiment_score` 并排序。
- `test.py`：新增 `diagnostic_v1` 场景，与 `score_desc`、`score_asc` 同时比较。

### diagnostic_v1 思路

- momentum：原总分、板块热度、量比、Wyckoff 在历史上偏反向，因此以低原总分/低热度/低量比为主。
- weak_momentum：保留板块、回撤、换手率、资金流的正向贡献。
- sideways：更看重资金流和换手率，同时降低高板块热度、高形态分、高反压分、高 Wyckoff 分的排序权重。

### 下一步

运行 `python test.py` 后比较 `diagnostic_v1` 是否同时改善 2025 全年和 2026Q1。如果只改善单一年份，再继续拆分市场状态 profile。

## 2026-05-23 实验开关：profile_v2 专业短线分风格评分

### 设计原则

`profile_v2` 不直接拟合历史 IC，而是按 A 股短线交易逻辑把三类机会拆开评分：

- `momentum`：强势延续，重视资金流、浅回撤、适中放量、目标空间，避免高涨幅过热。
- `weak_momentum`：弱动量启动，重视资金流、2%~8% 回撤、量比 0.8~3.2 的温和放量、板块轮动和止损质量。
- `sideways/bear`：震荡补涨/熊市反弹，重视资金流、板块补涨、位置未过热、温和量能、目标空间和短止损。

### 改动

- `backtest_v2.py`：新增 `--factor-profile profile_v2`，仍然只在回测阶段重排候选池，不替换 `main.py` 实盘评分。
- 实验 profile 仅负责排序；候选准入仍沿用原始 `score >= score_threshold`，避免实验分数尺度不同导致交易频率失真。
- `test.py`：新增 `profile_v2` 场景，和 `score_desc`、`score_asc`、`diagnostic_v1` 同台比较。

### 验证方式

先用一周窗口冒烟，再跑标准双段：

```text
python backtest_v2.py --mode short --offline --start 20250102 --end 20250110 --no-timing --hold 8 --topn 3 --factor-profile profile_v2
python test.py
```

### 判定标准

优先看胜率、平均 MFE、平均 MAE、窗口期末收益、最大回撤；如果总收益提高但 MFE/MAE 变差，不视为有效策略。

## 2026-05-24 路径质量诊断基线

### 背景

新增候选池路径质量字段后，完整运行一次标准矩阵，确认各实验 profile 是否真的改善短线可交易路径。

### 回测命令

```text
python test.py
```

### 结果

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | 最大回撤 | MFE均值 | MAE均值 | 窗口期末 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| score_desc | 2026Q1 | 48 | 20.83% | -20.44% | 23.09% | 9.19% | -7.64% | -0.51% |
| score_desc | 2025全年 | 251 | 35.06% | -10.99% | 32.61% | 6.85% | -5.47% | -0.27% |
| score_asc | 2026Q1 | 50 | 18.00% | -32.91% | 33.59% | 6.86% | -7.95% | -2.84% |
| score_asc | 2025全年 | 257 | 38.91% | +9.80% | 20.49% | 8.05% | -5.18% | +1.47% |
| diagnostic_v1 | 2026Q1 | 46 | 23.91% | -25.09% | 31.98% | 8.44% | -8.18% | -1.38% |
| diagnostic_v1 | 2025全年 | 243 | 31.28% | -48.56% | 51.89% | 6.43% | -6.03% | -0.83% |
| profile_v2 | 2026Q1 | 46 | 15.22% | -37.87% | 39.52% | 5.48% | -8.89% | -3.94% |
| profile_v2 | 2025全年 | 251 | 37.85% | -16.17% | 28.23% | 7.45% | -5.42% | +0.36% |

### 结论

- `profile_v2` 不能作为下一版策略基线；它虽然让部分收盘收益 IC 转正，但实际交易路径明显恶化，尤其 2026Q1 的 MFE 低、MAE 高、窗口期末收益差。
- 2025 全年只有 `score_asc` 为正收益，但 2026Q1 失效，说明简单反向评分不稳健，不能直接上线。
- `score_base` 在两个区间对 MFE 和窗口期末收益多为负相关，高原始分不等于更好的短线可交易空间。
- 2026Q1 中 `factor_turnover` 对 MFE/窗口期末相对正向；2025 中 `factor_pattern` 对 MAE/窗口期末相对更友好。
- 下一步 `profile_v3` 应该按路径质量设计：优先高 MFE、低 MAE、窗口期末不塌，而不是只优化 5/10/20 日 close-to-close IC。

### Git

- commit：`1be6647 analysis: add candidate path quality diagnostics`
- 结果文件：`test_result.json`

## 2026-05-24 测试脚本提速

### 背景

旧版 `python test.py` 默认跑 4 个场景 x 2 个长区间，日常验证太慢。

### 改动

- `test.py` 新增 `argparse` 参数。
- 默认 `python test.py` 改为一周快测，只跑 `score_desc` 和 `profile_v2`。
- `--full` 跑标准长周期核心场景。
- `--matrix` 保留旧版完整矩阵。
- `--scenario`、`--start`、`--end` 支持指定场景和自定义区间。

### 新用法

```text
python test.py
python test.py --full
python test.py --matrix
python test.py --scenario profile_v2 --full
python test.py --start 20250101 --end 20250131 --scenario score_desc,profile_v2
```

### 验证

```text
python -m py_compile test.py
python test.py --help
```

### Git

- commit：`faa4d52 test: add fast and full run modes`

## 2026-05-24 实验开关：profile_v3 路径质量评分

### 假设

`profile_v2` 的问题是提高了部分 close-to-close IC，但真实交易路径变差。`profile_v3` 改为围绕路径质量排序：高 MFE、低 MAE、窗口期末不塌。

### 改动

- `backtest_v2.py`：新增 `--factor-profile profile_v3`。
- `profile_v3` 仍只在回测层重排候选池，不修改 `main.py` 实盘选股逻辑。
- 候选准入仍使用原始 `score >= score_threshold`，避免实验分数尺度污染交易频率。
- `test.py`：默认核心实验从 `score_desc/profile_v2` 改为 `score_desc/profile_v3`。

### profile_v3 思路

- 资金流保留为催化剂，但不盲目追极端流入。
- 量比和换手率使用甜区评分，惩罚异常放量。
- 提高形态稳定、合理止损距离、适中目标空间的权重。
- 降低 `score_base` 的正向影响，高原始分只给极低权重甚至轻微反向。
- 降低高 Wyckoff 的直接追高影响，避免“筹码漂亮但无人接力”。
- 对当日过热涨幅、止损距离过宽、极端量比做惩罚。

### 验证

```text
python -m py_compile backtest_v2.py test.py
python test.py --scenario score_desc,profile_v3 --start 20250102 --end 20250110 --label smoke_v3
```

### Smoke 结果

一周样本中 `score_desc` 与 `profile_v3` 选到同一批 3 笔交易，结果相同：胜率 100.0%，总收益 +2.99%，MFE 均值 +5.27%，MAE 均值 -0.88%，窗口期末 +2.58%。

### 下一步

需要运行标准长周期验证：

```text
python test.py --full --scenario score_desc,profile_v3
```

只有当 2025 全年和 2026Q1 同时在收益、MFE、MAE、窗口期末、最大回撤上改善，才考虑继续推进；否则说明排序层仍不足，应转向候选池层过滤。

### Full 结果

运行时间：2026-05-24 11:06:38

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | MFE均值 | MAE均值 | 窗口期末 | IC10 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| score_desc | 2026Q1 | 48 | 20.83% | -20.44% | -21.28% | 23.09% | 9.19% | -7.64% | -0.51% | -0.1468 |
| profile_v3 | 2026Q1 | 52 | 25.00% | -25.61% | -26.45% | 28.45% | 8.14% | -7.48% | -1.28% | +0.1163 |
| score_desc | 2025全年 | 251 | 35.06% | -10.99% | -32.18% | 32.61% | 6.85% | -5.47% | -0.27% | -0.0943 |
| profile_v3 | 2025全年 | 255 | 38.43% | +1.53% | -19.66% | 26.12% | 7.48% | -5.39% | +0.47% | +0.0789 |

风格拆分：

- 2025 全年：`profile_v3` 明显改善，收益从 -10.99% 到 +1.53%，最大回撤从 32.61% 降到 26.12%，IC10 从 -0.0943 转为 +0.0789。
- 2026Q1：`profile_v3` 胜率提高，但收益和回撤变差。主要拖累来自 `sideways`：33 笔，均收益 -2.06%，窗口期末 -4.16%；`weak_momentum` 反而较好：16 笔，均收益 +0.75%，窗口期末 +2.93%。
- `momentum` 在两个区间都偏弱，后续应继续降权或只在明确强势市场启用。

结论：

- `profile_v3` 证明“路径质量排序”方向有效，但不是可上线基线。
- 下一步不应推翻 v3，而应做防守版：弱市/不确定市降低 `sideways` 和 `momentum` 暴露，优先 `weak_momentum`，再验证 `score_desc` vs 防守版 profile。

## 2026-05-24 实验开关：profile_v4 弱市防守版

### 假设

`profile_v3` 在 2025 全年有效，但 2026Q1 被 `sideways` 风格拖累。`profile_v4` 不推翻 v3 的路径质量排序，只增加防守门控：弱市/不确定市压低 `sideways` 与 `momentum`，优先 `weak_momentum`。

### 改动

- `backtest_v2.py`：新增 `--factor-profile profile_v4`。
- `profile_v4` 继承 `profile_v3` 的路径评分。
- `macro_mode=cautious` 时：
  - `weak_momentum` 乘数提高并加基础分；
  - `sideways` 大幅降权；
  - `momentum` 大幅降权；
  - 对宽止损、深回撤、非 weak_momentum 的弱当日表现追加惩罚。
- `test.py`：默认核心实验从 `score_desc/profile_v3` 改为 `score_desc/profile_v4`。

### 验证

```text
python -m py_compile backtest_v2.py test.py
python test.py --scenario score_desc,profile_v4 --start 20250102 --end 20250110 --label smoke_v4
```

### Smoke 结果

一周样本中 `score_desc` 与 `profile_v4` 选到同一批 3 笔交易，结果相同：胜率 100.0%，总收益 +2.99%，MFE 均值 +5.27%，MAE 均值 -0.88%，窗口期末 +2.58%。

### 下一步

运行标准长周期验证：

```text
python test.py --full --scenario score_desc,profile_v4
```

判定目标：保留 `profile_v3` 在 2025 全年的改善，同时修复 2026Q1 的收益和回撤恶化。

### Full 结果

运行时间：2026-05-24 12:08:56

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | MFE均值 | MAE均值 | 窗口期末 | IC10 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| score_desc | 2026Q1 | 48 | 20.83% | -20.44% | -21.28% | 23.09% | 9.19% | -7.64% | -0.51% | -0.1468 |
| profile_v4 | 2026Q1 | 49 | 26.53% | -20.70% | -21.54% | 23.72% | 8.47% | -7.05% | -0.71% | +0.3300 |
| score_desc | 2025全年 | 251 | 35.06% | -10.99% | -32.18% | 32.61% | 6.85% | -5.47% | -0.27% | -0.0943 |
| profile_v4 | 2025全年 | 257 | 38.91% | +16.75% | -4.44% | 23.87% | 7.68% | -5.31% | +0.68% | +0.0585 |

风格拆分：

- 2025 全年：`profile_v4` 大幅优于 `score_desc`，总收益 +16.75%，最大回撤 23.87%，IC10 转正，路径质量改善。
- 2026Q1：`profile_v4` 修复了 `profile_v3` 的大幅恶化，但仍略输 `score_desc`。它改善了胜率、MAE 和触及 3/5/10% 比例，但总收益、回撤、窗口期末略差。
- 2026Q1 剩余拖累来自 `active + sideways`：8 笔，胜率 0%，均收益 -4.18%，窗口期末 -5.16%。说明只靠 `macro_mode=cautious` 防守不够，弱市中的 `active sideways` 也需要识别。
- `weak_momentum` 仍是最稳的正向线索：2026Q1 16 笔，胜率 50.00%，均收益 +0.75%，窗口期末 +2.93%。

结论：

- `profile_v4` 是当前最强候选新基准，但还不能替代基准上线，因为 2026Q1 没有超过 `score_desc`。
- 下一步应做 `profile_v5`：保留 v4 的 2025 改善，同时针对弱市场 `sideways` 暴露加更细的风险门控。门控条件不能只用 `macro_mode`，还要结合 `market_style`、`today_chg`、`drawdown_from_high`、止损距离和量能异常。

## 2026-05-24 实验开关：profile_v5 sideways 风险门控

### 假设

`profile_v4` 已经证明路径质量 + 弱市防守方向有效，但 2026Q1 仍略输基准。交易拆分显示剩余问题集中在 `active + sideways`：8 笔全亏，均收益 -4.18%，窗口期末 -5.16%。这些票的共同特征是形态分偏低、板块热度偏高、回撤得分过高，像是弱市场中的低质量补涨。

### 改动

- `backtest_v2.py`：新增 `--factor-profile profile_v5`。
- `profile_v5` 继承 `profile_v4`。
- 对 `sideways` 追加风险门控：
  - 形态分低于 45 扣分；
  - 板块因子高于 55 扣分，避免弱市追热板块后排；
  - 回撤得分过高扣分，避免过深回调的低质量补涨；
  - `macro_mode=active` 但 `pattern<45` 且 `sector>50` 时额外扣分；
  - `active + sideways` 且量比过高时额外扣分。
- `test.py`：默认核心实验从 `score_desc/profile_v4` 改为 `score_desc/profile_v5`。
- `SHORT_FACTOR_COLUMNS` 增加 `change`、`volume_ratio`、`drawdown_from_high`、`turnover`，方便后续交易明细诊断。

### 验证

```text
python -m py_compile backtest_v2.py test.py
python test.py --scenario score_desc,profile_v5 --start 20250102 --end 20250110 --label smoke_v5
```

### Smoke 结果

一周样本中 `score_desc` 与 `profile_v5` 选到同一批 3 笔交易，结果相同：胜率 100.0%，总收益 +2.99%，MFE 均值 +5.27%，MAE 均值 -0.88%，窗口期末 +2.58%。

### 下一步

运行标准长周期验证：

```text
python test.py --full --scenario score_desc,profile_v5
```

判定目标：保持 `profile_v4` 的 2025 全年优势，同时让 2026Q1 明确优于或至少不弱于 `score_desc`。

### Full 结果

运行时间：2026-05-24 15:32:07

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | MFE均值 | MAE均值 | 窗口期末 | IC10 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| score_desc | 2026Q1 | 48 | 20.83% | -20.44% | -21.28% | 23.09% | 9.19% | -7.64% | -0.51% | -0.1468 |
| profile_v5 | 2026Q1 | 48 | 22.92% | -26.30% | -27.14% | 29.11% | 8.26% | -7.40% | -0.93% | +0.3273 |
| score_desc | 2025全年 | 251 | 35.06% | -10.99% | -32.18% | 32.61% | 6.85% | -5.47% | -0.27% | -0.0943 |
| profile_v5 | 2025全年 | 256 | 38.67% | +15.44% | -5.75% | 23.03% | 7.82% | -5.41% | +0.73% | +0.0677 |

风格拆分：

- 2025 全年：`profile_v5` 仍显著优于 `score_desc`，但略弱于 `profile_v4`（+15.44% vs +16.75%）。
- 2026Q1：`profile_v5` 明显失败，总收益 -26.30%，最大回撤 29.11%，弱于 `score_desc` 和 `profile_v4`。
- `active + sideways` 仍未被解决：8 笔，胜率 0%，均收益 -4.18%，窗口期末 -5.16%。
- 新增门控还让 `cautious + sideways` 从 v4 的均收益 -0.78% 变成 -1.86%，说明该门控过粗，扣掉了部分可用票但没有避开核心亏损。
- `weak_momentum` 继续保持最好：2026Q1 16 笔，胜率 50.00%，均收益 +0.75%，窗口期末 +2.93%。

结论：

- `profile_v5` 不应继续作为候选基准；应回到 `profile_v4` 作为当前最强候选。
- 下一步不要继续粗暴惩罚 `sideways`，而应做更结构化的实验：
  1. 保留 `profile_v4` 评分；
  2. 新增可开关的风格门控实验，如 `--style-gate weak_only/weak_first/no_momentum`；
  3. 单独验证“弱市只买 weak_momentum”是否能修复 2026Q1，同时看是否牺牲 2025。

## 2026-05-24 工具改造：独立 style_gate 风格门控

### 目的

`profile_v5` 把评分和风格惩罚混在一起，导致变量不干净：IC 变好但交易结果更差。为避免继续用混合变量调参，本次把风格暴露控制从评分 profile 中拆出来，作为独立实验开关。

### 改动

- `backtest_v2.py`：新增 `--style-gate` 参数，只过滤候选池，不改评分公式。
- 支持门控：
  - `none`：不过滤；
  - `no_momentum`：排除 `momentum`；
  - `no_active_sideways`：排除 `macro_mode=active` 且 `market_style=sideways`；
  - `weak_only`：只保留 `weak_momentum`；
  - `weak_or_cautious_sideways`：保留 `weak_momentum` 或 `cautious + sideways`。
- `test.py`：默认核心场景回到 `score_desc/profile_v4`，不再默认跑失败的 `profile_v5`。
- `test.py` 新增场景：
  - `profile_v4_no_momentum`
  - `profile_v4_no_active_sideways`
  - `profile_v4_weak_only`
  - `profile_v4_weak_or_cautious_sideways`

### 验证

```text
python -m py_compile backtest_v2.py test.py
python test.py --scenario profile_v4_no_active_sideways --start 20250102 --end 20250110 --label smoke_style_gate
python test.py --scenario profile_v4 --start 20250102 --end 20250110 --label smoke_profile_v4
```

### Smoke 结果

- `profile_v4_no_active_sideways`：开关生效，日志显示 `style_gate=no_active_sideways` 并过滤候选；该一周样本无有效成交。
- `profile_v4`：3 笔，胜率 100.0%，总收益 +2.99%，Alpha +5.29%，MFE 均值 +5.27%，MAE 均值 -0.88%，窗口期末 +2.58%。

### 下一步

运行标准长周期门控矩阵：

```text
python test.py --full --scenario score_desc,profile_v4,profile_v4_no_active_sideways,profile_v4_weak_only,profile_v4_weak_or_cautious_sideways
```

判定目标：优先看 2026Q1 是否能明显减少亏损和回撤；同时要求 2025 全年不能大幅牺牲 `profile_v4` 已经取得的收益改善。

### 2026Q1 Gate 结果

运行时间：2026-05-24 16:55:07

```text
python test.py --scenario score_desc,profile_v4,profile_v4_no_active_sideways,profile_v4_weak_only,profile_v4_weak_or_cautious_sideways --start 20260101 --end 20260420 --label 2026Q1_gate
```

| 场景 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | MFE均值 | MAE均值 | 窗口期末 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| score_desc | 48 | 20.83% | -20.44% | -21.28% | 23.09% | -2.524 | 9.19% | -7.64% | -0.51% |
| profile_v4 | 49 | 26.53% | -20.70% | -21.54% | 23.72% | -3.251 | 8.47% | -7.05% | -0.71% |
| profile_v4_no_active_sideways | 41 | 31.71% | -10.30% | -11.15% | 14.14% | -1.719 | 9.22% | -6.71% | +0.16% |
| profile_v4_weak_only | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 | 11.05% | -4.64% | +2.93% |
| profile_v4_weak_or_cautious_sideways | 38 | 34.21% | -6.72% | -7.56% | 14.14% | -1.165 | 8.85% | -6.63% | -0.46% |

风格拆分：

- `profile_v4` 中 `active + sideways` 为 8 笔，胜率 0%，均收益 -4.18%；`active + momentum` 为 3 笔，胜率 0%，均收益 -3.49%。
- `no_active_sideways` 删除了核心亏损的 `active + sideways`，总收益从 -20.70% 改善到 -10.30%，但仍保留 3 笔亏损的 `momentum`。
- `weak_or_cautious_sideways` 同时删除 `active + sideways` 和 `momentum`，总收益改善到 -6.72%，但 `cautious + sideways` 仍有 22 笔，均收益 -0.78%，继续拖累。
- `weak_only` 只保留 `weak_momentum`，16 笔，胜率 50.00%，均收益 +0.75%，总收益 +1.93%，最大回撤降到 3.84%，是 Q1 唯一转正方案。

结论：

- Q1 的主要问题不是 `profile_v4` 排序完全失效，而是弱市/震荡环境中不该继续交易 `sideways` 和 `momentum`。
- `weak_only` 是当前最强 Q1 防守门控候选，但交易笔数从 49 降到 16，需要用 2025 全年确认它是否过度降频。
- 下一步只需跑 2025 全年确认，不必再全量跑所有门控。

建议验证命令：

```text
python test.py --scenario score_desc,profile_v4,profile_v4_weak_only,profile_v4_weak_or_cautious_sideways --start 20250101 --end 20251231 --label 2025_gate_confirm
```

### 2025 全年确认结果

运行时间：2026-05-24 17:47:19

```text
python test.py --scenario score_desc,profile_v4,profile_v4_weak_only,profile_v4_weak_or_cautious_sideways --start 20250101 --end 20251231 --label 2025_gate_confirm
```

| 场景 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | MFE均值 | MAE均值 | 窗口期末 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| score_desc | 251 | 35.06% | -10.99% | -32.18% | 32.61% | -0.258 | 6.85% | -5.47% | -0.27% |
| profile_v4 | 257 | 38.91% | +16.75% | -4.44% | 23.87% | +0.542 | 7.68% | -5.31% | +0.68% |
| profile_v4_weak_only | 72 | 37.50% | +6.50% | -14.69% | 18.26% | +0.312 | 7.70% | -5.02% | +0.03% |
| profile_v4_weak_or_cautious_sideways | 101 | 34.65% | +3.02% | -18.17% | 20.05% | +0.134 | 7.84% | -5.43% | +0.44% |

风格拆分：

- 2025 全年 `profile_v4` 仍是收益最强，说明不能把 `weak_only` 作为全年常开门控。
- `profile_v4` 中 `active + sideways` 为 123 笔，胜率 47.97%，均收益 +1.30%，是全年主要正向来源。
- `weak_only` 只保留 72 笔 `weak_momentum`，收益 +6.50%，回撤 18.26%，防守更好但牺牲了全年收益。
- `weak_or_cautious_sideways` 表现弱于 `weak_only`，说明 `cautious + sideways` 并不是必要补充。

对比 Q1：

- Q1 的 `active + sideways` 是 8 笔、均收益 -4.18%、MAE -8.79%、窗口期末 -5.16%。
- 2025 全年的 `active + sideways` 是 123 笔、均收益 +1.30%、MAE -4.94%、窗口期末 +1.26%。
- 因子均值差异显示 Q1 亏损版 `active + sideways` 形态更差、板块更热、回撤更深：`factor_pattern` 38.75 vs 51.44，`factor_sector` 56.75 vs 42.94，`drawdown_from_high` 9.00 vs 6.90。

结论：

- `profile_v4` 应保留为当前全年主基准。
- `weak_only` 应升级为“压力市防守门控”，而不是全年常开。
- 下一轮实验应做自适应门控：正常环境使用 `profile_v4`，当市场/候选特征进入压力状态时，只保留 `weak_momentum` 或强惩罚低形态、高板块热度、深回撤的 `sideways`。

## 2026-05-24 实验开关：profile_v4_adaptive_quality

### 假设

2026Q1 与 2025 全年的差异不是“所有 sideways 都坏”，而是低质量 sideways 在压力环境中亏损严重。Q1 亏损版 `active + sideways` 具有形态低、板块热、回撤深的共同特征；而 2025 全年的 `active + sideways` 是 `profile_v4` 的主要收益来源。

### 改动

- `backtest_v2.py` 新增 `--style-gate adaptive_quality`。
- `adaptive_quality` 保留：
  - `weak_momentum`；
  - `macro_mode=active` 且未触发低质量条件的 `sideways`。
- `adaptive_quality` 排除：
  - 所有 `momentum`；
  - 所有 `cautious + sideways`；
  - 低质量 `sideways`：`factor_pattern<45`，或形态偏低且板块偏热，或回撤偏深且板块偏热，或量比偏冲且形态不强。
- `test.py` 新增场景 `profile_v4_adaptive_quality`。

### 验证

```text
python -m py_compile backtest_v2.py test.py
python test.py --scenario profile_v4_adaptive_quality --start 20250102 --end 20250110 --label smoke_adaptive_quality
python test.py --scenario profile_v4_adaptive_quality --start 20260101 --end 20260420 --label 2026Q1_adaptive_quality_v2
```

### Q1 结果

| 场景 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | MFE均值 | MAE均值 | 窗口期末 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality | 16 | 50.00% | +1.93% | +1.09% | 3.84% | 11.05% | -4.64% | +2.93% |

结论：

- 收紧后的 `adaptive_quality` 在 2026Q1 与 `weak_only` 表现一致，说明 Q1 中没有 `active + sideways` 通过质量门槛。
- 下一步只需要跑 2025 全年单场景确认，看它是否能保留一部分 2025 赚钱的高质量 `active + sideways`：

```text
python test.py --scenario profile_v4_adaptive_quality --start 20250101 --end 20251231 --label 2025_adaptive_quality
```

### 2025 全年确认结果

运行时间：2026-05-24 18:44:40

```text
python test.py --scenario profile_v4_adaptive_quality --start 20250101 --end 20251231 --label 2025_adaptive_quality
```

| 场景 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | MFE均值 | MAE均值 | 窗口期末 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality | 155 | 43.87% | +48.87% | +27.68% | 20.72% | +1.459 | 8.37% | -4.96% | +1.12% |

对比此前确认集：

| 场景 | 笔数 | 胜率 | 总收益 | 最大回撤 |
|---|---:|---:|---:|---:|
| score_desc | 251 | 35.06% | -10.99% | 32.61% |
| profile_v4 | 257 | 38.91% | +16.75% | 23.87% |
| profile_v4_weak_only | 72 | 37.50% | +6.50% | 18.26% |
| profile_v4_adaptive_quality | 155 | 43.87% | +48.87% | 20.72% |

风格拆分：

- `active + sideways`：83 笔，胜率 49.40%，均收益 +1.66%，MFE 均值 +8.96%。
- `active + weak_momentum`：69 笔，胜率 36.23%，均收益 +0.67%，MFE 均值 +7.80%。
- `cautious + weak_momentum`：3 笔，胜率 66.67%，均收益 +1.18%。
- 已排除 `momentum` 与 `cautious + sideways`。

结论：

- `adaptive_quality` 成功保留 2025 全年赚钱的高质量 `active + sideways`，同时在 2026Q1 退化为近似 `weak_only` 防守。
- 当前短线最强候选基准应升级为 `profile_v4_adaptive_quality`。
- 下一步应运行标准双区间确认，并开始针对出场算法做诊断，尤其是止损 53 次、止盈 39 次、`take_profit_next_open` 均收益 +15.30%，说明部分票存在较强冲高能力，出场参数仍有优化空间。

## 2026-05-24 基准升级与交易诊断

### 改动

- `test.py` 默认核心场景从 `score_desc + profile_v4` 调整为 `score_desc + profile_v4_adaptive_quality`。
- `test.py` 增加逐笔交易诊断 `trade_diagnostics`，自动读取最新 `trades_*.csv` 并写入 `test_result.json`。
- 诊断字段包括：
  - 高 MFE 交易数、冲高后转亏数、高 MFE 转亏率；
  - 大回吐交易数、平均回吐；
  - 曾冲高 5% 以上但最终防守类出场的交易数；
  - 按 `exit_reason` 和 `market_style` 拆分的笔数、胜率、均收益、MFE、MAE、回吐。

### Smoke 验证

```text
python -m py_compile backtest_v2.py test.py
python test.py --scenario profile_v4_adaptive_quality --start 20250102 --end 20250110 --label smoke_trade_diag
```

结果：通过。`test_result.json` 已写入 `trades_file` 和 `trade_diagnostics`。

短样本结果仅用于验证诊断链路：

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | MFE均值 | MAE均值 | 平均回吐 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality | 20250102-20250110 | 2 | 100.00% | +1.06% | +3.36% | +4.46% | -1.32% | +2.50% |

### 下一步

下一轮不急着继续改因子，先用新的诊断字段跑标准双区间，判断问题主要来自：

- 选股质量不足：低 MFE、高 MAE；
- 出场过早：高 MFE 后大回吐或防守类出场；
- 止盈过钝：大量高 MFE 交易没有转化为最终收益。

确认后再做 `exit_profile_v1`，优先测试移动止损激活阈值、回撤阈值、止盈/次日开盘止盈逻辑。

## 2026-05-24 标准 full 验证：adaptive_quality 默认基准

### 命令

```text
python test.py --full
```

### 汇总

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | MFE均值 | MAE均值 | 10d IC | 高MFE转亏 | 大回吐 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| score_desc | 2026Q1 | 48 | 20.83% | -20.44% | -21.28% | 23.09% | -2.524 | 9.19% | -7.64% | -0.1468 | 9 | 11 |
| profile_v4_adaptive_quality | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 | 11.05% | -4.64% | +0.3300 | 3 | 6 |
| score_desc | 2025全年 | 251 | 35.06% | -10.99% | -32.18% | 32.61% | -0.258 | 6.85% | -5.47% | -0.0943 | 47 | 46 |
| profile_v4_adaptive_quality | 2025全年 | 155 | 43.87% | +48.87% | +27.68% | 20.72% | +1.459 | 8.37% | -4.96% | +0.0585 | 26 | 36 |

### 结论

- `profile_v4_adaptive_quality` 在 2026Q1 与 2025 全年均显著优于 `score_desc`，可以作为当前短线主基准。
- 2026Q1 从 `score_desc` 的 -20.44% 改善到 +1.93%，最大回撤从 23.09% 降到 3.84%。
- 2025 全年从 `score_desc` 的 -10.99% 改善到 +48.87%，最大回撤从 32.61% 降到 20.72%。
- 这说明风格门控有效，但不能说明选股已经最终最优；仍需做样本外验证与实盘入口一致性检查。

### 交易诊断

`profile_v4_adaptive_quality` 的出场诊断显示：

- 2026Q1：16 笔中 11 笔曾达到 5% 以上 MFE，3 笔高 MFE 后转亏，6 笔大回吐，平均回吐 10.30%。
- 2025 全年：155 笔中 88 笔曾达到 5% 以上 MFE，26 笔高 MFE 后转亏，36 笔大回吐，平均回吐 7.16%。
- `trailing_stop` 尤其值得检查：
  - 2026Q1：3 笔，MFE 均值 19.43%，最终均收益 -0.32%，平均回吐 19.75%。
  - 2025 全年：13 笔，MFE 均值 11.57%，最终均收益 -0.78%，平均回吐 12.35%。

### 下一步

优先做 `exit_profile_v1`，固定选股为 `profile_v4_adaptive_quality`，只测试出场参数，避免把选股和卖点问题混在一起。

建议实验方向：

- 收紧移动止损回撤阈值：例如从 7% 降到 4%-5%；
- 提高或分层移动止损激活阈值：避免刚浮盈就被噪声触发，但冲高后必须锁住更多利润；
- 检查 `take_profit` 与 `take_profit_next_open` 的成交假设；
- 保持因子不动，先确认收益改善是否来自更好的卖点。

## 2026-05-24 工具升级：exit-profile 出场实验

### 改动

`test.py` 新增 `--exit-profile`，用于在固定选股逻辑的前提下批量测试出场参数。

内置配置：

| exit_profile | fallback_stop | fallback_profit | trailing_stop | trailing_activate | 用途 |
|---|---:|---:|---:|---:|---|
| baseline | -7.0% | 15.0% | 7.0% | 3.0% | 当前基准 |
| exit_v1_tight_lock | -6.0% | 12.0% | 4.5% | 5.0% | 更早锁利润，减少高MFE回吐 |
| exit_v1_mid_lock | -6.0% | 15.0% | 5.0% | 6.0% | 中等锁利 |
| exit_v1_profit_guard | -6.0% | 18.0% | 4.0% | 8.0% | 允许更大冲高后再强锁利 |

用法示例：

```text
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v1_tight_lock --start 20250102 --end 20250110 --label smoke_exit_profile
python test.py --scenario profile_v4_adaptive_quality --exit-profile all --start 20260101 --end 20260420 --label 2026Q1_exit_v1
python test.py --scenario profile_v4_adaptive_quality --exit-profile all --start 20250101 --end 20251231 --label 2025_exit_v1
```

### Smoke 验证

```text
python -m py_compile test.py backtest_v2.py
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v1_tight_lock --start 20250102 --end 20250110 --label smoke_exit_profile
```

结果：通过。`test_result.json` 能区分不同 `exit_profile`，并记录对应 `exit_params`、`trades_file`、`trade_diagnostics`。

短样本中 baseline 与 `exit_v1_tight_lock` 结果相同，因为该区间只有 2 笔交易且均为 `hold_complete`，未触发出场参数差异。

## 2026-05-24 Q1 exit-profile 出场参数实验

### 命令

```text
python test.py --scenario profile_v4_adaptive_quality --exit-profile all --start 20260101 --end 20260420 --label 2026Q1_exit_v1
```

### 汇总

| exit_profile | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | 盈亏比 | 高MFE转亏 | 大回吐 | 平均回吐 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 | 1.35 | 3 | 6 | 10.30% |
| exit_v1_tight_lock | 16 | 50.00% | +2.07% | +1.23% | 3.22% | +0.648 | 1.42 | 3 | 8 | 10.29% |
| exit_v1_mid_lock | 16 | 50.00% | +2.29% | +1.45% | 2.12% | +0.764 | 1.45 | 3 | 8 | 10.25% |
| exit_v1_profit_guard | 16 | 43.75% | +2.76% | +1.92% | 2.95% | +0.794 | 1.88 | 4 | 7 | 10.16% |

### 观察

- 三个 exit-profile 在 2026Q1 都优于 baseline，但改进幅度不大，不能只凭 Q1 定版。
- `exit_v1_mid_lock` 最大回撤最低：2.12%，收益也高于 baseline。
- `exit_v1_profit_guard` 收益、Alpha、Sharpe 最高，但胜率降到 43.75%，高MFE转亏从 3 笔增到 4 笔。
- 出场实验没有改变 MFE/MAE/命中率，说明选股样本保持一致，差异确实来自卖点参数。

### 下一步

不建议继续在 Q1 上细调，避免过拟合。下一步用 2025 全年确认两个候选：

```text
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v1_mid_lock,exit_v1_profit_guard --start 20250101 --end 20251231 --label 2025_exit_v1_confirm
```

判断标准：

- 若 `exit_v1_profit_guard` 在 2025 仍提高收益且回撤不恶化，可作为进攻型出场基准；
- 若 `exit_v1_mid_lock` 在 2025 提高或接近收益且显著降低回撤，优先作为稳健型出场基准；
- 若两者在 2025 退化，则保留 baseline，说明 Q1 的出场优化可能只是小样本噪声。

## 2026-05-25 2025 exit-profile 全年确认

### 命令

```text
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v1_mid_lock,exit_v1_profit_guard --start 20250101 --end 20251231 --label 2025_exit_v1_confirm
```

### 汇总

| exit_profile | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | 盈亏比 | 高MFE转亏 | 大回吐 | 平均回吐 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 155 | 43.87% | +48.87% | +27.68% | 20.72% | +1.459 | 2.12 | 26 | 36 | 7.16% |
| exit_v1_mid_lock | 155 | 45.81% | +26.68% | +5.49% | 27.01% | +0.933 | 1.76 | 23 | 41 | 7.49% |
| exit_v1_profit_guard | 155 | 45.16% | +46.18% | +24.99% | 21.75% | +1.395 | 1.98 | 24 | 35 | 7.20% |

### 观察

- `exit_v1_mid_lock` 在 2025 全年明显退化：收益从 +48.87% 降到 +26.68%，最大回撤从 20.72% 升到 27.01%。
- `exit_v1_profit_guard` 接近 baseline，但仍略差：收益少 2.69pct，最大回撤高 1.03pct，Sharpe 低 0.064。
- 两个实验版本都改善了 `trailing_stop` 的单项表现：
  - baseline：13 笔，胜率 30.77%，均收益 -0.78%；
  - `exit_v1_mid_lock`：20 笔，胜率 100%，均收益 +3.38%；
  - `exit_v1_profit_guard`：15 笔，胜率 100%，均收益 +5.79%。
- 但整体收益没有提升，说明收益下降主要来自其他出场结构变化：`take_profit` 次数减少、止损/时间止损次数增加、部分原本能跑到更高止盈的票被提前处理。

### 结论

- 不升级 `exit_v1_mid_lock` 或 `exit_v1_profit_guard` 为默认出场基准。
- 当前短线主基准仍是：`profile_v4_adaptive_quality + baseline exit`。
- Q1 出场优化收益属于小样本局部改善，不能直接推广到全年。

### 下一步

下一轮不继续调全局出场参数，改为做更细的归因：

- 保留 baseline 出场；
- 分析 `trailing_stop` 亏损样本与 `take_profit` 高收益样本的共同特征；
- 若要优化出场，应做条件化出场，而不是统一收紧所有股票：
  - 只对高波动/高MFE/弱收盘结构启用更紧移动止损；
  - 对强趋势或次日开盘溢价较高的票保留 baseline 的宽松止盈空间。

## 2026-05-25 实盘入口一致性与归因工具

### 改动

- 新增 `strategy_profiles.py`，集中维护短线实验评分与风格门控：
  - `profile_v4` 等 factor profile；
  - `adaptive_quality` 等 style gate。
- `backtest_v2.py` 改为调用共享 profile/gate，避免后续回测逻辑与实盘逻辑分叉。
- `config.py` 新增短线实盘基准配置：
  - `SHORT_LIVE_FACTOR_PROFILE = "profile_v4"`；
  - `SHORT_LIVE_STYLE_GATE = "adaptive_quality"`；
  - `SHORT_LIVE_SCORE_ORDER = "desc"`。
- `main.py` 日常实盘报告入口在非离线回测时，会对短线候选池执行上述后处理，保证实盘报告使用当前主基准。
- `main.py` 写入 `data/live_selections.csv` 时，额外记录 `original_score`、`experiment_score`、`factor_profile`、`style_gate`，方便之后做实盘跟踪。
- 新增 `exit_attribution.py`，用于分析 baseline 交易中：
  - 高 MFE 后转亏；
  - 大回吐；
  - 坏的 `trailing_stop` 与好的 `take_profit` 样本差异。

### 验证

```text
python -m py_compile strategy_profiles.py backtest_v2.py main.py exit_attribution.py test.py
python exit_attribution.py --trades backtest_results/trades_20260524_233925.csv --top 5
python test.py --scenario profile_v4_adaptive_quality --start 20250102 --end 20250110 --label smoke_shared_profile
```

结果：

- 语法检查通过。
- `exit_attribution.py` 可正常读取逐笔交易并输出出场归因。
- 短回测 smoke 恢复为原结果：2 笔，胜率 100%，总收益 +1.06%，Alpha +3.36%。

### 归因初步发现

基于 2025 baseline 逐笔交易 `trades_20260524_233925.csv`：

- 坏的 `trailing_stop` 相比好的 `take_profit/take_profit_next_open`：
  - `factor_pattern` 更弱：55.18 vs 64.64；
  - `factor_wyckoff` 更弱：56.58 vs 72.87；
  - `factor_volume_ratio` 更弱：52.72 vs 68.47；
  - `factor_drawdown` 更极端：97.59 vs 72.50；
  - MAE 更深：-7.42% vs -2.15%。

这支持下一轮做条件化出场，而不是全局收紧：

- 对形态弱、Wyckoff弱、量能质量弱、回撤极端的高 MFE 票启用更紧锁利；
- 对结构强、资金/量能质量好的票继续保留 baseline 的宽松止盈空间。

## 2026-05-25 条件化出场 v2：弱质高MFE票锁利

### 假设

2025 baseline 归因显示，坏的 `trailing_stop` 样本相比好的 `take_profit` 样本，形态、Wyckoff、量能质量更弱，且回撤更极端。因此不再全局收紧出场，而是仅对已经有明显浮盈/MFE、同时结构质量偏弱的个股收紧移动止损。

### 改动

- `backtest_v2.py` 新增 `conditional_lock_enabled`、`conditional_lock_activation_pct`、`conditional_lock_trailing_pct` 参数。
- `BacktestV2._conditional_trailing_pct()` 根据 `factor_pattern`、`factor_wyckoff`、`factor_volume_ratio`、`factor_drawdown`、`drawdown_from_high` 判断是否收紧单笔移动止损。
- `_simulate_trade()` 在移动止损更新时传入选股日已知子因子；默认关闭时保持 baseline 行为不变。
- `backtest_v2.py` CLI 新增 `--conditional-lock`、`--conditional-lock-activation`、`--conditional-lock-trailing`。
- `test.py` 新增 `exit_v2_conditional_lock` 出场实验档位。
- 新增 `tests/test_conditional_exit.py`，覆盖弱质高浮盈收紧、强质保持 baseline、未达激活阈值保持 baseline。

### 验证

```text
python -m py_compile backtest_v2.py test.py tests\test_conditional_exit.py
python tests\test_conditional_exit.py
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20250102 --end 20250110 --label smoke_exit_v2
```

结果：

- 语法检查通过。
- 单元测试通过：3 tests OK。
- smoke 回测通过，`test_result.json` 写入 baseline 与 `exit_v2_conditional_lock` 两条结果。

### Smoke 结果

| exit_profile | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | 平均MFE | 平均MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 2 | 100.00% | +1.06% | +3.36% | 0.00% | 6.118 | +4.46% | -1.32% |
| exit_v2_conditional_lock | 2 | 100.00% | +1.06% | +3.36% | 0.00% | 6.118 | +4.46% | -1.32% |

### 结论

- 本轮只证明代码链路可用，不能证明策略优劣。
- smoke 样本没有触发移动止损，baseline 与 `exit_v2_conditional_lock` 相同是正常结果。
- 下一步需要跑 Q1 与 2025 全年确认：

```text
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20260101 --end 20260420 --label 2026Q1_exit_v2
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20250101 --end 20251231 --label 2025_exit_v2_confirm
```

### Q1 与 2025 全年确认

命令：

```text
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20260101 --end 20260420 --label 2026Q1_exit_v2
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20250101 --end 20251231 --label 2025_exit_v2_confirm
```

结果：

| 区间 | exit_profile | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | 高MFE转亏 | 大回吐 | 平均回吐 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026Q1 | baseline | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 | 3 | 6 | 10.30% |
| 2026Q1 | exit_v2_conditional_lock | 16 | 50.00% | +1.40% | +0.56% | 3.17% | +0.347 | 3 | 8 | 10.41% |
| 2025 全年 | baseline | 155 | 43.87% | +48.87% | +27.68% | 20.72% | +1.459 | 26 | 36 | 7.16% |
| 2025 全年 | exit_v2_conditional_lock | 155 | 45.81% | +34.12% | +12.93% | 20.72% | +1.154 | 23 | 39 | 7.38% |

观察：

- Q1 中 `exit_v2_conditional_lock` 降低最大回撤，但收益和 Sharpe 同时下降。
- 2025 全年中 `exit_v2_conditional_lock` 胜率略升、高 MFE 转亏略降，但总收益从 +48.87% 降到 +34.12%，且最大回撤没有改善。
- 逐笔变化显示，条件化锁利减少了部分亏损，但也把多笔原本能 `take_profit` 的交易提前卖掉，误伤收益更大。

结论：

- 不升级 `exit_v2_conditional_lock` 为默认出场。
- 当前短线基准正式定为 `profile_v4_adaptive_quality + baseline exit`。
- 后续固定 baseline exit，开始优化选股质量。

## 2026-05-26 选股因子实验：profile_v6 质量重排（未保留）

### 假设

交易诊断报告显示：

- `Q4_high` 最高分组并不是收益最好的分组，说明总分排序存在失真。
- 亏损票的 `factor_drawdown` 明显更高，说明高回撤风险票可能被排得过前。
- 赢家相对更强的字段包括 `factor_counter_trend`、`factor_sector`、`factor_pattern`。

因此尝试基于 `profile_v4` 做一版 `profile_v6`：轻微提高结构质量字段权重，并惩罚高 `drawdown_from_high`、高 `factor_drawdown` 且形态偏弱的候选。

### Q1 验证

命令：

```text
python test.py --scenario profile_v4_adaptive_quality,profile_v6_adaptive_quality --exit-profile baseline --start 20260101 --end 20260420 --label 2026Q1_v6_factor_tuned
```

结果：

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | 5日IC | 10日IC | 20日IC |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 | +0.2661 | +0.3300 | +0.4117 |
| profile_v6_adaptive_quality | 2026Q1 | 16 | 43.80% | -1.12% | -1.96% | 4.50% | -0.670 | +0.0408 | +0.0001 | -0.0326 |

观察：

- `profile_v6` 虽然试图压低高回撤风险票，但把原本在 Q1 有效的排序信号打散。
- Q1 总收益从 `+1.93%` 变成 `-1.12%`，Sharpe 从 `+0.458` 变成 `-0.670`。
- 5/10/20日 IC 基本失效，说明这不是单纯出场问题，而是选股排序本身被削弱。

结论：

- `profile_v6` 不进入可运行场景，也不跑 2025 全年。
- 这个方向说明：不要直接重写总分权重；下一步更适合做“高分风险票过滤/降级”，只处理极端坏样本，避免破坏整体排序。

## 2026-05-26 选股门控实验：adaptive_quality_v2

### 假设

`profile_v6` 失败说明不能直接重写总分权重。改用更保守的方式：保留 `profile_v4` 的排序，只在 `adaptive_quality` 门控后，额外剔除“实验分很高但风险特征明显”的候选。

风险特征：

- 形态质量（`factor_pattern`）偏弱；
- 距高点回撤（`drawdown_from_high`）偏深；
- 同时回撤位置得分（`factor_drawdown`）、板块位置/热度（`factor_sector`）或量比（`volume_ratio`）显示风险。

### 调试发现

第一版 `adaptive_quality_v2` 在 Q1 和 2025 全年结果完全不变。排查后发现不是场景没跑，而是门控判断“高分风险票”时使用了原始 `score`，而回测排序使用的是 `experiment_score`。

典型漏过滤样本：

| 股票 | 日期 | 原始总分 | profile_v4实验分 | 形态质量 | 回撤位置得分 | 距高点回撤 | 收益 |
|---|---|---:|---:|---:|---:|---:|---:|
| 国轩高科（002074.SZ） | 20250718 | 55.19 | 79.84 | 43.33 | 100.00 | 9.50 | -4.88% |

修复：`adaptive_quality_v2` 优先使用 `experiment_score` 判断高分风险票，没有该字段时再退回 `score` / `score_base`。

### 验证

命令：

```text
python test.py --scenario profile_v4_adaptive_quality,profile_v4_adaptive_quality_v2 --exit-profile baseline --start 20260101 --end 20260420 --label 2026Q1_gate_v2_fixed
python test.py --scenario profile_v4_adaptive_quality,profile_v4_adaptive_quality_v2 --exit-profile baseline --start 20250101 --end 20251231 --label 2025_gate_v2_fixed
```

结果：

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | 最大回撤 | Sharpe | 高MFE转亏 | 大回吐 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 | 3 | 6 |
| profile_v4_adaptive_quality_v2 | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | 3.84% | +0.458 | 3 | 6 |
| profile_v4_adaptive_quality | 2025全年 | 155 | 43.87% | +48.87% | +27.68% | 20.72% | +1.459 | 26 | 36 |
| profile_v4_adaptive_quality_v2 | 2025全年 | 154 | 44.16% | +51.40% | +30.21% | 20.72% | +1.526 | 26 | 36 |

观察：

- Q1 完全不变，说明新门控没有伤害压力样本。
- 2025 全年少交易 1 笔，收益从 +48.87% 提升到 +51.40%，Sharpe 从 +1.459 提升到 +1.526。
- 新门控剔除的实际交易是国轩高科（002074.SZ），该笔 `profit_after_fee=-4.88%`。
- 最大回撤、高 MFE 转亏、大回吐没有改善，说明本轮只是小幅剔除单笔坏样本，不是系统性风险改进。

结论：

- `adaptive_quality_v2` 是正向小补丁，但样本命中很少。
- 暂不替换实盘默认配置，先保留为候选实验场景。
- 下一步继续扩展规则命中诊断，优先找“命中 Top3 且亏损集中、误杀盈利少”的过滤条件。

## 2026-05-26 规则命中诊断：rerank_low_base_weak_pattern（不做硬过滤）

### 诊断发现

扩展 `rule_hit_diagnostics.py`，一次性比较多条候选规则。2025 全年候选池中，`rerank_low_base_weak_pattern` 命中情况最值得注意：

| 规则 | 中文含义 | 候选命中 | Top3命中 | 实际买入命中 | 命中交易胜率 | 命中交易合计收益 |
|---|---|---:|---:|---:|---:|---:|
| `rerank_low_base_weak_pattern` | 重排高分 + 基础分偏低 + 形态弱 | 62 | 36 | 19 | 31.58% | -9.37% |
| `high_score_drawdown_risk` | 高分 + 形态弱 + 回撤深 + 板块/量能偏风险 | 4 | 1 | 1 | 0.00% | -4.88% |

含义：

- `rerank_low_base_weak_pattern` 能抓到更多实际亏损交易，比单一高回撤风险规则样本更厚。
- 但它覆盖 19 笔实际买入，规则更宽，误杀风险也更高。

### Q1 硬过滤验证

尝试把该规则作为 `adaptive_quality_v3` 硬过滤：

```text
python test.py --scenario profile_v4_adaptive_quality,profile_v4_adaptive_quality_v3 --exit-profile baseline --start 20260101 --end 20260420 --label 2026Q1_gate_v3
```

结果：

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | Sharpe | 高MFE转亏 | 平均回吐 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | +0.458 | 3 | 10.30% |
| profile_v4_adaptive_quality_v3 | 2026Q1 | 16 | 43.75% | +0.54% | -0.31% | +0.062 | 4 | 11.68% |

结论：

- `adaptive_quality_v3` Q1 不通过，不保留为可运行门控。
- `rerank_low_base_weak_pattern` 保留在规则命中诊断工具中，用于观察和后续轻量降级研究。
- 下一步不应把它一刀切过滤，而应考虑更窄条件，或只作为候选风险提示。

## 2026-05-29 因子体检：先找稳定因子，再改 main

### 工具

新增 `factor_audit.py`，直接读取回测生成的 `ic_short_*.csv` 候选池，输出单因子体检和跨区间稳定性对比。

常用命令：

```text
python factor_audit.py --candidates backtest_results\ic_short_20260526_151120.csv --output reports\factor_audit_2025_gate_v2_fixed.md
python factor_audit.py --candidates backtest_results\ic_short_20260526_142319.csv --output reports\factor_audit_2026Q1_gate_v2_fixed.md
python factor_audit.py --candidates backtest_results\ic_short_20260526_151120.csv --compare backtest_results\ic_short_20260526_142319.csv --left-label 2025 --right-label 2026Q1 --output reports\factor_stability_2025_vs_2026Q1.md
```

### 体检结论

| 因子 | 中文名 | 2025 | 2026Q1 | 当前判断 |
|---|---|---|---|---|
| `score` | 重排短线分 | 越高越好 | 越高越好 | 可以作为主排序参考 |
| `factor_sector` | 板块位置/热度 | 越低越好 | 越低越好 | 板块过热可能是风险信号，适合继续做窄规则 |
| `original_score` | 原始总分 | 越低越好 | 越低越好 | 不应简单追原始高分，可作为反向诊断 |
| `score_base` | 基础总分 | 越低越好 | 越低越好 | 与原始总分类似，暂不做正向加权 |
| `factor_volume_ratio` | 量能质量 | 方向冲突 | 方向冲突 | 不做全局加权 |
| `volume_ratio` | 量比 | 方向冲突 | 方向冲突 | 不做全局加权 |

补充观察：

- 2025 中最值得研究的是原始总分、基础总分、重排短线分。
- 2026Q1 中最值得研究的是重排短线分、形态质量、距高点回撤。
- `factor_pattern` 在 Q1 看起来偏反向，但在 2025 不稳定，不能直接一刀切降低形态弱票。

### 下一步

- 暂时不动实盘默认 `main.py` 因子权重。
- 下一轮优先围绕“重排短线分高，但板块过热/原始分偏高/基础分偏高”的组合做规则命中诊断。
- 量能类因子先只做分市场状态观察，不做全局加权。

## 2026-06-02 选股降权实验：profile_v4_adaptive_quality_v4（不保留）

### 假设

尝试在 `profile_v4` 基础上做“风险降权”，不直接删除候选股，而是降低以下类型股票的排序：

- 重排短线分高，但原始/基础分偏高且板块偏热；
- 回撤偏深且形态不够强；
- 量比偏冲且板块偏热。

### 验证

命令：

```text
python test.py --scenario profile_v4_adaptive_quality,profile_v4_adaptive_quality_v4 --exit-profile baseline --start 20260101 --end 20260420 --label 2026Q1_gate_v4
python test.py --scenario profile_v4_adaptive_quality,profile_v4_adaptive_quality_v4 --exit-profile baseline --start 20250101 --end 20251231 --label 2025_gate_v4
```

结果：

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | Sharpe | 5日IC | 高低差 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | +0.458 | +0.2661 | +4.28% |
| profile_v4_adaptive_quality_v4 | 2026Q1 | 16 | 50.00% | +2.23% | +1.39% | +0.532 | +0.2671 | +4.24% |
| profile_v4_adaptive_quality | 2025全年 | 155 | 43.87% | +48.87% | +27.68% | +1.459 | +0.1630 | +2.30% |
| profile_v4_adaptive_quality_v4 | 2025全年 | 157 | 43.31% | +43.55% | +22.36% | +1.335 | +0.1640 | +2.50% |

### 交易差异

2025 全年中，v4 相比 baseline：

- 少买 3 笔，合计收益 `+9.47%`；
- 多买 5 笔，合计收益 `-1.58%`；
- 其中少买了两笔大赢家：润建股份 `+6.18%`、永鼎股份 `+8.17%`。

### 结论

- v4 在 Q1 小幅改善，但 2025 全年明显变差。
- 问题在于“板块偏热/基础分偏高”不能直接当作风险降权条件，会误伤强势行情中的赢家。
- 不保留 `profile_v4_adaptive_quality_v4` 作为可运行场景。
- 当前最好的候选仍是 `profile_v4_adaptive_quality_v2`：Q1 不变，2025 从 `+48.87%` 提升到 `+51.40%`。

### 工具补充

新增 `trade_diff_diagnostics.py`，用于自动比较两个回测交易文件：

- 实验少买了哪些票；
- 实验多买了哪些票；
- 少买部分合计收益、多买部分合计收益；
- 替换收益差是否为正。

复盘 v4：

```text
python trade_diff_diagnostics.py --base backtest_results\trades_20260602_191929.csv --experiment backtest_results\trades_20260602_192259.csv --output reports\trade_diff_2026Q1_gate_v4.md --top 10
python trade_diff_diagnostics.py --base backtest_results\trades_20260602_193448.csv --experiment backtest_results\trades_20260602_194442.csv --output reports\trade_diff_2025_gate_v4.md --top 10
```

结果：

| 区间 | 少买收益 | 多买收益 | 替换收益差 | 判断 |
|---|---:|---:|---:|---|
| 2026Q1 | +2.00% | +2.96% | +0.96% | 小幅正向 |
| 2025全年 | +9.47% | -1.58% | -11.05% | 明显负向 |

后续所有选股规则实验都应先看交易替换诊断，避免只看总收益而不知道收益从哪里来。

## 2026-06-02 选股门控实验：adaptive_quality_v5（当前最强候选）

### 假设

v4 的宽泛风险降权失败后，改为只验证更窄的“高分量比过冲”风险：

```text
score >= 70
volume_ratio >= 3.2
```

含义：

- 只处理已经排到较高位置的短线候选；
- 只过滤量比明显过冲的票；
- 不再把“板块热/基础分高”单独当作风险，避免误伤强势赢家。

### 规则命中诊断

命令：

```text
python rule_hit_diagnostics.py --candidates backtest_results\ic_short_20260602_193448.csv --trades backtest_results\trades_20260602_193448.csv --rule high_score_volume_spike --output reports\rule_hits_high_score_volume_spike_2025.md --top 20
python rule_hit_diagnostics.py --candidates backtest_results\ic_short_20260602_191929.csv --trades backtest_results\trades_20260602_191929.csv --rule high_score_volume_spike --output reports\rule_hits_high_score_volume_spike_2026Q1.md --top 20
```

结果：

| 区间 | 候选命中 | Top3命中 | 实际买入命中 | 命中交易收益 | 未命中交易收益 |
|---|---:|---:|---:|---:|---:|
| 2025全年 | 20 | 12 | 8 | -26.20% | +158.01% |
| 2026Q1 | 3 | 1 | 0 | 0.00% | +6.24% |

### 回测验证

命令：

```text
python test.py --scenario profile_v4_adaptive_quality,profile_v4_adaptive_quality_v2,profile_v4_adaptive_quality_v5 --exit-profile baseline --start 20250101 --end 20251231 --label 2025_gate_v5
python test.py --scenario profile_v4_adaptive_quality,profile_v4_adaptive_quality_v2,profile_v4_adaptive_quality_v5 --exit-profile baseline --start 20260101 --end 20260420 --label 2026Q1_gate_v5
```

结果：

| 场景 | 区间 | 笔数 | 胜率 | 总收益 | Alpha | Sharpe | 平均MFE | 窗口期末 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| profile_v4_adaptive_quality | 2025全年 | 155 | 43.87% | +48.87% | +27.68% | +1.459 | +8.37% | +1.12% |
| profile_v4_adaptive_quality_v2 | 2025全年 | 154 | 44.16% | +51.40% | +30.21% | +1.526 | +8.42% | +1.17% |
| profile_v4_adaptive_quality_v5 | 2025全年 | 152 | 45.39% | +62.03% | +40.84% | +1.753 | +8.81% | +1.39% |
| profile_v4_adaptive_quality | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | +0.458 | +11.05% | +2.93% |
| profile_v4_adaptive_quality_v2 | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | +0.458 | +11.05% | +2.93% |
| profile_v4_adaptive_quality_v5 | 2026Q1 | 16 | 50.00% | +1.93% | +1.09% | +0.458 | +11.05% | +2.93% |

### 交易替换诊断

命令：

```text
python trade_diff_diagnostics.py --base backtest_results\trades_20260602_205450.csv --experiment backtest_results\trades_20260602_210455.csv --output reports\trade_diff_2025_v2_vs_v5.md --top 20
python trade_diff_diagnostics.py --base backtest_results\trades_20260602_230639.csv --experiment backtest_results\trades_20260602_231007.csv --output reports\trade_diff_2026Q1_v2_vs_v5.md --top 20
```

结果：

| 对比 | 少买收益 | 多买收益 | 替换收益差 | 判断 |
|---|---:|---:|---:|---|
| 2025 v2 → v5 | -26.20% | -5.58% | +20.62% | 显著正向 |
| 2026Q1 v2 → v5 | 0.00% | 0.00% | 0.00% | 完全不变 |

### 结论

- `adaptive_quality_v5` 是当前最强候选版本。
- 它继承 v2 的极端风险过滤，并额外过滤“高分 + 量比过冲”。
- 2025 全年收益从 baseline `+48.87%`、v2 `+51.40%` 提升到 v5 `+62.03%`。
- Q1 与 baseline/v2 完全一致，没有伤害压力样本。
- 暂不直接切实盘默认，下一步应做月度拆分和更多区间稳定性验证，再决定是否定板。

## 2026-06-02 月度稳定性验证计划：adaptive_quality_v5

### 目的

v5 的全年收益明显变好，但全年汇总不能说明它是否稳定。下一步需要把 2025 拆成 12 个月，确认提升不是靠少数月份偶然贡献。

### 新增工具入口

`test.py` 新增 `--monthly YEAR` 参数，用来自动生成 1-12 月自然月区间。

示例：
```text
python test.py --monthly 2025 --scenario profile_v4_adaptive_quality_v2,profile_v4_adaptive_quality_v5 --exit-profile baseline
```

跑完后看 `test_result.json`，重点比较：
- v5 月度收益是否多数月份不弱于 v2；
- v5 是否只靠 1-2 个月拉高全年收益；
- v5 是否降低大亏月份的亏损；
- 交易笔数是否过少，避免样本太薄导致误判。

### 判断标准

- 如果 v5 在多数月份持平或更好，且没有新增明显大亏月份，可以进入“默认候选”阶段。
- 如果 v5 只靠少数月份大幅领先，其余月份普遍变差，则只保留为研究版本，不直接定板。

### 2025 月度结果

命令：
```text
python test.py --monthly 2025 --scenario profile_v4_adaptive_quality_v2,profile_v4_adaptive_quality_v5 --exit-profile baseline
```

对比 `profile_v4_adaptive_quality_v2`：

| 月份 | v2收益 | v5收益 | v5-v2 |
|---|---:|---:|---:|
| 2025M01 | +1.74% | +1.74% | +0.00% |
| 2025M02 | +4.76% | +6.21% | +1.45% |
| 2025M03 | -10.90% | -10.06% | +0.84% |
| 2025M04 | 无交易 | 无交易 | - |
| 2025M05 | -6.65% | -6.65% | +0.00% |
| 2025M06 | -4.83% | -4.31% | +0.52% |
| 2025M07 | +10.07% | +10.76% | +0.69% |
| 2025M08 | +32.75% | +32.75% | +0.00% |
| 2025M09 | +13.32% | +17.23% | +3.91% |
| 2025M10 | +7.33% | +7.43% | +0.10% |
| 2025M11 | -3.35% | -3.35% | +0.00% |
| 2025M12 | -1.51% | -0.69% | +0.82% |

汇总：
- 有交易月份 11 个；
- v5 优于 v2：7 个月；
- v5 持平 v2：4 个月；
- v5 弱于 v2：0 个月；
- 月度差值合计约 `+8.33%`。

结论：
- v5 的提升不是只靠某一个月份偶然拉高。
- v5 在亏损月份也有一定减亏效果，尤其 3 月、6 月、12 月。
- v5 可以从“研究候选”升级为“默认候选”，但正式替换实盘默认前还应补一次 2024 或 2026 后续区间验证。
