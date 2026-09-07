# 其余研究脚本与策略归档审查（2026-09-07）

## 范围与方法

- 审查范围：`research/` 下 107 个 Python 文件，包含 `strategy_archive/`。按委托要求排除 basename 为 `clean_*`、`build_clean*`、`audit_clean*` 的文件，以及 `point_in_time_financials.py`、`download_historical_financial_snapshots.py`、`validate_walkforward_excess_bagged_lcb.py`、`evaluate_locked_candidate_new_holdout.py`。
- 所有 107 个文件都做了全文件结构审读：入口、输入输出、顶层函数/类、收益字段、时间切分、参数搜索、排序键、费用和成交约束；高风险策略家族再沿调用关系精读。先用 CodeGraph 定位 `build_year_panel`、`walk_forward`、规则搜索、退出模拟和归档复现路径，再读当前源码。
- 没有修改研究代码，没有联网，没有执行长训练或大规模数据读取。只运行了内存 DataFrame/固定随机种子的最小复现和不触发数据下载的轻量函数。
- “未发现确定问题”只表示静态审查没有找到可复现缺陷，不等于策略有效。统计功效、数据源真实性和真实撮合仍需独立验证。

## 结论

当前范围内确认 **1 个严重未来泄漏、4 个高风险研究设计问题、4 个中风险口径/证据问题**。

最严重的是 `engine_multibucket_strategy_search.py` 在同日候选分数相同时，以真实未来收益 `ret` 作为第三排序键，直接改变入选股票。其次，基础研究面板把 T+1 开盘和跳空信息先用于候选过滤，然后才做 TopN；这会在第一名无法成交时事后补入第二名，夸大可执行收益。历史面板还对所有日期复用当前 `stock_basic.parquet` 的名称和行业，无法支持历史 ST、退市和行业的点时正确性。

规则搜索家族大多是同样本探索：在同一批历史收益上生成数千至数万规则、挑“最佳”、再将该结果用于 `ready` 或“目标通过”判断。它们可以用于提出假设，不能把最佳行当成未偏的样本外业绩。`t3_confirmation_walkforward_validation.py` 的实现尤其与报告文字不符：120 条规则全部进入测试期，之后按测试期胜率和收益排序。

质量动量和反转家族中，多数年度模型确实只用目标年份以前的数据训练；`no_future_signal_pipeline.py` 也提供了正确的“先锁信号，再执行”基准。`opportunity_archetype_*`、`flow_breadth_factor_research.py`、`regime_conditioned_opportunity_research.py` 等先在训练期定方向，再评估 validation/sealed，边界设计相对清楚。不过，一旦 validation/sealed 已参与通过判定或报告排序，它们就已被消费，不能继续称为新的独立 holdout。

`strategy_archive/` 是历史快照和隔离复现，**不是当前实盘实现**。归档中的旧 `main.py`、新闻/市场雷达、页面服务均不得据此判断当前策略状态。归档复现实验本身也明确披露静态基础表和非账户净值限制；本审查补充指出其收益仍是未扣成本的毛收益。

## 确定问题

### OR-01（严重）：组合搜索用未来收益打破同日并列，直接泄漏标签

**位置**：`research/engine_multibucket_strategy_search.py:292-293`、`:330-331`。

两处都按 `['select_date', score_col, 'ret', 'ts_code']` 排序后每日取第一名。`ret` 是 `BacktestV2` 生成的真实退出收益，不是入场时可见字段。当两个候选 `score_col` 相同，未来收益更高者必然被选中。其后的年度、胜率和总收益均受污染。

最小复现：同日 A、B 的 `hybrid_score` 都为 50，A 的未来收益 -5，B 为 +5。当前排序选 B；删除 `ret` 键后按可观测字段和代码稳定排序会选 A。

```text
RET_TIEBREAK leaky= ['B'] observable= ['A']
```

影响：该脚本输出的单/多桶“最佳组合”与依赖它的候选，不能作为有效回测证据。即使总体网格另做 holdout，这两行也必须先从信号选择路径移除后重算。

### OR-02（高）：T+1 可成交信息在 TopN 之前过滤，产生事后替补偏差

**根源位置**：

- `research/all_market_multi_engine_research.py:145-152` 生成 T+1 `entry_open`/`entry_gap_pct`；`:185-193` 把它们并入 `tradeable`；`:263` 写入面板；`:276` 又把 `tradeable` 放进各引擎公共候选门。
- `research/walkforward_linear_ranker.py:52-59` 和 `research/two_stage_walkforward_research.py:190-197` 在建模/TopN 前删除不可成交行。
- `research/quality_momentum_reentry.py:49-71` 还直接以未来 `entry_gap_pct` 限制候选。

