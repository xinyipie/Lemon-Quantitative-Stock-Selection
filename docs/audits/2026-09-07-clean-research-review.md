# clean research 策略算法审查（2026-09-07）

## 范围与结论

本次只读审查覆盖 `research/` 下 65 个目标脚本：全部 `clean_*.py`、`build_clean*.py`、`audit_clean*.py`，以及 `point_in_time_financials.py`、`download_historical_financial_snapshots.py`、`validate_walkforward_excess_bagged_lcb.py`、`evaluate_locked_candidate_new_holdout.py`。先用 CodeGraph 定位调用关系，再逐文件读取或沿已核对的共享实现追踪；65 个文件也全部通过 AST 解析。没有修改生产代码或测试，也没有启动全量训练/回测。代码审读和小型复现均离线进行；D7 的历史交易制度由主审另行查阅深交所官方资料核实。

结论是：多数脚本的 T 日特征构造、先锁定候选再判断成交、财务公告日 `merge_asof`、按日/篮子聚合，以及部分家族内多重检验设计是合理的；但目前不能把这些结果整体视为严格无泄漏的样本外证据。发现 10 个确定代码或数据契约问题，其中 5 个会直接改变训练标签、入选股票或账户收益；另有 8 项方法限制（包含为便于引用而保留原编号的 D11）会使置信度高于证据本身。

最优先修复顺序：**D1 跨年标签泄漏 → D2 账户录入未成交记录 → D9 锁定候选用 T+1 信息预筛 → D4 缺失标签被编码为负类 → D5 预测池由未来标签完整性决定**。修复这些问题后，现有门槛、候选胜负和“通过/失败”状态均需重算。

## 确定问题

### D1（高）按信号年份切分，却未清除跨年持有标签

`all_market_multi_engine_research._future_path` 用下一交易日开盘和未来第 3/5/8 日价格生成标签（`research/all_market_multi_engine_research.py:145-181`）。技术基线按 `year` 取训练样本（`research/clean_walkforward_technical_hgb.py:87-96`），随后直接拟合并预测下一年（`research/clean_walkforward_technical_hgb.py:117-125`）；验证器也在预测完当年后把当年末样本直接追加到下一年训练池（`research/validate_walkforward_excess_bagged_lcb.py:61-88`）。财务模型同样只比较信号年份（`research/clean_financial_event_hgb.py:137-144`）。

可复现例子：2018-12-31 的 `ret_5d` 使用 2019 年交易日价格，却进入预测 2019 年的模型。也就是说，模型在回测 2019 年首个交易日前已经看过 2019 年价格。8 日目标应至少从每个训练段末尾清除最后 8 个可交易信号日；更稳妥的规则是按每条记录的实际退出日，要求 `label_exit_date < prediction_start_date`。修复后不必额外为历史特征设置长 embargo，但校准集与目标期之间也要应用同一 purge 规则。

影响：技术 HGB 中紧邻下一年预测的切分及其 excess/bagged/LCB 后代、2019-2024 市场头和沪深横截面家族、`clean_financial_event_hgb`、宽截面排序，以及 `two_stage_walkforward_research.walk_forward` 被锁定候选评估继承的年度排名层（该共享实现见 `research/two_stage_walkforward_research.py:247-269`）。使用“训练截至目标年前两年、前一年只做无标签分数校准”的 `clean_financial_abstention`/期限对齐/相对验证家族，以及 `clean_walkforward_technical_hgb_oos_calibrated`，在目标年之前留出一个完整校准年，不存在这项目标年标签泄漏。纯规则原型、事件、篮子脚本不受“模型训练”泄漏影响，但仍可能受 D3/D6/M4 的执行与缺失标签问题影响。

### D2（高）账户模拟器无视 `executed=False`

`apply_next_open_execution` 有意保留成交和未成交的锁定记录（`research/no_future_signal_pipeline.py:62-80`）。财务审计在 `research/audit_clean_financial_relative_candidate.py:55` 返回整张 execution 表，而 `simulate_portfolio` 在 `research/audit_clean_financial_relative_candidate.py:107-115` 对每一行排入建仓日，完全不检查 `executed`、`entry_open` 或 `net_ret`。同一模式由 `clean_financial_horizon_alignment.py:115-126`、`clean_financial_relative_validation.py:115-120,188`、`clean_financial_aligned5_sealed_2025.py:92-93`、`clean_broad_cross_sectional_rank.py:117-122,172` 继承。部分逐年汇总还使用 `len(group)`，把未成交行计入交易数。

