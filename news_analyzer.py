"""
新闻与消息面分析模块 v2.0

改动（D+A 方案）：
  - 方案D：新增 get_hot_concepts()，抓取东方财富概念板块实时涨跌热度
  - 方案A：新增 ai_parse_news_to_sectors() + build_sector_boosts()，
            用 AI 将新闻标题映射到申万一级行业，生成板块加分字典
  - 重写 analyze_news_sentiment()，整合 AI 解读结果和关键词兜底
  - 所有新功能失败时静默降级，不影响主选股流程
"""

import logging
import re
from typing import Callable, Dict, List, Optional

import pandas as pd

import config

logger = logging.getLogger(__name__)

# ==================== 申万一级行业关键词映射 ====================
# 用于概念板块名称 → 申万行业的模糊匹配
# key: 申万一级行业名，value: 概念名中可能出现的关键词
INDUSTRY_CONCEPT_KEYWORDS: Dict[str, List[str]] = {
    "农林牧渔": ["农业", "种业", "生猪", "粮食", "畜牧", "水产", "化肥"],
    "采掘":     ["煤炭", "煤矿", "采掘", "矿业", "焦煤", "动力煤"],
    "化工":     ["化工", "化学", "塑料", "橡胶", "农药", "化肥", "氢能", "氨"],
    "钢铁":     ["钢铁", "钢材", "铁矿", "特钢", "不锈钢"],
    "有色金属": ["黄金", "铜", "铝", "锂", "镍", "钴", "稀土", "有色", "贵金属"],
    "电子":     ["半导体", "芯片", "集成电路", "消费电子", "PCB", "面板", "存储"],
    "家用电器": ["家电", "空调", "冰箱", "洗衣机", "厨电", "白电"],
    "食品饮料": ["白酒", "啤酒", "食品", "饮料", "乳制品", "调味品"],
    "纺织服饰": ["纺织", "服装", "鞋类", "羽绒"],
    "轻工制造": ["造纸", "印刷", "家具", "包装"],
    "医药生物": ["医药", "生物", "疫苗", "CXO", "创新药", "医疗", "中药"],
    "公用事业": ["电力", "水务", "燃气", "核电", "清洁能源"],
    "交通运输": ["航空", "航运", "物流", "高铁", "公路", "港口"],
    "房地产":   ["房地产", "地产", "物业", "住房", "REITs"],
    "商贸零售": ["零售", "商超", "电商", "跨境"],
    "社会服务": ["旅游", "酒店", "餐饮", "教育", "职业培训"],
    "综合":     ["综合"],
    "建筑材料": ["水泥", "玻璃", "建材", "陶瓷"],
    "建筑装饰": ["建筑", "装饰", "园林", "基建"],
    "电力设备": ["光伏", "风电", "储能", "充电桩", "电池", "新能源"],
    "国防军工": ["军工", "航天", "军事", "国防", "导弹", "雷达", "无人机"],
    "计算机":   ["AI", "人工智能", "大模型", "云计算", "信创", "软件", "数字"],
    "传媒":     ["传媒", "游戏", "影视", "广告", "出版"],
    "通信":     ["通信", "5G", "6G", "卫星", "物联网"],
    "银行":     ["银行", "银行股"],
    "非银金融": ["券商", "保险", "信托", "期货"],
    "汽车":     ["汽车", "新能源车", "智能驾驶", "自动驾驶", "零部件"],
    "机械设备": ["机器人", "工业母机", "机械", "工程机械", "低空经济", "eVTOL"],
}

# ==================== 关键词库（兜底） ====================
POSITIVE_KEYWORDS = {
    "货币政策": ["降息", "降准", "宽松", "流动性", "放水", "LPR下调"],
    "财政政策": ["减税", "补贴", "刺激", "投资", "基建", "专项债"],
    "产业政策": ["支持", "鼓励", "扶持", "利好", "发展", "政策"],
    "地缘缓和": ["停火", "谈判", "和谈", "协议", "缓和", "撤军"],
    "监管放松": ["放开", "简化", "优化", "便利", "解禁"],
}

NEGATIVE_KEYWORDS = {
    "货币紧缩": ["加息", "提准", "紧缩", "回收"],
    "监管收紧": ["监管", "处罚", "整顿", "限制", "禁止", "退市"],
    "地缘风险": ["制裁", "关税", "贸易战", "冲突", "战争", "轰炸"],
    "风险警示": ["风险", "警示", "暂停", "调查", "违约"],
}


