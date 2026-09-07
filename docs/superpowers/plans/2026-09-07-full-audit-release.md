# 全面审查修复与上线计划

> **For agentic workers:** 使用 systematic-debugging 与 test-driven-development 逐项实施，按独立文件范围并行工作；主审负责集成、验证和发布。

**Goal:** 修复本次审查确认的代码与数据契约缺陷，推送经过验证的提交并部署现有 Stock 服务。

**Architecture:** 保留现有 Python/FastAPI/Jinja 架构和此前未提交修复。研究执行与标签使用共享时点契约；正式策略修复因果顺序和缺失数据默认值；页面统一挂载路径、状态与缺失字段。

**Tech Stack:** Python、pandas、pytest、Node 测试、Chromium、Git、SSH、Ubuntu systemd。

**Spec:** `docs/audits/2026-09-07-full-strategy-browser-review.md` 及其五份专项审查报告。

## 全局约束

- 用户已授权修复、推送和上线，完成可验证实现后直接发布。
- 纯选股/研究工具，不新增自动下单；Tushare 请求保持批量；新增注释中文。
- 现有工作分支 `codex/daily-leadership-report` 保留所有既有修复。只显式暂存任务文件，不提交密钥、运行数据库或打包缓存。
- 生产部署依项目本机运维记录：`root@124.221.27.192:/opt/stock`，`stock-web`；只使用现有密钥，不输出密钥内容。
- 方法限制须降低证据等级并阻止误用；不能伪造新样本外结果或通过随意调参宣称有效。

## 工作包与验收

- [x] **页面修复**：`web_app/**`、`stock_history_query.py`，B-01～B-08。先以缺基本面的指数 fixture 和挂载 TestClient 复现 500/404，再修资产类型模板、CSS、状态面板、日期和错误流程。新测试 `tests/test_browser_audit_fixes.py`；真实浏览器验证查询、收盘线、链接与更新反馈。
- [x] **根目录算法修复**：`main.py`、`backtest_v2.py`、`strategy_profiles.py`、`batch_backtest.py`、`ic_analysis.py`、长线/新闻/诊断模块，LS-01～LS-14、RA 确定问题。用空指数、同日止盈/时间退出、跨月日期、多财务版本、重复候选和旧闻 fixture 先复现；修复后运行专属及原有测试。
- [x] **研究契约修复**：`research/**`，D-01～D-10 与 OR 确定问题。用年度边界、未成交锁定信号、缺标签、高分不可成交与低分可成交两行数据验证；先锁信号再执行，按标签结束日 purge，账户拒绝未成交，未知/缺价不伪造收益。测试 `tests/test_research_audit_fixes.py`。
- [ ] **证据治理**：各实施者将每个报告编号映射到修复/方法标记/历史归档状态，写专项修复报告；既有研究输出不得继续冒充修复后的有效验证。
- [x] **集成验证**：检查三个文件范围的 diff；运行 `python -m pytest -q`、`node --test tests/js/*.test.cjs` 和 `git diff --check`；失败按根因修复后重新运行相关测试。回归本地实际浏览器主要流程。
- [x] **发布准备**：核对线上工作树、HEAD、运行入口、Python/依赖、环境变量是否设置（不打印值）；记录回滚提交/备份；不覆盖运行数据。对未提交线上代码先保存并与待发布内容比较，保留独立改动。
- [ ] **推送部署**：显式暂存验证过的代码/测试/文档，提交并推送；以仓库现有发布分支策略更新生产到精确提交，安装所需依赖，解析检查调度脚本，重启 `stock-web`。
- [ ] **线上验收**：核对 Git SHA 与服务 active；检查真实主路由、指数详情、更新状态和静态资源，验证页面日期/降级提示；失败则恢复已记录版本，不将“已推送”冒称“已上线”。

## 最小契约示例

```python
# 锁定记录不能因未来收益更好或次日不可成交而被另一只股票替补。
assert selected.ts_code.tolist() == ["A"]
assert executed.loc[0, "executed"] == False
# 年度训练样本所有标签必须在预测开始之前结束。
assert (training.label_exit_date < prediction_start).all()
# 指数没有股票财务项仍应渲染成功。
assert client.get("/stock/stock/000300.SH").status_code == 200
```

修复后的多年回测与新封存区间验证属于新的证据生成，不能由单元测试结果代替；上线报告需明确其状态。