策略口径是 T 日收盘出信号、T+1 开盘成交。T+1 开盘是否存在、跳空是否超限只能决定已锁定信号能否成交，不能让同日第二名递补。仓库里 `research/no_future_signal_pipeline.py:46-79` 已实现正确顺序：`:46-59` 先锁 TopN，`:62-79` 再应用次日执行。

最小复现：A 分数 100 但次日无开盘，B 分数 90 且可成交。现有预过滤选 B；正确顺序锁 A 后记为未成交。

```text
SUBSTITUTION biased_selected= ['B'] locked= [['A', False]]
```

**继承影响**：所有直接使用该面板或候选 CSV 的动量、反转、突破、质量动量、线性排序和事件研究，都必须把现有 `tradeable` 结果视为带替补偏差的上游数据。`opportunity_archetype_exit_backtest.py` 和 `v45_engine_exit_backtest.py` 虽然各自重新模拟 OHLC 退出，也不能自动消除候选在更早阶段已发生的替补偏差。

### OR-03（高）：历史面板复用当前名称/行业，ST、退市与行业不是点时数据

**位置**：

- `research/all_market_multi_engine_research.py:44-52` 只读单份当前 `stock_basic.parquet`；`:257-262` 将同一名称/行业映射到所有历史日，并据此计算行业相对强度；`:189` 用当前名称过滤 `ST|退`。
- `research/all_market_opportunity_audit.py:172-200` 同样只加载一次静态基础表并拼到所有历史样本；`:208-216` 用当前 `list_date`、名称和未来开盘构造历史可交易性。
- 归档复现 `research/strategy_archive/20260422_guangxun/experiment_results/reproduce_strategy.py:689-714` 也仅取当前 `list_status='L'` 列表；它在报告 `:612` 已承认退市股缺失的生存者偏差。

结果不是简单的展示字段误差：历史名称决定 ST 排除，历史行业决定 `industry_rs_20`、行业中性、行业集中度和板块条件。当前行业回填到旧日期会改变特征与样本池；当前仅上市列表还会丢掉后来退市股票。

最小复现的等价操作是把一个当前行业映射 join 到 2020 与 2026 两行，两个日期都会得到同一当前行业。代码没有按 `trade_date` 选择 `stock_basic_history/YYYYMMDD` 快照的分支，因此无法从现有实现恢复当时行业或当时 ST 名称。

影响：基于 `build_year_panel` 的所有历史策略只能标为“静态证券主数据口径”，不能声称已消除生存者偏差或行业未来偏差。缺少精确历史快照时，严格 PIT 研究应失败，而不是静默使用当前映射。

### OR-04（高）：T3“走前验证”没有在训练期选规则，而是用测试期筛选和排序

**位置**：`research/t3_confirmation_walkforward_validation.py:39-72` 从先前质量搜索取 Top120；`:121` 装载规则；`:131-160` 对每条规则同时计算 train/test，唯一训练过滤只是训练交易数至少 3；`:154-159` 用测试结果生成 `test_pass`；`:164-167` 再以测试胜率和测试总收益排序。与报告 `:199` “先在训练年份选规则”不一致。

轻量检查显示当前质量搜索文件存在，实际进入每个 split 的规则为 120 条；若文件缺失，备用网格有 14,400 条。测试集因此承担了模型选择功能，不是一次性验证集。

```text
{'t3_fallback': 14400, 'quality_source_exists': True, 'actual_rules': 120}
```

影响：`test_pass` 和输出首行有多重比较偏差。应只按训练分数预先确定固定数量规则，再对测试期做一次评估；当前报告只能归为探索搜索。

### OR-05（高）：大规模同样本规则搜索被用作“最佳/ready”证据

**代表位置**：

- `research/expansion_layer_rule_search.py:100-125` 生成规则，`:183-233` 用同一 `ret_5d` 评分，`:237-253` 在同一样本筛选并排序；实际规则数 17,280。
- `research/pattern_breadth_rule_search.py:68-92` 生成规则，`:130-167` 评分，`:171-182` 同样本排序；实际规则数 23,040。
- `research/consensus_rule_search.py:37-52` 遍历并按同一快照结果排序，`:77-117` 网格实际 4,608 条。
- `research/v45_engine_exit_optimizer.py:150-201` 穷举 15,552 个参数组合，并按同一批真实退出收益排序。
- `research/broad_engine_factor_miner.py:135-216`、`broad_engine_rule_union_search.py:56-121`、`delayed_confirmation_gate_search.py:133-191`、`live_base_filter_optimizer.py:71-151`、`live_readiness_optimizer.py:88-177`、`sparse_year_addon_search.py:71-170`、`strong_adjacent_engine_search.py:281-398`、`t3_confirmation_quality_search.py:149-208` 都在同一样本生成并挑选 `best`。
- `research/live_readiness_postmortem.py:126-144` 用这些历史指标给 `ready`，`:147-153` 又读取已在同样本筛出的候选；这不是独立上线验证。

