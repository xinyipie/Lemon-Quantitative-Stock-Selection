# A股量化选股系统

基于 Tushare、A 股离线行情数据和本地回测引擎的量化选股研究工具。项目当前重点是短线选股质量优化，支持日常选股、离线回测、交易归因、IC 分析和多版本实验记录。

> 当前定板短线版本：`profile_v4_adaptive_quality_v9_sector_quality_guard + baseline exit + fixed Top3`。长线当前为 v18 market-sync 观察池 + elite 提醒层，实盘已开启状态记录，但不包含任何交易执行。
> 短线 live 推送前额外启用硬风控：过滤 ST/退市名称和严重财务恶化样本；这不改变短线回测定板评分。

## 项目定位

- 这是研究和辅助决策工具，不是自动交易系统。
- 回测以 T 日收盘后选股、T+1 开盘买入为基础，避免使用未来数据。
- 生成的回测结果、日志和本地缓存默认不进入 Git，只保留代码和关键研究文档。

## 目录结构

```text
stock/
├── main.py                    # 日常选股与自选股分析入口
├── daily_web_update.py        # Web 看板一键同步：行情/实盘/短线复盘/长线审计
├── backtest_v2.py             # 短线/波段回测引擎
├── strategy_profiles.py       # 选股实验版本与配置档案
├── config.py                  # 实盘默认配置与 API 配置入口
├── batch_backtest.py          # 批量回测入口
├── analyze_trades.py          # 交易结果分析
├── trade_diagnostics.py       # 选股因子质量诊断报告
├── exit_attribution.py        # 卖点归因分析
├── ic_analysis.py             # IC 分析工具
├── data_downloader.py         # 离线数据下载
├── history_db_importer.py     # Parquet 缓存导入 SQLite 历史库
├── signal_backfill.py         # 短线 ic_short 回填到 Web 信号库
├── longterm_history_importer.py # 长线审计 CSV 导入 Web 信号库
├── web_app/                   # 本地只读 Web 研究看板
├── docs/                      # 研究结论、实验索引、版本说明
├── requirements.txt           # Python 依赖
└── VERSION.json               # 当前版本信息
```

## 当前基线

短线当前采用：

```text
选股：profile_v4_adaptive_quality_v9_sector_quality_guard
卖点：baseline exit
推荐：固定 Top3
实盘配置：SHORT_LIVE_FACTOR_PROFILE = "profile_v9_sector_quality_guard"
         SHORT_LIVE_STYLE_GATE = "adaptive_quality_v6"
         SHORT_LIVE_SCORE_ORDER = "desc"
         ENABLE_LONGTERM_LIVE = True
         LONGTERM_LIVE_PROFILE = "longterm_quality_lifecycle_v18_market_sync"
```

这个组合的含义是：行情压力较大时偏防守，行情可做时保留高质量主动进攻机会。TopN 容量实验确认固定 Top3 跨区间更稳；额外的 `exit_v2_conditional_lock` 没有优于 baseline。因此卖点和推荐数量暂时不再继续调，后续优先做选股因子质量。

详细结论见：

- [当前定板基线](docs/CURRENT_BASELINE.md)
- [实验索引](docs/EXPERIMENT_INDEX.md)
- [实验日志](docs/EXPERIMENT_LOG.md)
- [下一阶段研究计划](docs/STRATEGY_RESEARCH_PLAN.md)
- [因子中英对照表](docs/FACTOR_GLOSSARY.md)

## 快速开始

安装依赖：

```bash
pip install -r requirements.txt
```

配置 API：不要把真实 key 写进代码。请在本机环境变量中设置，或参考 `.env.example`。

```powershell
$env:TUSHARE_TOKEN="你的 tushare token"
$env:DEEPSEEK_API_KEY="你的 DeepSeek key"
```

日常更新 Web 看板数据（推荐）：

```bash
python daily_web_update.py --mode full --end 20260616
```

