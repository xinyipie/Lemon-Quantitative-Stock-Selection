# Stock 选股助手 — Codex 工作手册

> 更新于 2026-09-07。定位和修改前以当前代码核对，本手册下方 v4.0 算法参数保留为历史说明，不代表当前正式配置。

## 当前运行口径

- 当前短线：`profile_v9_sector_quality_guard + adaptive_quality_v6 + v39`；观察层 `best_balance`。
- 长线已启用：`longterm_quality_lifecycle_v18_market_sync` 观察池与 Elite 提醒。
- 行情默认地址：`http://14.nat0.cn:32817`，来自发布前代码与生产备份，用户已确认继续使用；配置位于 `config.py`，可由 `TUSHARE_HTTP_URL` 覆盖。
- 当前 AI 使用 `DEEPSEEK_API_KEY`；真实凭据只保存在环境配置中。
- 网页未配置 `STOCK_WEB_TOKEN` 时默认只读。生产入口为 `gateway:app`，服务名 `stock-web`。
- 严格历史回测需要对应日期的股票主数据快照；研究训练需要标签实际退出日期。缺数据不能以静态当前值或未来标签替代。
- [修改总览](docs/audits/2026-09-07-change-summary.md) 汇总代码变更、验证和未重跑事项；旧收益结果不作为本次修复后的有效验证。

## 快速启动

```bash
python main.py                          # 实盘选股（自动取最新交易日）
python main.py analyze watchlist.txt    # 批量分析自选股
python backtest_v2.py --mode short --offline --start 20240101 --end 20241231   # 短线回测
python backtest_v2.py --mode longterm --offline --start 20240101 --end 20241231 # 波段回测
python batch_backtest.py                # 批量回测（2023/2024/2025/全段 × 短线/波段）
python ic_analysis.py                   # IC分析（评估选股评分预测能力）
python patch_fina_netprofit_yoy.py      # 补丁：给现有parquet追加netprofit_yoy列
```

运行依赖见 `requirements.txt`，开发测试见 `requirements-dev.txt`，模型研究见 `requirements-research.txt`。生产使用 Python 3.12 虚拟环境；本地验收另覆盖 Python 3.14。

## 核心文件职责

| 文件 | 职责 | 行数 |
|------|------|------|
| main.py | 核心逻辑：选股/技术指标/AI分析/报告生成 | ~3700行 |
| config.py | 所有参数配置（策略参数/状态机/API Key） | ~200行 |
| backtest_v2.py | 离线回测引擎（BacktestV2短线 + BacktestLongterm波段） | ~1300行 |
| ai_prompts.py | AI提示词模板（短线/波段/批量分析） | ~460行 |
| market_analyzer.py | 市场综合决策（operation_mode输出） | - |
| news_analyzer.py | 新闻解读/概念热度分析 | - |
| ic_analysis.py | IC分析工具：评估longterm_score预测能力 | ~330行 |
| batch_backtest.py | 批量回测+IC汇总：多时间段×多策略一键跑 | ~430行 |
| patch_fina_netprofit_yoy.py | 补丁脚本：给已有parquet追加netprofit_yoy | ~130行 |

## 架构关键函数（v4.0）

```
run_daily_selection(trade_date)          # 主流程入口，回测/实盘共用
  ├── get_all_stocks()                   # 全市场基础候选池
  ├── check_market_risk()                # 短期大盘状态（4状态）
  ├── get_market_style()                 # 市场风格（momentum/sideways/bear）
  ├── get_market_regime()                # 四状态机（长期牛熊×短期方向）
  ├── check_regime_override()            # 快速翻转检测（解决MA60滞后）
  ├── get_weekly_macro_trend()           # 周线宏观趋势（Elder三重滤网）
  ├── get_ma_data_batch()                # 批量技术指标（MA/ATR/Wyckoff）
  ├── get_sector_ma10_status()           # 板块共振（申万28行业）
  ├── select_stock_pool()                # 短线选股（3种风格模式）
  └── select_longterm_pool()             # 波段选股v4.0（BULL状态时触发）
        ├── get_industry_rs_scores()     # 行业20日RS超额收益
        └── get_net_profit_growth_batch()# 净利润同比增速（fina_indicator）
```

## 四状态机（当前版本核心）

```
get_market_regime() → 判断CSI300的 MA20 vs MA60 + MA60斜率

  BULL_TREND      仓位×1.0  Top3  持8天  门槛≥45分   （长期牛+短期涨）
  BULL_PULLBACK   仓位×1.0  Top3  持5天  门槛≥50分   （长期牛+短期跌）
  BEAR_BOUNCE     仓位×0.33 Top1  持3天  门槛≥62分   （长期熊+短期涨）
  BEAR_TREND      仓位×0    空仓                      （长期熊+短期跌）

check_regime_override() → 4条微观结构信号（仅对 BEAR_TREND 生效）
  ① 全市场涨跌中位数 > 2%
  ② 上涨家数占比 > 70%
  ③ 涨停家数 > 80
  ④ 成交额 > 5日均额×1.5
  2条→ BEAR_BOUNCE_OVERRIDE（仓位×0.33，持3天，门槛≥80）
  3条→ BULL_PULLBACK_OVERRIDE（仓位×0.50，持4天，门槛≥65）
```

## 波段策略v4.0（select_longterm_pool）