固定随机种子复现：1000 条规则在 20 个零均值噪声样本上的平均规则均值接近 0，但挑出的最佳规则均值达到 0.842。

```text
MULTIPLE_TEST mean_of_rules= 0.003 selected_best= 0.842
```

影响：这些脚本适合发现假设和缩小搜索空间。`best`、`target_pass`、`ready` 不能直接升级为策略有效或可上线结论；必须在搜索结束后用未参与任何规则生成、阈值选择、邻域判断和报告排序的新时间段验证。

### OR-06（中）：5 日重叠收益被当作逐日收益，曲线、回撤和 Bootstrap 的时间单位错误

**位置**：

- `research/two_stage_walkforward_research.py:215-219` 按信号日聚合 `ret_5d` 后把它命名为日 `net_ret`；`:341-353` 对这些重叠 5 日标签做日块 Bootstrap。
- `research/walkforward_linear_ranker.py:139-172` 以信号日 5 日净收益累计成 `curve` 并计算 `max_cohort_drawdown_pct`。
- `research/full_market_event_research.py:200-213` 同样把信号日的 5 日回报作为逐日序列计算回撤和 Bootstrap。

连续交易日的 5 日持有区间彼此重叠，不能把每个标签当作当日已实现账户收益。两个连续信号都标记 +10% 时，当前 `_daily_portfolio` 产生两行 +10%，两行相加 20%，但第二个信号日第一笔仓位还没有完成五日持有。

```text
OVERLAP daily_rows= [['20260102', 10.0], ['20260105', 10.0]] two_row_sum= 20.0
```

`high_confidence_abstention_audit.py:61-109` 的 `overlap_adjusted_portfolio` 按五个并行 sleeve 展开逐日价格，是更接近账户口径的补充。已调用它的质量动量脚本，其“路径年度收益/回撤”可单独参考；但同一报告里的交易均值、重叠标签 Bootstrap 不能解释为账户净值置信区间。

### OR-07（中）：策略候选模拟的 “holdout” 早于训练期，命名不能表示前向留出

**位置**：`research/strategy_candidate_simulator.py:440-449` 把 2024H1 标为 `holdout`，把其后的 2024H2-2025H1 标为 `train`；`:411-429` 又用该“holdout”参与候选分类。

```text
[('20240301', 'holdout_2024H1'), ('20241001', 'train_2024H2_2025H1'), ('20250701', 'validate_2025H2')]
```

这是回溯期/时间稳定性检查，不是训练后未见数据。若规则是在后一个“train”期间形成，2024H1 的结果无法提供前向 holdout 证据。脚本标题和输出应按此降低证据等级。

### OR-08（中）：若干研究家族报告毛收益，未计费用或完整可成交约束

**位置**：

- `research/expansion_layer_rule_search.py:183-233`、`pattern_breadth_rule_search.py:130-167`、`consensus_rule_search.py:157-203`、`v41_v42_snapshot_experiment.py:83-111` 直接统计 `ret_5d`，没有扣成本。
- `research/dragon_reliability_backtest.py:45-104` 以 T+1 open 计算收益，`:366-381` 直接汇总毛收益；页面脚本 `dragon_page_backtest.py:244-273` 继续展示该口径。代码记录 `next_limit_up` 与 `gap_fail` 作为诊断，但日 OHLC 无法证明开盘限价委托可成交，且没有成交队列、佣金、印花税或滑点模型。
- 归档复现 `strategy_archive/20260422_guangxun/experiment_results/reproduce_strategy.py:574-598` 汇总原始 forward return；`:621` 只说明批次曲线不是资金约束净值，没有扣交易成本。

相对地，`two_stage_walkforward_research.py`/质量动量家族明确使用 0.25% 基准摩擦并做 0.35%/0.50% 压力，`v45_engine_exit_backtest.py:125-127` 优先使用 `profit_after_fee`。不同家族的总收益、盈亏比和“通过”阈值因此不可直接横向比较。OR-08 项只能作为毛收益/信号质量研究，不能视为可执行净收益。

### OR-09（中）：2025/2026 与 sealed 数据已参与验收或排序，不能再次称为独立留出

