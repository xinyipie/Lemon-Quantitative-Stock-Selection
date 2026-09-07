# 实盘策略与回测算法审查（2026-09-07）

## 审查范围与方法

本次审查以当前工作树为准，覆盖 `research/` 之外的实盘策略链、正式 profile、回测执行与根目录策略审计工具。先用 CodeGraph 追踪 `run_daily_selection → select_stock_pool/select_longterm_pool → BacktestV2/BacktestLongterm`，再定向阅读公式、状态分支和时点数据处理。没有联网，也没有运行多年回测；只运行了六个内存级最小复现。

当前共享工作树还包含 Web、数据更新和测试等并行改动；本报告只评估策略范围内以 `main.py` 和 `backtest_v2.py` 为主的算法 diff。本报告行号对应审查时的当前工作树。

## 总体结论

策略框架已经具备几项可靠基础：T 日选股、T+1 开盘执行的主时间顺序清楚；正式长线 v18 在宏观数据缺失时会拒绝入池；财务数据先按 `ann_date <= trade_date` 过滤；当前 diff 增加了历史股票成员/行业快照的时点约束，并停止在封死跌停时虚构成交。这些改动都改善了因果性。

但目前还不能把批量回测、IC 报表和实盘表现视为同一策略的可靠验证。确认了 5 个 P1 缺陷、9 个 P2 缺陷。最先应修的是回测成交事件顺序、涨停卖出语义、空行情时的风控默认值，以及短线 IC 评分列。否则收益、胜率和 IC 可能在同一份报告中互相矛盾。

## 策略家族覆盖

| 策略家族 | 当前入口/正式配置 | 审查重点 | 结论 |
|---|---|---|---|
| 短线基础池 | `main.py::select_stock_pool` | 状态机、板块、财务、次日执行衔接 | 公式方向总体一致；行情缺失时风控放行，历史板块时序数据被读取但未使用 |
| 短线正式强推荐 | `profile_v9_sector_quality_guard + adaptive_quality_v6 + consensus v39` | profile 评分、门控、实盘/回测一致性 | 正式实盘链已接通；止损风险公式分母错误；批量回测没有传入该组合 |
| 短线观察层 | `best_balance` | 与强推荐去重、排序 | 去重与分层方向合理；仍继承基础池的数据与状态风险 |
| 长线正式池 | `longterm_quality_lifecycle_v18_market_sync` | 宏观同步、财务时点、质量门槛 | 缺宏观或关键财务时基本为关闭状态，较安全；同报告期多公告版本选择不确定 |
| 长线观察/精英提醒 | `build_live_watchlists` | 重复出现、压缩分、行业上限 | 阈值方向合理；所谓 20 日实际是 20 次扫描，稀疏历史会放大旧信号 |
| 短线回测 | `BacktestV2` | 成交因果、组合槽位、净收益 | 固定槽位和逐日盯市改善明显；止盈事件优先级及涨停卖出处理错误 |
| 长线回测 | `BacktestLongterm` | 60 日持有、20 日止损、15 槽位 | 最大持仓限制合理；继承相同成交错误，外部暴露审计默认口径不匹配 |
| IC/批量汇总 | `ic_analysis.py`, `batch_backtest.py` | 评分列、前瞻收益、显著性 | 短线 IC 选错列；收益充当评分是结果泄漏；显著性假设偏强 |
| 根目录诊断工具 | 文件清单见“逐文件覆盖表” | 标签、时间单位、分位、基准 | 大部分为描述性诊断；若干默认降级会改变指标语义，不能直接据此调参 |

## `strategy_profiles.py` 全部注册项与算法家族

以下清单按 `available_profiles()`、`available_style_gates()`、`available_consensus_profiles()` 的注册表和实际分派分支逐项核对，共 23 个因子 profile、25 个风格门控、17 个共识 profile。配置中的正式直连组合是 `profile_v9_sector_quality_guard + adaptive_quality_v6 + v39`；`v39` 内部还实际运行 v19/v21 因子与 v19/v25/v27 风格门控。`original`、`none` 是兼容/关闭模式；代码没有“两个名称指向同一个注册项”的显式别名，但未知名称会被静默归一化为 `original` 或 `none`，属于兼容降级而不是可审计的别名（见方法局限第 7 项）。注册表内没有重名，也没有无法到达的死分派：`diagnostic_v1` 虽没有单独的 `if`，但会有意落到函数末尾的旧诊断公式；`v40` 则在共识通用分派之前进入专用双层回退函数。

### 因子评分 profile（23/23）