# ==================== 方案D：概念板块热度 ====================

def get_hot_concepts(top_n: Optional[int] = None) -> List[Dict]:
    """
    获取东方财富概念板块实时热度（方案D）。

    Returns:
        List of dicts: [{"concept": "低空经济", "change": 3.5, "heat": 85.0}, ...]
        热度 heat = 涨幅60% + 换手率40%，归一化到 0-100
        失败时返回空列表，不影响主流程
    v2.9优化：加当天文件缓存 + akshare 调用超时控制（15秒），避免 RemoteDisconnected 长时间阻塞
    """
    if not config.NEWS_ANALYSIS_CONFIG.get("enable_hot_concepts", True):
        return []

    if top_n is None:
        top_n = config.NEWS_ANALYSIS_CONFIG.get("concept_top_n", 10)

    # ── 当天文件缓存：akshare 经常断连，同一天只拉一次 ──
    import os
    today_str = __import__("datetime").date.today().strftime("%Y%m%d")
    cache_dir = os.path.join(config.LOGS_DIR, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"hot_concepts_{today_str}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = __import__("json").load(f)
            logger.info(f"✅ 概念板块热度：命中当天缓存，{len(cached)}个概念（跳过网络请求）")
            return cached[:top_n]
        except Exception as e_cache:
            logger.debug(f"读取概念板块缓存失败，重新拉取：{e_cache}")

    try:
        import akshare as ak
        import threading

        # ── 超时控制：akshare 默认无超时，RemoteDisconnected 会一直阻塞 ──
        _result_holder: List = []
        _error_holder: List = []

        def _fetch():
            try:
                _result_holder.append(ak.stock_board_concept_name_em())
            except Exception as e_inner:
                _error_holder.append(e_inner)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()
        t.join(timeout=15)  # 最多等15秒

        if t.is_alive():
            # 线程还在跑说明超时，daemon线程会在主进程结束时自动清理
            logger.warning("⚠️ 概念板块获取超时（15s），本次跳过（不影响选股）")
            return []

        if _error_holder:
            raise _error_holder[0]

        df = _result_holder[0] if _result_holder else None
        if df is None or df.empty:
            logger.warning("⚠️ 概念板块数据为空")
            return []

        logger.debug(f"概念板块原始列名：{df.columns.tolist()}")

        # 统一列名（东方财富接口列名可能变化）
        col_map = {}
        for col in df.columns:
            if "名称" in col or "板块" in col:
                col_map[col] = "concept"
            elif "涨跌幅" in col or "涨幅" in col:
                col_map[col] = "change"
            elif "换手率" in col or "换手" in col:
                col_map[col] = "turnover"
        df = df.rename(columns=col_map)

        required = {"concept", "change"}
        if not required.issubset(df.columns):
            logger.warning(f"⚠️ 概念板块接口列名不匹配，现有列：{df.columns.tolist()}")
            return []

        # 先强制转 str 再转数字，防止 akshare 返回 dict/object 类型列导致报错
        df["change"] = pd.to_numeric(df["change"].astype(str), errors="coerce").fillna(0)
        if "turnover" in df.columns:
            df["turnover"] = pd.to_numeric(df["turnover"].astype(str), errors="coerce").fillna(0)
        else:
            df["turnover"] = 0.0

        # 热度计算：涨幅60% + 换手率40%，归一化到 0-100
        max_change = df["change"].abs().max() or 1
        max_turnover = df["turnover"].max() or 1
        df["heat"] = (
            (df["change"] / max_change * 60).clip(-60, 60) +
            (df["turnover"] / max_turnover * 40).clip(0, 40)
        )

        # 只取上涨的概念（涨幅>0），按热度降序；缓存全量，top_n 由调用方控制
        hot_df = df[df["change"] > 0].sort_values("heat", ascending=False).head(50)

        result = [
            {
                "concept": str(row["concept"]),
                "change": round(float(row["change"]), 2),
                "heat": round(float(row["heat"]), 1),
            }
            for _, row in hot_df.iterrows()
        ]

        logger.info(
            f"✅ 获取到 {len(result)} 个热门概念板块："
            f"{', '.join(r['concept'] for r in result[:3])}..."
        )

        # ── 写入当天缓存 ──
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                __import__("json").dump(result, f, ensure_ascii=False)
            logger.debug(f"📦 概念板块热度已缓存：{cache_file}")
        except Exception as e_w:
            logger.debug(f"写入概念板块缓存失败（不影响结果）：{e_w}")

        return result[:top_n]

    except Exception as e:
        logger.warning(f"⚠️ 概念板块获取失败（不影响选股）：{e}")
        return []


def match_concept_to_industry(concept_name: str) -> List[str]:
    """
    将概念板块名称模糊匹配到申万一级行业列表。
    一个概念可能对应多个行业。
    """
    matched = []
    for industry, keywords in INDUSTRY_CONCEPT_KEYWORDS.items():
        if any(kw in concept_name for kw in keywords):
            matched.append(industry)
    return matched


def build_concept_industry_boosts(hot_concepts: List[Dict]) -> Dict[str, float]:
    """
    将热门概念板块热度映射到申万行业加分。
    同一行业取最高热度概念的分值。
    Returns: {"国防军工": 8.5, "计算机": 6.2, ...}  (0-10分)
    """
    industry_boost: Dict[str, float] = {}
    for item in hot_concepts:
        industries = match_concept_to_industry(item["concept"])
        boost = item["heat"] * 0.1  # heat(0-100) → boost(0-10)
        for ind in industries:
            if boost > industry_boost.get(ind, 0):
                industry_boost[ind] = round(boost, 2)
    return industry_boost


# ==================== 方案A：AI新闻→板块映射 ====================

def ai_parse_news_to_sectors(
    news_titles: List[str],
    call_ai_api_fn: Callable,
) -> List[Dict]:
    """
    用 AI 将新闻标题解读为板块影响（方案A）。

    Args:
        news_titles:    新闻标题列表（最多15条）
        call_ai_api_fn: main.py 中的 call_ai_api 函数引用（避免循环 import）

    Returns:
        List of dicts:
        [{"news": "关键词", "type": "国内政策", "sectors": ["军工"],
          "impact": "positive", "strength": 8, "duration": "1-3天", "reason": "..."}]
        失败时返回空列表
    """
    if not config.NEWS_ANALYSIS_CONFIG.get("enable_ai_news", True):
        return []

    if not news_titles:
        return []

    import json
    import ai_prompts

    titles_text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(news_titles[:15]))
    prompt = ai_prompts.PROMPT_NEWS_TO_SECTOR.format(news_titles=titles_text)

    try:
        raw = call_ai_api_fn(
            prompt=prompt,
            system=ai_prompts.SYSTEM_NEWS_ANALYST,
        )
        if not raw:
            return []

        # 提取 JSON 数组
        m = re.search(r"\[[\s\S]*\]", raw)
        if not m:
            logger.warning("⚠️ AI新闻解读：未找到JSON数组")
            return []

        parsed = json.loads(m.group())
        if not isinstance(parsed, list):
            return []

        # 校验字段完整性
        valid = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if "sectors" not in item or "impact" not in item or "strength" not in item:
                continue
            # strength 转数字
            try:
                item["strength"] = int(float(item["strength"]))
            except (ValueError, TypeError):
                item["strength"] = 0
            if item["strength"] < 1:
                continue
            # sectors 确保是列表
            if isinstance(item["sectors"], str):
                item["sectors"] = [item["sectors"]]
            valid.append(item)

        logger.info(f"✅ AI新闻解读完成：{len(valid)} 条板块影响")
        return valid

    except Exception as e:
        logger.warning(f"⚠️ AI新闻解读失败（不影响选股）：{e}")
        return []