**位置**：

- `research/defensive_quality_reentry_v16_2019_2026.py:120-143` 把 2025-2026 的正收益纳入通过条件，并明确写出 `recent_validation_contaminated=True`；v17 在 `:146-148` 同样披露。
- `research/all_market_opportunity_archetypes.py:288-328` 同时用 train、validation、sealed 生成 `research_pass` 并按 sealed 指标排序。
- `research/opportunity_archetype_ranking_research.py:190-218` 用 validation 和 sealed 共同验收，`:308-315` 还按 sealed 结果决定报告展示项。

这里的实现多数已诚实披露，不属于隐藏未来函数；问题是证据命名和后续复用。以上日期段已被研究决策消费，只能作为已观察的验证/近期样本。下一轮策略变更必须另找新的封存区间，不能继续用同一批数据声称独立确认。

## 家族级算法判断

| 家族 | 算法判断 | 主要边界 |
|---|---|---|
| 全市场面板/机会库 | 历史价格滚动和 T+1 至 T+N 标签计算方向基本正确 | OR-02 的事后替补、OR-03 的静态主数据使候选集不满足严格 PIT |
| 画像、排序、退出归因 | 多数先训练定画像/方向/退出，再看 validation/sealed；退出脚本使用 OHLC 路径 | sealed 已被验收消费；上游继承 OR-02/03；固定费用仍是近似 |
| 反转/行业中性/共识 | `contrarian_dynamic_selector` 与 `contrarian_consensus_selector` 按前三年选择下一年配置，年度边界合理 | 上游候选与行业继承 OR-02/03；同一历史反复研究后的“recent”不独立 |
| 质量动量/资金确认 | 年度 expanding/rolling 训练边界总体合理，哈希冻结版能阻止事后改参 | 基础候选直接用次日 gap，继承 OR-02/03；v16/v17 recent 已污染 |
| 双层走前/线性/非线性 | 目标年训练只取更早年份；禁止 outcome 字段作为模型特征的设计合理 | OR-02 候选替补、OR-06 重叠标签统计；validation 被用于验收后不可重复使用 |
| 规则挖掘/扩容/v45 | 规则本身多用入场前字段，真实退出版复用 BacktestV2 | OR-01 直接标签排序；OR-04/05 多重搜索；部分 OR-08 毛收益 |
| 龙头/快钱/页面 | 事件日字段与未来收益字段在代码上分开，排序没有发现直接用 `ret_*` | OR-08 毛收益、次日涨停/滑点/容量未形成统一成交模型；同样本规则版本迭代 |
| 历史审计/矩阵/健康检查 | 主要是已有结果的汇总与诊断，不生成新交易信号 | 输入报告本身可能已被筛选，不能把二次汇总当独立验证 |
| 下载/补缓存/夜间调度 | 属于研究运维，不评价策略收益算法 | 未联网运行，供应商字段、频控和增量幂等性未实测 |
| strategy_archive | 历史快照和隔离复现 | 明确非当前实盘；静态基础表、毛收益、近似新闻代理均限制结论 |

## 逐文件覆盖表

阅读层次含义：“精读”表示逐分支检查信号、标签、切分、排序与收益；“家族精读”表示逐文件结构审读并结合其共享实现做行级核对；“结构审读”表示全文扫描入口、依赖、输入输出和危险字段，适用于汇总/运维脚本；“归档”表示只评价历史复现边界，不映射到当前实盘。`↑` 表示继承上游数据问题。