| 注册名称 | 身份 | 公式继承/增量 | 已确认问题 |
|---|---|---|---|
| `original` | 兼容基线 | 直接返回入口原始 `score` | 未发现本层独有公式缺陷 |
| `diagnostic_v1` | 可选诊断 | 使用末尾的旧诊断加权公式；不是未知名称别名 | 未使用止损风险项；未知 profile 却也会先降级到 `original` |
| `profile_v2` | 可选 | 独立 v2 多因子公式 | 直接使用错误的 `stop_risk_pct`，受 LS-09 影响 |
| `profile_v3` | 可选 | v3 路径质量基础式 | 共享止损风险项，受 LS-09 影响 |
| `profile_v4` | 正式链祖先 | v3 加宏观/风格修正，是后续主干基础式 | 受 LS-09 影响 |
| `profile_v5` | 可选 | v4 加横盘与量能惩罚 | 继承 LS-09 |
| `profile_v8_sector_rank` | 可选 | v4 加行业排序因子 | 继承 LS-09 |
| `profile_v9_sector_quality_guard` | **正式直连** | v4 加行业质量保护 | 继承 LS-09；正式候选排序受影响 |
| `profile_v10_mid_deep_drawdown_guard` | 可选 | v4 加中深回撤保护 | 继承 LS-09 |
| `profile_v11_mid_deep_drawdown_strict_guard` | 可选 | v4 加更严格的中深回撤保护 | 继承 LS-09 |
| `profile_v12_2026h1_guard` | 正式链祖先/可选 | v9 加 2026H1 窗口保护 | 继承 LS-09 |
| `profile_v13_high_win_quality_gate` | 可选 | v9 加高胜率质量门 | 继承 LS-09 |
| `profile_v14_sector_pattern_gate` | 可选 | v13 加行业形态门 | 继承 LS-09 |
| `profile_v15_dual_lane_quality_gate` | 可选 | v14 加双通道质量门 | 继承 LS-09 |
| `profile_v16_window_confidence` | 可选 | v14 加窗口置信度 | 继承 LS-09 |
| `profile_v17_followthrough_factor` | 可选 | v12 加延续性因子 | 继承 LS-09 |
| `profile_v18_stable_followthrough` | 正式链祖先/可选 | v12 加稳定延续约束 | 继承 LS-09 |
| `profile_v19_calm_followthrough` | **v39 正式通道** | v18 加平静延续约束 | 继承 LS-09 |
| `profile_v20_low_noise_followthrough` | 可选 | v19 加低噪声约束 | 继承 LS-09 |
| `profile_v21_sector_calm_followthrough` | **v39 正式通道** | v19 加行业平静约束 | 继承 LS-09 |
| `profile_v22_two_lane_followthrough` | 可选 | v19 加双通道延续规则 | 继承 LS-09 |
| `profile_v23_cautious_window` | 可选 | v19 加谨慎窗口规则 | 继承 LS-09 |
| `profile_v24_momentum_pullback` | 可选 | v17 加动量回调规则 | 继承 LS-09 |

### 风格门控 profile（25/25）

