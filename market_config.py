# ==================== 市场决策配置 ====================
# v2.9新增：灵活的市场决策参数

# 主跌浪中的反弹阈值
REBOUND_THRESHOLD = {
    'strong_limit_up': 50,      # 强反弹：涨停数量阈值
    'strong_ratio': 3.0,        # 强反弹：涨停/跌停比阈值
    'super_limit_up': 80,       # 超强反弹：涨停数量阈值（无视其他条件）
    'policy_score': 5           # 政策利好分数阈值（关键词统计）
}

# 消息面覆盖空仓配置（D+A方案新增）
NEWS_OVERRIDE_CONFIG = {
    'policy_override_downtrend': True,   # 政策/消息利好是否可覆盖downtrend空仓
    'policy_override_strength': 15,      # 覆盖downtrend所需的最低单板块消息强度（0-30）
}

# 仓位建议（可根据个人风险偏好调整）
POSITION_ADVICE = {
    'aggressive': {             # 激进型
        'full': '60-90%',
        'short_only': '40-60%',
        'light': '20-40%',
        'stop': '空仓'
    },
    'moderate': {               # 稳健型（默认）
        'full': '50-80%',
        'short_only': '30-50%',
        'light': '20-30%',
        'stop': '空仓'
    },
    'conservative': {           # 保守型
        'full': '30-50%',
        'short_only': '20-30%',
        'light': '10-20%',
        'stop': '空仓'
    }
}

# 当前使用的仓位策略（可选：aggressive/moderate/conservative）
POSITION_STRATEGY = 'moderate'

# 是否允许主跌浪中抢反弹（True=灵活，False=保守）
ALLOW_REBOUND_IN_DOWNTREND = True
