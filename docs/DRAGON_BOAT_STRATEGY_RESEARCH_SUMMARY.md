# 端午策略研究阶段总结

> 研究状态：阶段性结论。本文只记录 research 证据，不代表上线策略变更。

## 研究边界

- 短线正式版保持：`profile_v4_adaptive_quality_v9_sector_quality_guard + baseline exit + Top3`。
- 长线当前研究版保持：`longterm_quality_lifecycle_v18_market_sync`。
- 本轮新增内容只读历史 CSV 和报告，不改 `main.py` 默认策略，不写交易执行逻辑。
- 2026 数据只作为参考，不作为唯一决策依据。

## 新增研究工具

| 工具 | 作用 | 默认命令 |
|---|---|---|
| `research/strategy_research_overview.py` | 汇总短线 v9、长线 v18 已有证据 | `python research/strategy_research_overview.py --output reports/research/dragon_boat_research_overview.md` |
| `research/strategy_factor_stability.py` | 做跨文件因子稳定性诊断 | `python research/strategy_factor_stability.py --output reports/research/dragon_boat_factor_stability.md` |
| `research/strategy_layer_quality.py` | 比较 TopN 与全样本，判断分数是否只在头部有效 | `python research/strategy_layer_quality.py --output reports/research/dragon_boat_layer_quality.md` |
| `research/strategy_candidate_simulator.py` | 对保守候选 research rule 做跨区间离线模拟 | `python research/strategy_candidate_simulator.py --output reports/research/dragon_boat_candidate_simulation.md` |

## 短线 v9 结论

### 目前证据

- 分层诊断显示：短线 v9 的 Top1、Top3、Top5 相对全候选有质量优势，说明当前 Top3 定板不是拍脑袋。
- 但因子稳定性显示：单个线性因子没有稳定正相关项，`score` 本身在不同文件/阶段里表现不稳定。
- 候选模拟显示：
  - `short_v9_top1_concentration` 没有跨区间改善，验证段和 2026 参考段都弱于 Top3。
  - `short_v9_sector_flow_tiebreak_top3` 变差，不建议继续。
  - `short_v9_quality_floor_top3` 整体略好，但验证段弱于基准，只能继续观察，不能升级。

### 判断

短线 v9 仍有优化空间，但不适合再靠简单加权微调。当前最稳妥做法是保留 v9 Top3，后续重点研究：

- 是否改善出场与持有体验，而不是强改入选评分。
- 对“有效信号/观察信号/弱信号”做更好的实盘提示，但不要直接改变 Top3 逻辑。
- 用新增实盘数据持续更新分层诊断，确认 v9 是否阶段性失效。

## 长线 v18 结论

### 目前证据

- 分层诊断显示：长线 v18 的 Top1/Top3 并不优于全池，Top10 接近或略好。
- 候选模拟显示：
  - `long_v18_top10_watchlist` 相比 Top3 在训练段和验证段都更好。
  - `long_v18_quality_floor_top10` 也更好，且逻辑更符合长线：先用财务和行业强度做质量地板，再做观察池。
  - `long_v18_quality_rs_rerank_top10` 与 Top10 类似，未证明重排明显优于简单扩大观察池。
- 这说明 v18 的核心问题不是“池子完全没价值”，而是“精确排序能力不足”。强行 Top3 容易错过池内更好的票。

### 判断

长线 v18 暂不建议上线更激进版本。下一轮更合理方向是：

- 把长线从“每日 Top3 推荐”改成“少量观察池 + 生命周期状态”。
- 入池规则继续严格，但排序不要过度自信。
- 重点验证 `long_v18_quality_floor_top10` 是否能在更多时间段稳定减少劣质样本。
- 如果未来要做 v19，优先改“池子经营方式”和“质量地板”，而不是再追求单日 Top3 排名。

## 稳定与不稳定因子

### 相对稳定

- 短线：暂未发现可靠的稳定正相关单因子。
- 长线：`volatility` 在少数阶段呈正相关，但样本阶段不足，不能单独作为策略依据。

### 不稳定或需谨慎

- 短线：`score`、`original_score`、`score_base` 的线性相关性不稳定，不能简单理解为“分数越高收益越好”。
- 长线：`longterm_score`、`quality_rank_score`、`pool_rank_score`、`score_rs`、`drawdown_from_high`、`netprofit_yoy` 都有阶段切换问题。

## 候选策略清单

| 候选 | 当前结论 | 下一步 |
|---|---|---|
| `short_v9_top1_concentration` | 不建议继续。减少到 Top1 没有跨区间改善。 | 放弃 |
| `short_v9_sector_flow_tiebreak_top3` | 不建议继续。轻微叠加资金/板块后表现变差。 | 放弃 |
| `short_v9_quality_floor_top3` | 有一点研究价值，但验证段未改善。 | 继续观察，不进入上线验证 |
| `long_v18_top10_watchlist` | 比 Top3 更像合理经营方式，但样本仍需扩展。 | 进入下一轮验证 |
| `long_v18_quality_floor_top10` | 目前最值得继续研究的长线候选。 | 进入下一轮验证 |
| `long_v18_quality_rs_rerank_top10` | 没明显胜过 Top10，暂不单独升级。 | 保留对照 |

## 下一步建议

1. 短线先不改正式策略，继续积累实盘样本和分层诊断。
2. 长线围绕 `quality_floor + Top10观察池 + 生命周期状态` 做下一轮验证。
3. 不用收益率作为唯一目标，重点观察：
   - 胜率是否跨阶段稳定；
   - MAE 是否下降；
   - 80 日收益是否跑赢沪深300；
   - 样本是否太少导致偶然性过高。
4. 任何候选策略即便表现好，也只进入“建议验证”，不直接替换线上版本。