| 注册名称 | 身份 | 门控家族/增量 | 审查结论 |
|---|---|---|---|
| `none` | 关闭/兼容 | 不过滤 | 合理的显式关闭模式；未知名称也静默落到此模式 |
| `no_momentum` | 可选基础门 | 排除 `momentum` | 简单布尔门；缺失风格会被放行 |
| `no_active_sideways` | 可选基础门 | 排除主动横盘 | 简单布尔门；缺失风格会被放行 |
| `weak_only` | 可选基础门 | 仅弱势风格 | 缺失风格会被拒绝 |
| `weak_or_cautious_sideways` | 可选基础门 | 弱势或谨慎横盘 | 缺失风格会被拒绝 |
| `adaptive_quality` | 可选主干 | 自适应质量基础门 | 阈值方向一致，未发现独有算术错误 |
| `adaptive_quality_v2` | 可选 | 基础门加高分风险/弱动量保护 | 阈值方向一致 |
| `adaptive_quality_v5` | 可选 | v2 加高分放量保护 | 阈值方向一致 |
| `adaptive_quality_v6` | **正式直连** | v2 加弱行业放量保护 | 正式单通道门控；未发现独有算术错误 |
| `adaptive_quality_v13` | 可选 | 高质量核心与风格质量双通道 | 阈值方向一致 |
| `adaptive_quality_v14` | 可选 | 更紧的核心质量门 | 阈值方向一致 |
| `adaptive_quality_v15` | 可选 | 双通道质量门 | 阈值方向一致 |
| `adaptive_quality_v16` | 可选 | 平静双通道门 | 阈值方向一致 |
| `adaptive_quality_v17` | 可选 | 延续性门 | 阈值方向一致 |
| `adaptive_quality_v18` | 可选 | 稳定延续门 | 阈值方向一致 |
| `adaptive_quality_v19` | **v39 正式通道** | 平静延续门 | 正式共识的 v19 通道 |
| `adaptive_quality_v20` | 可选 | 低噪声延续门 | 阈值方向一致 |
| `adaptive_quality_v21` | 可选 | 行业平静延续门 | 阈值方向一致 |
| `adaptive_quality_v22` | 可选 | 双通道延续门 | 阈值方向一致 |
| `adaptive_quality_v23` | 可选 | 谨慎窗口门 | 阈值方向一致 |
| `adaptive_quality_v24` | 可选 | 动量回调门 | 阈值方向一致 |
| `adaptive_quality_v25` | **v39 正式通道** | v19 的市场保护版本 | 行情字段为 NaN 时部分默认值偏放行；v39 后置保护通常会再拒绝缺列样本 |
| `adaptive_quality_v26` | 可选 | v25 加热市通道 | 同上；热市分支对缺失值较保守 |
| `adaptive_quality_v27` | **v39 正式通道** | 行业平静与市场保护双通道 | 行情字段为 NaN 时保护通道可能使用偏积极默认值 |
| `adaptive_quality_v28` | 可选 | v27 加市场热度保护 | 同上；缺失 `limit_up_count` 的默认值会使部分热度条件偏放行 |

### 共识 profile（17/17）

除 `none` 外，注册表中的 v29-v44 都先运行完全相同的三个投票通道：`v19 = profile_v19_calm_followthrough/adaptive_quality_v19`、`v25 = profile_v19_calm_followthrough/adaptive_quality_v25`、`v27 = profile_v21_sector_calm_followthrough/adaptive_quality_v27`，默认至少两票。因而所有 v29-v44 都继承因子链的 LS-09；版本号只改变投票后的市场保护或重排。

| 注册名称 | 身份 | v29 基础共识之后的分派 | 已确认问题/关系 |
|---|---|---|---|
| `none` | 关闭/兼容 | 不构建共识，原样返回 | 合理的显式关闭模式；未知名称也静默落到此模式 |
| `v29` | 正式链祖先/可选 | 三通道投票基础式：票数、平均分、平均名次 | 三条通道均继承 LS-09 |
| `v30` | 可选 | v29 加涨停热度与中性板块广度保护 | 缺必要列时关闭，方向合理 |
| `v31` | 可选 | v29 加分层热度、过伸过滤与中性广度降权 | 缺必要列时关闭，方向合理 |
| `v32` | 可选 | v29 加中等热度与量比上限 | 缺必要列时关闭，方向合理 |
| `v33` | 正式链祖先/可选 | v29 加防御核心/中性广度选择双通道 | v35/v39 的保护祖先 |
| `v34` | 可选 | v33 加谨慎模式跌停摩擦过滤 | 方向合理 |
| `v35` | **v39 正式祖先** | v33 的谨慎过滤加高形态例外 | v39 会调用此保护 |
| `v36` | 可选 | v35 加快照顶层规则 | 方向合理 |
| `v37` | 可选 | v35 后按形态、行业、量比、跌停数重排 | 重排仍基于受 LS-09 影响的投票分数 |
| `v38` | 可选 | v35 后加入平均名次保护再重排 | 同上 |
| `v39` | **正式直连** | v35 后要求 `consensus_avg_rank <= 1.5` | 正式强推荐；继承 LS-09 |
| `v40` | 可选 | 若 v35 非空只返回主层；仅 v35 全空时改走 v29 的 gap-fill | 是二选一回退状态机，不是两层合并；继承 LS-09 |
| `v41` | 可选 | v39 加板块广度上限与形态下限 | 缺必要列时关闭，方向合理 |
| `v42` | 可选 | v39 加广度上限，并按形态/广度/跌停数重排 | 继承 LS-09 |
| `v43` | 可选 | 直接在 v29 上要求平均名次不高于 2 且宏观谨慎 | 不继承 v35 的市场保护，但仍继承 LS-09 |
| `v44` | 可选 | 直接在 v29 上要求平均名次、形态及跌停数阈值 | 不继承 v35 的市场保护，但仍继承 LS-09 |

### 观察 profile（1/1）

