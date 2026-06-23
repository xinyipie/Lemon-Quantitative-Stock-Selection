# 策略研究自动化说明

## 目标

每天晚上 20:00 进入 `codex/strategy-research` 研究分支，做策略研究巡检和候选实验准备。正式 Web、数据库闭环、短线 v9 和长线 v18 的上线策略保持稳定，不在夜间任务里直接改默认策略。

## 怎么解决“Codex 等确认就停住”

夜间自动化使用明确的无人值守规则：

- 普通实现选择：Codex 自行按保守方案推进，不停下来问用户。
- 破坏性动作：不执行，写入阻塞报告。
- Git 冲突、鉴权失败、外部接口不可用：不反复等待用户，记录失败原因并继续能做的部分。
- 新策略只作为 research profile 或研究报告，不改 `main.py` 默认上线策略。
- 不做自动交易、不接券商下单、不写交易执行代码。

这不是让 Codex “无条件乱改”，而是把它的确认点前移成规则：低风险自动做，高风险跳过并留痕。

## 手动运行

```powershell
git switch codex/strategy-research
python research/nightly_strategy_runner.py --until 08:00
```

## Windows 任务计划兜底

Codex App 自动化可能受应用未唤醒、电脑睡眠或调度环境影响。项目里额外提供 Windows 任务计划兜底，直接由系统每天 20:00 调 PowerShell 跑研究脚本。

安装或重装任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_nightly_strategy_research_task.ps1 -StartTime 20:00
```

手动验证一次：

```powershell
Start-ScheduledTask -TaskName "Stock Nightly Strategy Research"
```

查看任务状态：

```powershell
Get-ScheduledTaskInfo -TaskName "Stock Nightly Strategy Research"
```

任务日志：

```text
reports/research/nightly/logs/nightly_strategy_research_YYYYMMDD_HHMMSS.log
```

输出目录：

```text
reports/research/nightly/YYYYMMDD/
```

核心总报告：

```text
reports/research/nightly/YYYYMMDD/nightly_strategy_research_YYYYMMDD.md
```

## 每天早上怎么看

优先看总报告里的三块：

- `任务结果`：确认五个研究诊断有没有失败。
- `失败详情`：如果有失败，先修数据/脚本，不急着改策略。
- 各子报告：只看跨区间稳定改善，不看单一区间收益尖峰。

## 当前固定巡检任务

- `research/strategy_research_overview.py`：研究资产总览。
- `research/strategy_layer_quality.py`：Top 层级质量诊断。
- `research/strategy_factor_stability.py`：短线/长线因子稳定性。
- `research/strategy_candidate_simulator.py`：候选策略离线模拟。
- `research/official_strategy_health_check.py`：定板策略健康检查。

## 后续可增强

- 增加真正的 walk-forward 训练/验证/留出区间报告。
- 增加候选策略自动登记表，只允许标注为 `research_only`。
- 将夜间报告写入研究数据库，供 Web 端展示。
- 做一个 Codex skill，但当前脚本 + 自动化已经能满足今晚无人值守。
