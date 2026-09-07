# research 审查缺陷修复记录（2026-09-07）

## 结论与证据边界

本轮只修改 `research/**`、研究专属测试和本记录。没有运行网络下载、全量训练或历史结果重算，也没有把旧报告数字改写成修复后的结果。修复后的严格研究入口会拒绝缺少逐样本标签退出日、历史证券主数据或已验证财务版本的数据。因此，现有 clean store、候选 CSV 和历史 `pass/ready` 报告均须视为旧口径；在完成下述数据重建和研究重跑前，它们不能继续充当上线证据。

机器可读证据资格位于 `research/research_evidence_status.json`，生成逻辑位于 `research/research_evidence_registry.py`。同样本搜索、毛收益、重叠标签曲线、已消费 holdout 和归档快照均带明确 blocker；`live_readiness_postmortem._readiness` 会把证据 blocker 加入拒绝理由，不能仅凭历史阈值返回 `ready`。归档另有 `research/strategy_archive/EVIDENCE_STATUS.json`，明确冻结为历史复现材料。

## D1-D11 修复状态

| 编号 | 状态 | 实现与影响范围 |
|---|---|---|
| D1 | 已修复，需重建数据后重跑 | `all_market_multi_engine_research._future_path` 现在随 `ret_3d/5d/8d` 写出真实 `label_exit_date_3d/5d/8d`；`build_clean_all_market_store` 保存这些字段。`research_integrity.purge_overlapping_label_tail` 以 `label_exit_date < prediction_start_date` 为严格条件，支持字符串、整数 YYYYMMDD 和时间戳；缺列或任一退出日缺失时 fail-closed。所有 clean 技术、财务、市场头、沪深分类、宽截面和 two-stage 年度拟合调用都显式传入预测起点。旧 store 缺列时必须重建，不能以固定行数或经验日历间隔声称无泄漏。 |
| D2 | 已修复 | `audit_clean_financial_relative_candidate.simulate_portfolio` 在边界内再次拒绝 `executed=False`，空成交直接返回空曲线。财务、期限对齐、宽截面等继承该账户模拟器的家族不再把锁定但未成交记录建仓。 |
| D3 | 已修复 | `apply_next_open_execution` 分开保存 `executed`、`label_matured`、`evaluable`、`execution_reason` 和 `evaluation_reason`。T+1 开盘存在且未超过买入 gap 上限即可记成交；未来路径不完整只影响是否可评价，不再倒改成交状态。 |
| D4 | 已修复 | `clean_shsz_bagged_top_decile_classifier_2019_2024.add_top_decile_target` 使用 nullable `Int64`，未来排名缺失仍为缺失，不再被编码为负类。 |
| D5 | 已修复 | `clean_broad_cross_sectional_rank.prepare_year` 和 `clean_walkforward_excess_downside_utility` 的预测池只按 T 日特征完整性建立；未来标签缺失保留到锁定后的评价状态，不再在 TopN 前递补其他股票。 |
| D6 | 已修复 | `clean_moneyflow_overlay`、`clean_breadth_gate`、`clean_equal_weight_market_gate` 均在 Top1 和冷却规则锁定后调用共享 T+1 execution helper，统计只消费 `evaluable` 记录，且不递补。 |
| D7 | 已修复 | `clean_limit_event_family.limit_threshold` 接收交易日；创业板 2020-08-24 前用 10% 制度近似阈值 9.3%，切换日起与科创板使用 18.5%。固定阈值仍是没有封单数据时的保守近似。 |
| D8 | 已修复 | 财务账户模拟器遇计划退出日停牌时维持旧估值并延迟到下一有效行情日退出；`high_confidence_abstention_audit.overlap_adjusted_portfolio` 用原 cohort 大小作分母，不再把缺价股票的权重转给幸存股票。 |
| D9 | 已修复 | `full_market_contrarian_candidates` 的候选分数与 TopN 不再读取 `tradeable` 或 `entry_gap_pct`。该修复也扩展到 all-market/quality/industry/post-earnings/volatility/moneyflow/high-momentum 等候选构造器；旧 CSV 中的未来成交列不再参与候选锁定。 |
| D10 | 已修复 | 8 日 MFE/MAE 只有 8 个 high/low 路径点全部存在才写值，部分窗口保持缺失。 |
| D11 | 方法限制，保持原语义 | `signal_date_drawdown` 仍只作为启发式信号日代理指标；未把它改称账户 MDD，也未据此新增通过结论。 |