最小复现：构造一条 `executed=False, entry_open=NaN, net_ret=NaN` 的交易，但缓存中下一日有该股票行情。模拟器仍建仓，得到类似：

```text
20200102 nav=0.9975 positions=1
20200103 nav=1.09725 positions=0
```

这会让账户收益、最大回撤、交易数和最终门槛建立在策略明确拒绝的交易上。调用账户模拟前必须筛 `executed == True`；模拟器自身也应拒绝无有效成交价的行，形成双重数据契约。

### D3（高）共享成交判断用未来结果完整性定义 T+1 是否成交

`apply_next_open_execution` 要求 `outcome.notna()` 才把记录标为成交（`research/no_future_signal_pipeline.py:70-77`）。未来第 N 日标签是否完整不会改变 T+1 是否已经成交；它只能决定该成交是否已经成熟、能否评价。最小输入 `entry_open=10, entry_gap_pct=0, ret_5d=NaN` 会得到 `executed=False, execution_reason="insufficient_path"`，把一笔已满足次日开盘条件的交易改写为未成交。将两种状态合并会让停牌、退市和数据尾部记录从“成交分母”中消失。

影响 `clean_archetype_family.py`、`clean_limit_event_family.py`、全部使用财务 execution helper 的脚本和 `clean_broad_cross_sectional_rank.py`。应分别保存 `executed_at_t1` 与 `label_matured`，前者只由 T+1 可见的证券状态和行情决定，后者负责评价状态。

### D4（高）Top-decile 分类器把缺失未来排名编码成负类

`research/clean_shsz_bagged_top_decile_classifier_2019_2024.py:33-38` 执行 `(rank_target >= 0.90).astype(int)`；在 pandas 中 `NaN >= 0.90` 为 `False`，因此缺失未来收益的行被永久编码为 0。后续 `dropna` 检查的是已经没有 NaN 的二元列（`research/clean_shsz_bagged_top_decile_classifier_2019_2024.py:54-60`），无法剔除这些伪负类，并在每年末追加到下一年训练池（`research/clean_shsz_bagged_top_decile_classifier_2019_2024.py:100-110`）。

最小复现：`pd.Series([np.nan, .95]).ge(.90).astype(int).tolist()` 得到 `[0, 1]`。应先保留缺失状态，再只对非缺失排名生成 0/1 标签。影响该 top-decile 分类器及其输出的全部判定。

### D5（高）未来标签完整性改变当年预测候选池

`clean_walkforward_excess_downside_utility.py` 从未来收益构造 downside 标签（`research/clean_walkforward_excess_downside_utility.py:31-40`），却在预测当年先对 `FEATURES + [DOWNSIDE_TARGET]` 做 `dropna`（`research/clean_walkforward_excess_downside_utility.py:57-58`）。`clean_broad_cross_sectional_rank.prepare_year` 也先构造未来收益排名，再返回仅保留 `target_rank_5d` 非空的行（`research/clean_broad_cross_sectional_rank.py:71-79`）。

这不只是评价时剔除右删失样本：若当日最高预测股票的未来路径缺失，它会在排序前消失，低分股票会递补。预测池只能按 T 日特征完整性建立；未来标签完整性应在锁定后作为“未完成/不可评价”状态报告。影响 downside utility 和 broad cross-sectional rank 全链路。

### D6（中）三套规则策略完全绕过次日成交检查

`clean_moneyflow_overlay.build_variant_candidates` 锁定 Top1 后只检查 `ret_8d`（`research/clean_moneyflow_overlay.py:159-175`）；`clean_breadth_gate.select_variant` 同样只检查结果标签（`research/clean_breadth_gate.py:99-120`）；`clean_equal_weight_market_gate.select_variant` 也是如此（`research/clean_equal_weight_market_gate.py:95-116`）。三者虽从存储读取 `entry_open/entry_gap_pct`，却未使用。

结果会包含无次日开盘或达到策略所设买入涨停阈值的信号，且与报告中其他“先锁定、不可成交不递补”的口径不一致。影响这三个家族的 baseline、所有 overlay/gate 变体及其增量比较。

### D7（中）涨停事件阈值忽略创业板历史制度切换

`clean_limit_event_family.limit_threshold` 对所有 `300/301` 代码固定返回 18.5%（`research/clean_limit_event_family.py:32-38`）。创业板在 2020-08-24 前是 10% 涨跌幅，因此 2016 至制度切换前的大量真实涨停不会被识别；“20 日首次/重复涨停”历史也随之错误。阈值函数应同时接收交易日期，并按板块、日期和当日证券状态确定阈值。影响三个涨停事件定义及其 27 个配置。

