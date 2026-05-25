"""
v8.0 交易胜负特征分析
=====================
目的：找出"未来会涨的股"在T日到底有什么特征
用法：python analyze_trades.py
会自动读取 test_result.json 里最新的交易文件
"""

import json
import os
import pandas as pd
import numpy as np

# ── 读取最新的交易文件 ──
with open('test_result.json', 'r', encoding='utf-8') as f:
    result = json.load(f)

# 取2025全年那段
target = next((r for r in result['results'] if '2025' in r['label']), result['results'][-1])
trades_file = os.path.join('backtest_results', target['metrics_file'].replace('metrics_', 'trades_'))
print(f"分析文件：{trades_file}")
print(f"区间：{target['period']}")

df = pd.read_csv(trades_file)
print(f"总笔数：{len(df)}")

# ── 统一收益率字段名 ──
profit_col = next((c for c in ['profit_pct', 'return_pct', 'pnl_pct', 'profit'] if c in df.columns), None)
if profit_col is None:
    print("❌ 找不到收益率字段，可用字段：", df.columns.tolist())
    exit()

df['win'] = df[profit_col] > 0
win = df[df['win']]
lose = df[~df['win']]

print(f"\n胜率：{len(win)}/{len(df)} = {len(win)/len(df)*100:.1f}%")
print(f"平均盈利：{win[profit_col].mean():.2f}%")
print(f"平均亏损：{lose[profit_col].mean():.2f}%")

# ── 对比各字段的胜/败均值 ──
print("\n" + "="*60)
print("【胜败组关键字段对比】")
print("="*60)

compare_cols = [
    'score', 'short_score', 'change', 'volume_ratio', 'main_net_inflow',
    'catchup_bonus', 'drawdown_from_high', 'turnover', 'relative_turnover',
    'wyckoff_score', 'accel_score', 'mf_3d', 'margin_net_buy',
    'mf_3d_bonus', 'margin_bonus', 'top_list_bonus',
]

rows = []
for col in compare_cols:
    if col not in df.columns:
        continue
    w_mean = win[col].mean()
    l_mean = lose[col].mean()
    diff = w_mean - l_mean
    rows.append({'字段': col, '胜组均值': round(w_mean, 3), '败组均值': round(l_mean, 3),
                 '差值(胜-败)': round(diff, 3)})

cmp = pd.DataFrame(rows).sort_values('差值(胜-败)', key=abs, ascending=False)
print(cmp.to_string(index=False))

# ── 出场原因分布 ──
print("\n" + "="*60)
print("【出场原因分布】")
print("="*60)
if 'exit_reason' in df.columns:
    exit_dist = pd.crosstab(df['exit_reason'], df['win'],
                            values=df[profit_col], aggfunc='count').fillna(0)
    exit_dist.columns = ['败组笔数', '胜组笔数']
    exit_dist['总计'] = exit_dist.sum(axis=1)
    exit_dist['胜率'] = (exit_dist['胜组笔数'] / exit_dist['总计'] * 100).round(1)
    exit_dist['平均收益'] = df.groupby('exit_reason')[profit_col].mean().round(2)
    print(exit_dist.sort_values('总计', ascending=False).to_string())

# ── 按regime（市场状态）分组 ──
print("\n" + "="*60)
print("【按市场状态(regime)分组】")
print("="*60)
regime_col = next((c for c in ['regime', 'market_regime', 'operation_mode'] if c in df.columns), None)
if regime_col:
    reg = df.groupby(regime_col).agg(
        笔数=(profit_col, 'count'),
        胜率=(profit_col, lambda x: (x > 0).mean() * 100),
        平均收益=(profit_col, 'mean'),
    ).round(2)
    print(reg.to_string())
else:
    print("无regime字段")

# ── 按catchup_bonus分组（有补涨加分 vs 无）──
print("\n" + "="*60)
print("【有/无补涨加分(catchup_bonus)对比】")
print("="*60)
if 'catchup_bonus' in df.columns:
    df['has_catchup'] = df['catchup_bonus'] > 0
    cat = df.groupby('has_catchup').agg(
        笔数=(profit_col, 'count'),
        胜率=(profit_col, lambda x: (x > 0).mean() * 100),
        平均收益=(profit_col, 'mean'),
    ).round(2)
    cat.index = ['无补涨加分', '有补涨加分']
    print(cat.to_string())
else:
    print("无catchup_bonus字段")

# ── 按评分段分组 ──
print("\n" + "="*60)
print("【按评分段分组】")
print("="*60)
score_col = 'score' if 'score' in df.columns else 'short_score'
if score_col in df.columns:
    df['score_bin'] = pd.cut(df[score_col], bins=5)
    sbin = df.groupby('score_bin').agg(
        笔数=(profit_col, 'count'),
        胜率=(profit_col, lambda x: (x > 0).mean() * 100),
        平均收益=(profit_col, 'mean'),
    ).round(2)
    print(sbin.to_string())

# ── 按今日涨幅(change)分组 ──
print("\n" + "="*60)
print("【按入场当日涨幅分组】")
print("="*60)
if 'change' in df.columns:
    df['change_bin'] = pd.cut(df['change'], bins=[-10, 0, 1, 2, 3, 4, 5, 6, 10])
    cbin = df.groupby('change_bin').agg(
        笔数=(profit_col, 'count'),
        胜率=(profit_col, lambda x: (x > 0).mean() * 100),
        平均收益=(profit_col, 'mean'),
    ).round(2)
    print(cbin.to_string())

# ── 按主力净流入分组 ──
print("\n" + "="*60)
print("【按主力净流入(main_net_inflow)分组】")
print("="*60)
if 'main_net_inflow' in df.columns:
    df['inflow_bin'] = pd.cut(df['main_net_inflow'],
                               bins=[-1e9, -1000, 0, 1000, 5000, 1e9],
                               labels=['大幅净流出(<-1000万)', '小幅净流出', '小幅净流入(0~1000万)',
                                       '中幅净流入(1000~5000万)', '大幅净流入(>5000万)'])
    ibin = df.groupby('inflow_bin').agg(
        笔数=(profit_col, 'count'),
        胜率=(profit_col, lambda x: (x > 0).mean() * 100),
        平均收益=(profit_col, 'mean'),
    ).round(2)
    print(ibin.to_string())

# ── 胜组TOP10 vs 败组BOTTOM10 ──
print("\n" + "="*60)
print("【胜组最佳10笔 vs 败组最差10笔】")
print("="*60)
show_cols = [c for c in ['code', 'name', 'industry', profit_col, 'score',
                          'change', 'catchup_bonus', 'main_net_inflow',
                          'exit_reason', 'hold_days'] if c in df.columns]
print("\n--- 胜组最佳10笔 ---")
print(win.nlargest(10, profit_col)[show_cols].to_string(index=False))
print("\n--- 败组最差10笔 ---")
print(lose.nsmallest(10, profit_col)[show_cols].to_string(index=False))

print("\n✅ 分析完成")