| 注册名称 | 身份 | 公式/分派 | 审查结论 |
|---|---|---|---|
| `best_balance` | **正式观察层** | `build_live_observation_candidates` 唯一接受的名称；先构造 v39 强推荐阴影集，再以 v9/观察门槛形成去重后的补充候选 | 未知名称会明确抛错，不会静默别名；评分仍继承 v9 的 LS-09，且整体继承 LS-01 的基础池数据风险 |

## 确定缺陷

### LS-01（P1）：行情缺失时两层市场风控都默认放行

- 位置：`main.py:1029-1030`, `main.py:1134-1135`, `main.py:1171-1184`, `main.py:1194-1196`, `main.py:1208-1210`, `main.py:1331-1333`, `main.py:5522-5537`。
- 现象：`check_market_risk` 在指数为空或异常时返回 `normal`；核心 `get_market_regime` 在 CSI300 不足、均线不足或异常时返回 `BULL_TREND`，并携带仓位乘数 `1.0`、门槛 `45`。只有真实得到 `BEAR_TREND` 才会在主流程提前空仓。
- 最小复现：令 `pro.index_daily(...)` 返回空表，实际输出为 `BULL_TREND, position_multiplier=1.0, score_threshold=45`。
- 影响：数据源故障、缓存缺口或 schema 变化会被解释为最积极的市场状态；短线可继续生成候选。正式长线 v18 随后会因 market-sync 数据为零而关闭，但不能抵消短线风险。
- 建议：未知状态使用明确的 `DATA_UNAVAILABLE` 或至少 `BEAR_TREND/stop`；只有完整指标通过校验后才能升级为牛市。

### LS-02（P1）：回测把收盘退出放在当日日内止盈之前

- 位置：`backtest_v2.py:912-963` 的时间止损、短线时间止损、弱收盘和动态到期，都先于 `backtest_v2.py:965-985` 的 `day_high >= profit_price`。
- 现象：同一天先用全天收盘值触发退出，随后才检查盘中最高价是否已经成交止盈单。
- 最小复现：买入价 100、目标 110、止损 90；下一日 `high=111, low=95, close=96`，且当日满足时间止损。当前返回 `time_stop, sell=96, gross=-4%`，而已存在的 110 限价止盈在日内可成交。
- 影响：退出原因、收益、MFE 后的回吐结论和所有依赖这些交易的参数实验都会被污染。这里不是“保守假设”，而是使用收盘后信息覆盖更早已发生的可成交事件。
- 建议：先处理开盘跳空和前一日已知止损；若同日日线同时触及止损与止盈且无法知道顺序，应标为歧义并采用预先声明的保守规则；任何收盘退出必须放在盘中可成交事件之后。

### LS-03（P1）：涨停日持仓卖出语义相反

- 位置：`backtest_v2.py:822-823`, `backtest_v2.py:965-980`。
- 现象：只要收盘涨幅达到涨停阈值，止盈就被标记为 `take_profit_next_open`。A 股涨停主要限制买入；已有持仓的卖单通常可向涨停买盘成交。即使曾开板后回封，只要 `high >= target`，低于或等于涨停价的卖出限价也具备成交条件。
- 最小复现：持仓成本 100、目标 108；当日 `open=105, high=110, low=105, close=110, pct_chg=10%`，次日开盘 100。当前结果是次日 100 元、收益 0%，而 108 元止盈当日已可成交。
- 影响：引入不必要的次日价格依赖，可能显著低估或高估收益。当前 diff 对封死跌停的处理方向正确，但涨停卖出规则仍需单独修正。
- 建议：涨停持仓卖出按正常可成交处理；需要延期的是封死跌停的卖出。若要模拟排队，应基于盘口或至少 `open=high=low=close=涨停价` 的证据，并采用符合交易方向的规则。

### LS-04（P1）：批量短线 IC 恒优先选择 `longterm_score`

- 位置：`backtest_v2.py:1307-1308`, `batch_backtest.py:210-220`, `batch_backtest.py:267-276`。
- 现象：每笔交易无论模式都会写出 `longterm_score` 和 `short_score`；短线的 `longterm_score` 默认为 0。`compute_ic_summary` 只要看见 `longterm_score` 列就选它，因此短线 IC 使用常数列并得到 `NaN`，有效的 `short_score` 被忽略。
- 最小复现：`longterm_score=[0,0,0,0,0]`、`short_score=[1,2,3,4,5]`，当前选择前者，`nunique()==1`。
- 影响：批量汇总无法回答短线分数是否有预测能力，也可能把“无 IC”误读为策略失效。
- 建议：由 `mode` 明确选择评分列；短线优先 `short_score`，长线优先 `longterm_score`，并在常数列时报告数据质量错误而不是静默输出 NaN。

