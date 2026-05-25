"""
市场综合分析模块
整合技术面、情绪面、新闻面，给出统一的市场判断和仓位建议
"""
import logging
from typing import Dict, Optional, Tuple
import market_config

logger = logging.getLogger(__name__)

def get_market_decision(
    market_state: str,
    sentiment_data: Dict,
    news_sentiment: Dict,
    sector_news_boosts: Optional[Dict[str, float]] = None,
) -> Tuple[str, str, str]:
    """
    综合判断市场环境，返回操作建议。

    Args:
        market_state:       技术面状态 ('normal'/'rebound'/'downtrend')
        sentiment_data:     情绪数据 {sentiment, ratio, limit_up_count, limit_down_count}
        news_sentiment:     新闻情绪 {sentiment, score, ai_boost_total, top_positive_sectors}
        sector_news_boosts: 行业消息面加分字典 {"军工": 25, "电子": 18, ...}（可选）

    Returns:
        (操作模式, 仓位建议, 说明)
        操作模式: 'full'全开 | 'short_only'仅短线 | 'light'轻仓 | 'stop'停止
    """
    # 提取数据
    emotion = sentiment_data.get('sentiment', '未知')
    ratio = sentiment_data.get('ratio', 0)
    limit_up = sentiment_data.get('limit_up_count', 0)
    limit_down = sentiment_data.get('limit_down_count', 0)

    news_tone = news_sentiment.get('sentiment', 'neutral') if news_sentiment else 'neutral'
    news_score = news_sentiment.get('score', 0) if news_sentiment else 0
    ai_boost_total = news_sentiment.get('ai_boost_total', 0.0) if news_sentiment else 0.0
    top_positive = news_sentiment.get('top_positive_sectors', []) if news_sentiment else []

    # 消息面强度：AI板块加分最高值（单个板块）
    if sector_news_boosts:
        max_sector_boost = max(sector_news_boosts.values()) if sector_news_boosts else 0
    else:
        max_sector_boost = 0

    # 获取仓位策略
    position_map = market_config.POSITION_ADVICE[market_config.POSITION_STRATEGY]
    cfg = market_config.REBOUND_THRESHOLD
    override_cfg = market_config.NEWS_OVERRIDE_CONFIG

    # ─── 决策矩阵 ───────────────────────────────────────────────────────
    if market_state == 'normal':
        if emotion in ['高涨', '正常']:
            return 'full', position_map['full'], '市场环境良好，可积极操作'
        elif emotion == '偏弱':
            return 'light', position_map['light'], '市场偏弱，降低仓位'
        else:
            return 'light', position_map['light'], '情绪恐慌，极度谨慎'

    elif market_state == 'rebound':
        if emotion == '高涨' or limit_up > 50:
            return 'short_only', position_map['short_only'], '超跌反弹启动，短线抢反弹'
        elif emotion == '正常':
            return 'short_only', position_map['light'], '反弹信号出现，轻仓试探'
        else:
            return 'stop', position_map['stop'], '反弹力度不足，继续观望'

    elif market_state == 'downtrend':
        # ── 强反弹信号判断（原有逻辑）──
        strong_rebound = (
            (limit_up > cfg['strong_limit_up'] and ratio > cfg['strong_ratio'])
            or (limit_up > cfg['super_limit_up'])
        )

        # ── 新增：消息面利好可覆盖 downtrend 空仓（D+A方案核心）──
        policy_override = override_cfg.get('policy_override_downtrend', True)
        override_strength = override_cfg.get('policy_override_strength', 15)

        # 判断是否有足够强的政策/消息利好
        # 条件：AI板块加分最高值 >= 阈值，或 AI总加分 >= 阈值*1.5，或 关键词情绪为正且分数足够
        strong_policy = (
            policy_override and (
                max_sector_boost >= override_strength
                or ai_boost_total >= override_strength * 1.5
                or (news_tone == 'positive' and news_score > cfg['policy_score'])
            )
        )

        if strong_policy:
            # 有政策/消息利好：即使大跌也推荐，但只做轻仓短线
            sectors_hint = f"（{'/'.join(top_positive[:2])}利好）" if top_positive else ""
            return (
                'short_only',
                position_map['light'],
                f'大跌但消息面利好{sectors_hint}，消息强度{max_sector_boost:.0f}分，轻仓布局利好板块'
            )
        elif strong_rebound and not market_config.ALLOW_REBOUND_IN_DOWNTREND is False:
            return 'light', position_map['light'], f'主跌浪中强反弹（涨停{limit_up}家），极轻仓试探'
        else:
            return 'stop', position_map['stop'], '主跌浪且无政策支撑，保护本金'

    return 'light', position_map['light'], '市场不明朗，谨慎操作'