## OR-01 至 OR-09 修复状态

| 编号 | 状态 | 实现与剩余边界 |
|---|---|---|
| OR-01 | 已修复 | `engine_multibucket_strategy_search` 两处 TopN 均通过 `lock_observable_topn`，并列只按 T 日分数和稳定代码键处理，未来 `ret` 不再打破并列。 |
| OR-02 | 已修复代码路径，需重建上游数据 | `all_market_multi_engine_research.tradeable` 已改成仅含 T 日条件；线性排序器、two-stage 和全部已定位候选构造器不再预筛旧 `tradeable`/T+1 gap。最终 T+1 状态只在锁定后判定。 |
| OR-03 | fail-closed | `_load_stock_info` 的严格默认要求 `data/cache/stock_basic_history/YYYYMMDD.parquet`；单份当前 `stock_basic.parquet` 会明确报错。存在历史快照时按 `ts_code + effective_date` backward as-of 合并。当前工作区没有核实可用的历史快照，故严格历史面板暂不能重建。 |
| OR-04 | 已修复 | `t3_confirmation_walkforward_validation` 每个 split 先仅按训练期 `train_score` 和稳定规则名锁定一个规则，再对测试期评价一次；结果排序不再使用测试期胜率或收益做规则选择。 |
| OR-05 | 证据用途已修复 | 大规模规则搜索保留为探索工具，`research_evidence_registry` 为所有审查定位的搜索器标记 `same_sample_optimization`；`live_readiness_postmortem` 读取 blocker 并强制 `research_only`。没有虚构新的样本外结果。 |
| OR-06 | 账户结论已禁止，未重算 | `two_stage_walkforward_research`、`walkforward_linear_ranker`、`full_market_event_research` 标记 `overlapping_horizon_not_account_curve`，旧的重叠 5 日序列不得解释为账户净值、账户回撤或独立逐日 Bootstrap。真正账户结论仍需用 sleeve/逐日持仓模拟重跑。 |
| OR-07 | 已修复命名 | `strategy_candidate_simulator` 将 2024H1 政名 `retrospective_2024H1`，2024H2-2025H1 政名 `development_2024H2_2025H1`；候选分类不再把前置时期当成前向 holdout。 |
| OR-08 | 证据用途已修复，未补造成本结果 | 毛收益或成交约束不完整的脚本统一标记 `gross_return_or_incomplete_execution`，不能用于 deployment ready。没有在缺乏盘口、滑点和容量数据时伪造“净收益”。 |
| OR-09 | 证据用途已修复 | 已参与验收/排序的 2025、2026 和 sealed 家族标记 `consumed_holdout`；所有名称含 `2019_2024` 的反复开发脚本另标记 `historical_validation_period_reused_for_development`。下一次独立确认必须使用尚未被研究决策消费的新时期。 |

## 实际改动覆盖矩阵