### LS-05（P1）：`--no-timing`/批量“纯选股”不能真正关闭前置市场门控

- 位置：`backtest_v2.py:460-480`, `backtest_v2.py:502-514`, `main.py:5522-5537`, `main.py:5673-5675`, `batch_backtest.py:115-143`。
- 现象：回测先调用 `run_daily_selection`；该函数在 `BEAR_TREND` 或 `operation_mode=stop` 时已经返回空池。回测随后才检查 `use_market_timing`，此时即使为 `False` 也无法恢复候选，而且 `position_multiplier==0` 仍会在 512-514 行清空。
- 影响：代码注释所称“忽略所有宏观过滤、纯验证选股逻辑”没有实现。批量实验既不是正式实盘策略，也不是纯因子实验，样本选择口径含有隐式状态过滤。
- 建议：把“生成原始候选”和“应用市场准入”拆成显式阶段，或将 `use_market_timing` 传入主流程并在任何提前返回前处理。

### LS-06（P2）：批量回测没有运行当前正式短线组合

- 位置：正式配置见 `config.py:130-138`；直接 CLI 默认正确传入见 `backtest_v2.py:1955-1979`；批量构造见 `batch_backtest.py:115-143`；引擎缺省值见 `backtest_v2.py:250-256`。
- 现象：`batch_backtest.py` 没有传 `factor_profile/style_gate/consensus_profile`，因此短线退回 `original/none/none`；同时固定 5 日持有、关闭开盘确认并声明关闭择时。长线虽会从配置取得 v18，但也关闭择时和开盘确认。
- 影响：批量结果不能作为当前首页 v39 强推荐或完整长线执行规则的 KPI。它最多是一个混合口径的组件基准。
- 建议：批量任务保存完整 profile 与执行参数；正式验证模式复用 CLI 的官方默认，纯因子模式使用不同名称和输出目录。

### LS-07（P2）：胜负、盈亏比和连亏按毛收益统计，净值按扣费收益统计

- 位置：成本常量 `backtest_v2.py:110-113`；净收益计算 `backtest_v2.py:1052-1065`；胜负与连亏 `backtest_v2.py:1417-1435`；汇总 `backtest_v2.py:1498-1518`。
- 现象：总成本为 0.36%，但 `win_rate`、`avg_win/avg_loss`、盈亏比、最大连亏和单笔极值使用 `profit_pct`；净值和平均扣费收益使用 `profit_after_fee`。
- 最小复现：毛收益 `+0.20%` 的交易写成净收益 `-0.16%`，报表仍把它计为胜利。
- 影响：同一报告可能显示正胜率提升而真实净值下降，尤其影响低收益、高换手的短线策略。
- 建议：绩效统计统一以 `profit_after_fee` 为主；如需毛指标，使用明确的 `gross_*` 名称并并列展示。

### LS-08（P2）：长线观察的 `lookback_days=20` 实际表示 20 个扫描批次

- 位置：`longterm_live_pipeline.py:21-50`, `longterm_pool_compression_audit.py:121-143`。
- 现象：压缩器把所有出现过的 `select_date` 映射为连续 `_scan_index`，再按索引差取窗口。稀疏扫描时，20 次扫描可能跨越数月。
- 最小复现：同一股票仅在 20260101 和 20260701 两次出现，`lookback_days=20` 时第二次的 `recent_appearances` 仍为 2。
- 影响：旧信号会获得 75 分重复度奖励并参与正式 live watchlist 排序，参数名和真实时间含义不一致。
- 建议：明确选择“最近 N 个交易日”或“最近 N 次扫描”；前者按交易日历/日期差过滤，后者重命名为 `lookback_scans` 并设置历史最长跨度。

### LS-09（P2）：短线 profile 的止损风险百分比公式分母错误

- 位置：`strategy_profiles.py:671`, `strategy_profiles.py:673-678`, `strategy_profiles.py:1394-1457`。正式 v9 在 `strategy_profiles.py:730-731` 复用 profile_v4，因此受影响。
- 现象：代码使用 `(close / stop - 1) * 100`；从入场价衡量最大损失应为 `(close - stop) / close * 100`。
- 最小复现：`close=100, stop=80` 时当前得到 25%，实际入场资金风险为 20%。
- 影响：风险越大，误差越大；当前方向偏保守，但会改变 v39 的候选排序与门控，且报告字段不再表示通常定义的风险百分比。
- 建议：统一采用入场价为分母，并对 5%、10%、20% 止损距离加入公式级测试。

