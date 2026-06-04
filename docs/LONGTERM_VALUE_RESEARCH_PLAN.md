# 长线价值质量策略研究计划

更新时间：2026-06-04

## 当前决策

短线已经定板，波段暂时留档，下一条主线转向真正长线策略。

波段保留为 `swing` 实验线：

```text
当前较优候选：zscore_v5_quality_guard + trailing_activate=15 + trailing_stop=10 + max_positions=15
v7_quality_guard：不升级，弱市未改善，2025 明显误伤高弹性票
```

判断：
- 波段能找到高弹性票，但对市场环境依赖很强；
- 2025 强行情可改善，2024H2/2026 弱震荡环境仍不稳定；
- 继续在波段上加护栏容易过拟合；
- 后续暂停深挖波段，转向真正长线策略研究。

## 长线策略边界

长线不复用当前波段逻辑。当前 `longterm` 更接近波段，真正长线应另起研究线。

```text
目标：公司质量 + 成长稳定 + 财务安全 + 合理价格 + 长期趋势辅助
调仓：月度或季度
持有：6-24个月
组合：10-30只等权
退出：基本面恶化、估值过高、长期趋势破坏，而不是短线移动止损
```

## 第一阶段：因子审计

先做因子审计，不直接写策略。

新增工具：

```text
longterm_value_quality_diagnostics.py
```

示例命令：

```text
python longterm_value_quality_diagnostics.py --asof-date 20250102 --start 20240101 --end 20260603 --forward-days 120 240 --output reports/longterm_value_quality_audit_20250102.md
```

已生成首份报告：

```text
reports/longterm_value_quality_audit_20250102.md
```

首份审计初步观察：
- 2025-01-02 截面共分析 5354 个样本；
- `ret_120d` 均值 +16.00%，中位数 +9.46%；
- 单纯 `quality_score` 对 120 日收益相关性较弱；
- 过去一年涨幅、回撤、价格相对长期均线的相关性更明显；
- 长线不能只靠 ROE/净利增速，后续需要加入估值维度和更稳定的多年财务质量。

## 当前数据限制

- `fina_indicator.parquet` 当前含 `roe/debt_to_assets/netprofit_yoy`；
- `income.parquet` 当前含 `revenue`；
- `daily_basic` 当前只有 `turnover_rate/volume_ratio`，尚无 PE/PB/股息率；
- 第一版长线审计先看财务质量、成长、负债、长期趋势和一年回撤；
- 估值维度后续需补充 `pe/pb/ps/dv_ratio/total_mv` 等字段。

## 下一步

1. 补充估值数据缓存字段。
2. 做多个截面审计，而不是只看 2025-01-02。
3. 观察 120/240 日维度上哪些因子稳定有效。
4. 再设计 `select_value_growth_pool()`，不要过早进入回测。