| 文件/家族 | 共享逻辑或直接修复 | 对应问题 |
|---|---|---|
| `research/research_integrity.py` | 严格真实退出日 purge、可观测 TopN、证据资格 | D1、OR-01、OR-05/06/08/09 |
| `research/research_evidence_registry.py`、`research/research_evidence_status.json` | 脚本级机器可读 blocker | OR-05/06/07/08/09 |
| `research/all_market_multi_engine_research.py`、`research/build_clean_all_market_store.py` | 真实标签退出日、完整 MFE/MAE、T 日资格、历史证券主数据 as-of/fail-closed | D1、D10、OR-02、OR-03 |
| `research/no_future_signal_pipeline.py` | 成交与标签成熟分离、统一 T 日候选资格 | D3、D6、D9、OR-02 |
| `research/clean_walkforward_technical_hgb*.py`、`clean_walkforward_excess*.py`、`clean_walkforward_cross_section_rank_hgb.py` | 年度边界显式 purge；同年随机校准改成日期前后切分 | D1、D5、M1 |
| `research/clean_walkforward_absolute_bagged_lcb_2019_2024.py`、`validate_walkforward_excess_bagged_lcb.py`、`clean_shsz_*2019_2024.py` | 每年成员样本先用真实退出日隔离再入训练池 | D1、D4 |
| `research/clean_bagged_lcb_market_*2019_2024.py` | 市场日标签携带实际退出日，年度模型显式 purge | D1 |
| `research/clean_financial_event_hgb.py`、`clean_financial_abstention.py`、`clean_financial_horizon_alignment.py`、`clean_financial_relative_validation.py`、`clean_financial_aligned5_sealed_2025.py`、`audit_clean_financial_aligned5_candidate.py` | 显式年度/校准起点、严格标签边界、财务版本验证 | D1、D2、D3、OR-03 |
| `research/point_in_time_financials.py`、`download_historical_financial_snapshots.py`、`post_earnings_*.py` | 未验证当前回拉数据标为 `point_in_time_verified=false`；严格入口拒绝 | M7、OR-03 |
| `research/audit_clean_financial_relative_candidate.py`、`high_confidence_abstention_audit.py` | 拒绝未成交、停牌延迟退出、缺价不重分配 | D2、D8 |
| `research/clean_moneyflow_overlay.py`、`clean_breadth_gate.py`、`clean_equal_weight_market_gate.py` | 锁定后共享成交与成熟判断 | D6 |
| `research/full_market_contrarian_candidates.py`、`walkforward_linear_ranker.py`、`two_stage_walkforward_research.py` | 移除未来可成交预筛；年度 purge | D9、OR-02、OR-06 |
| `research/quality_momentum_reentry.py`、`industry_relative_reversal_candidates.py`、`volatility_contraction_breakout.py`、`post_earnings_*.py`、`preregistered_nonlinear_broad_model.py`、`full_market_event_research.py`、`high_momentum_continuation_v13_2019_2026.py`、`moneyflow_breakout_factor_audit.py` | 候选排序不再读取 T+1 gap/旧 tradeable；高动量 gap 评分改为 T 日涨跌幅偏离 | OR-02 |
| `research/engine_multibucket_strategy_search.py` | 删除未来收益并列键 | OR-01 |
| `research/t3_confirmation_walkforward_validation.py` | train-only 选规则 | OR-04 |
| `research/strategy_candidate_simulator.py` | 证据阶段改名和分类降级 | OR-07、OR-08 |
| `research/live_readiness_postmortem.py` | blocker 进入 ready 判定 | OR-05 |
| `research/strategy_archive/EVIDENCE_STATUS.json` | 归档冻结、禁止作为当前/新 OOS 证据 | OR-03、OR-08/09 |

## 轻量回归覆盖

专属合成测试覆盖：成交/标签成熟分离、未成交账户拒绝、停牌延迟退出、缺价袖套分母、NaN 分类标签、候选不读 T+1、8 日路径完整性、创业板制度日期、真实退出日跨年 purge、旧 store fail-closed、整数日期解析、宽截面预测池、未来收益并列键、静态财务和证券主数据拒绝、证据 blocker、候选阶段命名。另更新既有研究夹具以携带 `trade_date`/`label_exit_date_5d`，并把“次日无开盘/涨停改变 T 日资格”的旧断言改为锁定后执行语义。

已执行的轻量验证不读取全市场数据，也不联网。最终测试数字以本次任务结束前最后一次 `pytest` 输出为准。

## 必须完成的数据迁移与重跑

1. 准备并核实历史证券主数据快照 `data/cache/stock_basic_history/YYYYMMDD.parquet`，至少包含当时的 `ts_code/name/industry`，并覆盖退市证券；当前单份 `stock_basic.parquet` 不满足严格研究。
2. 使用可证明历史首次公告版本的财务数据，为每条记录写入可信的 `point_in_time_verified=true`。当前按报告期在今天回拉的缓存会被明确标为 false。
3. 重新运行 `build_clean_all_market_store.py`，生成含 `label_exit_date_3d/5d/8d` 的 clean store。旧 parquet 缺列时严格拟合会报错，这是预期保护。
4. 删除“沿用旧 pass/ready 数字”的发布流程，按修复后候选、成交、purge 和账户契约重跑研究。2022-2024、2025/2026 及 sealed 已被消费，不能再命名为新的独立 holdout。
5. 使用尚未参与搜索或报告排序的新时间段做一次冻结验证；对需要账户结论的家族，使用逐日持仓/现金/停牌延期和费用模型，而非重叠 N 日标签累加。

未完成项均是需要外部历史数据、网络下载或昂贵重跑的工作，本轮按约束没有执行。代码层不会再静默降级为旧口径，也没有生成任何新的 OOS 或上线结论。
