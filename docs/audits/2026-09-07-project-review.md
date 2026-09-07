# 项目审查记录（2026-09-07）

## 范围与边界

基于当前工作区（包含已有未提交修改和未跟踪文件）进行只读代码审查，覆盖前端模板与交互、Web API、更新调度、数据缓存、选股与回测。未修改业务代码，未部署，未调用交易接口。本文为重点路径审查，不代表每个研究脚本、每段历史数据或线上部署均已验证。

项目规模抽样：main.py 7464 行，strategy_profiles.py 2148 行，backtest_v2.py 2053 行，web_app/app.py 902 行，signal_service.py 2257 行；tests 下有 221 个测试文件，research 根目录有 161 个 Python 文件。

## 已确认的更新与工程问题

### R1 / P1：不同任务共用状态文件，导致全量更新漏重试

位置：deploy/stock-daily-full-retry:17-21；deploy/stock-daily-full-update:4-16；deploy/stock-market-radar-update:4-16。

full 与 radar 使用不同 flock 文件，却都写 data/web_update_status.json。重试脚本仅检查 state、returncode 和 started_at，没有检查 mode。因此同一天 full 失败后 radar 成功，重试判断返回 no；重叠执行时也会覆盖运行状态。已按脚本条件构造 radar 成功状态，复现 no。

建议：每种任务维护独立运行记录和最后成功记录；重试检查 full 的目标数据日期及成功结果。需要互斥的资源使用共同的跨进程锁。

### R2 / P2：更新包装程序吞掉失败退出码

位置：web_app/services/update_worker.py:21-22；web_app/services/update_service.py:209-240。

run_update_job 把失败写入 JSON，但 main 无条件 return 0。隔离临时目录中运行退出码 7 的子进程，结果为 worker_return=0、child_return=7、state=failed。依赖进程退出码的调度与监控会误报成功。

建议：让运行函数返回结果，并将非零退出码传给调度器；异常也应返回非零值。

### R3 / P1：常规更新无法保证财务数据刷新

位置：daily_web_update.py:295-298、610-611；data_downloader.py:564-569；main.py:2335-2344。

日更默认跳过财务，full 调度未启用 --with-financial；即便启用，下载器只要发现已有财务文件就直接返回，需要额外 --force，而日更命令没有传递该参数。净利润增速读取本地缓存时没有新鲜度门槛。按仓库提供的日常运行路径，财报更新后仍可能长期使用旧 ROE/净利润数据，影响选股评分。

建议：按公告日期增量更新、保留历史版本，并在选股与页面中展示财务覆盖率和数据时点；季度强制刷新只能作为临时措施。

### R4 / P1（采用默认网络配置时）：令牌和行情请求走明文 HTTP

位置：config.py:260-265；main.py:55-63。

默认中转站为 http:// 协议，checked_query 把 token 放进请求 JSON 后直接发送。使用默认配置时，链路无法提供 TLS 的保密性和完整性，既影响凭据也影响输入行情可信度。此结论来自配置与请求代码，未对远端进行探测。

建议：使用可验证证书的 HTTPS 地址，并禁止正式环境默认为明文中转站。

### R5 / P2：依赖清单不足以重建运行环境

位置：requirements.txt；requirements-dev.txt；data_downloader.py:125；ic_analysis.py:36；research/clean_walkforward_technical_hgb.py:10。

下载器明确使用 pyarrow，IC 分析直接导入 scipy，研究模型导入 sklearn，但依赖清单没有声明这些直接依赖。测试使用 FastAPI TestClient 所需的 httpx 也仅作为注释存在。全局环境中已经安装的库会掩盖新机器或干净部署的问题。此外只有版本下限，缺少经过验证的环境锁定。

建议：区分运行、研究、测试依赖；显式声明直接依赖，固定可验证环境，在干净环境执行安装和最小启动检查。

### R6 / P2：测试断言与当前契约脱节，且依赖真实日期

位置：tests/test_web_app.py:75；tests/test_ai_prompt_output.py；tests/test_ai_news_brief_quality.py:8-58；market_radar/evidence_pack.py:314-317。

页面测试要求旧 CSS 版本标识，但模板已使用新版本；AI 测试仍要求旧 buy_condition 字段，而当前提示词已改为观察性输出。新闻测试使用固定 2026-08-12 新闻，却按真实当前时间过滤：9 月运行得到 0 条，冻结时间为 8 月 12 日时得到 1 条。这些失败不能证明实际功能回归，也降低了失败信号的可信度。

建议：测试结构与行为契约，不断言无关构建版本；统一可注入时钟；将更新任务和外部数据访问完整隔离，避免普通单测依赖本地真实数据库或外部服务。

## 前后端问题

### R7 / P1：对外网关入口无法启动

位置：deploy/gateway.py:12、15；web_app/app.py:64；tests/test_gateway_home.py:56。

