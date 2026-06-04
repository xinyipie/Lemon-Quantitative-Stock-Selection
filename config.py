import os
from datetime import datetime

# ==================== 选股配置 ====================
MIN_STOCK_AMOUNT = 200000    # 基础候选池最小成交额（千元，等于2亿元；tushare daily 的 amount 字段单位是千元）
MIN_STOCK_AMOUNT_SHORT = 150000  # 短线二次过滤最小成交额（千元，等于1.5亿元；涨停回调策略放宽要求）
MIN_CHANGE = 1                # 最小涨幅（%，次日潜力策略：刚启动不追高）
MAX_CHANGE = 6                # 最大涨幅（%，涨太多次日容易回调）
MIN_TURNOVER = 3              # 最小换手率（%，过滤流动性不足的僵尸股）
MAX_TURNOVER = 12             # 最大换手率（%，适度放宽；>12%说明分歧过大或量化刷量）

# ==================== 市场状态机配置（4状态 Regime Filter）====================
# 参考：Faber(2007) "A Quantitative Approach to Tactical Asset Allocation"
#       Asness et al.(2013) "Value and Momentum Everywhere"
#
# 4种市场状态（由 get_market_regime() 判断）：
#   BULL_TREND    → 长期牛市 + 短期上涨：全力出击
#   BULL_PULLBACK → 长期牛市 + 短期回调：缩减仓位
#   BEAR_BOUNCE   → 长期熊市 + 短期反弹：轻仓超短
#   BEAR_TREND    → 长期熊市 + 短期下跌：空仓观望
#
# 判断标准：
#   长期牛/熊：CSI300 日线MA30（约1.5个月），价格 > MA30 且 MA30 斜率向上 → 长期牛市
#   短期方向：  MA10 > MA30（金叉）→ 短期上涨；反之短期下跌
#   【方案C】MA60→MA30（长期）+ MA20→MA10（短期）：响应速度比原方案快2倍，
#             MA10/MA30 跨度20日，信号灵敏但在宽幅震荡市可能频繁切换

# 各状态下仓位乘数（作用于回测的 Top N 开仓数量）
REGIME_POSITION_MULTIPLIER = {
    'BULL_TREND':    1.0,   # 满仓 Top3
    'BULL_PULLBACK': 1.0,   # 牛市回调：不减仓位数量，靠评分门槛和ATR过滤质量
    'BEAR_BOUNCE':   0.33,  # ≈ Top1（极轻仓）
    'BEAR_TREND':    0.0,   # 空仓
}

# 各状态下最大持仓天数（覆盖回测/实盘默认值）
REGIME_MAX_HOLD_DAYS = {
    'BULL_TREND':    8,     # 正常周期
    'BULL_PULLBACK': 5,     # 牛市回调缩短持仓，减少被套风险
    'BEAR_BOUNCE':   3,     # 缩短至3天，快进快出
    'BEAR_TREND':    0,     # 不开仓
}

# 各状态下评分准入门槛（final_score 低于此值不开仓）
# 【重新校准 2026-04-25】：加入 catchup_bonus/vol_shrink_bonus/close_pos_penalty 后
#   实际评分分布已从原来的 35~65 变为 50~120，门槛需同步上移
#   BULL_TREND:    55 → 过滤底部 ~30% 信号，维持合理交易频率
#   BULL_PULLBACK: 60 → 比牛市多过滤 ~15%，聚焦高质量标的
#   BEAR_BOUNCE:   72 → 严格过滤，只选 top ~15% 的信号（轻仓超短）
#   BEAR_TREND:    999 → 不开仓
REGIME_SCORE_THRESHOLD = {
    'BULL_TREND':    55,   # reconstructed v8 baseline
    'BULL_PULLBACK': 60,   # 回调期收紧
    'BEAR_BOUNCE':   72,   # 极轻仓期只选高确定性
    'BEAR_TREND':    999,  # 不开仓
}

# 波段策略专属评分门槛（Z-Score后分布为 20~95，均值60）
# 注意：Z-Score是截面相对分，每天候选池规模不同，不宜设过高绝对门槛
# 50 = 均值附近（保留约50%候选股，每天至少有信号）
# 55 = 约均值+0.5σ（保留约30%），60 = 均值（不过滤）
# 设置55作为宽松基础门槛，仅排除明显低质量标的，不过滤整个时段
LONGTERM_SCORE_THRESHOLD = {
    'BULL_TREND':    55,    # 宽松门槛：保留约30%候选，避免因早期市场候选池小而空仓
    'BULL_PULLBACK': 57,    # 牛市回调：略严格，但仍保留足够候选
}