def build_sector_boosts(ai_news_result: List[Dict]) -> Dict[str, float]:
    """
    将 AI 解读结果转换为行业加分字典。

    Rules:
      - positive impact: boost = strength * 3  (strength=10 → +30分)
      - negative impact: boost = -(strength * 2) (strength=10 → -20分)
      - 同一行业多条消息：取代数和，最终 clip 到 [news_boost_min, news_boost_max]
    """
    cfg = config.NEWS_ANALYSIS_CONFIG
    boost_max = cfg.get("news_boost_max", 30)
    boost_min = cfg.get("news_boost_min", -20)

    raw_boosts: Dict[str, float] = {}

    for item in ai_news_result:
        strength = item.get("strength", 0)
        impact = item.get("impact", "neutral")
        sectors = item.get("sectors", [])

        if impact == "positive":
            delta = strength * 3.0
        elif impact == "negative":
            delta = -(strength * 2.0)
        else:
            continue  # neutral 不加分

        for sector in sectors:
            raw_boosts[sector] = raw_boosts.get(sector, 0) + delta

    # clip 到配置范围
    return {
        sector: round(max(boost_min, min(boost_max, val)), 1)
        for sector, val in raw_boosts.items()
    }


# ==================== 新闻情绪综合分析（保留+增强） ====================