### LS-10（P2）：同报告期多公告版本的财务选择不确定

- 位置：公告过滤正确实现于 `main.py:2316-2332`；版本选择在 `main.py:2415-2436`, `main.py:2503-2509`, `main.py:2552-2586`。
- 现象：过滤公告日后只按 `end_date` 排序。相同 `ts_code/end_date` 若有不同 `ann_date` 的更正或快报版本，ROE 的 `drop_duplicates('ts_code')` 和同比增速的前两行依赖输入顺序；增速“上一期”甚至可能是同一报告期的另一个版本。
- 影响：同一截面在不同 parquet 行顺序下可能得到不同 ROE、YoY 和加速标记。正式 v18 强依赖这些硬门槛。
- 建议：先按 `ts_code,end_date,ann_date` 排序，在截止日内保留每个报告期最新公告版本，再跨不同 `end_date` 比较。

### LS-11（P2）：长线持仓暴露审计默认槽位与真实引擎不一致

- 位置：`longterm_backtest_audit.py:30-55`, `longterm_backtest_audit.py:127-136`；真实引擎 `backtest_v2.py:1591-1621`。
- 现象：审计默认 `top_n=3`，将每笔权重估为 33.33%；`BacktestLongterm` 默认 `max_positions=15`，实际单槽位约 6.67%。交易 CSV 已含 `portfolio_slot`，审计仍不使用。
- 影响：最大暴露和“超过 100%/200% 天数”可被放大 5 倍，可能产生错误的组合风险结论。
- 建议：优先从 metrics/CSV 读取 `max_positions` 和槽位；无法读取时要求显式参数，避免带默认值运行。

### LS-12（P2）：观察天数用 YYYYMMDD 整数相减

- 位置：`longterm_pool_watchlist_audit.py:113-115`。
- 现象：`days_since_first_seen = int(current_yyyymmdd) - int(first_yyyymmdd)`。
- 最小复现：20260201 与 20260131 相减得到 70，而实际为 1 天。
- 影响：跨月、跨年后的观察年龄字段错误，可能误导人工判断。当前晋级判断主要依赖扫描次数，因此影响以展示和离线审计为主。
- 建议：解析为日期后使用 `Timedelta.days`；同时注明是日历日还是交易日。

### LS-13（P2）：IC 工具允许把已实现收益当作预测分数

- 位置：`ic_analysis.py:67-76`, `ic_analysis.py:153-183`, `ic_analysis.py:217-255`, `ic_analysis.py:435`。
- 现象：缺少有效评分或使用 `--use-profit` 时，`profit_after_fee` 被选作 score，再与买入日之后的前瞻收益做 Spearman 相关。这个变量是交易完成后才知道的结果，不是选股时点特征。
- 影响：指标不再是预测 IC；持有区间与前瞻窗口重叠时还会产生机械相关。旧 CSV 兼容不能改变其统计含义。
- 建议：无可用评分时停止计算 IC，仅输出收益描述；若研究收益延续性，应改名并显式设置不重叠窗口。

### LS-14（P2）：赢家标签在缺基准列时把绝对收益冒充超额收益

- 位置：`longterm_winner_profile_audit.py:115-122`, `longterm_market_winner_profile_audit.py:235-239`。
- 现象：缺 `excess_ret_*` 时直接令其等于 `ret_*`，随后仍使用“超额收益”阈值划分赢家/输家；前一个脚本还据此生成 `outperform`。
- 影响：强牛市中跟随指数上涨的股票可能被标为超额赢家，熊市中的相对赢家可能被漏掉。
- 建议：缺基准时将超额标签标为不可用；若提供绝对收益分类，使用不同组名和阈值。

## 方法局限与低风险偏差