# 各状态下 ATR 止损倍数（控制单笔最大损失）
REGIME_ATR_MULTIPLIER = {
    'BULL_TREND':    1.5,   # 正常止损空间
    'BULL_PULLBACK': 1.2,   # 略收紧
    'BEAR_BOUNCE':   1.0,   # 收紧止损，快进快出
    'BEAR_TREND':    1.0,   # 不开仓，无意义
}

# 月线长期趋势判断参数
# 月线长期趋势判断参数
REGIME_LONG_TERM_MA = 60        # 长期均线：日线MA60（约3个月，April 18基准）
REGIME_SHORT_TERM_MA = 20       # 短期均线：日线MA20（约1个月）
# 理论依据：Weinstein四阶段（MA60≈30周均线的日线近似）+ Faber(2007)月均线择时
# 经2023~2025全段验证：短线胜率47.5%，波段231笔胜率35%+17.93%总收益
REGIME_MA60_SLOPE_THRESHOLD = 0.02  # MA60斜率阈值（%/日），< -0.02%/日视为趋势向下

# ==================== 快速翻转检测配置（Override）====================
# 解决状态机滞后问题：当市场出现极端单日信号时，
# 临时覆盖慢速状态机的判断，避免踏空政策驱动的急速反转。
# 参考：Chan(2013) "Algorithmic Trading" — 微观结构实时信号
#
# 仅对 BEAR_TREND 生效（已经是BEAR_BOUNCE则不再升级）
# 升级规则（触发条件计分，每条满足+1）：
#   满足 2/4 条 → BEAR_TREND 升级为 BEAR_BOUNCE（允许极轻仓Top1）
#   满足 3/4 条 → BEAR_TREND 升级为 BULL_PULLBACK（允许半仓Top2）
#
# 4个触发条件的阈值（可独立调整）：
REGIME_OVERRIDE_INDEX_CHG    = 2.0   # ① 大盘中位数涨幅阈值（%）
REGIME_OVERRIDE_UP_RATIO     = 0.70  # ② 全市场上涨家数占比阈值（70%）
REGIME_OVERRIDE_LIMIT_UP     = 80    # ③ 涨停家数阈值
REGIME_OVERRIDE_VOLUME_RATIO = 1.5   # ④ 今日成交额/5日均额阈值

# Override后的状态机参数（比正常BEAR_BOUNCE/BULL_PULLBACK稍保守）
REGIME_OVERRIDE_POSITION = {
    'BEAR_BOUNCE_OVERRIDE':   0.33,  # 同正常BEAR_BOUNCE，仅开Top1
    'BULL_PULLBACK_OVERRIDE': 0.50,  # 比正常BULL_PULLBACK(0.67)略保守
}
REGIME_OVERRIDE_SCORE_THRESHOLD = {
    'BEAR_BOUNCE_OVERRIDE':   80,    # 极严格，只有最高分才进
    'BULL_PULLBACK_OVERRIDE': 65,    # 比正常BULL_PULLBACK略严
}
REGIME_OVERRIDE_MAX_HOLD = {
    'BEAR_BOUNCE_OVERRIDE':   3,     # 只持3天，快进快出
    'BULL_PULLBACK_OVERRIDE': 4,     # 只持4天
}

# ==================== 财务过滤配置 ====================
MIN_ROE = 3                   # 最低ROE（%，3%过滤掉严重亏损股，0表示不过滤）
MAX_DEBT_RATIO = 85           # 最高资产负债率（%，85%过滤高风险股）
MIN_REVENUE_GROWTH = -20      # 最低营收增长率（%，-20%允许轻微下滑，过滤严重衰退股）
ENABLE_FINANCIAL_FILTER = True  # 是否启用财务过滤（可关闭以对比效果）
ENABLE_FINANCIAL_FILTER_SHORT = False  # 短线策略是否启用财务过滤（方案B：短线不看基本面）

# 短线实盘报告使用的已验证基准：与 backtest_v2.py 的当前主基准保持一致。
SHORT_LIVE_FACTOR_PROFILE = "profile_v9_sector_quality_guard"
SHORT_LIVE_STYLE_GATE = "adaptive_quality_v6"
SHORT_LIVE_SCORE_ORDER = "desc"
ENABLE_LONGTERM_LIVE = False  # 当前主线先专注短线；波段策略整理完成后再打开

# ==================== AI配置（通义千问） ====================
# 配置说明：
# 1. 优先从环境变量读取（推荐，更安全）
# 2. 如果环境变量未设置，使用下方配置的默认值
# 3. 修改密钥：直接修改下方的字符串即可

# AI API Keys
# Keep real keys in environment variables; never commit them to Git.
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# ==================== AI模型配置（可切换） ====================
# 支持的模型配置（取消注释即可切换）