主审补充联网核实：深交所 2020-08-21 [创业板注册制首批企业上市安排答记者问](https://www.szse.cn/aboutus/trends/news/t20200821_580924.html) 明确存量创业板股票自 8 月 24 日起涨跌幅限制调整为 20%；深交所此前的 [创业板交易特别规定说明](https://investor.szse.cn/index/update/t20200729_580056.html) 说明改革前竞价交易涨跌幅限制比例为 10%。本子任务本身仍按离线代码审读执行，以上官方来源由主审补充核实。

### D8（中）组合路径在缺行情时按旧值强制退出或把权重转给幸存股票

账户模拟器在某日缺少持仓行情时跳过盯市（`research/audit_clean_financial_relative_candidate.py:129-135`），但只要该日是计划退出日，就按旧 `value` 变现（`research/audit_clean_financial_relative_candidate.py:154-160`）。停牌时这不是可实现的退出。另一共享组合函数对缺收盘价的股票直接 `continue`，随后对剩余股票求均值并给予完整袖套权重（`research/high_confidence_abstention_audit.py:93-105`）；已计算的 `cohort_size` 没有用于保持原权重（`research/high_confidence_abstention_audit.py:76-78`）。

前者影响所有调用 `simulate_portfolio` 的财务、宽截面和技术账户指标；后者影响 `clean_financial_event_hgb.py` 的重叠路径和 `evaluate_locked_candidate_new_holdout.py`。应明确停牌估值与延迟退出规则，并让缺价仓位维持原权重/现金，而不是把权重重新分配给有价股票。

### D9（高）“锁定候选新增样本”在排序前使用 T+1 信息

`evaluate_locked_candidate_new_holdout.py:55-56` 先构建面板并调用 `full_market_contrarian_candidates.build_candidates`。该构造器在计算分数和 Top50 前要求 `tradeable` 且 `entry_gap_pct.between(-4, 6)`（`research/full_market_contrarian_candidates.py:38-50`），而这些字段来自 T+1 开盘。排序发生在过滤之后（`research/full_market_contrarian_candidates.py:53-70`）。

因此，如果真正的 T 日高分股次日不可成交，回测会提前删除它并让低分股递补；这与“锁定候选后不递补”相反。随后年度模型的排序结果（`research/two_stage_walkforward_research.py:247-305`）建立在已被未来开盘筛过的候选上。影响 `evaluate_locked_candidate_new_holdout.py` 对逆向候选的全部新增样本结论。应仅用 T 日信息生成候选和模型排名，最后对锁定结果应用独立的成交状态。

### D10（中）8 日 MFE/MAE 会接受不完整路径

共享标签生成用逐日路径列的 `max(axis=1)` / `min(axis=1)`（`research/all_market_multi_engine_research.py:163-181`）；pandas 默认 `skipna=True`。只要 8 日路径中有任意一天存在，就可能产生非空 `mfe_8d/mae_8d`，字段名却暗示完整 8 日窗口。`audit_clean_return_labels.py` 要求 `ret_8d` 完整后才核查，因而不会发现只在 MFE/MAE 字段上的部分窗口。

影响所有使用或输出这两个路径标签的 clean store、原型/事件分析和报告。应在 8 个路径点全部有效时才写 8 日 MFE/MAE，或同时存储 `path_observations` 并明确部分窗口语义。

### D11（方法限制，保留编号）`signal_date_drawdown` 是启发式代理指标

`clean_momentum_exit_family._metrics` 将每笔总收益除以持有天数，按信号日取均值后做加法累计（`research/clean_momentum_exit_family.py:138-149`），结果明确命名为 `signal_date_drawdown`，并以 `>-20%` 作为一个通过门槛（`research/clean_momentum_exit_family.py:198-203`）。它没有构造持仓重叠、资金占用、逐日复利或退出当天现金流，因此不能用来推断账户最大回撤；代码和报告中未发现把它明确宣称为账户 MDD 的证据。

影响所有动量退出配置的启发式风险门槛。保留该指标本身是合理的，但通过状态只能解释为通过这项代理压力检查，不能据此声称通过账户回撤约束；`clean_delayed_confirmation.py` 只复用了路径读取函数，没有复用这个指标。

## 方法限制与证据解释

### M1 同年随机 80/20 校准并非独立时间校准

`clean_walkforward_technical_hgb_holdout_calibrated.split_fit_and_calibration` 对每年所有股票行随机洗牌再切 80/20（`research/clean_walkforward_technical_hgb_holdout_calibrated.py:28-42`）。小型合成实验用 12 个连续交易日、每天 20 只股票，得到 `fit_dates=12`、`calibration_dates=11`、`same_dates_in_both=11`，且同一股票在 5 个交易日以内跨分区的样本对有 263 个。因而市场日冲击和重叠 5 日标签几乎必然跨分区。

该脚本的阈值只取校准预测分布的 99% 分位（`research/clean_walkforward_technical_hgb_holdout_calibrated.py:50-56`），没有直接用校准标签挑阈值，所以这里不是“读取下一预测年收益”的确定泄漏；问题是留出集不独立，无法支持“独立校准”的解释。`oos_calibrated` 用前一整年做校准，时间结构更合理；`train_calibrated` 用拟合内预测分位，只能称训练分布阈值。

### M2 2022-2024 被同一研究计划反复用于新变体选择

初始验证器把 2022-2024 定义为一次性独立验证（`research/validate_walkforward_excess_bagged_lcb.py:49-90`），但后续多个脚本读取同一 internal/validation 结果并继续设计和比较市场头、硬门、rolling3y、HGB 分类、成本门、尾部风险 veto、沪深条件排名和退出变体。典型入口见 `clean_bagged_lcb_existing_regime_gate.py:126-141`、`clean_bagged_lcb_market_head_2019_2024.py:109-125`。

单个脚本可能保持参数冻结，但整个目录已经对同一时期进行多次选择，且没有跨脚本 family-wise correction。故 2022-2024 应视为开发/二级验证集，不能再作为最终独立 holdout。`evaluate_locked_candidate_new_holdout.py:116` 对 2026-07-01 至 2026-08-07 的样本也正确承认它不是自然流逝的实时前瞻样本；其 `month_count >= 6` 门槛（`evaluate_locked_candidate_new_holdout.py:87-95`）在当前约一个月区间内必然失败，是合理的安全门而非 bug。

### M3 三成员 `mean - std` 不是统计意义的置信下界

`clean_walkforward_excess_bagged_lcb.conservative_score` 对仅三个模型计算总体标准差 `ddof=0`，再取 `mean - std`（`research/clean_walkforward_excess_bagged_lcb.py:33-39`）。成员模型结构相同且训练样本高度重叠，三点离散度既没有覆盖率保证，也不是预测误差或收益分布的下置信界；`ddof=0` 还会进一步缩小离散度。所有名称含 bagged LCB 的后续策略可把它当启发式分歧惩罚，但不应把它解释为概率校准或统计置信度。

### M4 完整标签筛选带来右删失/停牌/退市选择偏差

多数组合在锁定后要求 `ret_3d/5d/8d.notna()` 才纳入统计，例如技术基线 `research/clean_walkforward_technical_hgb.py:151-158`。剔除数据文件末端尚未成熟的信号是必要的，但把停牌、退市、缺数据也静默删除会选择性排除难以交易的路径。建议分别报告 `locked / execution_eligible / executed / label_matured / label_missing_reason`，并保留锁定信号分母。

### M5 策略与基准的可交易池、成本和缺失值口径不一致

技术基线的日基准是全部 predictions 的未来收益均值减固定成本（`research/clean_walkforward_technical_hgb.py:175-176`），验证器同样如此（`research/validate_walkforward_excess_bagged_lcb.py:78-80,106`）；规则篮子/市场门也多用 `groupby(date).mean() - 0.25`。基准没有应用与策略相同的次日成交掩码、缺失标签规则和持仓容量，策略却只保留少数可成交股票。因此“edge vs universe”混合了选股能力与样本口径差异。应在同一 T 日候选池和同一成交规则下构造基准，并另报对 CSI300 的同期可实现收益。

执行阈值本身也只是近似：共享 helper 固定使用 9.5% 上界（`research/no_future_signal_pipeline.py:65-76`），技术/篮子家族固定使用 `-9.5%` 下界和 `7%` 上界。它们没有按板块、日期、ST 状态或真实封单处理制度差异。上界会保守排除创业板/科创板部分仍可交易的高开，下界不是“跌停无法买入”的充分条件，因此都不应解释为精确成交模型。

### M6 重叠持有期使行级均值、盈亏比和普通检验过度自信

每日信号的 5/8 日收益高度重叠，个股行、同日股票和相邻日期都不是独立观测。部分脚本已经按日/篮子聚合，`clean_archetype_family`、`clean_limit_event_family`、`clean_delayed_confirmation` 也做了家族内校正，这是优点；但很多接受门槛仍同时依赖行级交易数、普通 profit factor 或未校正 Sharpe。应以不重叠再平衡篮子或真实账户日收益作为主要抽样单位，并使用时间块 bootstrap；即便如此也需把 M2 的跨脚本选择计入。

### M7 历史财务值是否真为首次公告版本尚未验证

`point_in_time_financials.prepare_financial_events` 按 `ann_date` 排序并保留报告期第一次公告（`research/point_in_time_financials.py:13-36`），`merge_point_in_time` 使用 backward `merge_asof`（`research/point_in_time_financials.py:39-57`），财务候选又要求公告后至少 1 日，时间对齐设计本身合理。但下载脚本按报告期在当前时间拉取 `fina_indicator`，字段不含版本/更新标志，并按 `ts_code, ann_date, end_date` 去重（`research/download_historical_financial_snapshots.py:19-47`）。无法仅从代码证明数值是当年首次公告时可见版本，而非数据商当前修订值。需抽样对照修订历史后，才能把该缓存称为严格 point-in-time fundamentals。

## 各策略家族合理性判断

| 家族 | 合理部分 | 主要阻断项 | 当前判断 |
|---|---|---|---|
| clean store / 标签审计 / PIT 财务 | T 日特征与未来标签分栏；公告日 backward join；有标签重建审计 | D10、M7；标签审计未覆盖全部缺失原因 | 数据骨架可用，路径完整性和财务版本需补证 |
| 原型、资金流、广度、等权市场门 | 截面排名、先定候选族、训练/确认分段直观 | D3、D6、M4-M6 | 原型思想合理；三套 overlay 的成交结果目前不可采信 |
| 涨停、延迟确认、动量退出 | 延迟确认确实在 T+1 收盘确认、T+2 开盘进入；事件家族有家族校正 | D3、D7、D11 | 延迟确认时间顺序较好；事件历史和风险门需修 |
| 低风险/三日反转篮子、因子发现 | 非重叠再平衡、按篮子统计；因子发现期做 BH 校正并冻结到确认期 | M4-M6；固定阈值仍是研究选择 | 是目录中证据结构较好的家族，仍不能把完整标签样本当全体成交 |
| 财务 HGB、弃权、相对置信、期限对齐 | 财务至少滞后 1 日；部分校准使用前一年；先锁定 Top1 再门控 | D1-D3、D8、M4/M7 | 特征时间设计较好，但账户和年度切分错误会改变结论 |
| 技术 HGB 与校准变体 | 特征均为 T 日；模型复杂度受限；直接执行器有缺口上下界 | D1、D5（宽截面）、M1/M4-M6 | 可作为研究基线，现有 OOS 数字不严格 |
| excess/bagged/LCB 与退出/风险 gate | 目标减同日均值能削弱市场 beta；Top3 cohort 比逐股统计好 | D1/D5/D8、M2-M6 | 模型思路合理，LCB 名称和证据强度明显超出实际统计含义 |
| 2019-2024 市场头/沪深条件族 | 年度扩展训练、行业分散和风险 veto 有经济含义 | D1/D4、M2-M6 | 属同一开发集上的大量二次搜索，不能再称独立确认 |
| 锁定逆向候选新样本 | 冻结配置、设 6 个月最低证据、明确非实时前瞻 | D8/D9；样本不足 | 安全门合理，但当前候选构造含 T+1 预筛，结果需作废重算 |

## 逐文件覆盖表

“共享”表示该文件的主体是薄包装器，已同时核对它继承的核心函数；不是只看文件名推断。

| # | 文件 | 策略家族 | 覆盖方式 | 关联问题 |
|---:|---|---|---|---|
| 1 | `audit_clean_financial_aligned5_candidate.py` | 财务 aligned-5 审计 | 已读；共享财务预测、execution、账户模拟 | D2、D3、D8、M4-M7 |
| 2 | `audit_clean_financial_relative_candidate.py` | 财务相对候选/账户 | 已读核心选择、扰动、组合模拟 | D2、D3、D8、M4-M7 |
| 3 | `audit_clean_return_labels.py` | 标签重建审计 | 已读重建、抽样和容差逻辑 | D10、M4 |
| 4 | `build_clean_all_market_store.py` | clean 全市场存储 | 已读；共享 `build_year_panel/_future_path` | D10、M4 |
| 5 | `build_clean_moneyflow_store.py` | 资金流存储 | 已读下载合并/滚动特征 | M7（数据版本类比，不涉及财务） |
| 6 | `clean_archetype_family.py` | 规则原型家族 | 已读候选、执行、家族校正 | D3、M4-M6 |
| 7 | `clean_bagged_lcb_existing_regime_gate.py` | LCB 既有 regime gate | 已读 gate/evaluate；共享 excess 交易 | D1、M2-M6 |
| 8 | `clean_bagged_lcb_market_head_2019_2024.py` | LCB 市场回归头 | 已读市场目标、年度预测、gate | D1、M2-M6 |
| 9 | `clean_bagged_lcb_market_head_hard_gate_2019_2024.py` | 市场头硬门 | 已读薄 gate；共享市场头 | D1、M2-M6 |
| 10 | `clean_bagged_lcb_market_head_rolling3y_2019_2024.py` | rolling-3y 市场头 | 已读滚动训练/gate；共享市场头 | D1、M2-M6 |
| 11 | `clean_bagged_lcb_market_hgb_classifier_2019_2024.py` | 市场方向分类器 | 已读分类目标、年度训练、gate | D1、M2-M6 |
| 12 | `clean_bagged_lcb_market_rolling3y_cost_gate_2019_2024.py` | 市场头+成本门 | 已读薄 gate；共享 rolling 市场头 | D1、M2-M6 |
| 13 | `clean_bagged_lcb_market_tail_risk_classifier_2019_2024.py` | 市场尾部风险分类 | 已读分类目标、年度 veto | D1、M2-M6 |
| 14 | `clean_breadth_gate.py` | 广度门控 | 已读广度状态、选择、门槛 | D6、M4-M6 |
| 15 | `clean_broad_cross_sectional_rank.py` | 宽截面排名 HGB | 已读面板、排名目标、WF、账户 | D1-D3、D5、D8、M4-M6 |
| 16 | `clean_delayed_confirmation.py` | T+1 确认/T+2 入场 | 已读逐路径进入和退出 | D3、M4-M6 |
| 17 | `clean_equal_weight_market_gate.py` | 等权市场门控 | 已读市场特征、gate、edge | D6、M4-M6 |
| 18 | `clean_factor_discovery_confirmation.py` | 因子发现/确认 | 已读 BH、低相关选择、确认门槛 | M4-M6 |
| 19 | `clean_financial_abstention.py` | 财务高置信弃权 | 已读年度训练/前一年校准/执行 | D2、D3、M4-M7 |
| 20 | `clean_financial_aligned5_sealed_2025.py` | 财务 aligned-5 sealed | 已读 2025 构建、锁定、账户 | D2、D3、D8、M4/M7 |
| 21 | `clean_financial_event_hgb.py` | 财务事件 HGB | 已读 PIT 候选、WF、账户路径 | D1、D3、D8、M4-M7 |
| 22 | `clean_financial_horizon_alignment.py` | 财务期限对齐 | 已读 5/8 日目标、预测和汇总 | D2、D3、D8、M4-M7 |
| 23 | `clean_financial_relative_confidence.py` | 财务相对置信 | 已读阈值、cooldown、gate | D2、D3、M4-M7 |
| 24 | `clean_financial_relative_validation.py` | 财务相对首次验证 | 已读分段、验证 WF、账户 | D2、D3、D8、M4-M7 |
| 25 | `clean_limit_event_family.py` | 涨停事件家族 | 已读历史、阈值、27 配置/校正 | D3、D7、M4-M6 |
| 26 | `clean_low_risk_reversal_basket.py` | 五日低风险反转篮子 | 已读 5 偏移、篮子汇总 | M4-M6 |
| 27 | `clean_momentum_exit_family.py` | 动量退出家族 | 已读逐股路径退出和风险指标 | D11、M4-M6 |
| 28 | `clean_moneyflow_overlay.py` | 资金流 overlay | 已读资金流滚动、4 变体、门槛 | D6、M4-M6 |
| 29 | `clean_risk_adjusted_bagged_lcb_market_2019_2024.py` | 风险调整 LCB+市场 | 已读双模型分数；共享 LCB/market | D1、M2-M6 |
| 30 | `clean_sector_diverse_bagged_lcb_market_2019_2024.py` | 行业分散 LCB+市场 | 已读行业约束执行；共享 LCB/market | D1、M2-M6 |
| 31 | `clean_shsz_bagged_cross_section_rank_2019_2024.py` | 沪深截面排名 bagging | 已读 rank target/年度 bagging | D1、M2-M6 |
| 32 | `clean_shsz_bagged_lcb_high_conf_tail_veto_2019_2024.py` | 沪深高置信尾部 veto | 已读薄 veto；共享市场尾部模型 | D1、M2-M6 |
| 33 | `clean_shsz_bagged_top_decile_classifier_2019_2024.py` | 沪深前十分位分类 | 已读标签、采样、年度分类 | D1、D4、M2-M6 |
| 34 | `clean_shsz_conditional_rank_existing_exit_2019_2024.py` | 沪深条件排名+既有退出 | 已读薄退出；共享条件排名 | D1、D8、M2-M6 |
| 35 | `clean_shsz_conditional_risk_rank_2019_2024.py` | 沪深条件风险排名 | 已读 eligibility/ranking；共享双模型 | D1、M2-M6 |
| 36 | `clean_three_day_reversal_basket.py` | 三日反转篮子 | 已读 3 偏移、篮子汇总 | M4-M6 |
| 37 | `clean_walkforward_absolute_bagged_lcb_2019_2024.py` | 绝对收益 bagged LCB | 已读年度采样/预测/evaluate | D1、M2-M6 |
| 38 | `clean_walkforward_cross_section_rank_hgb.py` | 截面 rank HGB | 已读目标、年度预测；共享执行 | D1、M4-M6 |
| 39 | `clean_walkforward_excess_bagged3.py` | excess 三成员 bagging | 已读分年采样/均值预测 | D1、M3-M6 |
| 40 | `clean_walkforward_excess_bagged_lcb.py` | excess LCB | 已读 mean/std/LCB 和执行 | D1、M2-M6 |
| 41 | `clean_walkforward_excess_bagged_lcb_3d_2019_2024.py` | 3 日 excess LCB | 已读 3 日标签/Top3；共享 LCB | D1、M2-M6 |
| 42 | `clean_walkforward_excess_corrected_scale.py` | excess 尺度修正 | 已读薄缩放 wrapper；共享 excess | D1、M4-M6 |
| 43 | `clean_walkforward_excess_corrected_top1.py` | excess Top1 | 已读 Top1 执行；共享 excess | D1、M4-M6 |
| 44 | `clean_walkforward_excess_downside_utility.py` | excess/downside utility | 已读双目标、utility、评估 | D1、D5、M4-M6 |
| 45 | `clean_walkforward_excess_existing_exit.py` | excess 既有退出 | 已读压力成本/账户归一化/退出 | D1、D8、M4-M6 |
| 46 | `clean_walkforward_excess_falling_breadth_gate.py` | excess 广度下降 gate | 已读广度特征/gate；共享 excess | D1、M4-M6 |
| 47 | `clean_walkforward_excess_positive_abstention.py` | excess 正预测弃权 | 已读薄 abstention；共享 excess | D1、M4-M6 |
| 48 | `clean_walkforward_excess_rolling3y.py` | excess rolling-3y | 已读滚动切分/预测 | D1、M4-M6 |
| 49 | `clean_walkforward_excess_tail_risk.py` | excess 双模型尾部风险 | 已读风险标签、双模型、Top3 | D1、D8、M4-M6 |
| 50 | `clean_walkforward_technical_hgb.py` | 技术 HGB 基线 | 已读特征、年度 WF、执行、指标 | D1、M4-M6 |
| 51 | `clean_walkforward_technical_hgb_daily_top3.py` | 技术 HGB 每日 Top3 | 已读锁定、cohort、执行 | D1、M4-M6 |
| 52 | `clean_walkforward_technical_hgb_daily_top3_account.py` | Top3 账户路径 | 已读账户指标；共享错误模拟器 | D1、D8、M4-M6 |
| 53 | `clean_walkforward_technical_hgb_excess_8d.py` | 技术 8 日 excess | 已读 8 日标签/适配评估 | D1、M4-M6 |
| 54 | `clean_walkforward_technical_hgb_excess_risk_gate.py` | excess 既有风险 gate | 已读风险状态掩码/evaluate | D1、D8、M4-M6 |
| 55 | `clean_walkforward_technical_hgb_excess_target.py` | 技术 excess 主干 | 已读 excess 目标/WF/账户 | D1、D8、M4-M6 |
| 56 | `clean_walkforward_technical_hgb_holdout_calibrated.py` | 随机留出校准 HGB | 已读拆分、阈值、执行 | D1、M1、M4-M6 |
| 57 | `clean_walkforward_technical_hgb_oos_calibrated.py` | 前一年 OOS 校准 HGB | 已读时间切分、阈值、执行 | M4-M6 |
| 58 | `clean_walkforward_technical_hgb_relative_top1.py` | 相对 Top1 HGB | 已读相对门槛/执行 | D1、M4-M6 |
| 59 | `clean_walkforward_technical_hgb_top5_basket.py` | 技术 Top5 篮子 | 已读篮子锁定/执行/汇总 | D1、M4-M6 |
| 60 | `clean_walkforward_technical_hgb_train_calibrated.py` | 拟合内校准 HGB | 已读训练预测分位/执行 | D1、M1、M4-M6 |
| 61 | `clean_walkforward_technical_hgb_zscore_abstention.py` | 日截面 z-score 弃权 | 已读 zscore/执行/evaluate | D1、M4-M6 |
| 62 | `download_historical_financial_snapshots.py` | 历史财务下载 | 已读字段、分期请求、去重 | M7 |
| 63 | `evaluate_locked_candidate_new_holdout.py` | 锁定候选新增样本 | 已读全流程；追踪候选和账户依赖 | D8、D9、M2/M4-M6 |
| 64 | `point_in_time_financials.py` | PIT 财务工具 | 已读准备、去重、asof join | M7 |
| 65 | `validate_walkforward_excess_bagged_lcb.py` | excess LCB 独立验证 | 已读年度扩展、Top3、cohort、门槛 | D1、M2-M6 |

## 小型验证与未验证范围

完成的安全验证：

- 65 个目标文件均以 `ast.parse` 成功解析。
- 用极小 DataFrame 复现 D2：`executed=False` 行仍进入账户并产生收益。
- 用单行 DataFrame 复现 D3：有效 T+1 开盘且 0% 缺口，只因 `ret_5d=NaN` 就被共享 helper 标为未成交。
- 用两元素 Series 复现 D4：缺失排名被编码为 0。
- 用 12 日 × 20 股票合成面板复现 M1：随机 fit/calibration 在 11 个日期重叠，且存在 263 个同股票、5 日内跨分区样本对。

D2-D4 的实际执行脚本（只在临时目录写入 3 个极小 parquet）：

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
import pandas as pd
from research.audit_clean_financial_relative_candidate import simulate_portfolio
from research.no_future_signal_pipeline import apply_next_open_execution
from research.clean_shsz_bagged_top_decile_classifier_2019_2024 import (
    add_top_decile_target, RANK_TARGET, TOP_DECILE_TARGET,
)

with TemporaryDirectory() as d:
    daily = Path(d) / "daily"
    daily.mkdir()
    for date, close, pct in [("20200101", 10.0, 0.0), ("20200102", 10.0, 0.0), ("20200103", 11.0, 10.0)]:
        pd.DataFrame({"ts_code": ["000001.SZ"], "open": [10.0], "close": [close], "pct_chg": [pct]}).to_parquet(daily / f"{date}.parquet")
    rejected = pd.DataFrame({
        "trade_date": ["20200101"], "ts_code": ["000001.SZ"],
        "executed": [False], "entry_open": [np.nan], "net_ret": [np.nan],
    })
    print("D2", simulate_portfolio(rejected, cache_dir=Path(d), slots=1, holding_days=2).to_dict("records"))

immature = pd.DataFrame({"entry_open": [10.0], "entry_gap_pct": [0.0], "ret_5d": [np.nan]})
print("D3", apply_next_open_execution(immature).loc[0, ["executed", "execution_reason", "net_ret"]].to_dict())
ranked = add_top_decile_target(pd.DataFrame({RANK_TARGET: [np.nan, .95]}))
print("D4", ranked[TOP_DECILE_TARGET].tolist())
```

实际输出：

```text
D2 [{'trade_date': '20200102', 'nav': 0.9975, 'cash': 0.0, 'positions': 1},
    {'trade_date': '20200103', 'nav': 1.09725, 'cash': 1.09725, 'positions': 0}]
D3 {'executed': False, 'execution_reason': 'insufficient_path', 'net_ret': None}
D4 [0, 1]
```

M1 的实验直接调用 `split_fit_and_calibration`，输入仅含 2018 年 12 个连续交易日、每天 20 个股票、所有 `FEATURES` 为 0、`TARGET` 为 1。固定随机种子下实际输出为：

```text
fit_rows=192 calibration_rows=48 fit_dates=12 calibration_dates=11
same_dates_in_both=11 same_stock_cross_partition_pairs_within_5_sessions=263
```

未验证范围：没有读取网络数据商文档或核验 Tushare 历史修订语义；没有重新生成 parquet、重新训练 HGB、重跑 bootstrap 或验证报告中的历史数值；没有检查 65 个脚本之外所有候选构造器的每一种策略，只追踪了本范围实际继承且与结论相关的共享函数；没有验证真实涨跌停是否封单、逐笔成交量、冲击成本、复权方法和退市现金流。上述未验证项不削弱 D1-D10 的确定代码结论，也不改变 D11 的代理指标用途边界，但会限制修复后业绩数值的解释。