日常同步只做高频经营所需步骤：补行情缓存、导入 `stock_history.db`、刷新市场上下文、运行 `main.py` 写入当天实盘信号，并为当天短线/长线 live 信号补齐 AI 解释缓存和首页“今日AI摘要”。短线历史复盘和长线历史审计比较慢，默认跳过。

如果当天只想刷新数据、不调用大模型生成解释：

```bash
python daily_web_update.py --mode daily --end 20260616 --skip-ai-explanations
```

如果只想预览将要执行哪些步骤：

```bash
python daily_web_update.py --mode daily --end 20260616 --dry-run
```

如果需要补齐短线复盘和当前半年度长线审计：

```bash
python daily_web_update.py --mode full --end 20260616
```

如果需要重刷 2024H1 至今的全部半年度长线历史池：

```bash
python daily_web_update.py --mode full --end 20260616 --full-history
```

下载离线数据：

```bash
python data_downloader.py --start 20250101 --end 20251231
```

把已下载的 Parquet 缓存同步到本地历史数据库（供后续 Web、股票详情和信号复盘查询）：

```bash
python history_db_importer.py --cache-dir data/cache --db data/stock_history.db
```

只同步某个区间或部分数据源：

```bash
python history_db_importer.py --start 20250101 --end 20251231 --tables daily daily_basic moneyflow index_daily
```

运行日常选股：

```bash
python main.py
```

当前 `main.py` 会输出短线定板信号，并同步记录长线 v18 Watch/Elite/无入池状态到 `data/stock_signals.db`。它不负责补齐历史行情库；日常经营前端建议优先使用 `daily_web_update.py`。

批量检测自选股：

```bash
python main.py analyze watchlist.txt
python main.py analyze 000001,600519 sh600000
```

`analyze` 支持文件、逗号/空格/中文标点分隔、`000001`、`000001.SZ`、`sz000001`、`sh600000` 等常见输入格式。

启动本地 Web 研究看板：

```bash
python -m uvicorn web_app.app:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`。当前 Web 端只读展示本地 SQLite 数据，不包含任何交易执行功能。

日常查看顺序建议：

1. 盘后先跑 `python daily_web_update.py --mode full --end 最新交易日`，把行情、实盘、短线复盘、长线审计和市场上下文一次补齐。
2. 打开 Web 首页，看“数据同步提醒”和“今日决策”。
3. 短线复盘页先看近 100 日，重点看“系统原因”“收益路径”“AI状态”。日常同步会自动补当天 AI 解释。
4. 只有需要批量补历史解释时再跑：

```bash
python backfill_signal_explanations.py --start 20260501 --end 20260618 --mode short
```

5. 如果历史复盘或长线半年度审计缺数据，再使用 `--mode full`，不要每天都跑完整同步。

运行当前短线基线回测：

```bash
python test.py --scenario profile_v4_adaptive_quality_v9_sector_quality_guard --exit-profile baseline --topn 3 --start 20250102 --end 20251231
```

对已有交易结果做卖点归因：

```bash
python exit_attribution.py --trades backtest_results/trades_xxx.csv
```

对已有交易结果做选股因子质量诊断：

```bash
python trade_diagnostics.py --trades backtest_results/trades_xxx.csv
```

## 有用脚本清单

### 日常经营与 Web 数据