# 方案1：DeepSeek Chat（当前使用，OpenAI-compatible）
AI_CONFIG = {
    "provider": "deepseek",
    "api_key": DEEPSEEK_API_KEY,
    "base_url": "https://api.deepseek.com/v1/chat/completions",
    "model": "deepseek-chat",
    "timeout": 60,
    "temperature": 0.1,
    "max_tokens": 6000
}

# 方案2：通义千问 Plus（推荐升级，能力强很多，价格适中）
# AI_CONFIG = {
#     "api_key": os.environ.get("DASHSCOPE_API_KEY", DASHSCOPE_API_KEY),
#     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
#     "model": "qwen-plus",
#     "timeout": 60,
#     "temperature": 0.1,
#     "max_tokens": 6000
# }

# 方案3：通义千问 Max（最强，但贵）
# AI_CONFIG = {
#     "api_key": os.environ.get("DASHSCOPE_API_KEY", DASHSCOPE_API_KEY),
#     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
#     "model": "qwen-max",
#     "timeout": 60,
#     "temperature": 0.1,
#     "max_tokens": 6000
# }

# 方案4：DeepSeek（强烈推荐，便宜且能力强）
# 获取API Key：https://platform.deepseek.com/
# AI_CONFIG = {
#     "api_key": os.environ.get("DEEPSEEK_API_KEY", "你的DeepSeek API Key"),
#     "base_url": "https://api.deepseek.com/v1",
#     "model": "deepseek-chat",
#     "timeout": 60,
#     "temperature": 0.1,
#     "max_tokens": 6000
# }

# 方案5：DeepSeek Reasoner（推理模型，分析最深入）
# AI_CONFIG = {
#     "api_key": os.environ.get("DEEPSEEK_API_KEY", "你的DeepSeek API Key"),
#     "base_url": "https://api.deepseek.com/v1",
#     "model": "deepseek-reasoner",
#     "timeout": 90,  # 推理模型需要更长时间
#     "temperature": 0.1,
#     "max_tokens": 6000
# }

# 方案6：OpenAI GPT-4（能力强但贵，需要国际支付）
# 获取API Key：https://platform.openai.com/
# AI_CONFIG = {
#     "api_key": os.environ.get("OPENAI_API_KEY", "你的OpenAI API Key"),
#     "base_url": "https://api.openai.com/v1",
#     "model": "gpt-4-turbo-preview",
#     "timeout": 60,
#     "temperature": 0.1,
#     "max_tokens": 6000
# }

# 方案7：Claude 3.5 Sonnet（分析最专业但最贵，需要国际支付）
# 获取API Key：https://console.anthropic.com/
# 注意：Claude API格式不同，需要修改main.py中的call_ai_api函数
# AI_CONFIG = {
#     "api_key": os.environ.get("ANTHROPIC_API_KEY", "你的Anthropic API Key"),
#     "base_url": "https://api.anthropic.com/v1/messages",
#     "model": "claude-3-5-sonnet-20241022",
#     "timeout": 60,
#     "temperature": 0.1,
#     "max_tokens": 6000
# }

# ==================== Tushare配置 ====================
# Tushare Token
# 获取地址：https://tushare.pro/register
# 要求：积分 >= 5000（通过签到、分享等方式获取）
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")

TUSHARE_CONFIG = {
    "token": TUSHARE_TOKEN,
    "timeout": 30,   # 从10秒改为30秒，中转站延迟高
    "retry_count": 3
}

# ==================== 消息面配置 ====================
NEWS_ANALYSIS_CONFIG = {
    "enable_ai_news": True,           # 是否启用AI新闻解读（消耗API额度，约1次调用）
    "enable_hot_concepts": False,     # 是否启用概念板块热度（akshare免费，东方财富接口不稳定）
    "news_boost_max": 30,             # 消息面最大加分（单个板块）
    "news_boost_min": -20,            # 消息面最大扣分（单个板块）
    "concept_top_n": 10,              # 抓取前N个热门概念板块
    "policy_override_downtrend": True,   # 政策利好是否可覆盖downtrend空仓决策
    "policy_override_strength": 15,      # 覆盖downtrend所需的最低消息强度（0-30）
}

# ==================== 路径配置 ====================
# 创建专门的存储目录
LOGS_DIR = "logs"
REPORTS_DIR = "reports"

# 确保目录存在
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# 文件路径
LOG_FILE_PATH = os.path.join(LOGS_DIR, f"trading_log_{datetime.now().strftime('%Y%m%d')}.log")

# ==================== 日志配置 ====================
LOG_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(levelname)s - %(message)s",
    "datefmt": "%Y-%m-%d %H:%M:%S"
}