1. `factor_audit.py:111-120` 用 `rank(method="first")` 后分位切桶，相同因子值会按行顺序拆到不同组。粗粒度/大量并列因子会产生顺序敏感的高低组差异。
2. `ic_analysis.py:243-255` 对汇总交易的 Spearman 相关直接套独立同分布 t 检验。每日 TopN 同源、持有窗口重叠，p 值通常偏乐观；应按选股日先算截面 IC，再做时间序列均值、Newey-West 或区块 bootstrap。
3. `longterm_pool_quality_audit.py:104-140` 对股票按其自身有效行情行数推进 80 日，对基准按指数行情推进 80 日。停牌股票的终点可能晚于基准终点，超额收益窗口不完全对齐。正常连续交易股票不受影响。
4. `longterm_pool_lifecycle_audit.py:190-204` 和 `longterm_pool_compression_audit.py:194-201` 把 80 日持有解释为日历日；`BacktestLongterm` 和 `ret_80d` 使用交易日。暴露/生命周期报告不能直接与 80 交易日结果对齐。
5. `main.py:5545-5561` 已加载前两日涨停/行业数据，但 `main.py:5590-5601` 明确传 `prev_stocks_list=None`。当前实际策略没有板块时序乘数，前面的 API/缓存读取是死工作，注释“用于板块时序乘数”与行为冲突。
6. `main.py:3914-3926` 的长线说明仍写 MA60 斜率、回调 5%~35%、行业 RS>-5%、距 MA60 5% 等旧规则；当前实现是回调 3%~35%、行业 RS>-8%、距 MA60 不超过 30%，并移除了 MA20 斜率硬过滤（`main.py:4095-4143`）。文档不能作为当前算法口径。
7. `strategy_profiles.py:210-219` 对未知 profile 名静默回退 `original/none`。CLI 的 choices 能防住拼写错误，但程序化配置错误会悄悄关闭正式门控。

## 80 日标签与当前页面“仍在观察”

`longterm_pool_quality_audit.py:104-126` 以选股日收盘为基准，在之后第 80 个交易日才生成 `ret_80d`；`longterm_history_importer.py:33-40`, `longterm_history_importer.py:77-84`, `longterm_history_importer.py:136-146` 只导入 CSV 已有值；`longterm_outcome_refresher.py:41-78` 才会依据 `history.db` 中的行情补算。因此页面显示 `t+83`（日历天）但仍未满 80 个交易日并不矛盾。若行情库最新仅到 6 月 30 日，刷新器也不可能补出其后的 80 日标签。

需要注意，刷新器的 `coalesce(new, old)`（`longterm_outcome_refresher.py:61-72`）只补空值，不会覆盖已成熟但后来因复权/数据修正而变化的旧值。这适合增量补齐，不适合数据版本重算。

## 逐文件覆盖表