```
触发条件：regime in (BULL_TREND, BULL_PULLBACK, BULL_PULLBACK_OVERRIDE)
候选池：get_all_stocks(min_volume_ratio=0)  ← 波段不要求今日放量
硬过滤：MA20>MA60 + MA60斜率>0 + 动量排名>P20 + 行业RS>-5% + 回调5-35% + 价格vsMA60<25%
5维评分（100分）：
  ① 动量    30% — MA20斜率强度（负斜率=0分，不扣分）+ 行业RS加分
  ② 资金流  25% — 主力净流入 + eod_strong/vol_accelerating
  ③ 行业RS  20% — 行业20日超额收益（-15%~+15%线性映射）
  ④ 财务    15% — ROE + netprofit_yoy + 增速加速奖励
  ⑤ 入场    10% — 回调幅度(5-15%最佳) + 量能收缩 + Wyckoff
输出字段：
  longterm_score      综合评分（实测范围53~72，区分度偏低待优化）
  stop_loss_price     MA60×0.98（跌破MA60止损）
  trailing_stop_pct   10%（峰值回撤10%，需+25%后激活）
  target_price        近20日高点×1.5（设高以确保主要靠移动止损退出）
```

## 回测引擎参数（BacktestV2 / BacktestLongterm）

```
短线（BacktestV2）：
  hold_days=5  fallback_stop=-7%  fallback_profit=15%  trailing_stop=7%
  trailing_activate 硬编码=3%（不可从外部传入）
  is_offline 自动检测（传入LocalDataProxy实例即为离线）

波段（BacktestLongterm，继承BacktestV2）：
  max_hold_days=60  fallback_stop=-12%  fallback_profit=50%
  trailing_stop=10%  trailing_activate=25%
  time_stop_days=20  time_stop_threshold=-3%（持20天仍亏>3%则出场）

离线模式：
  from local_data_proxy import LocalDataProxy
  proxy = LocalDataProxy(cache_dir='data/cache')
  stock_main.set_pro(proxy)   ← 注入后自动识别为离线，跳过所有sleep
```

## IC分析（ic_analysis.py）

```
python ic_analysis.py                          # 分析最新trades CSV，10/20/30日
python ic_analysis.py --forward 10 20          # 指定前瞻天数
# 缺有效预测评分时 IC 明确不可用，不允许用已实现 profit 冒充评分。

IC值参考：> 0.10=优秀  0.05~0.10=良好  < 0.02=无效
高低分差（高分1/3组 - 低分1/3组平均涨幅）比IC值更直观

实测结果（2023~2025全段，231笔波段交易）：
  10日IC=+0.044  高低分差=+3.0%（评分有一定区分度但偏弱）
  20日IC=+0.030  高低分差=+5.4%
  根因：评分区间53~72分（仅19分跨度），候选股同质化，待优化
```

## 批量回测（batch_backtest.py）

```
python batch_backtest.py                # 自动按年分段+全段，short+longterm
python batch_backtest.py --mode short   # 只跑短线
python batch_backtest.py --skip-backtest # 只做IC分析（用已有CSV）

输出：backtest_results/batch_summary_*.csv（IC汇总对比表）
注意：文件名含 short_/longterm_ 前缀的是batch生成的规范文件
     旧的 trades_YYYYMMDD_HHMMSS.csv 可归档到 backtest_results/archive/
```

## 回测 vs 实盘差异

```
完全一致：四状态机 / 技术指标 / 资金流 / 板块共振 / 5维评分
回测缺少：新闻板块加分（最多+30分）/ 概念热度加分（最多+10分）/ AI个股分析
买入方式：T日收盘选股 → T+1开盘价买入（低开>0.5%或涨停则跳过）
胜率基准：短线45%（可信度高）/ 波段35%（保守，自管出场会更好）
```

## 绝对约束（必须遵守）

- **纯选股工具**，严禁生成任何自动下单/仓位管理/交易执行代码
- **批量拉取**：所有Tushare请求必须批量，严禁逐股循环调用接口
- **中文注释**：所有新增代码注释使用中文
- **回测/实盘共用**：逻辑修改只改 main.py，backtest_v2.py 自动复用

## Tushare 字段踩坑备忘

```
资金流:   moneyflow → net_mf_amount（万元），不是 net_mf_vol×close
换手率:   daily_basic → turnover_rate，代码内需 rename 为 turnover
行业指数: 申万一级用 801xxx.SI 格式（不用88/399前缀）
股东减持: stk_holdertrade，in_de='DE'，需分 G/P/C 三种 holder_type 查
财务数据: fina_indicator 含 ann_date 字段（防止回测未来函数）
          fina_indicator 有 netprofit_yoy 字段（净利润同比增速，波段策略用）
积分提醒: fina_indicator=2000积分，income=2000积分，总余额5000，注意频控
波段策略: industry_rs 用 index_daily 拉申万指数+沪深300，无额外积分消耗
```

## 环境变量（启动必需）

```
TUSHARE_TOKEN      → https://tushare.pro
TUSHARE_HTTP_URL   → 可选，默认 http://14.nat0.cn:32817
DEEPSEEK_API_KEY   → 当前 AI 服务凭据
```

Tushare 中转地址由 `config.py` 的 `LEGACY_TUSHARE_HTTP_URL` / `TUSHARE_HTTP_URL` 配置，`main.py` 初始化时校验并注入客户端；不再通过固定代码行号定位。
