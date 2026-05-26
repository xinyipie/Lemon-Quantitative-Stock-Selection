# A股量化选股系统

基于 Tushare、A 股离线行情数据和本地回测引擎的量化选股研究工具。项目当前重点是短线选股质量优化，支持日常选股、离线回测、交易归因、IC 分析和多版本实验记录。

> 当前定板基线：`profile_v4_adaptive_quality + baseline exit`。卖点规则先冻结，下一阶段集中优化选股因子。

## 项目定位

- 这是研究和辅助决策工具，不是自动交易系统。
- 回测以 T 日收盘后选股、T+1 开盘买入为基础，避免使用未来数据。
- 生成的回测结果、日志和本地缓存默认不进入 Git，只保留代码和关键研究文档。

## 目录结构

```text
stock/
├── main.py                    # 日常选股与自选股分析入口
├── backtest_v2.py             # 短线/波段回测引擎
├── strategy_profiles.py       # 选股实验版本与配置档案
├── config.py                  # 实盘默认配置与 API 配置入口
├── batch_backtest.py          # 批量回测入口
├── analyze_trades.py          # 交易结果分析
├── trade_diagnostics.py       # 选股因子质量诊断报告
├── exit_attribution.py        # 卖点归因分析
├── ic_analysis.py             # IC 分析工具
├── data_downloader.py         # 离线数据下载
├── docs/                      # 研究结论、实验索引、版本说明
├── requirements.txt           # Python 依赖
└── VERSION.json               # 当前版本信息
```

## 当前基线

短线当前采用：

```text
选股：profile_v4_adaptive_quality
卖点：baseline exit
实盘配置：SHORT_LIVE_FACTOR_PROFILE = "profile_v4"
         SHORT_LIVE_STYLE_GATE = "adaptive_quality"
         SHORT_LIVE_SCORE_ORDER = "desc"
```

这个组合的含义是：行情压力较大时偏防守，行情可做时保留高质量主动进攻机会。最近几轮实验已经确认，额外的 `exit_v2_conditional_lock` 没有优于 baseline，因此卖点暂时不再继续调，后续优先做选股因子质量。

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
$env:DASHSCOPE_API_KEY="你的通义千问 key"
```

下载离线数据：

```bash
python data_downloader.py --start 20250101 --end 20251231
```

运行日常选股：

```bash
python main.py
```

运行当前短线基线回测：

```bash
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline --start 20250102 --end 20251231
```

对已有交易结果做卖点归因：

```bash
python exit_attribution.py --trades backtest_results/trades_xxx.csv
```

对已有交易结果做选股因子质量诊断：

```bash
python trade_diagnostics.py --trades backtest_results/trades_xxx.csv
```

## 常用实验命令

对比 baseline 与实验卖点：

```bash
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline,exit_v2_conditional_lock --start 20250102 --end 20251231
```

只跑 2026Q1 压力测试：

```bash
python test.py --scenario profile_v4_adaptive_quality --exit-profile baseline --start 20260101 --end 20260331
```

查看策略档案：

```bash
python test.py --list-scenarios
```

## 研究流程

1. 先在 `docs/CURRENT_BASELINE.md` 确认当前定板版本。
2. 新实验只改一个核心变量，例如因子权重、过滤条件或市场风格门控。
3. 同时跑 2025 全年和 2026Q1，避免只对单一行情过拟合。
4. 把结论记录到 `docs/EXPERIMENT_LOG.md`，重要版本再更新 `docs/EXPERIMENT_INDEX.md`。
5. 只有跨区间稳定优于基线的版本，才进入实盘候选。

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