| 文件 | 已审查内容 | 结果 |
|---|---|---|
| `main.py` | 双层市场状态、Override、周线宏观、短/长池、财务时点、正式 profile 接线 | 发现行情缺失放行、财务版本不确定、板块时序死链和说明过期；v18 缺宏观/财务时关闭 |
| `strategy_profiles.py` | profile 归一化、v9/v39、观察层、风格门控、风险公式 | 发现止损风险分母错误和静默 profile 降级；正式链路接线完整 |
| `longterm_live_pipeline.py` | 压缩池、行业限制、精英阈值 | 精英阈值方向合理；继承扫描次数窗口缺陷 |
| `backtest_v2.py` | T+1 准入、止损/止盈、涨跌停、移动止损、槽位净值、绩效 | 发现两项成交顺序错误和毛/净统计混用；当前 diff 的时点异常传播、封死跌停等待、固定槽位是正向改进 |
| `batch_backtest.py` | 引擎参数、年度区间、IC 汇总 | 发现正式参数脱节、no-timing 名不副实、短线 IC 选错列 |
| `ic_analysis.py` | 评分列、前瞻收益、相关和显著性 | 发现结果变量充当分数；重叠样本显著性偏乐观 |
| `factor_audit.py` | IC、分位层、稳定性比较 | 并列值分桶顺序敏感；适合作描述，不宜直接给参数因果结论 |
| `longterm_pool_quality_audit.py` | 10/40/80 日收益、MFE/MAE、基准 | 正常交易股票公式正确；停牌时股票/基准终点可能错位 |
| `longterm_history_importer.py` | CSV 导入、80 日字段、run 摘要 | 只导入已有标签，行为明确；不会主动补算未成熟结果 |
| `longterm_outcome_refresher.py` | 历史库补算、80 交易日成熟、摘要回写 | 成熟口径正确；只补空值，不支持数据版本重算 |
| `longterm_pool_compression_audit.py` | 重复度、压缩分、快照上限、计划退出 | 扫描次数冒充日数；计划退出按日历日 |
| `longterm_pool_alert_audit.py` | 冷却、精英阈值、分期汇总 | 阈值方向合理；冷却使用日历日，需明确口径 |
| `longterm_pool_lifecycle_audit.py` | 首次/连续入池、活跃池时间线 | 连续扫描逻辑合理；80 日活跃窗口使用日历日 |
| `longterm_pool_state_audit.py` | new/continue/exit 状态转换 | 按观测扫描更新，逻辑自洽；不是逐交易日持仓状态 |
| `longterm_pool_watchlist_audit.py` | 观察次数、晋级、首次出现年龄 | 晋级依赖扫描次数合理；日期整数相减错误 |
| `longterm_pool_path_diagnostics.py` | 80 日路径、MFE/MAE、回吐分类 | 路径分类方向合理；继承成熟窗口和停牌错位局限 |
| `longterm_factor_stability_audit.py` | 跨阶段赢家/坏票因子方向 | 适合作探索；默认最小组可为 1，不能据此宣称稳定 |
| `longterm_rank_sort_diagnostics.py` | 日内排名层、倒挂案例、因子相关 | 能发现排序倒挂；并列分数按首次顺序拆分 |
| `longterm_winner_profile_audit.py` | 赢家/输家标签、因子差 | 缺基准时把绝对收益当超额收益 |
| `longterm_market_winner_profile_audit.py` | 市场候选赢家标签、时点估值 | 估值按日截面读取；缺基准时标签语义错误 |
| `longterm_backtest_audit.py` | 重叠、组合暴露、退出原因 | 默认槽位权重与真实长线引擎不一致 |
| `longterm_candidate_quality_diagnostics.py` | 候选路径分组、TopN 质量 | 分类阈值方向合理；并列排名顺序敏感且是选择后诊断 |
| `longterm_loss_path_diagnostics.py` | 止损票、高 MFE 亏损、因子差 | 归因口径清楚；依赖回测退出原因和 MFE 正确性 |
| `longterm_signal_diagnostics.py` | 候选排名遗漏、高 MFE 回吐、入场分桶 | 描述性诊断合理；TopN 并列按输入顺序 |
| `longterm_trade_diagnostics.py` | 长线交易分数层、退出类型、极端样本 | 使用可用净收益列；聚合不能替代组合净值 |
| `longterm_value_quality_diagnostics.py` | 公告日前财务快照、质量分、远期收益 | 公告日过滤方向正确；单截面分位相关仅是探索性证据 |
| `candidate_rank_diagnostics.py` | 短线 Top3 与第 4-10 名遗漏 | 当日对照设计合理；并列 score 依赖原始行顺序 |
| `trade_diagnostics.py` | 胜负、分数层、因子差、退出分组 | 优先使用扣费收益；并列分位采用首次顺序，收益求和不是组合收益 |
| `trade_diff_diagnostics.py` | 基准/实验交易集合差异 | 交易键与增删比较清楚；增删收益相加未考虑槽位和时间重叠 |
| `drawdown_bucket_diagnostics.py` | 回调位置分桶、MFE/MAE、风格拆分 | 分桶边界明确；缺失收益被填 0 后计入非赢家 |
| `risk_combo_diagnostics.py` | 多因子风险规则命中、收益/MFE/MAE | 适合作筛查坏票集中度；同一交易可命中多规则，组间不能视为独立 |
| `winner_loser_factor_diagnostics.py` | 跨文件赢家/输家因子差 | 优先扣费收益；缺失收益填 0 会进入输家组 |
| `exit_attribution.py` | 退出原因、MFE 回吐、条件化出场 | 归因字段方向合理；结论继承回测的止盈顺序错误 |

## 当前 diff 评估

当前 diff 的两类算法改动值得保留：

- `main.py:1887-1918` 让离线历史 `stock_basic` 按截面日期读取，并复用同一时点的行业映射；`main.py:2360-2385` 避免离线代理错误读取默认目录财务缓存。这堵住了上市成员、退市成员和当前行业映射倒灌历史的问题。
- `backtest_v2.py:700-714`, `backtest_v2.py:828-885`, `backtest_v2.py:1008-1017` 使用开盘时可知的涨停价/前收盘判断买入准入，对封死跌停保留退出意图，末尾未成交则抛出异常。相比按跌停价假定成交或用买入价补平，更符合可成交性。

这些改动没有解决本报告的日内止盈优先级和涨停卖出语义，且回测说明中的“跌停按跌停价”“无固定持仓期”“波段兜底止盈 30%”等文字仍与当前实现存在差异，应在修复时同步校正。

## 验证边界

本次只读审查没有运行全量测试或昂贵回测。六个最小复现覆盖：空 CSI300、稀疏扫描窗口、止盈/时间止损同日、涨停日卖出、毛正净负与日期整数相减。它能证明对应分支的确定性错误，但不能量化修复后的年化收益、回撤变化或阈值最优性。阈值是否有效仍需在修复执行口径后，用固定策略版本、逐日截面 IC、时间分块和样本外区间重新验证。