| # | 文件 | 家族 | 阅读层次 | 问题/限制 |
|---:|---|---|---|---|
| 1 | `research/__init__.py` | 包边界 | 结构审读 | 无；明确 research-only |
| 2 | `research/all_market_multi_engine_research.py` | 全市场面板/多引擎 | 精读 | OR-02、OR-03 |
| 3 | `research/all_market_opportunity_archetypes.py` | 机会画像 | 精读 | OR-02↑、OR-03↑、OR-09 |
| 4 | `research/all_market_opportunity_audit.py` | 全市场机会审计 | 精读 | OR-02、OR-03 |
| 5 | `research/archived_momentum_reconstruction.py` | 历史动量恢复 | 家族精读 | OR-02↑、OR-03↑；研究恢复，不是当前策略 |
| 6 | `research/bear_bounce_interaction_research.py` | 熊反交互 | 家族精读 | OR-02↑、OR-03↑ |
| 7 | `research/broad_engine_factor_miner.py` | 规则挖掘 | 精读 | OR-05；输入为真实退出版 |
| 8 | `research/broad_engine_rule_union_search.py` | 规则并集 | 精读 | OR-05 |
| 9 | `research/consensus_rule_search.py` | 共识规则 | 精读 | OR-05、OR-08 |
| 10 | `research/consensus_snapshot_builder.py` | 共识快照 | 家族精读 | OR-02↑、OR-03↑；输出依赖输入池 provenance |
| 11 | `research/contrarian_candidate_stress.py` | 反转压力 | 家族精读 | OR-02↑、OR-03↑；路径指标优于简单重叠累计 |
| 12 | `research/contrarian_consensus_selector.py` | 反转共识 | 精读 | OR-02↑、OR-03↑；年度选择边界未见直接泄漏 |
| 13 | `research/contrarian_cross_sectional_audit.py` | 反转横截面审计 | 家族精读 | OR-02↑、OR-03↑；描述性剔除，不是策略训练 |
| 14 | `research/contrarian_dynamic_selector.py` | 反转动态选择 | 精读 | OR-02↑、OR-03↑；前三年选下一年边界合理 |
| 15 | `research/contrarian_incremental_alpha.py` | 反转增量收益 | 家族精读 | 固定持有收益；未形成完整账户撮合 |
| 16 | `research/contrarian_industry_neutral.py` | 反转行业中性 | 家族精读 | OR-03↑ |
| 17 | `research/contrarian_reality_check.py` | 反转 Reality Check | 精读 | OR-02↑、OR-03↑；block 校正设计合理 |
| 18 | `research/defensive_quality_reentry_v16_2019_2026.py` | 质量动量防御 v16 | 精读 | OR-02↑、OR-03↑、OR-09 |
| 19 | `research/defensive_quality_reentry_v17_stress_2019_2026.py` | 质量动量防御 v17 | 精读 | OR-02↑、OR-03↑、OR-09 |
| 20 | `research/delayed_confirmation_gate_search.py` | 延迟确认搜索 | 精读 | OR-05 |
| 21 | `research/delayed_entry_path_audit.py` | 延迟入场路径 | 家族精读 | 同样本路径比较；只适合生成假设 |
| 22 | `research/dragon_data_collector.py` | 龙头数据采集 | 结构审读 | 未联网验证供应商 schema/幂等性 |
| 23 | `research/dragon_fast_money_experiment.py` | 龙头快钱 | 家族精读 | OR-08；同一事件库连续迭代 v3/v4/v5 |
| 24 | `research/dragon_page_backtest.py` | 龙头页面回测 | 精读 | OR-08 |
| 25 | `research/dragon_reliability_backtest.py` | 龙头可靠性 | 精读 | OR-08 |
| 26 | `research/engine_multibucket_strategy_search.py` | 多入场桶搜索 | 精读 | OR-01、OR-05 |
| 27 | `research/entry_timing_bucket_research.py` | 入场时点标签/搜索 | 精读 | OR-05；未来收益只用于标签，但规则仍为同样本探索 |
| 28 | `research/expansion_layer_rule_search.py` | 扩容规则 | 精读 | OR-05、OR-08 |
| 29 | `research/factor_attribution_research.py` | 因子归因 | 家族精读 | OR-05；分段排序为描述性探索 |
| 30 | `research/fill_index_daily_range.py` | 缓存补齐 | 结构审读 | 未联网验证 |
| 31 | `research/flow_breadth_factor_research.py` | 资金/行业扩散 | 精读 | OR-02↑、OR-03↑；训练定方向边界合理 |
| 32 | `research/forward_cache_download.py` | 前瞻缓存下载 | 结构审读 | 未联网验证；非策略算法 |
| 33 | `research/full_market_contrarian_candidates.py` | 全市场反转候选 | 家族精读 | OR-02、OR-03↑ |
| 34 | `research/full_market_event_research.py` | 全市场事件 | 精读 | OR-02、OR-03↑、OR-06 |
| 35 | `research/high_confidence_abstention_audit.py` | 高置信弃权/账户压力 | 精读 | OR-02↑、OR-03↑；sleeve 路径实现可作对照 |
| 36 | `research/high_momentum_continuation_v13_2019_2026.py` | 高动量延续 | 精读 | OR-02、OR-03↑；2025/26 已被观察 |
| 37 | `research/historical_strategy_audit.py` | 历史策略汇总 | 结构审读 | 二次汇总，继承输入回测偏差 |
| 38 | `research/historical_winner_commonality_research.py` | 历史赢家共性 | 家族精读 | 结果条件化/幸存者描述，不可当因果特征证据 |
| 39 | `research/hybrid_delayed_confirmation_experiment.py` | 混合延迟确认 | 家族精读 | 同样本变体比较；只适合探索 |
| 40 | `research/industry_relative_reversal_candidates.py` | 行业相对反转 | 精读 | OR-02、OR-03 |
| 41 | `research/limit_pool_collector.py` | 涨停池采集 | 结构审读 | 未联网验证供应商 schema/日期完整性 |
| 42 | `research/live_base_filter_optimizer.py` | live base 寻优 | 精读 | OR-05 |
| 43 | `research/live_readiness_optimizer.py` | live readiness 寻优 | 精读 | OR-05 |
| 44 | `research/live_readiness_postmortem.py` | 上线准备复盘 | 精读 | OR-05 |
| 45 | `research/live_ready_variant_compare.py` | ready 变体比较 | 家族精读 | OR-05↑；输入候选已被同样本选过 |
| 46 | `research/moneyflow_breakout_factor_audit.py` | 资金突破因子 | 家族精读 | OR-02↑、OR-03↑；描述性方向审计 |
| 47 | `research/moneyflow_breakout_online_opportunity_v10_2019_2024.py` | 资金突破在线门 | 精读 | OR-02↑、OR-03↑；门槛只用历史分位 |
| 48 | `research/moneyflow_breakout_ridge_v9_2019_2024.py` | 资金突破 Ridge | 精读 | OR-02、OR-03↑；年度 walk-forward 边界合理 |
| 49 | `research/nightly_strategy_runner.py` | 研究调度 | 结构审读 | 未运行子任务；非策略算法 |
| 50 | `research/no_future_signal_pipeline.py` | 无未来信号基准 | 精读 | 未发现确定问题；正确实现先锁信号再执行 |
| 51 | `research/official_strategy_health_check.py` | 正式策略健康检查 | 结构审读 | 二次报告；不证明策略有效性 |
| 52 | `research/opportunity_archetype_exit_backtest.py` | 画像 OHLC 退出 | 精读 | OR-02↑、OR-03↑；退出路径本身未见未来字段进规则 |
| 53 | `research/opportunity_archetype_ranking_research.py` | 画像内部排序 | 精读 | OR-02↑、OR-03↑、OR-09 |
| 54 | `research/opportunity_exit_attribution.py` | 画像退出归因 | 精读 | OR-02↑、OR-03↑；训练期选择退出，边界合理 |
| 55 | `research/pattern_breadth_rule_search.py` | 形态/宽度搜索 | 精读 | OR-05、OR-08 |
| 56 | `research/post_earnings_pullback.py` | 财报后回调 | 家族精读 | OR-02、OR-03↑；财务 PIT 依赖排除范围内的 helper |
| 57 | `research/post_earnings_quality_drift.py` | 财报后质量漂移 | 家族精读 | OR-02、OR-03↑；财务 PIT 依赖排除范围内的 helper |
| 58 | `research/preregistered_broad_ridge.py` | 预注册 Ridge | 精读 | OR-02↑、OR-03↑、OR-06；预注册边界清楚 |
| 59 | `research/preregistered_nonlinear_broad_model.py` | 预注册非线性 | 精读 | OR-02、OR-03↑、OR-06；禁止未来特征集合合理 |
| 60 | `research/quality_momentum_direct_top2_2019_2024.py` | 质量动量 Top2 | 家族精读 | OR-02↑、OR-03↑ |
| 61 | `research/quality_momentum_dual_window_consensus_v15_2019_2026.py` | 质量动量双窗 v15 | 家族精读 | OR-02↑、OR-03↑、OR-09 |
| 62 | `research/quality_momentum_moneyflow_confirm_v11_2019_2025.py` | 质量动量资金确认 | 精读 | OR-02↑、OR-03↑；确认变量时序未见直接泄漏 |
| 63 | `research/quality_momentum_moneyflow_v12_observation_2026.py` | 质量动量 2026 观察 | 家族精读 | OR-02↑、OR-03↑、OR-09 |
| 64 | `research/quality_momentum_reentry_horizon_v8_2019_2024.py` | 质量动量持有期 | 精读 | OR-02↑、OR-03↑；内部 OOF 选期限 |
| 65 | `research/quality_momentum_reentry_loss_averse_v7_2019_2024.py` | 质量动量损失厌恶 | 精读 | OR-02↑、OR-03↑；年度 OOF/在线门合理 |
| 66 | `research/quality_momentum_reentry_margin_v3_2019_2024.py` | 质量动量 margin v3 | 精读 | OR-02↑、OR-03↑；重叠账户路径另有修正 |
| 67 | `research/quality_momentum_reentry_margin_v3_holdout_2025.py` | v3 2025 冻结验证 | 精读 | OR-02↑、OR-03↑；哈希冻结有效，2025 已消费 |
| 68 | `research/quality_momentum_reentry_online_gate_v5_2019_2024.py` | 质量动量在线门 v5 | 精读 | OR-02↑、OR-03↑；在线尺度只用已知历史 |
| 69 | `research/quality_momentum_reentry_rank_only_v4_2019_2024.py` | 质量动量纯排序 v4 | 精读 | OR-02↑、OR-03↑ |
| 70 | `research/quality_momentum_reentry_sealed_2025.py` | 质量动量封存执行 | 精读 | OR-02↑、OR-03↑；代码最大构建到 2024，边界清楚 |
| 71 | `research/quality_momentum_reentry_top1_v2_2019_2024.py` | 质量动量 Top1 v2 | 家族精读 | OR-02↑、OR-03↑ |
| 72 | `research/quality_momentum_reentry_turnover_guard_v6_2019_2024.py` | 质量动量换手护栏 | 家族精读 | OR-02↑、OR-03↑ |
| 73 | `research/quality_momentum_reentry.py` | 质量动量基线 | 精读 | OR-02、OR-03 |
| 74 | `research/quality_momentum_rolling3y_v14_2019_2026.py` | 质量动量滚动三年 | 精读 | OR-02↑、OR-03↑、OR-09；窗口边界合理 |
| 75 | `research/regime_conditioned_opportunity_research.py` | 状态条件机会 | 精读 | OR-02↑、OR-03↑；训练定方向边界合理 |
| 76 | `research/short_signal_factor_miner.py` | 短线因子挖掘 | 家族精读 | OR-05；结果条件化、同样本规则探索 |
| 77 | `research/sparse_year_addon_search.py` | 稀少年份补强 | 精读 | OR-05 |
| 78 | `research/strategy_archive/20260422_guangxun/ai_prompts_20260310_vscode_history.py` | 光迅归档提示词 | 归档结构审读 | 非当前实盘；无收益算法 |
| 79 | `research/strategy_archive/20260422_guangxun/experiment_results/reproduce_strategy.py` | 光迅归档复现 | 归档精读 | OR-03、OR-08；报告已披露近似恢复 |
| 80 | `research/strategy_archive/20260422_guangxun/experiment_results/test_reproduce_strategy.py` | 光迅归档测试 | 归档结构审读 | 只覆盖小函数，不验证总体无偏性 |
| 81 | `research/strategy_archive/20260422_guangxun/main_20260420_vscode_history.py` | 历史 main 快照 | 归档结构审读 | 明确非当前实盘；不得运行或覆盖当前 main |
| 82 | `research/strategy_archive/market_radar_20260812_pre_official_balance/code/market_context_snapshot.py` | 雷达归档快照 | 归档结构审读 | 非当前实盘；含外部 AI/新闻依赖，未联网验证 |
| 83 | `research/strategy_archive/market_radar_20260812_pre_official_balance/code/market_radar/ai_news_brief.py` | 雷达归档 AI 摘要 | 归档结构审读 | 非当前实盘；不进入量化评分的历史实现 |
| 84 | `research/strategy_archive/market_radar_20260812_pre_official_balance/code/market_radar/evidence_pack.py` | 雷达归档证据包 | 归档结构审读 | 非当前实盘；来源真实性未联网验证 |
| 85 | `research/strategy_archive/market_radar_20260812_pre_official_balance/code/market_radar/freshness.py` | 雷达归档时效 | 归档精读 | 非当前实盘；时区/时间解析结构未见确定泄漏 |
| 86 | `research/strategy_archive/market_radar_20260812_pre_official_balance/code/news_source_provider.py` | 雷达归档新闻源 | 归档结构审读 | 非当前实盘；未联网验证解析器 |
| 87 | `research/strategy_archive/market_radar_20260812_pre_official_balance/code/official_information_provider.py` | 雷达归档官方源 | 归档结构审读 | 非当前实盘；未联网验证解析器 |
| 88 | `research/strategy_archive/market_radar_20260812_pre_official_balance/code/web_app/services/sector_service.py` | 雷达归档页面服务 | 归档结构审读 | 非当前实盘；展示/聚合服务，不作策略证据 |
| 89 | `research/strategy_candidate_simulator.py` | 候选策略模拟 | 精读 | OR-07、OR-08 |
| 90 | `research/strategy_delta_audit.py` | 策略差异 | 结构审读 | 描述性审计，继承输入偏差 |
| 91 | `research/strategy_factor_stability.py` | 因子稳定性 | 家族精读 | 输入后验样本的稳定性，不是独立预测证据 |
| 92 | `research/strategy_layer_quality.py` | 策略分层质量 | 家族精读 | 输入后验样本的分层，不是独立预测证据 |
| 93 | `research/strategy_research_overview.py` | 研究总览 | 结构审读 | 选择“最新/最大”报告，仅是资产盘点 |
| 94 | `research/strong_adjacent_engine_search.py` | 强信号邻域搜索 | 精读 | OR-05 |
| 95 | `research/t3_confirmation_quality_search.py` | T3 质量搜索 | 精读 | OR-05 |
| 96 | `research/t3_confirmation_walkforward_validation.py` | T3 走前验证 | 精读 | OR-04 |
| 97 | `research/ten_year_cache_audit.py` | 十年缓存审计 | 结构审读 | 只审文件覆盖，不审内容 PIT 正确性 |
| 98 | `research/ten_year_strategy_matrix.py` | 十年策略矩阵 | 家族精读 | 批量跑既有策略；继承其费用、PIT 与成交模型 |
| 99 | `research/two_stage_walkforward_research.py` | 双层 walk-forward | 精读 | OR-02、OR-03↑、OR-06 |
| 100 | `research/v41_v42_snapshot_experiment.py` | v41-v44 快照实验 | 精读 | OR-05、OR-08 |
| 101 | `research/v45_engine_exit_backtest.py` | v45 真实退出 | 精读 | OR-02↑；单笔退出含 fee，组合资本占用未建模 |
| 102 | `research/v45_engine_exit_optimizer.py` | v45 退出寻优 | 精读 | OR-05 |
| 103 | `research/v45_t1_t5_confirmation_backtest.py` | v45 T1/T5 确认 | 家族精读 | 同样本变体比较；OR-05 类证据限制 |
| 104 | `research/volatility_contraction_breakout.py` | 波动收缩突破 | 家族精读 | OR-02、OR-03↑ |
| 105 | `research/walk_forward_overfit_audit.py` | walk-forward 过拟合审计 | 精读 | 只能识别矩阵内退化，不能修复 OR-02/03/05 |
| 106 | `research/walkforward_linear_ranker.py` | 线性走前排序 | 精读 | OR-02、OR-03↑、OR-06；训练/validation 年界清楚 |
| 107 | `research/winner_commonality_audit.py` | 赢家共性 | 家族精读 | 结果条件化描述，不能直接转成未验证选股规则 |