| 脚本 | 何时使用 | 常用命令 |
|------|----------|----------|
| `daily_web_update.py` | Web 日常推荐入口；默认建议用 `--mode full` 补齐行情、实盘、短线复盘、长线审计和市场上下文；只想快速刷新当日信号时用 `--mode daily` | `python daily_web_update.py --mode full --end 20260616` |
| `data_downloader.py` | 单独补 Tushare/离线 Parquet 缓存 | `python data_downloader.py --start 20260616 --end 20260616 --skip-financial` |
| `history_db_importer.py` | 把 `data/cache` 的 Parquet 导入 `data/stock_history.db`，供 Web/单股体检查询 | `python history_db_importer.py --cache-dir data/cache --db data/stock_history.db --start 20260616 --end 20260616 --tables daily daily_basic moneyflow index_daily stock_basic` |
| `history_db_check.py` | 检查历史数据库覆盖范围和最新日期 | `python history_db_check.py --db data/stock_history.db` |
| `main.py` | 只跑当天实盘短线/长线扫描并写入 `stock_signals.db` | `python main.py` |
| `sector_heat_diagnostics.py` | 生成行业热度雷达报告，辅助判断健康主线、过热退潮和板块候选 | `python sector_heat_diagnostics.py --db data/stock_history.db --output reports/sector_heat_latest.md --csv-output reports/sector_heat_latest.csv --stocks-output reports/sector_heat_latest_stocks.csv` |
| `market_context_snapshot.py` | 刷新 Web 行业页的概念热度和新闻板块缓存，供一键同步与市场雷达使用 | `python market_context_snapshot.py --date 20260616` |
| `longterm_history_importer.py` | 把长线历史池审计 CSV 导入 Web 信号库 | `python longterm_history_importer.py --source reports/longterm_pool_quality_2026H1_v18_market_sync_full.csv` |
| `signal_backfill.py` | 把短线回测生成的 `ic_short_*.csv` 回填到 Web 短线复盘 | `python signal_backfill.py --source backtest_results/ic_short_xxx.csv --profile short_v9_final --top 3` |
| `backfill_signal_explanations.py` | 批量补齐 Web 中短线/长线信号的 AI 解释缓存；已有缓存默认不重复调用模型 | `python backfill_signal_explanations.py --start 20260501 --end 20260618 --mode short --profile short_v9_final` |
| `daily_ai_brief.py` | 单独生成首页“今日AI摘要”；日常同步已自动调用，通常无需手动跑 | `python daily_ai_brief.py --date 20260618` |

### 策略回测与定板验证

| 脚本 | 何时使用 | 常用命令 |
|------|----------|----------|
| `test.py` | 当前主要短线实验入口，支持多 scenario / exit-profile 对比 | `python test.py --scenario profile_v4_adaptive_quality_v9_sector_quality_guard --exit-profile baseline --topn 3 --start 20250102 --end 20251231` |
| `backtest_v2.py` | 底层离线回测引擎；需要直接控制 mode/longterm-profile/max-positions 时使用 | `python backtest_v2.py --mode short --offline --start 20250101 --end 20251231` |
| `batch_backtest.py` | 批量跑年度/全段回测和 IC 汇总 | `python batch_backtest.py --mode short` |
| `ic_analysis.py` | 对已有交易 CSV 做 IC 分析 | `python ic_analysis.py --forward 5 10 20` |

### 短线复盘与因子诊断

| 脚本 | 何时使用 | 常用命令 |
|------|----------|----------|
| `candidate_rank_diagnostics.py` | 分析 Top3 与第4-10名错过好票的因子差异 | `python candidate_rank_diagnostics.py --candidates backtest_results/ic_short_xxx.csv --output reports/candidate_rank_diagnostics.md` |
| `factor_audit.py` | 审计候选池因子表现和跨区间稳定性 | `python factor_audit.py --candidates backtest_results/ic_short_xxx.csv --output reports/factor_audit.md` |
| `trade_diff_diagnostics.py` | 对比两个版本具体换了哪些交易、收益差异在哪里 | `python trade_diff_diagnostics.py --base backtest_results/trades_base.csv --experiment backtest_results/trades_exp.csv --output reports/trade_diff.md` |
| `winner_loser_factor_diagnostics.py` | 对比赢家/输家因子差异，找下一轮优化线索 | `python winner_loser_factor_diagnostics.py --trades backtest_results/trades_xxx.csv --output reports/winner_loser.md` |

### 长线池研究与审计

