# 版本控制约定

## 提交流程

每个策略版本按以下顺序推进：

1. 确认 `git status --short`，只允许本实验相关文件进入提交。
2. 在 `docs/EXPERIMENT_LOG.md` 新增实验记录。
3. 修改代码。
4. 运行两段回测：
   - 2025 全年：`20250101~20251231`
   - 2026Q1：`20260101~20260420`
5. 把关键指标写回实验记录。
6. 单独提交。

## Commit 命名

建议格式：

- `docs: ...` 文档或实验记录。
- `baseline: ...` 建立可复现基线。
- `experiment: ...` 策略实验。
- `fix: ...` 修复明确 bug。
- `chore: ...` 工程清理，不改变策略。

示例：

```text
baseline: restore v8 short strategy for reproducible tests
experiment: add weak-market no-leader guard
experiment: filter catchup candidates by sector inflow rank
fix: restore fixed topn weighting in short backtest
```

## 回测产物

`backtest_results/` 的新产物默认不自动进入 Git。

原因：

- 单次实验会产生大量 CSV/JSON/LOG，容易淹没代码改动。
- 大多数结果可由命令复现。

需要保留证据时：

- 优先把指标写进 `docs/EXPERIMENT_LOG.md`。
- 必须保留文件时，用 `git add -f` 强制添加少量关键 `metrics_*.json` 或 `trades_*.csv`。

## 禁止事项

- 不把多个策略变量塞进一个提交。
- 不用未记录的回测结果指导下一轮实验。
- 不回滚用户或历史未知改动，除非先确认。
- 不把回测引擎变更和因子变更混在一个实验提交里。