## 轻量复现记录

复现均为内存数据，不读取市场大文件、不联网：

```text
SUBSTITUTION biased_selected= ['B'] locked= [['A', False]]
RET_TIEBREAK leaky= ['B'] observable= ['A']
OVERLAP daily_rows= [['20260102', 10.0], ['20260105', 10.0]] two_row_sum= 20.0
MULTIPLE_TEST mean_of_rules= 0.003 selected_best= 0.842
{'expansion': 17280, 'pattern': 23040, 'consensus': 4608}
{'t3_fallback': 14400, 'quality_source_exists': True, 'actual_rules': 120}
[('20240301', 'holdout_2024H1'), ('20241001', 'train_2024H2_2025H1'), ('20250701', 'validate_2025H2')]
```

另一次尝试导入 `engine_multibucket_strategy_search.py` 时，由 `backtest_v2 -> main` 的模块级 Tushare 初始化触发 `TUSHARE_HTTP_URL` 校验而失败；这说明四个直接导入 `BacktestV2` 的研究脚本（该文件、`strong_adjacent_engine_search.py`、`v45_engine_exit_optimizer.py`、`v45_engine_exit_backtest.py`）不是完全无配置的离线可导入模块。本次没有为绕过它而配置地址或触发网络。它是可复现性限制，不改变上述静态代码结论。

## 未验证限制

- 没有运行 107 个入口的端到端研究，也没有复算任何历史报告数字；规则数量只对可安全导入的纯函数轻量核对。
- 没有联网验证 Tushare、AkShare、龙虎榜、热榜、新闻与官方网页的字段、时区、复权、停牌和退市覆盖；下载/采集脚本只做静态审读。
- 没有逐笔盘口、集合竞价、涨跌停封单、滑点、容量和冲击成本数据。日 OHLC 最多证明价格路径存在，不能证明开盘价可以按目标仓位成交。
- 没有审查本任务明确排除的 clean/PIT/新 holdout 脚本；它们的结论不能由本报告背书。
- 当前工作区存在其他并行修复的未提交改动。本报告只新增这一份 Markdown，没有改写、清理或回退任何既有 diff。