| 脚本 | 何时使用 | 常用命令 |
|------|----------|----------|
| `longterm_pool_quality_audit.py` | 审计长线池质量，输出 10/40/80 日收益 | `python longterm_pool_quality_audit.py --start 20260101 --end 20260616 --longterm-profile longterm_quality_lifecycle_v18_market_sync --forward-days 10 40 80 --sample-step 1 --output reports/longterm_pool_quality_2026H1_v18_market_sync_full.md --csv-output reports/longterm_pool_quality_2026H1_v18_market_sync_full.csv` |
| `longterm_pool_compression_audit.py` | 压缩长线候选池，控制一年推荐数量和行业集中度 | `python longterm_pool_compression_audit.py --help` |
| `longterm_pool_state_audit.py` | 分析长线池每日新入、延续、降级、移出状态 | `python longterm_pool_state_audit.py --help` |
| `longterm_pool_alert_audit.py` | 评估 Elite 强提醒层条件 | `python longterm_pool_alert_audit.py --help` |
| `longterm_factor_stability_audit.py` | 对比多个长线版本因子稳定性 | `python longterm_factor_stability_audit.py --inputs reports/longterm_pool_quality_*_v18_market_sync_full.csv --output reports/longterm_factor_stability.md` |
| `research/strategy_research_overview.py` | 端午策略研究总览：汇总短线 v9、长线 v18 现有证据，不改变上线策略 | `python research/strategy_research_overview.py --output reports/research/dragon_boat_research_overview.md` |
| `research/strategy_factor_stability.py` | 端午因子稳定性研究：按短线 v9 与长线 v18 口径识别稳定/不稳定因子，不改变上线策略 | `python research/strategy_factor_stability.py --output reports/research/dragon_boat_factor_stability.md` |
| `research/strategy_layer_quality.py` | 端午分层质量诊断：比较短线 v9、长线 v18 的 TopN 与全样本收益差异，判断分数是否只在头部有效 | `python research/strategy_layer_quality.py --output reports/research/dragon_boat_layer_quality.md` |
| `research/strategy_candidate_simulator.py` | 端午候选策略离线模拟：对短线 v9、长线 v18 的保守 research rule 做跨区间验证，不直接上线 | `python research/strategy_candidate_simulator.py --output reports/research/dragon_boat_candidate_simulation.md` |
| `research/official_strategy_health_check.py` | 定板策略健康检查：汇总 research 结论，判断哪些只做监控、哪些进入下一轮验证，不改变上线默认策略 | `python research/official_strategy_health_check.py --output reports/research/official_strategy_health_check.md` |

## 常用实验命令

对比 baseline 与实验卖点：

```bash
python test.py --scenario profile_v4_adaptive_quality_v6 --exit-profile baseline,exit_v2_conditional_lock --start 20250102 --end 20251231
```

只跑 2026Q1 压力测试：

```bash
python test.py --scenario profile_v4_adaptive_quality_v6 --exit-profile baseline --start 20260101 --end 20260331
```

查看策略档案：

```bash
python test.py --list-scenarios
```

## 研究流程

1. 先在 `docs/CURRENT_BASELINE.md` 确认当前定板版本。
2. 新实验只改一个核心变量，例如因子权重、过滤条件或市场风格门控。
3. 同时跑 2025 全年和 2026Q1，避免只对单一行情过拟合。
4. 当前主基准固定 Top3；TopN 不是下一阶段主战场。
5. 把结论记录到 `docs/EXPERIMENT_LOG.md`，重要版本再更新 `docs/EXPERIMENT_INDEX.md`。
6. 只有跨区间稳定优于基线的版本，才进入实盘候选。

## Git 管理原则

Git 只保存代码、配置模板和研究文档。以下内容默认留在本地，不上传：

- `backtest_results/`
- `data/`
- `logs/`
- `reports/`
- `*.log`
- `.env`
- `.claude/`

如果某次实验结果特别重要，建议把关键指标写进文档，而不是提交大量 CSV/JSON 输出文件。

## 风险提示

本项目仅用于学习、研究和策略验证，不构成投资建议。量化回测不代表未来收益，实盘使用前需要结合交易成本、流动性、滑点和个人风险承受能力独立判断。