gateway 导入不存在的 PRODUCT_WORK_DIR。直接执行 `python -c "from deploy.gateway import app"` 已复现 ImportError。对应测试通过 monkeypatch 补入属性，没有覆盖真实入口导入。使用 web_app.app 启动与使用 deploy.gateway 启动是不同路径，前者可运行不代表后者可部署。

建议：显式配置并验证原型目录，增加不注入缺失属性的网关启动检查。

### R8 / P1：短线策略切换后，顶部收益统计和明细不属于同一批样本

位置：web_app/app.py:658-675；web_app/templates/signals.html:42-44。

active_strategy 过滤了 all_strategy_signals，但顶部 short_stats 又单独查询固定 review_sources/review_profiles，未使用所选策略。访问 `/signals?strategy=repair` 或 balance，明细已经切换，顶部仍统计正式层样本，文字却称“当前筛选样本”。这直接影响用户对策略胜率与收益的判断。

建议：让统计与表格共享同一筛选结果，或明确独立显示“正式策略全局统计”，不可保留当前误导标签。

### R9 / P2：长线风险筛选混合了不同时间窗口

位置：web_app/app.py:791-825、868-870；web_app/services/signal_service.py:561-583、612-660。

页面80日风险汇总基于 mae_80d，但 risk 视图按 watch_risk_tone 过滤，后者依赖入池日至当前行情的路径。缺历史路径时深回撤样本可能被遗漏；历史已完成样本也可能因80日之后的下跌被纳入。建议把“当前观察风险”和“已完成80日最大回撤”分成明确的视图与筛选条件。

### R10 / P2：更新轮询不能可靠恢复，且工作台重复轮询

位置：web_app/templates/base.html:111-125；web_app/templates/dashboard.html:299-348。

base 的 fetchStatus 遇到非2xx直接返回，不安排重试；网络异常只在本标签页设置了 reloadWhenFinished 时重试。查看其他标签或定时任务启动的更新时，一次故障可令状态永久停留，文案却说稍后自动重试。dashboard 还另有一套同一状态接口轮询，与 base 重复，运行中每5秒请求两次。

建议：保留一个有退避与错误状态的轮询控制器，将运行状态与“完成后刷新页面”意图区分处理。

### R11 / P2：策略切换链接没有编码查询参数

位置：web_app/templates/partials/short_strategy_selector.html:4-5。

href 直接拼接 q/start/end/industry。HTML 转义不能代替 URL query 编码，`&`、`#`、`+` 会改变参数语义。建议通过 URL builder 或 URLSearchParams 生成链接，并验证切换策略后筛选不变。

### R12 / P1（对外开放且无上游认证时）：匿名用户可触发更新和 AI 生成

位置：web_app/app.py:66、239-242、467-474、728-759。

应用未配置统一鉴权；更新端点可直接启动后台任务，GET explain/signal 还会按需生成 AI 内容并写库，refresh 可强制重建。若反向代理没有额外保护，匿名用户或诱导的跨站请求能消耗接口额度和计算资源。此项未核验线上反向代理配置，不能断言线上已公开暴露。

建议：对外入口增加身份验证，对写操作实施 CSRF/Origin 校验及资源限制，GET 只读，AI 生成改为显式操作。

### R13 / P1：雷达缓存并发写会冲突

位置：web_app/app.py:321-343、390-409。

缓存冷启动的多个请求均可写缓存；所有写者使用固定 `.tmp` 文件，且读、合并、替换过程没有锁。并行审查在隔离路径以8线程复现7个 PermissionError，异常未被保存调用处理，会导致请求500；即便不报错，也可能覆盖另一个请求刚加入的键。

建议：对读改写整体加并发控制，唯一临时文件名不足以单独解决丢更新；跨进程部署需跨进程锁或事务数据库。

### R14 / P2：缓存读取路径重复执行数据库迁移，锁冲突直接传播

位置：web_app/services/explanation_service.py:525-569；market_radar/store.py:59-100。

_read_cached 每次都调用建表与 legacy migration 并 commit。雷达读取也调用 schema 初始化。并行审查在独立连接持有排他锁时复现 OperationalError，路由没有可用降级。当前本地数据库为 DELETE journal、默认5秒 busy timeout；这是本地观察，未核验线上数据库设置。

建议：迁移与读取分离，缩短写事务，根据部署评估 WAL，并为忙锁提供旧缓存或明确503响应；不能仅无限增加超时。

## 算法数据隔离问题

### R15 / P1：自定义回测缓存被默认财务缓存覆盖

位置：main.py:2335-2344、5830-5832。

get_net_profit_growth_batch 优先读固定的 data/cache/fina_indicator.parquet。即使 pro 是指向其他目录的 LocalDataProxy，只要默认缓存存在并含 netprofit_yoy，就不会读取该代理中的财务数据；主流程调用也没有传 cache_path。隔离验证中注入 cache_dir=isolated-cache 的代理，实际读取仍为 data/cache/fina_indicator.parquet。

