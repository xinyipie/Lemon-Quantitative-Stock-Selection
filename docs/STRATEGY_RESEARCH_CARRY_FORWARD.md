# 策略研究吸收记录

更新时间：2026-06-22

本文记录端午 research 结果中可以吸收到现有定板流程的部分。它不是上线策略变更说明。

## 当前正式策略不变

短线正式版保持：

```text
profile_v4_adaptive_quality_v9_sector_quality_guard + baseline exit + Top3
```

长线当前版保持：

```text
longterm_quality_lifecycle_v18_market_sync
```

## 已吸收的内容

1. 短线 v9 不直接改权重。
   - 分层诊断显示 Top3 仍有质量优势。
   - Top1 收缩、资金/板块轻重排没有跨区间稳定改善。
   - `short_v9_quality_floor_top3` 只保留观察，不进入上线验证。

2. 长线 v18 不再过度相信 Top3 精准排序。
   - 研究显示 v18 池子不是完全无效，主要问题是排序精度不足。
   - `long_v18_quality_floor_top10` 是下一轮验证候选。
   - 推荐方向是“质量地板 + Top10观察池 + 生命周期状态经营”，不是直接替换线上默认。

3. 新增定板健康检查入口。
   - 使用 `research/official_strategy_health_check.py` 汇总 research 结论。
   - 输出 `reports/research/official_strategy_health_check.md`。
   - 该报告用于判断是否进入下一轮验证，不会自动改 `main.py`。

## 不吸收的内容

- 不把短线 Top3 改成 Top1。
- 不把短线资金/板块轻重排复制到正式 v9。
- 不把长线 `long_v18_quality_floor_top10` 直接设置成正式默认。
- 不根据 2026 单一区间表现升级策略。

## 复跑命令

```powershell
python research\strategy_layer_quality.py --output reports\research\dragon_boat_layer_quality.md
python research\strategy_factor_stability.py --output reports\research\dragon_boat_factor_stability.md
python research\strategy_candidate_simulator.py --output reports\research\dragon_boat_candidate_simulation.md
python research\official_strategy_health_check.py --output reports\research\official_strategy_health_check.md
```