def get_policy_news(days: int = 3) -> pd.DataFrame:
    """
    获取近期财经要闻（使用 akshare）。
    失败时返回空 DataFrame，不影响主流程。
    """
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol="全部")
        if df is None or df.empty:
            return pd.DataFrame()

        # 统一列名
        rename_map = {}
        for col in df.columns:
            if "标题" in col:
                rename_map[col] = "title"
            elif "时间" in col or "日期" in col:
                rename_map[col] = "date"
            elif "内容" in col:
                rename_map[col] = "content"
        df = df.rename(columns=rename_map)

        if "title" not in df.columns:
            return pd.DataFrame()

        logger.info(f"✅ 获取到 {len(df)} 条财经新闻（取最新{min(20, len(df))}条）")
        return df.head(20)

    except Exception as e:
        logger.warning(f"⚠️ 新闻获取失败（不影响选股）：{e}")
        return pd.DataFrame()


def analyze_news_sentiment(
    news_df: pd.DataFrame,
    ai_news_result: Optional[List[Dict]] = None,
) -> Dict:
    """
    综合分析新闻情绪。
    优先使用 AI 解读结果，关键词统计作为兜底。

    Returns:
        {
          "sentiment": "positive/negative/neutral",
          "score": int,           # 关键词统计分
          "positive": int,
          "negative": int,
          "ai_boost_total": float,  # AI板块加分总和（衡量整体利好程度）
          "top_positive_sectors": ["军工", "电子"],  # AI识别的利好板块
          "top_negative_sectors": ["房地产"],
        }
    """
    # 1. 关键词统计（兜底）
    pos_count = neg_count = 0
    if not news_df.empty and "title" in news_df.columns:
        titles = " ".join(news_df["title"].astype(str).tolist())
        for kws in POSITIVE_KEYWORDS.values():
            pos_count += sum(titles.count(w) for w in kws)
        for kws in NEGATIVE_KEYWORDS.values():
            neg_count += sum(titles.count(w) for w in kws)

    kw_score = pos_count - neg_count

    # 2. AI 解读结果整合
    ai_boost_total = 0.0
    top_positive: List[str] = []
    top_negative: List[str] = []

    if ai_news_result:
        sector_boosts = build_sector_boosts(ai_news_result)
        ai_boost_total = sum(sector_boosts.values())
        pos_sectors = sorted(
            [(s, v) for s, v in sector_boosts.items() if v > 0],
            key=lambda x: -x[1]
        )
        neg_sectors = sorted(
            [(s, v) for s, v in sector_boosts.items() if v < 0],
            key=lambda x: x[1]
        )
        top_positive = [s for s, _ in pos_sectors[:3]]
        top_negative = [s for s, _ in neg_sectors[:2]]

    # 3. 综合情绪判断（AI结果优先）
    if ai_news_result:
        if ai_boost_total > 20:
            sentiment = "positive"
        elif ai_boost_total < -15:
            sentiment = "negative"
        elif kw_score > 3:
            sentiment = "positive"
        elif kw_score < -3:
            sentiment = "negative"
        else:
            sentiment = "neutral"
    else:
        # 纯关键词兜底
        if kw_score > 3:
            sentiment = "positive"
        elif kw_score < -3:
            sentiment = "negative"
        else:
            sentiment = "neutral"

    if top_positive:
        logger.info(f"📰 消息面利好板块：{', '.join(f'{s}' for s in top_positive)}")
    if top_negative:
        logger.info(f"📰 消息面利空板块：{', '.join(f'{s}' for s in top_negative)}")

    return {
        "sentiment": sentiment,
        "score": kw_score,
        "positive": pos_count,
        "negative": neg_count,
        "ai_boost_total": round(ai_boost_total, 1),
        "top_positive_sectors": top_positive,
        "top_negative_sectors": top_negative,
    }


def get_policy_score_adjustment(news_sentiment: Dict) -> float:
    """
    根据新闻情绪调整选股评分（兼容旧接口）。
    返回：-5 到 +5 的调整分数
    """
    if not news_sentiment:
        return 0.0
    score = news_sentiment.get("score", 0)
    if score > 10:
        return 5.0
    elif score > 5:
        return 3.0
    elif score > 0:
        return 1.0
    elif score < -10:
        return -5.0
    elif score < -5:
        return -3.0
    elif score < 0:
        return -1.0
    return 0.0