影响：换数据目录进行干净回测或数据版本对比时，可能混入另一套财务快照，实验输入不再受 --cache-dir 控制。这与公告日期过滤是否存在是不同问题，不据此直接断言所有回测都有未来函数。

建议：所有数据入口统一从注入的数据提供者读取；若保留独立 cache_path，必须由运行上下文显式传递，并记录实际使用的数据目录与版本。

### R16 / P1：移动止损用收盘后信息模拟当天盘中成交

位置：backtest_v2.py:823-835、890-905。

先用当日收盘价判断是否激活并提高 trailing_stop，再拿同一日最低价判断触发。验证：买入价100，下一日 O/H/L/C=100/109/99/108、涨幅8%，回测以108×0.93=100.44卖出并标记 trailing_stop。这个新止损位到收盘才可计算，不能用于此前的低点。

建议：盘中检查只使用前一交易日已知的止损；收盘后更新下个交易日阈值。若使用盘中高点移动止损，必须有足够粒度的数据来确定事件顺序。

### R17 / P1：跳空和封死跌停时模拟不可成交的卖价

位置：backtest_v2.py:805-810、893-905、939-940。

持仓日非收盘跌停时按 effective_stop 卖出，不检查开盘是否已穿越该价。验证：买入100，下一日 O/H/L/C=90/92/88/91、涨幅-9%，回测卖价93，甚至高于全天最高价92。另以 O/H/L/C 全为90、跌幅-10%的行情验证，仍记录90卖出；日线本身无法证明封死跌停时存在可成交对手盘。

建议：跳空止损按可成交开盘价格及滑点模拟；一字跌停应延期成交或采用明确、保守的流动性假设，不应无条件卖出。

### R18 / P1：历史股票池使用静态当前属性

位置：main.py:1897-1913、2033-2038；local_data_proxy.py:213-229；main.py:122。

历史选股调用 stock_basic(list_status='L')，按返回的当前名称过滤 ST/退市、按当前行业分组；离线实现只读一份静态 stock_basic，忽略 list_status。未使用随历史日期变化的上市状态、ST名称、行业属性。

影响：后来退市或变ST的股票可能从过去样本中消失；行业统计也可能套用后来的分类。存在幸存者偏差及历史属性错配风险，具体影响幅度需要补齐时点股票池后重跑，本文未量化。

建议：维护包含退市股的历史证券主表、名称/ST状态与行业有效期，并按选股日查询。

### R19 / P1：用买入日收盘涨幅决定开盘能否买入

位置：backtest_v2.py:669-674。

buy_pct 取自日线 pct_chg，却被当作“开盘已涨停”条件。合成输入保持开盘价100不变，只将买入日 pct_chg 从0改为10，交易从 accepted=True 变为 False。实际日线 pct_chg 是收盘相对前收盘的涨幅，不能证明开盘不可买。

影响：根据开盘时未知的信息事后筛选交易，收益偏差方向不固定；如盘中后来涨停的赢家被排除，会扭曲策略比较。

建议：以开盘价对比当日适用涨停价判断，结合一字板或更细粒度的成交可行性规则；禁止使用当日最终涨跌幅作为开盘准入条件。

## 验证记录

- 定向运行 tests/test_update_service.py、tests/test_scheduled_update.py、tests/test_backtest_portfolio_accounting.py、tests/test_point_in_time_financials.py、tests/test_no_future_signal_pipeline.py：30 passed，3.33 秒。
- tests/test_web_app.py -x：8 passed、1 failed，失败是旧 CSS 版本断言。
- tests/test_ai_news_brief_quality.py 与 tests/test_ai_prompt_output.py：1 passed、3 failed；两项真实时钟依赖、一项旧字段契约。
- 全 tests 和较大核心组合运行耗时较长，主动中止，未取得完整汇总；不能声称全套测试通过。
- 定向日志位于 tmp/project_audit_targeted_20260907.log、tmp/project_audit_web_first_20260907.log、tmp/project_audit_ai_20260907.log。
- 30 项通过不代表整个回测无未来数据；其中研究管线的时点防护不自动覆盖所有生产入口。
- 对正式 BacktestV2._simulate_trade 的独立合成行情验证复现 R16、R17、R19，未运行全历史策略重算，因此不提供“修复后收益下降多少”的推断数字。

## 架构建议

主流程、供应商接口、技术指标、策略筛选、AI 分析和报告职责集中于大型模块。建议先建立正式策略版本与数据快照清单，冻结输入/输出契约，再逐步拆分数据适配层、纯计算层和编排层。每次实验记录代码版本、参数、缓存时点、交易成本与样本区间。大量实验本身不能证明过拟合；但在未核验封存样本和完整试验记录前，也不能据最佳历史结果判断泛化能力。

修复顺序应优先保障输入数据可信与更新成功可判定，其次修复前后端的具体行为缺陷，最后才是进一步调参和重构。
