# 审查修复发布验收

## 已完成的本地验收

- 全量 `python -m pytest -q`：997 passed、22 skipped；另有两条既有 pandas FutureWarning。
- `node --test tests/js/*.test.cjs`：5 passed。
- 实际 Chromium 页面回归见 `2026-09-07-release-browser-regression.md`。
- `git diff --check` 通过。pytest 默认范围固定为正式 tests 和已有归档复现测试，避免自动收集 tmp 中的联网探测脚本。
- 运行数据库 `data/stock_signals.db` 从 Git 索引移除，实际文件保留，发布包不再包含运行数据。

## 发布前环境核对

生产服务为 `stock-web`，工作目录 `/opt/stock`，Python 3.12。现有 `gateway:app` 入口已提供兼容 shim；外部原型目录通过环境变量配置，并保留旧 `/stock/prototypes/` 路径。唯一缺少的运行依赖 filelock 已安装，生产依赖检查通过。

生产源文件已备份并与本地基线对比：独有的入口/原型路径行为已保留，没有发现需要丢弃的独立算法热修复。正式发布采用精确提交源文件包，保留 `.env`、`.venv`、数据库、缓存、日志和现有定时任务；启动失败自动回滚源文件及环境配置。

## 尚需外部输入或新证据

- 生产环境缺少 `TUSHARE_HTTP_URL`。需要服务商确认的 HTTPS 接口地址；旧 HTTP 中转不会继续接收 Token。网页可提供现有数据，但行情更新成功路径未验证。
- Web 未配置访问令牌，保持默认只读；部署不会开放匿名写操作。
- 历史证券主数据、财务版本真实性、clean store 标签退出日期需要满足新契约后重建；本次没有重跑多年研究，也没有生成新的独立样本外收益。
- 具体问题状态见算法、研究和浏览器三份 `*-fixes.md`。方法限制已降低证据等级，不能将自动化测试通过理解为策略收益已获证明。

生产兼容测试、最终提交与部署验收将在发布后追加记录。

## 生产隔离验收追加修复

- 全新检出缺少 `data` 目录时下载模块导入失败：先初始化日志目录；独立子进程空目录回归通过。
- pandas 3/Arrow 缺失退市日期导致布尔计算异常：生命周期比较显式处理缺失并统一布尔类型；以 Arrow 字符串在本地复现后修复。
- Windows Git 打包会转换 shell 换行：增加 `deploy/* text eol=lf` 属性，最终发布包重新执行 Linux `bash -n`。
- Python 3.12/pandas 3 隔离回归最终通过 126 项；空库页面及旧测试数据隔离均已修复。
