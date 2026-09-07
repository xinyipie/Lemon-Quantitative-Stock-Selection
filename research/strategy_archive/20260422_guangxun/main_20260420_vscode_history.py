import tushare as ts
import pandas as pd
import json
import os
import logging
import requests
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import config
import ai_prompts
import news_analyzer
import market_analyzer

# ==================== 日志初始化 ====================
def init_logger():
    logging.basicConfig(
        filename=config.LOG_FILE_PATH,
        level=getattr(logging, config.LOG_CONFIG["level"]),
        format=config.LOG_CONFIG["format"],
        datefmt=config.LOG_CONFIG["datefmt"],
        encoding='utf-8'  # 修复：指定UTF-8编码，避免中文乱码
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(config.LOG_CONFIG["format"]))
    logging.getLogger().addHandler(console_handler)
    return logging.getLogger(__name__)

logger = init_logger()

# ==================== Tushare初始化 ====================
def init_tushare():
    try:
        token = config.TUSHARE_CONFIG["token"]
        if not token:
            raise ValueError(
                "Tushare Token 未配置！\n"
                "请在 config.py 中设置 TUSHARE_TOKEN，或设置环境变量 TUSHARE_TOKEN"
            )
        ts.set_token(token)
        pro = ts.pro_api(timeout=config.TUSHARE_CONFIG["timeout"])
        pro._DataApi__http_url = 'http://121.40.135.59:8010/'  # 买的便宜Tushare接口的中转站
        logger.info("✅ Tushare接口初始化成功")
        return pro
    except Exception as e:
        logger.error(f"❌ Tushare初始化失败：{e}", exc_info=True)
        raise

pro = init_tushare()

# ── 保存原始 pro 实例，用于 restore_pro() ──
_original_pro = pro

# ── 板块MA10状态进程内内存缓存（key: trade_date → Dict[str, bool]）──
# 离线回测跑全年252个交易日时，每天都调一次 get_sector_ma10_status，
# 有了内存缓存后每个日期只读一次文件，后续直接返回，速度极快。
_sector_ma10_mem_cache: Dict[str, Dict[str, bool]] = {}


def _tushare_query_with_retry(func, *args, max_retries: int = 3, retry_delay: float = 2.0, **kwargs):
    """
    Tushare 请求重试包装器。
    遇到超时或连接错误时自动重试，避免因中转站瞬时抖动导致整个程序崩溃。
    max_retries: 最多重试次数（不含首次）
    retry_delay: 每次重试前等待秒数（逐次翻倍：2s/4s/8s）
    """
    import requests as _requests
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except (_requests.exceptions.Timeout,
                _requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries:
                wait = retry_delay * (2 ** attempt)
                logger.warning(
                    f"⚠️ Tushare请求超时/连接失败（第{attempt + 1}次），{wait:.0f}秒后重试... ({e})"
                )
                time.sleep(wait)
            else:
                logger.error(f"❌ Tushare请求失败，已重试{max_retries}次：{e}")
    raise last_exc


def set_pro(proxy) -> None:
    """
    将全局 pro 替换为任意兼容对象（如 LocalDataProxy）。
    用于离线回测时注入本地数据代理，使所有后续调用都从本地 Parquet 文件读取。

    Example:
        from local_data_proxy import LocalDataProxy
        import main as stock_main
        proxy = LocalDataProxy("data/cache")
        stock_main.set_pro(proxy)
        # ... run backtest ...
        stock_main.restore_pro()
    """
    global pro
    pro = proxy
    logger.info(f"[set_pro] pro 已替换为：{type(proxy).__name__}")


def restore_pro() -> None:
    """恢复 pro 为初始化时的真实 Tushare 实例。"""
    global pro
    pro = _original_pro
    logger.info("[restore_pro] pro 已恢复为 Tushare 实例")


# ==================== 工具函数 ====================
def get_latest_trade_date() -> str:
    """获取最新交易日（验证有实际行情数据）"""
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
    try:
        cal_df = _tushare_query_with_retry(
            pro.trade_cal, start_date=start_date, end_date=end_date, fields='cal_date,is_open'
        )
    except Exception:
        # 部分中转接口不支持参数过滤，拉全量后本地过滤
        cal_df = _tushare_query_with_retry(pro.trade_cal)
    if cal_df.empty:
        raise RuntimeError("trade_cal 返回空数据，请检查网络或Token")
    cal_df = cal_df[(cal_df['cal_date'] >= start_date) & (cal_df['cal_date'] <= end_date)]
    cal_df = cal_df.sort_values('cal_date', ascending=False)
    open_dates = cal_df[cal_df['is_open'].astype(int) == 1]['cal_date'].tolist()
    if not open_dates:
        raise RuntimeError("近30天无交易日数据")

    # 验证是否有实际行情数据（用上证指数测试）
    for date in open_dates[:5]:  # 最多回退5个交易日
        try:
            test_df = _tushare_query_with_retry(
                pro.daily, ts_code='000001.SH', trade_date=date, fields='close'
            )
            if not test_df.empty:
                logger.info(f"✅ 最新交易日：{date}")
                return date
        except:
            continue

    # 如果都没数据，返回第一个
    latest = open_dates[0]
    logger.info(f"✅ 最新交易日：{latest}")
    return latest

def get_recent_trade_dates(end_date: str, n: int = 6) -> List[str]:
    """获取最近 n 个交易日列表（含 end_date，降序）"""
    start_date = (datetime.strptime(end_date, '%Y%m%d') - timedelta(days=20)).strftime('%Y%m%d')
    cal_df = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date, fields='cal_date,is_open')
    dates = cal_df[cal_df['is_open'] == 1].sort_values('cal_date', ascending=False)['cal_date'].tolist()
    return dates[:n]

def format_code(code: str) -> str:
    if '.' in code:
        return code
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    return f"{code}.SZ"

def revert_code(code: str) -> str:
    return code.split('.')[0] if '.' in code else code

# ==================== 批量数据获取 ====================
def get_batch_moneyflow(ts_codes: List[str], trade_date: str) -> Dict[str, float]:
    """
    批量获取主力资金净流入（万元）。
    修复：失败批次不 fillna(0)，保留 NaN 让调用方决定如何处理。
    """
    is_offline = type(pro).__name__ == 'LocalDataProxy'
    batch_size = 500
    result = {}
    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i:i + batch_size]
        try:
            df = pro.moneyflow(
                ts_code=",".join(batch),
                trade_date=trade_date,
                fields='ts_code,net_mf_amount'
            )
            if not df.empty:
                for _, row in df.iterrows():
                    if pd.notna(row['net_mf_amount']):
                        result[row['ts_code']] = round(float(row['net_mf_amount']), 2)
        except Exception as e:
            logger.warning(f"资金流第{i // batch_size + 1}批失败：{e}")
        if not is_offline:
            time.sleep(0.8)
    logger.info(f"✅ 批量资金流获取完成，共{len(result)}只")
    return result


def get_hot_sectors_index(trade_date: str) -> Tuple[Dict[str, float], float]:
    """
    获取热门板块（申万一级行业指数）。
    返回：(板块涨幅字典, 市场整体强度均值)
    修复：返回 market_strength 浮点数，避免 key 格式不匹配问题。
    """
    sw_codes = [
        '801010.SI', '801020.SI', '801030.SI', '801040.SI', '801050.SI',
        '801080.SI', '801110.SI', '801120.SI', '801130.SI', '801140.SI',
        '801150.SI', '801160.SI', '801170.SI', '801180.SI', '801200.SI',
        '801210.SI', '801230.SI', '801710.SI', '801720.SI', '801730.SI',
        '801740.SI', '801750.SI', '801760.SI', '801770.SI', '801780.SI',
        '801790.SI', '801880.SI', '801890.SI'
    ]
    try:
        df = pro.index_daily(
            ts_code=",".join(sw_codes),
            trade_date=trade_date,
            fields='ts_code,pct_chg'
        )
        if df.empty:
            return {}, 0.0
        df = df.sort_values('pct_chg', ascending=False)
        top5 = {row['ts_code']: round(float(row['pct_chg']), 2) for _, row in df.head(5).iterrows()}
        # 市场整体强度 = 全部行业涨幅均值
        market_strength = round(float(df['pct_chg'].mean()), 2)
        return top5, market_strength
    except Exception as e:
        logger.warning(f"获取热门板块失败：{e}")
        return {}, 0.0


def get_sector_ma10_status(trade_date: str) -> Dict[str, bool]:
    """
    v2.6新增：获取申万一级行业指数是否站上MA10
    返回：{行业名称: 是否站上MA10}
    v2.9优化：加当天文件缓存，同一天第二次运行直接读缓存，跳过28次串行网络请求
    v3.0优化：新增进程内内存缓存（_sector_ma10_mem_cache），离线回测时同一trade_date
              无需重复读文件，彻底消除重复 I/O。
    """
    # ── 进程内内存缓存（最快）──
    if trade_date in _sector_ma10_mem_cache:
        return _sector_ma10_mem_cache[trade_date]
    sw_map = {
        '801010.SI': '农林牧渔', '801020.SI': '采掘', '801030.SI': '化工',
        '801040.SI': '钢铁', '801050.SI': '有色金属', '801080.SI': '电子',
        '801110.SI': '家用电器', '801120.SI': '食品饮料', '801130.SI': '纺织服饰',
        '801140.SI': '轻工制造', '801150.SI': '医药生物', '801160.SI': '公用事业',
        '801170.SI': '交通运输', '801180.SI': '房地产', '801200.SI': '商贸零售',
        '801210.SI': '社会服务', '801230.SI': '综合', '801710.SI': '建筑材料',
        '801720.SI': '建筑装饰', '801730.SI': '电力设备', '801740.SI': '国防军工',
        '801750.SI': '计算机', '801760.SI': '传媒', '801770.SI': '通信',
        '801780.SI': '银行', '801790.SI': '非银金融', '801880.SI': '汽车',
        '801890.SI': '机械设备'
    }

    # ── 当天文件缓存：同一天只拉一次，避免每次运行都发28次串行请求 ──
    cache_dir = os.path.join(config.LOGS_DIR, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"sector_ma10_{trade_date}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            # json key 是 str，bool 值需要还原
            result = {k: bool(v) for k, v in cached.items()}
            logger.info(f"✅ 板块MA10状态：命中当天缓存，{len(result)}个行业（跳过网络请求）")
            _sector_ma10_mem_cache[trade_date] = result  # 同步写入内存缓存
            return result
        except Exception as e_cache:
            logger.debug(f"读取板块MA10缓存失败，重新拉取：{e_cache}")

    try:
        start_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=20)).strftime('%Y%m%d')

        all_dfs = []
        is_local = type(pro).__name__ == 'LocalDataProxy'

        # 先尝试批量拉取（部分 tushare 版本支持逗号分隔 ts_code）
        codes_list = list(sw_map.keys())
        batch_ok = False
        try:
            df_batch = pro.index_daily(
                ts_code=",".join(codes_list),
                start_date=start_date,
                end_date=trade_date,
                fields='ts_code,trade_date,close'
            )
            if df_batch is not None and not df_batch.empty:
                all_dfs.append(df_batch)
                batch_ok = True
                logger.info(f"✅ 板块共振：批量拉取成功，{len(df_batch)}条记录")
        except Exception:
            pass  # 批量失败，回退逐个拉取

        # 批量失败时逐个拉取，设90秒总超时（中转站慢，适当延长）
        if not batch_ok:
            deadline = time.time() + 90
            for code in codes_list:
                if time.time() > deadline:
                    logger.warning("⚠️ 板块共振：逐个拉取超时（90s），已获取部分数据继续")
                    break
                try:
                    df_i = pro.index_daily(
                        ts_code=code,
                        start_date=start_date,
                        end_date=trade_date,
                        fields='ts_code,trade_date,close'
                    )
                    if df_i is not None and not df_i.empty:
                        all_dfs.append(df_i)
                except Exception as e_i:
                    logger.debug(f"  index_daily 单条查询失败（{code}）：{e_i}")
                if not is_local:
                    time.sleep(0.05)

        df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

        if df.empty:
            logger.warning("⚠️ 板块MA10状态：指数数据为空，板块共振过滤将跳过")
            return {}

        result = {}
        for code, name in sw_map.items():
            sector_df = df[df['ts_code'] == code].sort_values('trade_date')
            if len(sector_df) >= 10:
                sector_df['ma10'] = sector_df['close'].rolling(10).mean()
                latest = sector_df.iloc[-1]
                if not pd.isna(latest['ma10']):
                    result[name] = bool(latest['close'] > latest['ma10'])

        logger.info(f"✅ 板块MA10状态：{len(result)}个行业")

        # ── 写入内存缓存 + 当天文件缓存，下次调用/运行直接命中 ──
        if result:
            _sector_ma10_mem_cache[trade_date] = result
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False)
                logger.debug(f"📦 板块MA10状态已缓存：{cache_file}")
            except Exception as e_w:
                logger.debug(f"写入板块MA10缓存失败（不影响结果）：{e_w}")

        return result
    except Exception as e:
        logger.warning(f"获取板块MA10失败：{e}")
        return {}


def _compute_sector_ma10_from_stocks(stocks: pd.DataFrame, ma_dict: Dict) -> Dict[str, bool]:
    """
    申万指数不可用时的替代方案：将个股 above_ma10 状态按行业聚合。
    各行业中 ≥50% 的个股收盘价站上MA10，则该行业视为站上MA10。
    入参：
      stocks  - get_all_stocks() 返回的 DataFrame，含 code / industry 列
      ma_dict - get_ma_data_batch() 返回的字典，key=ts_code，含 above_ma10 字段
    返回：{行业名称: bool}，格式与 get_sector_ma10_status() 完全一致
    """
    if stocks.empty or not ma_dict:
        return {}
    # 按行业收集 above_ma10 状态列表（显式 iterrows 避开 pandas bool+NaN 类型坑）
    sector_above: Dict[str, list] = {}
    matched = 0
    for _, row in stocks.iterrows():
        code = row['code']
        industry = row.get('industry')
        if not industry or (isinstance(industry, float) and pd.isna(industry)):
            continue
        ma_data = ma_dict.get(code) or ma_dict.get(format_code(code))
        if ma_data is None:
            continue
        matched += 1
        sector_above.setdefault(industry, []).append(ma_data.get('above_ma10', False))
    if not sector_above:
        logger.warning(f"⚠️ 板块共振聚合：matched={matched}，未找到行业数据（code格式不匹配？）")
        return {}
    # 按行业聚合：≥50% 个股站上MA10视为该行业站上MA10
    return {ind: bool(sum(vals) / len(vals) >= 0.5) for ind, vals in sector_above.items()}


def get_hot_sectors_from_stocks(trade_date: str, all_stocks: pd.DataFrame) -> Dict[str, float]:
    """
    v2.8新增：板块轮动追踪
    返回：{行业名称: 热度分数(0-100)}
    """
    if all_stocks.empty:
        return {}

    # 按行业统计涨幅和资金流
    sector_stats = all_stocks.groupby('industry').agg({
        'change': 'mean',
        'main_net_inflow': 'sum'
    }).reset_index()

    # 计算热度分数：涨幅50% + 资金流50%
    max_change = sector_stats['change'].max() if sector_stats['change'].max() > 0 else 1
    max_inflow = sector_stats['main_net_inflow'].max() if sector_stats['main_net_inflow'].max() > 0 else 1

    sector_stats['heat_score'] = (
        (sector_stats['change'] / max_change * 50).clip(0, 50) +
        (sector_stats['main_net_inflow'] / max_inflow * 50).clip(0, 50)
    )

    result = dict(zip(sector_stats['industry'], sector_stats['heat_score']))

    # 找出前3热门板块
    top3 = sector_stats.nlargest(3, 'heat_score')
    logger.info(f"🔥 热门板块Top3：{', '.join(top3['industry'].tolist())}")

    return result


def get_market_sentiment(trade_date: str, market_df: pd.DataFrame = None) -> Dict[str, any]:
    """
    v2.8新增：市场情绪指标
    v2.9优化：支持传入已拉取的全市场数据，避免重复请求
    返回：{指标名: 值}
    """
    try:
        if market_df is not None and not market_df.empty and 'pct_chg' in market_df.columns:
            df = market_df
        else:
            df = pro.daily(trade_date=trade_date, fields='ts_code,pct_chg')
        if df.empty:
            return {}

        limit_up_count = len(df[df['pct_chg'] >= 9.8])
        limit_down_count = len(df[df['pct_chg'] <= -9.8])

        # 涨停/跌停比
        ratio = limit_up_count / limit_down_count if limit_down_count > 0 else 10

        # 情绪等级
        if ratio > 3:
            sentiment = "高涨"
        elif ratio > 1.5:
            sentiment = "正常"
        elif ratio > 0.5:
            sentiment = "偏弱"
        else:
            sentiment = "恐慌"

        logger.info(f"📊 市场情绪：{sentiment}（涨停{limit_up_count}/跌停{limit_down_count}，比值{ratio:.1f}）")

        return {
            'limit_up_count': limit_up_count,
            'limit_down_count': limit_down_count,
            'ratio': ratio,
            'sentiment': sentiment
        }
    except Exception as e:
        logger.warning(f"获取市场情绪失败：{e}")
        return {}


def get_market_index(trade_date: str) -> float:
    """获取上证指数当日涨跌幅，用于判断大盘环境"""
    try:
        df = pro.index_daily(ts_code='000001.SH', trade_date=trade_date, fields='pct_chg')
        if not df.empty:
            index_change = float(df.iloc[0]['pct_chg'])
            logger.info(f"✅ 上证指数涨跌：{index_change:.2f}%")
            return index_change
    except Exception as e:
        logger.warning(f"获取大盘指数失败：{e}")
    return 0.0


def check_market_risk(trade_date: str, market_df: pd.DataFrame = None) -> Tuple[str, str]:
    """
    v3.1优化：多指数综合大盘状态判断，新增警戒区
    - 同时监控上证（000001.SH）+ 沪深300（000300.SH）
    - 两个指数都确认才判断为 downtrend，避免单一指数误判
    - 新增 caution 状态：任一指数出现回调信号，不停止选股但提高准入门槛
    返回：(市场状态, 提示信息)
    状态：'normal'正常 | 'caution'短期回调警戒 | 'rebound'超跌反弹 | 'downtrend'主跌浪
    """
    try:
        start_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=35)).strftime('%Y%m%d')

        def _fetch_index(ts_code):
            return pro.index_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=trade_date,
                fields='trade_date,close,pct_chg'
            )

        df_sh  = _fetch_index('000001.SH')
        df_hs3 = _fetch_index('000300.SH')

        if df_sh.empty:
            return 'normal', "大盘数据获取失败，谨慎操作"

        # 检查跌停家数（复用已有全市场数据）
        if market_df is not None and not market_df.empty and 'pct_chg' in market_df.columns:
            df_limit = market_df
        else:
            df_limit = pro.daily(trade_date=trade_date, fields='ts_code,pct_chg')
        limit_down_count = len(df_limit[df_limit['pct_chg'] <= -9.8])

        def _analyze_index(df):
            """分析单个指数状态，返回 (deviation, below_ma20_days, slope_5d, cumret_5d)"""
            if df.empty or len(df) < 6:
                return 0.0, 0, 0.0, 0.0
            df = df.sort_values('trade_date')
            df['ma20'] = df['close'].rolling(20).mean()
            latest = df.iloc[-1]
            ma20 = latest['ma20']
            close = latest['close']

            deviation = (close - ma20) / ma20 * 100 if not pd.isna(ma20) else 0.0

            below_days = 0
            for i in range(len(df)-1, max(0, len(df)-6), -1):
                if not pd.isna(df.iloc[i]['ma20']) and df.iloc[i]['close'] < df.iloc[i]['ma20']:
                    below_days += 1
                else:
                    break

            slope_5d = 0.0
            if len(df) >= 6 and not pd.isna(df.iloc[-1]['ma20']) and not pd.isna(df.iloc[-6]['ma20']):
                slope_5d = (df.iloc[-1]['ma20'] - df.iloc[-6]['ma20']) / df.iloc[-6]['ma20'] * 100

            # 近5日累计涨跌幅（比MA斜率更直接）
            cumret_5d = df.tail(5)['pct_chg'].sum() if len(df) >= 5 else 0.0

            return deviation, below_days, slope_5d, cumret_5d

        dev_sh,  below_sh,  slope_sh,  cum5_sh  = _analyze_index(df_sh)
        dev_hs3, below_hs3, slope_hs3, cum5_hs3 = _analyze_index(df_hs3)

        # ── 1. 冰点区：超跌反弹 ──
        recent_3d_sh = df_sh.sort_values('trade_date').tail(3)
        consecutive_down = all(recent_3d_sh['pct_chg'] < 0)
        if (consecutive_down and dev_sh < -5) or limit_down_count > 50:
            return 'rebound', f"超跌反弹期（偏离MA20 {dev_sh:.1f}%），短线可抢反弹"

        # ── 2. 退潮区：主跌浪（双指数同时确认）──
        # 双指数同时满足：MA20下方≥3日 + 斜率<-1% + 5日累跌<-3%
        sh_bearish  = (below_sh  >= 3 and slope_sh  < -1.0 and cum5_sh  < -3.0)
        hs3_bearish = (below_hs3 >= 3 and slope_hs3 < -1.0 and cum5_hs3 < -3.0)

        if sh_bearish and hs3_bearish:
            return 'downtrend', (
                f"主跌浪（上证MA20下方{below_sh}日/5日跌{cum5_sh:.1f}%，"
                f"沪深300 5日跌{cum5_hs3:.1f}%），建议空仓"
            )

        # ── 3. 警戒区：短期回调（任一指数出现回调信号）──
        # 任一指数满足：MA20下方≥2日 + 斜率<-0.5% + 5日累跌<-2%
        # 不停止选股，但提高准入门槛（select_stock_pool中score-10惩罚）
        sh_caution  = (below_sh  >= 2 and slope_sh  < -0.5 and cum5_sh  < -2.0)
        hs3_caution = (below_hs3 >= 2 and slope_hs3 < -0.5 and cum5_hs3 < -2.0)

        if sh_caution or hs3_caution:
            caution_idx = "上证" if sh_caution else "沪深300"
            caution_cum = cum5_sh if sh_caution else cum5_hs3
            return 'caution', (
                f"短期回调警戒（{caution_idx} 5日累跌{caution_cum:.1f}%），"
                f"提高准入门槛，仅选高确定性标的"
            )

        # ── 4. 正常/上升区 ──
        return 'normal', "大盘环境正常"

    except Exception as e:
        logger.warning(f"大盘风控检查失败：{e}")
        return 'normal', "大盘数据获取失败，谨慎操作"


def get_market_regime(trade_date: str) -> Tuple[str, Dict]:
    """
    四状态市场状态机（Regime Filter）——核心防熊模块
    =====================================================
    解决2024年熊市策略失效问题：在原有短期大盘状态（check_market_risk）之上，
    增加一层"长期牛熊"判断，形成二维状态矩阵：

        长期方向 × 短期方向 = 4种状态
        ┌─────────────┬──────────────────┬──────────────────┐
        │             │  短期上涨        │  短期下跌        │
        │             │  MA20 > MA60     │  MA20 < MA60     │
        ├─────────────┼──────────────────┼──────────────────┤
        │ 长期牛市     │ BULL_TREND ✅   │ BULL_PULLBACK ⚠️ │
        │ 价格>MA60    │ 全力出击×1.0    │ 缩仓×0.67        │
        ├─────────────┼──────────────────┼──────────────────┤
        │ 长期熊市     │ BEAR_BOUNCE ⚠️  │ BEAR_TREND  ❌   │
        │ 价格<MA60    │ 轻仓×0.33       │ 空仓×0.0         │
        └─────────────┴──────────────────┴──────────────────┘

    长期牛熊判断（参考Faber 2007月线策略）：
      - 使用CSI300日线MA60近似"月线均线"
      - 价格 > MA60 且 MA60斜率 > 阈值 → 长期牛市
      - 价格 < MA60 或 MA60斜率 < 0 → 长期熊市

    短期方向判断：
      - MA20 > MA60（金叉） → 短期上涨
      - MA20 < MA60（死叉） → 短期下跌

    返回：(状态字符串, 详情字典)
    状态：'BULL_TREND' | 'BULL_PULLBACK' | 'BEAR_BOUNCE' | 'BEAR_TREND'
    """
    regime_data = {
        'regime': 'BULL_TREND',
        'is_long_term_bull': True,
        'is_short_term_up': True,
        'ma20': 0.0,
        'ma60': 0.0,
        'close': 0.0,
        'ma60_slope_pct': 0.0,    # MA60近10日斜率（%/日）
        'price_vs_ma60_pct': 0.0, # 价格相对MA60偏离（%）
        'position_multiplier': 1.0,
        'score_threshold': 45,
        'max_hold_days': 8,
        'atr_multiplier': 1.5,
    }
    try:
        # 拉取CSI300近120个交易日（覆盖MA60 + 斜率计算）
        start_dt = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=120)).strftime('%Y%m%d')
        df = pro.index_daily(
            ts_code='000300.SH',
            start_date=start_dt,
            end_date=trade_date,
            fields='trade_date,close'
        )
        if df.empty or len(df) < 25:
            logger.warning("⚠️ 市场状态机：CSI300数据不足，默认 BULL_TREND")
            return 'BULL_TREND', regime_data

        df = df.sort_values('trade_date').reset_index(drop=True)
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma60'] = df['close'].rolling(60).mean()

        latest = df.iloc[-1]
        close_now = float(latest['close'])
        ma20_now  = float(latest['ma20']) if not pd.isna(latest['ma20']) else None
        ma60_now  = float(latest['ma60']) if not pd.isna(latest['ma60']) else None

        if ma20_now is None or ma60_now is None:
            logger.warning("⚠️ 市场状态机：均线数据不足，默认 BULL_TREND")
            return 'BULL_TREND', regime_data

        # ── 长期方向：价格 vs MA60 + MA60斜率 ──
        price_vs_ma60 = (close_now - ma60_now) / ma60_now * 100

        # MA60近10日斜率（日均涨幅%）
        ma60_slope = 0.0
        if len(df) >= 70:  # 60+10
            ma60_10d_ago = float(df.iloc[-11]['ma60']) if not pd.isna(df.iloc[-11]['ma60']) else ma60_now
            ma60_slope = (ma60_now - ma60_10d_ago) / ma60_10d_ago * 100 / 10

        # 长期牛市条件（双重判断）：
        # ① 价格不低于MA60太多：容忍区间 -3%（原-1%太窄，在MA60附近震荡时反复误判为熊市）
        #   -3% 对应于：在均线下方轻微回测，属于正常技术性回调，不是趋势转熊的信号
        #   Faber(2007)月线策略用的是严格价格>SMA10月线，但日线MA60噪音更大，需要更宽容忍
        # ② MA60斜率不能持续向下：斜率 >= -0.02%/日 视为"持平或向上"
        is_long_bull = (price_vs_ma60 >= -3.0) and (ma60_slope >= -config.REGIME_MA60_SLOPE_THRESHOLD)

        # ── 短期方向：MA20 vs MA60（金叉/死叉）──
        is_short_up = (ma20_now > ma60_now)

        # ── 状态映射 ──
        if is_long_bull and is_short_up:
            regime = 'BULL_TREND'
        elif is_long_bull and not is_short_up:
            regime = 'BULL_PULLBACK'
        elif not is_long_bull and is_short_up:
            regime = 'BEAR_BOUNCE'
        else:
            regime = 'BEAR_TREND'

        # 从config读取各状态参数
        position_multiplier = config.REGIME_POSITION_MULTIPLIER.get(regime, 1.0)
        score_threshold     = config.REGIME_SCORE_THRESHOLD.get(regime, 45)
        max_hold_days       = config.REGIME_MAX_HOLD_DAYS.get(regime, 8)
        atr_multiplier      = config.REGIME_ATR_MULTIPLIER.get(regime, 1.5)

        regime_data.update({
            'regime': regime,
            'is_long_term_bull': is_long_bull,
            'is_short_term_up': is_short_up,
            'ma20': round(ma20_now, 2),
            'ma60': round(ma60_now, 2),
            'close': round(close_now, 2),
            'ma60_slope_pct': round(ma60_slope, 4),
            'price_vs_ma60_pct': round(price_vs_ma60, 2),
            'position_multiplier': position_multiplier,
            'score_threshold': score_threshold,
            'max_hold_days': max_hold_days,
            'atr_multiplier': atr_multiplier,
        })

        regime_label = {
            'BULL_TREND':    '🟢 牛市趋势（全力出击）',
            'BULL_PULLBACK': '🟡 牛市回调（缩仓观望）',
            'BEAR_BOUNCE':   '🟠 熊市反弹（极轻仓超短）',
            'BEAR_TREND':    '🔴 熊市下跌（空仓观望）',
        }.get(regime, regime)

        logger.info(
            f"📊 四状态市场机制：{regime_label}"
            f" | CSI300={close_now:.0f}  MA20={ma20_now:.0f}  MA60={ma60_now:.0f}"
            f" | 价格vsMA60={price_vs_ma60:+.1f}%  MA60斜率={ma60_slope:+.4f}%/日"
            f" | 仓位×{position_multiplier}  门槛≥{score_threshold}分  持仓≤{max_hold_days}天"
        )
        return regime, regime_data

    except Exception as e:
        logger.warning(f"市场状态机判断失败：{e}，默认 BULL_TREND")
        return 'BULL_TREND', regime_data


def check_regime_override(
    trade_date: str,
    current_regime: str,
    market_pct_df: pd.DataFrame,
) -> Tuple[str, Dict]:
    """
    快速翻转检测器（Regime Override）
    ====================================
    解决 MA60 约30天滞后问题：
    状态机用均线判断趋势，天然滞后。
    但政策驱动的急速反转（如2024年9月24日）在当日微观结构上有明确特征，
    可以在均线还没反应时，通过"当日盘面快照"提前识别，临时上调状态机级别。

    设计原则（参考 Chan 2013 & Lo 2004 市场微观结构理论）：
      ─ 只升级，不降级（宁可偶尔误判一天入场，不踏空大行情）
      ─ 只对 BEAR_TREND 生效（已在BEAR_BOUNCE则无需升级）
      ─ 升级仅对"今日选出的票、明日买入"有效，不影响历史持仓
      ─ 升级后的参数比正常状态保守（更高评分门槛 + 更短持仓周期）

    4个触发条件（独立评分，满足即+1分）：
      ① 大盘力度：全市场涨跌幅中位数 > REGIME_OVERRIDE_INDEX_CHG（2%）
                   → 排除"少数权重股拉指数"的失真
      ② 市场宽度：上涨家数占比 > REGIME_OVERRIDE_UP_RATIO（70%）
                   → 验证普涨，非板块轮动
      ③ 情绪高度：涨停家数 > REGIME_OVERRIDE_LIMIT_UP（80家）
                   → 市场情绪真实爆发，资金极度乐观
      ④ 量能验证：今日全市场成交额 > 5日均额 × REGIME_OVERRIDE_VOLUME_RATIO（1.5×）
                   → 真实反转必有成交量配合，死猫跳往往无量

    升级规则：
      2分 → BEAR_TREND 临时升为 BEAR_BOUNCE_OVERRIDE（仓位×0.33，Top1，持3天）
      3分 → BEAR_TREND 临时升为 BULL_PULLBACK_OVERRIDE（仓位×0.50，Top2，持4天）
      4分 → 同3分（顶格处理，不再进一步冒险）

    返回：(最终regime字符串, override_info字典)
    override_info 包含：
      triggered: bool         是否触发
      score: int              触发分数（0~4）
      from_regime: str        原始状态
      reasons: List[str]      命中的触发条件说明
    """
    override_info = {
        'triggered': False,
        'score': 0,
        'from_regime': current_regime,
        'reasons': [],
        'position_multiplier': config.REGIME_POSITION_MULTIPLIER.get(current_regime, 0.0),
        'score_threshold':     config.REGIME_SCORE_THRESHOLD.get(current_regime, 999),
        'max_hold_days':       config.REGIME_MAX_HOLD_DAYS.get(current_regime, 0),
    }

    # 只对 BEAR_TREND 生效
    if current_regime != 'BEAR_TREND':
        return current_regime, override_info

    if market_pct_df is None or market_pct_df.empty or 'pct_chg' not in market_pct_df.columns:
        logger.debug("Override检测：无全市场数据，跳过")
        return current_regime, override_info

    score = 0
    reasons = []

    # ── 条件① 大盘力度：全市场涨跌中位数 ──
    # 用中位数而非指数涨幅，排除权重股失真（如9月24日银行股拉指数）
    try:
        median_chg = float(market_pct_df['pct_chg'].median())
        if median_chg > config.REGIME_OVERRIDE_INDEX_CHG:
            score += 1
            reasons.append(f"大盘中位数涨幅{median_chg:.1f}%（>{config.REGIME_OVERRIDE_INDEX_CHG}%）")
    except Exception:
        pass

    # ── 条件② 市场宽度：上涨家数占比 ──
    try:
        total = len(market_pct_df)
        if total > 0:
            up_ratio = float((market_pct_df['pct_chg'] > 0).sum()) / total
            if up_ratio > config.REGIME_OVERRIDE_UP_RATIO:
                score += 1
                reasons.append(f"上涨家数占比{up_ratio:.0%}（>{config.REGIME_OVERRIDE_UP_RATIO:.0%}）")
    except Exception:
        pass

    # ── 条件③ 情绪高度：涨停家数 ──
    try:
        limit_up_count = int((market_pct_df['pct_chg'] >= 9.8).sum())
        if limit_up_count > config.REGIME_OVERRIDE_LIMIT_UP:
            score += 1
            reasons.append(f"涨停{limit_up_count}家（>{config.REGIME_OVERRIDE_LIMIT_UP}家）")
    except Exception:
        pass

    # ── 条件④ 量能验证：今日成交额 vs 5日均额 ──
    # 需要拉取历史成交额数据
    try:
        start_dt = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=10)).strftime('%Y%m%d')
        df_vol = pro.index_daily(
            ts_code='000001.SH',
            start_date=start_dt,
            end_date=trade_date,
            fields='trade_date,amount'
        )
        if df_vol is not None and not df_vol.empty and len(df_vol) >= 2:
            df_vol = df_vol.sort_values('trade_date')
            today_amount  = float(df_vol.iloc[-1]['amount'])
            avg_5d_amount = float(df_vol.iloc[:-1].tail(5)['amount'].mean())
            if avg_5d_amount > 0 and today_amount > avg_5d_amount * config.REGIME_OVERRIDE_VOLUME_RATIO:
                score += 1
                ratio = today_amount / avg_5d_amount
                reasons.append(f"成交额{ratio:.1f}×5日均量（>{config.REGIME_OVERRIDE_VOLUME_RATIO}×）")
    except Exception as e:
        logger.debug(f"Override量能检测失败（不影响结果）：{e}")

    # ── 升级决策 ──
    override_info['score'] = score
    override_info['reasons'] = reasons

    if score >= 3:
        new_regime = 'BULL_PULLBACK_OVERRIDE'
        override_info['triggered']          = True
        override_info['position_multiplier'] = config.REGIME_OVERRIDE_POSITION['BULL_PULLBACK_OVERRIDE']
        override_info['score_threshold']     = config.REGIME_OVERRIDE_SCORE_THRESHOLD['BULL_PULLBACK_OVERRIDE']
        override_info['max_hold_days']       = config.REGIME_OVERRIDE_MAX_HOLD['BULL_PULLBACK_OVERRIDE']
        logger.warning(
            f"⚡ 快速翻转Override触发（{score}/4分）→ BEAR_TREND 临时升为 BULL_PULLBACK_OVERRIDE\n"
            f"   命中条件：{' | '.join(reasons)}\n"
            f"   参数：仓位×{override_info['position_multiplier']}  "
            f"门槛≥{override_info['score_threshold']}分  "
            f"持仓≤{override_info['max_hold_days']}天"
        )
        return new_regime, override_info

    elif score >= 2:
        new_regime = 'BEAR_BOUNCE_OVERRIDE'
        override_info['triggered']          = True
        override_info['position_multiplier'] = config.REGIME_OVERRIDE_POSITION['BEAR_BOUNCE_OVERRIDE']
        override_info['score_threshold']     = config.REGIME_OVERRIDE_SCORE_THRESHOLD['BEAR_BOUNCE_OVERRIDE']
        override_info['max_hold_days']       = config.REGIME_OVERRIDE_MAX_HOLD['BEAR_BOUNCE_OVERRIDE']
        logger.warning(
            f"⚡ 快速翻转Override触发（{score}/4分）→ BEAR_TREND 临时升为 BEAR_BOUNCE_OVERRIDE\n"
            f"   命中条件：{' | '.join(reasons)}\n"
            f"   参数：仓位×{override_info['position_multiplier']}  "
            f"门槛≥{override_info['score_threshold']}分  "
            f"持仓≤{override_info['max_hold_days']}天"
        )
        return new_regime, override_info

    else:
        if score > 0:
            logger.info(f"📊 Override检测：仅{score}/4分（需≥2），维持BEAR_TREND | 命中：{' | '.join(reasons)}")
        return current_regime, override_info


def get_weekly_macro_trend(trade_date: str) -> Tuple[str, Dict]:
    """
    一级筛选：周线宏观方向判断（Elder三重滤网第一重）
    基于CSI300和上证指数的"伪周线"（5日=1周）判断宏观趋势方向。

    逻辑：
      - 计算过去 52 个"交易周"（约260个交易日）的价格走势
      - 用 20 周均线（约MA100）判断长期趋势方向
      - 用 4 周均线（约MA20）判断中期趋势

    返回 (宏观模式, 详情字典)：
      'active'    → 主动做多（MA20斜率>0 且 价格>MA100）
      'cautious'  → 谨慎（MA20持平或轻微向下，价格仍在MA100上方）
      'defensive' → 防御（价格跌破MA100，停止追多）
    """
    macro_data = {
        'weekly_trend': 'unknown',
        'ma20_slope_pct': 0.0,   # CSI300 MA20（日线20日）近5日斜率
        'ma100_slope_pct': 0.0,  # CSI300 MA100（日线100日）近5日斜率
        'price_vs_ma100': 0.0,   # 价格相对MA100偏离百分比
    }
    try:
        start_dt = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=150)).strftime('%Y%m%d')
        df = pro.index_daily(
            ts_code='000300.SH',
            start_date=start_dt,
            end_date=trade_date,
            fields='trade_date,close'
        )
        if df.empty or len(df) < 30:
            return 'cautious', macro_data

        df = df.sort_values('trade_date').reset_index(drop=True)
        df['ma20']  = df['close'].rolling(20).mean()
        df['ma100'] = df['close'].rolling(100).mean()

        latest = df.iloc[-1]
        close_now  = float(latest['close'])
        ma20_now   = float(latest['ma20'])  if not pd.isna(latest['ma20'])  else None
        ma100_now  = float(latest['ma100']) if not pd.isna(latest['ma100']) else None

        # MA20 近5日斜率
        ma20_slope = 0.0
        if len(df) >= 25 and ma20_now:
            ma20_5d_ago = float(df.iloc[-6]['ma20']) if not pd.isna(df.iloc[-6]['ma20']) else ma20_now
            ma20_slope = (ma20_now - ma20_5d_ago) / ma20_5d_ago * 100

        # MA100 近5日斜率
        ma100_slope = 0.0
        price_vs_ma100 = 0.0
        if ma100_now:
            if len(df) >= 105:
                ma100_5d_ago = float(df.iloc[-6]['ma100']) if not pd.isna(df.iloc[-6]['ma100']) else ma100_now
                ma100_slope = (ma100_now - ma100_5d_ago) / ma100_5d_ago * 100
            price_vs_ma100 = (close_now - ma100_now) / ma100_now * 100

        macro_data['ma20_slope_pct']  = round(ma20_slope, 3)
        macro_data['ma100_slope_pct'] = round(ma100_slope, 3)
        macro_data['price_vs_ma100']  = round(price_vs_ma100, 2)

        # 三档判断
        if price_vs_ma100 < -3.0 or ma100_slope < -0.5:
            # 价格跌破MA100 3%以上，或MA100本身向下倾斜：宏观下行，防御模式
            mode = 'defensive'
        elif ma20_slope > 0.1 and price_vs_ma100 > -1.0:
            # MA20向上 且 价格高于MA100（轻微容忍1%内偏差）：主动模式
            mode = 'active'
        else:
            # 中间状态：谨慎模式
            mode = 'cautious'

        macro_data['weekly_trend'] = mode

        mode_label = {'active': '主动做多🟢', 'cautious': '谨慎观望🟡', 'defensive': '防御避险🔴'}
        logger.info(
            f"📊 宏观周线趋势：{mode_label.get(mode, mode)}"
            f" | 价格vs MA100={price_vs_ma100:+.1f}%"
            f" | MA20斜率={ma20_slope:+.3f}%/d"
            f" | MA100斜率={ma100_slope:+.3f}%/d"
        )
        return mode, macro_data

    except Exception as e:
        logger.warning(f"周线宏观趋势判断失败：{e}，默认使用谨慎模式")
        return 'cautious', macro_data


def get_sector_flow_acceleration(trade_date: str) -> Dict[str, float]:
    """
    二级筛选：板块资金流加速度检测（Elder三重滤网第二重变体）
    计算各申万行业指数的"近5日均涨幅 / 近20日均涨幅"加速度比。
    加速度比 > 1.5 表示板块正在加速上涨（资金持续流入加速）。

    返回：{行业名称: 加速度比（0~5+，>1.5为热门）}
    """
    sw_map = {
        '801010.SI': '农林牧渔', '801020.SI': '采掘', '801030.SI': '化工',
        '801040.SI': '钢铁', '801050.SI': '有色金属', '801080.SI': '电子',
        '801110.SI': '家用电器', '801120.SI': '食品饮料', '801130.SI': '纺织服饰',
        '801140.SI': '轻工制造', '801150.SI': '医药生物', '801160.SI': '公用事业',
        '801170.SI': '交通运输', '801180.SI': '房地产', '801200.SI': '商贸零售',
        '801210.SI': '社会服务', '801230.SI': '综合', '801710.SI': '建筑材料',
        '801720.SI': '建筑装饰', '801730.SI': '电力设备', '801740.SI': '国防军工',
        '801750.SI': '计算机', '801760.SI': '传媒', '801770.SI': '通信',
        '801780.SI': '银行', '801790.SI': '非银金融', '801880.SI': '汽车',
        '801890.SI': '机械设备'
    }
    result = {}
    try:
        start_dt = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=35)).strftime('%Y%m%d')
        df_idx = pro.index_daily(
            ts_code=",".join(sw_map.keys()),
            start_date=start_dt,
            end_date=trade_date,
            fields='ts_code,trade_date,pct_chg'
        )
        if df_idx.empty:
            return result

        for ts_code, grp in df_idx.groupby('ts_code'):
            industry = sw_map.get(ts_code, ts_code)
            grp = grp.sort_values('trade_date')
            if len(grp) < 6:
                continue

            # 近5日平均涨幅（绝对值，方向相关）
            avg_5d  = grp.tail(5)['pct_chg'].mean()
            # 近20日平均涨幅
            avg_20d = grp.tail(20)['pct_chg'].mean() if len(grp) >= 20 else grp['pct_chg'].mean()

            # 加速度比：近5日均涨 / 近20日均涨
            # 若20日均为负且5日均也为负，且5日跌幅更大（加速下跌），加速比为负
            if abs(avg_20d) < 0.01:
                # 避免除零：20日均涨幅接近0时，直接用5日均涨幅判断
                accel = avg_5d * 10  # 放大，便于比较
            else:
                accel = avg_5d / abs(avg_20d) * (1 if avg_20d > 0 else -1)

            result[industry] = round(float(accel), 3)

        # 打印 Top3 加速板块
        top3 = sorted(result.items(), key=lambda x: -x[1])[:3]
        if top3:
            logger.info(f"📊 板块资金加速（Top3）：" +
                        " | ".join(f"{n}({v:+.2f}x)" for n, v in top3))
    except Exception as e:
        logger.warning(f"板块资金流加速检测失败：{e}")

    return result


def get_market_style(trade_date: str) -> Tuple[str, Dict]:
    """
    市场风格检测：区分"动量牛市"、"弱动量牛市"、"震荡市"、"熊市"，自动切换选股模式。

    判断维度（三票制）：
      ① 趋势强度：CSI300近20日涨幅（≥5%动量票，≤-5%熊市票）
      ② 广度：申万行业站上MA10比例（≥55%动量票，≤35%熊市票）
      ③ 动量：近5日日均涨幅（≥0.3%动量票，≤-0.3%熊市票）

    返回（4种风格）：
      'momentum'      → 强动量牛市（≥2票），追涨突破模式
      'weak_momentum' → 弱动量牛市（恰好1票），混合模式（量比降低+涨幅适度放宽）
      'sideways'      → 震荡市（0票动量），吸筹模式
      'bear'          → 熊市（≥2票熊市），控制仓位

    style_data 包含详细指标供调试和打印。
    """
    style_data = {
        'trend_score': 0.0,   # CSI300 20日涨幅
        'breadth': 0.0,       # 站上MA10比例
        'momentum_5d': 0.0,   # 近5日日均涨幅
        'votes_momentum': 0,
        'votes_sideways': 0,
        'votes_bear': 0,
    }
    try:
        # ── 指标①：CSI300近20日趋势 ──
        start_dt = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=35)).strftime('%Y%m%d')
        df_idx = pro.index_daily(
            ts_code='000300.SH',
            start_date=start_dt,
            end_date=trade_date,
            fields='trade_date,close'
        )
        trend_score = 0.0
        momentum_5d = 0.0
        if not df_idx.empty and len(df_idx) >= 6:
            df_idx = df_idx.sort_values('trade_date')
            close_20d_ago = float(df_idx.iloc[max(0, len(df_idx)-21)]['close'])
            close_now     = float(df_idx.iloc[-1]['close'])
            trend_score   = (close_now - close_20d_ago) / close_20d_ago * 100

            close_5d_ago  = float(df_idx.iloc[max(0, len(df_idx)-6)]['close'])
            momentum_5d   = (close_now - close_5d_ago) / close_5d_ago * 100 / 5  # 日均

        style_data['trend_score']  = round(trend_score, 2)
        style_data['momentum_5d']  = round(momentum_5d, 2)

        # 投票①（趋势强度，阈值从8%降至5%，适配弱动量牛市）
        if trend_score >= 5:
            style_data['votes_momentum'] += 1
        elif trend_score <= -5:
            style_data['votes_bear'] += 1
        else:
            style_data['votes_sideways'] += 1

        # 投票③（5日动量，阈值从0.4%降至0.3%）
        if momentum_5d >= 0.3:
            style_data['votes_momentum'] += 1
        elif momentum_5d <= -0.3:
            style_data['votes_bear'] += 1
        else:
            style_data['votes_sideways'] += 1

        # ── 指标②：市场宽度（申万行业站上MA10比例）──
        breadth = 0.5  # 默认值，若无法获取则中性
        sector_ma10 = get_sector_ma10_status(trade_date)
        if sector_ma10:
            above_count = sum(1 for v in sector_ma10.values() if v)
            breadth = above_count / len(sector_ma10)
        style_data['breadth'] = round(breadth, 2)

        # 投票②（宽度阈值从65%降至55%，适配弱动量市场）
        if breadth >= 0.55:
            style_data['votes_momentum'] += 1
        elif breadth <= 0.35:
            style_data['votes_bear'] += 1
        else:
            style_data['votes_sideways'] += 1

    except Exception as e:
        logger.warning(f"市场风格检测失败：{e}，默认使用震荡模式")
        return 'sideways', style_data

    # ── 三票多数决（新增弱动量模式）──
    vm = style_data['votes_momentum']
    vs = style_data['votes_sideways']
    vb = style_data['votes_bear']

    if vm >= 2:
        style = 'momentum'       # 强动量牛市：≥2票
    elif vb >= 2:
        style = 'bear'           # 熊市：≥2票
    elif vm == 1:
        style = 'weak_momentum'  # 弱动量牛市：恰好1票（新增）
    else:
        style = 'sideways'       # 震荡市：0票动量

    style_label = {
        'momentum': '强动量牛市🚀',
        'weak_momentum': '弱动量牛市📈',
        'sideways': '震荡市🎯',
        'bear': '熊市🐻',
    }.get(style, style)

    logger.info(
        f"📊 市场风格：{style_label}（动量{vm}/震荡{vs}/熊市{vb}票）"
        f" | CSI300_20d={trend_score:+.1f}%  宽度={breadth:.0%}  5d日均={momentum_5d:+.2f}%"
    )
    return style, style_data


def get_limit_up_stocks(trade_date: str) -> List[str]:
    """获取涨停股票列表（纯数字代码）"""
    try:
        df = pro.daily(trade_date=trade_date, fields='ts_code,pct_chg')
        if df.empty or 'pct_chg' not in df.columns:
            logger.warning(f"⚠️ {trade_date}无涨停数据")
            return []
        codes = df[df['pct_chg'] >= 9.8]['ts_code'].apply(revert_code).tolist()
        logger.info(f"✅ {trade_date}涨停股数：{len(codes)}")
        return codes
    except Exception as e:
        logger.warning(f"⚠️ 获取涨停股失败：{e}")
        return []


def filter_restricted_stocks(codes: List[str], trade_date: str) -> List[str]:
    """过滤近期解禁/减持股票"""
    start_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(15)).strftime('%Y%m%d')
    restricted = set()

    # 1. 限售股解禁
    try:
        lift_df = pro.share_float(start_date=start_date, end_date=trade_date, fields='ts_code')
        if not lift_df.empty:
            restricted.update(lift_df['ts_code'].apply(revert_code).tolist())
    except Exception as e:
        logger.warning(f"share_float失败：{e}")

    # 2. 股东减持（修复：分别查 G/P/C 三种类型，避免漏掉）
    for holder_type in ['G', 'P', 'C']:
        try:
            df = pro.stk_holdertrade(
                start_date=start_date,
                end_date=trade_date,
                holder_type=holder_type,
                fields='ts_code,in_de'
            )
            if not df.empty:
                sell_df = df[df['in_de'] == 'DE']
                restricted.update(sell_df['ts_code'].apply(revert_code).tolist())
        except Exception as e:
            logger.warning(f"stk_holdertrade({holder_type})失败：{e}")

    safe = [c for c in codes if c not in restricted]
    logger.info(f"✅ 过滤解禁/减持：{len(codes)}只 → {len(safe)}只")
    return safe

# ==================== 持仓管理代码已删除（v2.2纯选股工具） ====================

# ==================== 选股策略 ====================
def get_all_stocks(min_change: float = None, max_change: float = None,
                   min_turnover: float = None, max_turnover: float = None,
                   min_volume_ratio: float = 1.5,
                   trade_date: str = None) -> Tuple[pd.DataFrame, str, int]:
    """
    全市场选股。参数默认取 config，可由调用方覆盖（长线用更宽的过滤范围）。
    daily_basic volume_ratio 无效时自动回退到前一交易日，data_date 标注来源。
    返回：(股票DataFrame, 交易日期, 涨停股数量)

    Args:
        trade_date: 指定交易日期（YYYYMMDD），None则使用最新交易日
        min_volume_ratio: 最低量比门槛（短线默认1.5，波段选股传0跳过此过滤）
    """
    if min_change is None:
        min_change = config.MIN_CHANGE
    if max_change is None:
        max_change = config.MAX_CHANGE
    if min_turnover is None:
        min_turnover = config.MIN_TURNOVER
    if max_turnover is None:
        max_turnover = config.MAX_TURNOVER

    latest_trade_date = trade_date if trade_date else get_latest_trade_date()
    logger.info(f"📊 基于{latest_trade_date}开始选股（涨幅{min_change}%~{max_change}%）")

    try:
        # 1. 获取A股基础信息，过滤 ST/退市
        stock_basic = pro.stock_basic(
            exchange='', list_status='L',
            fields='ts_code,symbol,name,industry,list_date'
        )
        if stock_basic.empty or 'name' not in stock_basic.columns:
            logger.error("❌ stock_basic返回空数据或缺少字段")
            return pd.DataFrame(), latest_trade_date, 0

        # 修复：过滤特殊股票
        stock_basic = stock_basic[
            ~stock_basic['name'].str.contains(r'ST|＊ST|\*ST|退市', na=False, regex=True) &
            ~stock_basic['symbol'].str.startswith('688') &
            ~stock_basic['symbol'].str.startswith('300') &
            ~stock_basic['symbol'].str.startswith('8')
        ].reset_index(drop=True)
        if stock_basic.empty:
            return pd.DataFrame(), latest_trade_date, 0

        all_ts_codes = stock_basic['ts_code'].tolist()
        batch_size = 500
        is_offline = type(pro).__name__ == 'LocalDataProxy'
        logger.info(f"📦 共{len(all_ts_codes)}只股票，分批获取行情")

        # 2. 批量获取行情（daily 接口不含换手率/量比，只取价格和成交数据）
        # 注意：amount 单位是"千元"，例如 300000 表示 3亿元（300000 * 1000 = 3亿）
        DAILY_FIELDS = 'ts_code,trade_date,close,pct_chg,vol,amount'

        def fetch_daily(trade_date: str) -> List[pd.DataFrame]:
            # 离线模式：直接读单日全量文件，无需分批也无需 sleep
            if is_offline:
                try:
                    df_all = pro.daily(trade_date=trade_date, fields=DAILY_FIELDS)
                    return [df_all] if not df_all.empty else []
                except Exception as e:
                    logger.warning(f"离线行情读取失败（{trade_date}）：{e}")
                    return []
            # 在线模式：按批次请求 + 限速
            dfs = []
            for i in range(0, len(all_ts_codes), batch_size):
                batch = all_ts_codes[i:i + batch_size]
                try:
                    df_batch = pro.daily(
                        ts_code=",".join(batch),
                        trade_date=trade_date,
                        fields=DAILY_FIELDS
                    )
                    if not df_batch.empty:
                        dfs.append(df_batch)
                except Exception as e:
                    logger.warning(f"行情第{i // batch_size + 1}批失败：{e}")
                time.sleep(0.8)
            return dfs

        def fetch_daily_basic(trade_date: str) -> pd.DataFrame:
            """获取换手率和量比（daily_basic 只传 trade_date，一次拿全市场，不支持批量 ts_code）"""
            try:
                df = pro.daily_basic(
                    trade_date=trade_date,
                    fields='ts_code,turnover_rate,volume_ratio'
                )
                if not df.empty:
                    return df.drop_duplicates(subset='ts_code').reset_index(drop=True)
            except Exception as e:
                logger.warning(f"daily_basic 获取失败：{e}")
            return pd.DataFrame()

        df_list = fetch_daily(latest_trade_date)

        # 无数据时回退到前一交易日
        if not df_list:
            logger.warning("最新交易日无数据，尝试前一交易日")
            prev_dates = get_recent_trade_dates(latest_trade_date, n=7)
            # prev_dates[0] 是 latest_trade_date 本身，取 [1] 才是前一日
            prev_trade_dates = [d for d in prev_dates if d < latest_trade_date]
            if not prev_trade_dates:
                logger.error("❌ 无可用前一交易日")
                return pd.DataFrame(), latest_trade_date, 0
            latest_trade_date = prev_trade_dates[0]
            logger.info(f"回退到交易日：{latest_trade_date}")
            df_list = fetch_daily(latest_trade_date)

        if not df_list:
            logger.error("❌ 无法获取任何行情数据")
            return pd.DataFrame(), latest_trade_date, 0

        # 3. 合并清洗行情数据
        df_price = pd.concat(df_list, ignore_index=True)
        df_price = df_price[(df_price['amount'] > 0) & (df_price['close'] > 0)].copy()
        # 在 rename 前保存全市场 pct_chg，供 check_market_risk/get_market_sentiment 复用
        market_pct_df_raw = df_price[['ts_code', 'pct_chg']].drop_duplicates(subset='ts_code').copy()
        df_price = df_price.rename(columns={'pct_chg': 'change'})
        df_price = df_price.drop_duplicates(subset='ts_code').reset_index(drop=True)

        # 3b. 获取换手率和量比（daily_basic 接口）
        logger.info("📊 获取换手率和量比...")
        df_basic = fetch_daily_basic(latest_trade_date)
        has_basic_data = not df_basic.empty

        # volume_ratio 无效时回退到前一交易日（重新拉取全部数据）
        if has_basic_data and df_basic['volume_ratio'].notna().mean() <= 0.5:
            prev_dates = get_recent_trade_dates(latest_trade_date, n=3)
            prev = [d for d in prev_dates if d < latest_trade_date]
            if prev:
                latest_trade_date = prev[0]
                logger.warning(f"⚠️ 今日数据未完整入库，回退使用 {latest_trade_date} 数据（仅供参考）")
                df_list = fetch_daily(latest_trade_date)
                if not df_list:
                    logger.error("❌ 回退日期也无行情数据")
                    return pd.DataFrame(), latest_trade_date, 0, pd.DataFrame()
                df_price = pd.concat(df_list, ignore_index=True)
                df_price = df_price[(df_price['amount'] > 0) & (df_price['close'] > 0)].copy()
                market_pct_df_raw = df_price[['ts_code', 'pct_chg']].drop_duplicates(subset='ts_code').copy()
                df_price = df_price.rename(columns={'pct_chg': 'change'})
                df_price = df_price.drop_duplicates(subset='ts_code').reset_index(drop=True)
                df_basic = fetch_daily_basic(latest_trade_date)
                has_basic_data = not df_basic.empty

        if has_basic_data:
            df_basic = df_basic.rename(columns={'turnover_rate': 'turnover'})
            df_price = pd.merge(df_price, df_basic[['ts_code', 'turnover', 'volume_ratio']],
                                on='ts_code', how='left')
            logger.info(f"✅ daily_basic 获取成功，共{len(df_basic)}只")
        else:
            logger.warning("⚠️ daily_basic 无数据，跳过换手率/量比过滤")
            df_price['turnover'] = 5.0
            df_price['volume_ratio'] = 1.0

        # stock_basic 只保留必要列
        stock_basic = stock_basic[['ts_code', 'symbol', 'name', 'industry', 'list_date']]

        # 4. 合并，去重，reset_index（确保 index 唯一）
        df = pd.merge(stock_basic, df_price, on='ts_code', how='inner')
        df = df.drop_duplicates(subset='ts_code').reset_index(drop=True)
        df['code'] = df['symbol'].astype(str)

        # 换手率/量比：先记录有效数据比例，再 fillna
        has_vol_ratio_data = df['volume_ratio'].notna().mean() > 0.5 if 'volume_ratio' in df.columns else False
        has_turnover_data = df['turnover'].notna().mean() > 0.5 if 'turnover' in df.columns else False
        df['turnover'] = df['turnover'].fillna(5.0)
        df['volume_ratio'] = df['volume_ratio'].fillna(1.0)
        if not has_turnover_data:
            logger.warning("⚠️ turnover 有效数据不足50%，跳过换手率过滤")

        # 5. 批量资金流（失败批次保留 NaN）
        logger.info("📊 批量获取资金流...")
        mf_dict = get_batch_moneyflow(all_ts_codes, latest_trade_date)
        df['main_net_inflow'] = df['ts_code'].map(mf_dict)

        # 6. 涨停标记
        limit_up_codes = get_limit_up_stocks(latest_trade_date)
        limit_up_count = len(limit_up_codes)
        df['is_limit_up'] = df['code'].isin(limit_up_codes)

        # 7. 过滤条件（修复：避免使用.values，直接用Series布尔运算，防止index对齐问题）
        # 资金流：NaN（数据缺失）视为中性，不过滤；确认为负才过滤
        mf_ok = df['main_net_inflow'].isna() | (df['main_net_inflow'].fillna(0) >= 0)
        # 基础过滤：成交额 + 涨幅
        mask = (
            (df['amount'] >= config.MIN_STOCK_AMOUNT) &
            (df['change'] >= min_change) &
            (df['change'] <= max_change) &
            mf_ok
        )
        # 有 daily_basic 数据且字段有效时才加量比和换手率过滤
        if has_basic_data and has_vol_ratio_data and min_volume_ratio > 0:
            mask = mask & (df['volume_ratio'] >= min_volume_ratio)
        if has_basic_data and has_turnover_data:
            mask = mask & (df['turnover'] >= min_turnover)
            mask = mask & (df['turnover'] <= max_turnover)

        # 修复：过滤前再次确保index唯一，防止reindex错误
        df = df.reset_index(drop=True)
        df = df[mask].copy()

        # 9. 过滤解禁/减持
        safe_codes = filter_restricted_stocks(df['code'].tolist(), latest_trade_date)
        df = df[df['code'].isin(safe_codes)]

        # main_net_inflow NaN 填 0 仅用于展示
        df['main_net_inflow'] = df['main_net_inflow'].fillna(0.0)

        df = df[["code", "name", "industry", "close", "change", "turnover",
                 "volume_ratio", "main_net_inflow", "is_limit_up", "amount"]].reset_index(drop=True)
        logger.info(f"✅ 基础选股完成：{len(df)}只")
        # 返回全市场 pct_chg 数据（供 check_market_risk / get_market_sentiment 复用，避免重复拉取）
        return df, latest_trade_date, limit_up_count, market_pct_df_raw

    except Exception as e:
        logger.error(f"❌ 全市场选股失败：{e}", exc_info=True)
        return pd.DataFrame(), latest_trade_date, 0, pd.DataFrame()


def get_industry_rs_scores(trade_date: str, sw_map: Dict = None) -> Dict[str, float]:
    """
    计算申万一级行业相对于沪深300的20日相对强度（RS）得分。
    公式：行业指数20日累计涨幅 - CSI300同期20日累计涨幅
    正值 = 行业跑赢大盘，负值 = 行业跑输大盘。
    用于波段选股的行业强度维度评分（权重20%）。

    返回：{行业名称: RS得分（%，行业超额涨幅）}
    """
    if sw_map is None:
        sw_map = {
            '801010.SI': '农林牧渔', '801020.SI': '采掘', '801030.SI': '化工',
            '801040.SI': '钢铁', '801050.SI': '有色金属', '801080.SI': '电子',
            '801110.SI': '家用电器', '801120.SI': '食品饮料', '801130.SI': '纺织服饰',
            '801140.SI': '轻工制造', '801150.SI': '医药生物', '801160.SI': '公用事业',
            '801170.SI': '交通运输', '801180.SI': '房地产', '801200.SI': '商贸零售',
            '801210.SI': '社会服务', '801230.SI': '综合', '801710.SI': '建筑材料',
            '801720.SI': '建筑装饰', '801730.SI': '电力设备', '801740.SI': '国防军工',
            '801750.SI': '计算机', '801760.SI': '传媒', '801770.SI': '通信',
            '801780.SI': '银行', '801790.SI': '非银金融', '801880.SI': '汽车',
            '801890.SI': '机械设备'
        }

    result = {}
    try:
        # 拉取行业指数近30天（确保能覆盖20个交易日）
        start_dt = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=35)).strftime('%Y%m%d')

        # 行业指数
        df_sw = pro.index_daily(
            ts_code=",".join(sw_map.keys()),
            start_date=start_dt,
            end_date=trade_date,
            fields='ts_code,trade_date,close'
        )
        # 沪深300基准
        df_csi = pro.index_daily(
            ts_code='000300.SH',
            start_date=start_dt,
            end_date=trade_date,
            fields='ts_code,trade_date,close'
        )

        if df_sw.empty or df_csi.empty:
            return result

        # 计算沪深300的20日累计涨幅
        df_csi_sorted = df_csi.sort_values('trade_date')
        if len(df_csi_sorted) >= 2:
            csi_start = float(df_csi_sorted.iloc[max(0, len(df_csi_sorted) - 21)]['close'])
            csi_end   = float(df_csi_sorted.iloc[-1]['close'])
            csi_return = (csi_end - csi_start) / csi_start * 100 if csi_start > 0 else 0.0
        else:
            csi_return = 0.0

        # 计算各行业20日累计涨幅，取超额收益
        for ts_code, grp in df_sw.groupby('ts_code'):
            industry = sw_map.get(ts_code, ts_code)
            grp = grp.sort_values('trade_date')
            if len(grp) < 2:
                continue
            idx_start = float(grp.iloc[max(0, len(grp) - 21)]['close'])
            idx_end   = float(grp.iloc[-1]['close'])
            idx_return = (idx_end - idx_start) / idx_start * 100 if idx_start > 0 else 0.0
            # 相对强度 = 行业涨幅 - 大盘涨幅
            rs = round(idx_return - csi_return, 2)
            result[industry] = rs

        if result:
            top3 = sorted(result.items(), key=lambda x: -x[1])[:3]
            logger.info(f"📊 行业RS（Top3强势）：" +
                        " | ".join(f"{n}({v:+.1f}%)" for n, v in top3))

    except Exception as e:
        logger.warning(f"行业RS计算失败：{e}")

    return result


def get_net_profit_growth_batch(codes: List[str], trade_date: str = '') -> Dict[str, Dict]:
    """
    批量获取净利润同比增长率（用于波段策略财务质量评分）。
    优先从 Tushare fina_indicator 字段 netprofit_yoy 获取，若无则降级跳过。
    回测时严格遵守 ann_date 截面约束（防未来函数）。

    返回：{code: {netprofit_yoy: float, profit_growth_accel: bool}}
      netprofit_yoy: 净利润同比增速（%），正=盈利增长，负=衰退
      profit_growth_accel: 是否加速增长（最近一期 > 上一期 YoY，需两期数据）
    """
    if not codes:
        return {}

    ts_codes = [format_code(c) for c in codes]
    is_offline = type(pro).__name__ == 'LocalDataProxy'
    result = {}

    try:
        batch_size = 50
        all_dfs = []

        if is_offline:
            try:
                # 离线模式：全量读取，包含 netprofit_yoy 字段
                df = pro.fina_indicator(
                    ts_code='',
                    fields='ts_code,ann_date,end_date,netprofit_yoy'
                )
                if not df.empty:
                    all_dfs.append(df)
            except Exception as e:
                logger.debug(f"离线fina_indicator(netprofit_yoy)读取失败：{e}")
        else:
            for i in range(0, len(ts_codes), batch_size):
                batch = ts_codes[i:i + batch_size]
                if i > 0:
                    time.sleep(0.8)
                try:
                    df = pro.fina_indicator(
                        ts_code=",".join(batch),
                        fields='ts_code,ann_date,end_date,netprofit_yoy'
                    )
                    if not df.empty:
                        all_dfs.append(df)
                except Exception as e:
                    logger.debug(f"fina_indicator(netprofit_yoy) 批次{i//batch_size+1}失败：{e}")

        if not all_dfs:
            return result

        df_all = pd.concat(all_dfs, ignore_index=True)
        if is_offline:
            df_all = df_all[df_all['ts_code'].isin(set(ts_codes))]

        # 时间截面约束（防未来函数）
        if trade_date and 'ann_date' in df_all.columns:
            df_all = df_all[
                df_all['ann_date'].notna() &
                (df_all['ann_date'].astype(str) <= trade_date)
            ]

        df_all = df_all.sort_values('end_date', ascending=False)

        for ts_code in ts_codes:
            code = revert_code(ts_code)
            stock_df = df_all[df_all['ts_code'] == ts_code].sort_values('end_date', ascending=False)
            if stock_df.empty:
                continue

            latest_row = stock_df.iloc[0]
            yoy = latest_row.get('netprofit_yoy', None)
            if yoy is None or pd.isna(yoy):
                continue

            yoy_val = float(yoy)

            # 利润增速加速：比较最新期 vs 上一期 YoY（需两期）
            accel = False
            if len(stock_df) >= 2:
                prev_yoy = stock_df.iloc[1].get('netprofit_yoy', None)
                if prev_yoy is not None and not pd.isna(prev_yoy):
                    # 上一期YoY也为正，且本期比上期更快
                    accel = bool(yoy_val > 0 and float(prev_yoy) > 0 and yoy_val > float(prev_yoy))

            result[code] = {
                'netprofit_yoy': round(yoy_val, 2),
                'profit_growth_accel': accel,
            }

        logger.info(f"✅ 净利润增速获取完成：{len(result)}只")

    except Exception as e:
        logger.warning(f"净利润增速获取失败：{e}")

    return result


def get_financial_data_batch(codes: List[str], trade_date: str = '') -> Dict[str, Dict]:
    """
    批量获取财务数据（ROE、营收增长率、资产负债率）。
    使用截至 trade_date 已公告的最新一期财报数据。
    若 trade_date 为空则不做截面约束（实盘/调试时使用最新数据）。
    返回：{code: {roe, revenue_growth, debt_ratio}}
    """
    if not codes or not config.ENABLE_FINANCIAL_FILTER:
        return {}

    ts_codes = [format_code(c) for c in codes]
    is_offline = type(pro).__name__ == 'LocalDataProxy'
    financial_dict = {}

    try:
        # 批量获取财务指标（ROE、资产负债率等）
        # 离线模式：静态文件有 lru_cache，一次全量读取；在线模式分批限速
        batch_size = 50
        all_fina_dfs = []

        if is_offline:
            try:
                df = pro.fina_indicator(
                    ts_code='',
                    fields='ts_code,ann_date,end_date,roe,debt_to_assets'
                )
                if not df.empty:
                    all_fina_dfs.append(df)
            except Exception as e:
                logger.warning(f"离线fina_indicator读取失败：{e}")
        else:
            for i in range(0, len(ts_codes), batch_size):
                batch = ts_codes[i:i + batch_size]
                if i > 0:
                    time.sleep(0.8)
                try:
                    # 新增 ann_date 字段，用于截面约束
                    df = pro.fina_indicator(
                        ts_code=",".join(batch),
                        fields='ts_code,ann_date,end_date,roe,debt_to_assets'
                    )
                    if not df.empty:
                        all_fina_dfs.append(df)
                except Exception as e:
                    logger.warning(f"fina_indicator批次{i//batch_size + 1}失败：{e}")

        if all_fina_dfs:
            df_fina = pd.concat(all_fina_dfs, ignore_index=True)
            # 离线全量读取时，过滤到候选股范围
            if is_offline:
                df_fina = df_fina[df_fina['ts_code'].isin(set(ts_codes))]
            # 时间截面约束：只使用截至 trade_date 已公告的财报
            # 避免回测时用到尚未发布的未来财报（Look-Ahead Bias）
            # 注意：旧版 parquet 可能无 ann_date 列（下载时未包含），此时跳过截面约束
            if trade_date and 'ann_date' in df_fina.columns:
                df_fina = df_fina[
                    df_fina['ann_date'].notna() &
                    (df_fina['ann_date'].astype(str) <= trade_date)
                ]
            elif trade_date and 'ann_date' not in df_fina.columns:
                logger.warning("fina_indicator 缺少 ann_date 列，时间截面约束已跳过（建议重新下载 parquet）")
            # 每只股票取已公告中最新一期（end_date最大）
            df_fina = df_fina.sort_values('end_date', ascending=False).drop_duplicates('ts_code').reset_index(drop=True)
        else:
            df_fina = pd.DataFrame()

        # 批量获取利润表（营收增长率）
        all_income_dfs = []
        if is_offline:
            try:
                df = pro.income(
                    ts_code='',
                    fields='ts_code,ann_date,end_date,revenue'
                )
                if not df.empty:
                    all_income_dfs.append(df)
            except Exception as e:
                logger.warning(f"离线income读取失败：{e}")
        else:
            for i in range(0, len(ts_codes), batch_size):
                batch = ts_codes[i:i + batch_size]
                if i > 0:
                    time.sleep(0.8)
                try:
                    # 获取最近2期财报，用于计算同比增长
                    df = pro.income(
                        ts_code=",".join(batch),
                        fields='ts_code,ann_date,end_date,revenue'
                    )
                    if not df.empty:
                        all_income_dfs.append(df)
                except Exception as e:
                    logger.warning(f"income批次{i//batch_size + 1}失败：{e}")

        if all_income_dfs:
            df_income = pd.concat(all_income_dfs, ignore_index=True)
            # 离线全量读取时，过滤到候选股范围
            if is_offline:
                df_income = df_income[df_income['ts_code'].isin(set(ts_codes))]
            # 同样做时间截面约束
            # 注意：旧版 parquet 可能无 ann_date 列，此时跳过截面约束
            if trade_date and 'ann_date' in df_income.columns:
                df_income = df_income[
                    df_income['ann_date'].notna() &
                    (df_income['ann_date'].astype(str) <= trade_date)
                ]
            elif trade_date and 'ann_date' not in df_income.columns:
                logger.warning("income 缺少 ann_date 列，时间截面约束已跳过（建议重新下载 parquet）")
            df_income = df_income.sort_values('end_date', ascending=False)
        else:
            df_income = pd.DataFrame()

        # 合并数据
        for ts_code in ts_codes:
            code = revert_code(ts_code)
            fin_data = {}

            # ROE和资产负债率
            if not df_fina.empty:
                fina_row = df_fina[df_fina['ts_code'] == ts_code]
                if not fina_row.empty:
                    roe = fina_row.iloc[0]['roe']
                    debt = fina_row.iloc[0]['debt_to_assets']
                    fin_data['roe'] = float(roe) if pd.notna(roe) else None
                    fin_data['debt_ratio'] = float(debt) if pd.notna(debt) else None

            # 营收增长率（真正的同比：最新报告期 vs 上年同期）
            # end_date 格式 YYYYMMDD，同期 = 日期相同但年份-1
            if not df_income.empty:
                stock_income = df_income[df_income['ts_code'] == ts_code].sort_values('end_date', ascending=False)
                if not stock_income.empty:
                    latest_row = stock_income.iloc[0]
                    latest_end = latest_row['end_date']  # e.g. '20231231'
                    rev_latest = latest_row['revenue']
                    # 同期 = 上年相同报告期（年份-1，月日不变）
                    same_period_last_year = str(int(latest_end[:4]) - 1) + latest_end[4:]
                    prev_rows = stock_income[stock_income['end_date'] == same_period_last_year]
                    if not prev_rows.empty:
                        rev_prev = prev_rows.iloc[0]['revenue']
                        if pd.notna(rev_latest) and pd.notna(rev_prev) and float(rev_prev) > 0:
                            growth = (float(rev_latest) - float(rev_prev)) / float(rev_prev) * 100
                            fin_data['revenue_growth'] = round(growth, 2)
                        else:
                            fin_data['revenue_growth'] = None
                    else:
                        fin_data['revenue_growth'] = None
                else:
                    fin_data['revenue_growth'] = None

            if fin_data:
                financial_dict[code] = fin_data

        logger.info(f"✅ 财务数据获取完成：{len(financial_dict)}只")
        return financial_dict

    except Exception as e:
        logger.error(f"❌ 财务数据获取失败：{e}", exc_info=True)
        return {}


def get_ma_data_batch(codes: List[str], trade_date: str, index_change: float = 0.0) -> Dict[str, Optional[Dict]]:
    """
    批量计算技术指标，拉取近100天行情本地计算（覆盖MA60）。
    v2.6新增：index_change用于计算逆势抗跌因子。
    """
    if not codes:
        return {}

    ts_codes = [format_code(c) for c in codes]
    # 100天覆盖MA60 + 近20日高低点 + 涨停基因
    start_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=105)).strftime('%Y%m%d')
    is_offline = type(pro).__name__ == 'LocalDataProxy'

    all_dfs = []

    if is_offline:
        # 离线模式：直接读区间全量文件，无需按 ts_code 分批，一次拿完所有股票所有日期
        # LocalDataProxy._read_date_range 有目录缓存，单文件有 lru_cache，速度极快
        try:
            df = pro.daily(
                start_date=start_date,
                end_date=trade_date,
                fields='ts_code,trade_date,open,close,high,low,vol,pct_chg'
            )
            if not df.empty:
                all_dfs.append(df)
        except Exception as e:
            logger.warning(f"离线MA数据读取失败：{e}")
    else:
        # 在线模式：按批次请求 + 限速
        batch_size = 200
        for i in range(0, len(ts_codes), batch_size):
            batch = ts_codes[i:i + batch_size]
            # 优化：首批不延迟，后续批次延迟0.8秒，提升性能
            if i > 0:
                time.sleep(0.8)
            try:
                df = pro.daily(
                    ts_code=",".join(batch),
                    start_date=start_date,
                    end_date=trade_date,
                    fields='ts_code,trade_date,open,close,high,low,vol,pct_chg'
                )
                if not df.empty:
                    all_dfs.append(df)
            except Exception as e:
                logger.warning(f"MA数据第{i // batch_size + 1}批失败：{e}")

    if not all_dfs:
        return {}

    df_all = pd.concat(all_dfs, ignore_index=True)

    # 离线模式读取的是全市场数据，需按候选股过滤，避免计算无关股票
    if is_offline and not df_all.empty:
        ts_code_set = set(ts_codes)
        df_all = df_all[df_all['ts_code'].isin(ts_code_set)]

    result = {}
    for ts_code, grp in df_all.groupby('ts_code'):
        grp = grp.sort_values('trade_date').reset_index(drop=True)
        if len(grp) < 10:
            result[ts_code] = None
            continue

        grp['ma5'] = grp['close'].rolling(5).mean()
        grp['ma10'] = grp['close'].rolling(10).mean()
        grp['ma20'] = grp['close'].rolling(20).mean()
        grp['ma60'] = grp['close'].rolling(60).mean()
        grp['vol_ma5'] = grp['vol'].rolling(5).mean()
        grp['vol_ma20'] = grp['vol'].rolling(20).mean()

        latest = grp.iloc[-1]
        prev = grp.iloc[-2] if len(grp) >= 2 else latest

        if any(pd.isna(latest[c]) for c in ['ma5', 'ma10', 'vol_ma5']):
            result[ts_code] = None
            continue

        ma20_val = float(latest['ma20']) if not pd.isna(latest['ma20']) else None
        ma60_val = float(latest['ma60']) if not pd.isna(latest['ma60']) else None

        # MA20斜率（波段趋势强度）：最近5日MA20的日均涨幅
        ma20_slope = 0.0
        if ma20_val and len(grp) >= 25:
            recent5_ma20 = grp.tail(5)['ma20'].dropna()
            if len(recent5_ma20) >= 2:
                total_change = (recent5_ma20.iloc[-1] - recent5_ma20.iloc[0]) / recent5_ma20.iloc[0] * 100
                ma20_slope = total_change / 5  # 日均涨幅

        # 近20日高低点（目标价/止损参考）
        recent20 = grp.tail(20)
        high20 = float(recent20['high'].max())
        low20 = float(recent20['low'].min())
        close = float(latest['close'])

        # 距20日高点回撤幅度（越大说明越在低位）
        drawdown_from_high = (high20 - close) / high20 * 100

        # 回撤速度判断：区分急跌和阴跌
        is_sharp_drop = False
        if drawdown_from_high > 5 and len(grp) >= 4:
            recent_3_drop = (grp.iloc[-4]['close'] - close) / grp.iloc[-4]['close'] * 100
            is_sharp_drop = recent_3_drop / drawdown_from_high > 0.6 if drawdown_from_high > 0 else False

        # 近10日是否有涨停（涨停基因）
        recent10_pct = grp.tail(10)['pct_chg']
        has_limit_up_gene = bool((recent10_pct >= 9.5).any())

        # MA5突破：今天收盘>MA5，昨天收盘<=MA5（刚突破比已在上方更有爆发力）
        just_broke_ma5 = bool(latest['close'] > latest['ma5'] and prev['close'] <= prev['ma5'])

        # 历史波动率（近10日收益率标准差，用于估算目标价区间）
        recent10_returns = grp.tail(10)['pct_chg'].dropna()
        volatility = float(recent10_returns.std()) if len(recent10_returns) >= 5 else 3.0

        # 方案B新增：K线形态判断（排除假突破）
        open_price = float(latest['open'])
        high_price = float(latest['high'])
        is_positive = close >= open_price  # 阳线或假阴真阳
        body_len = abs(close - open_price)
        upper_shadow = high_price - max(close, open_price)
        is_short_upper_shadow = upper_shadow < body_len * 1.5 if body_len > 0 else True

        # 近3日量比（判断连续放量）- 修复：正确计算每日量比，增强边界检查
        vol_3d_avg = 1.0
        vol_accelerating = False

        if len(grp) >= 8:  # 至少需要8天数据（5日均量+3日）
            recent3 = grp.tail(3)
            vol_ratios_3d = []

            # 修复：增强边界检查，确保索引有效
            for idx in range(max(5, len(grp) - 3), len(grp)):  # 从max(5, len-3)开始，确保idx>=5
                if idx >= 5 and idx < len(grp):  # 双重检查
                    day_vol = grp.iloc[idx]['vol']
                    prev_5d_avg = grp.iloc[idx-5:idx]['vol'].mean()
                    if prev_5d_avg > 0 and not pd.isna(day_vol):
                        vol_ratios_3d.append(day_vol / prev_5d_avg)

            vol_3d_avg = sum(vol_ratios_3d) / len(vol_ratios_3d) if vol_ratios_3d else 1.0
            # 量能加速：今日量 > 昨日量
            if len(recent3) >= 2:
                today_vol = recent3.iloc[-1]['vol']
                yesterday_vol = recent3.iloc[-2]['vol']
                if not pd.isna(today_vol) and not pd.isna(yesterday_vol):
                    vol_accelerating = today_vol > yesterday_vol

        # ── 目标价（修复：降低最低止盈门槛，提升止盈触发率）──
        # 原逻辑：min(volatility*2.5, 6)，5天内触发6%的概率只有14%
        # 新逻辑：分层目标价，用 high20 前高作为第一目标，波动率作为参考
        # 第一目标：距 high20 的一半（先锁住部分利润）
        # 保底最低：1.5倍波动率（约等于2-3天的正常振幅）
        mid_target_pct = max(volatility * 1.5, 3.0)   # 最低3%，约1-2天到达
        full_target_pct = max(volatility * 2.5, 5.0)  # 最低5%，完整目标
        # 以 high20 为上限参考：如果 high20 只有4%空间，目标价不能超过 high20
        high20_upside = (high20 - close) / close * 100 if high20 > close else 0
        # 最终目标价：在波动率目标和high20之间取合理值
        if high20_upside >= full_target_pct:
            target_pct = full_target_pct
        elif high20_upside >= mid_target_pct:
            target_pct = mid_target_pct   # 用较保守目标，更容易触盈
        else:
            target_pct = max(mid_target_pct, 3.0)  # 至少3%
        target_price = round(close * (1 + target_pct / 100), 2)

        # 止损价：基于技术支撑位动态计算
        # 优先用 MA10/MA20 而非 MA5，给股票正常回调留出空间
        # 高波动(>5%)留4%，正常(3-5%)留2.5%，低波动(<3%)留1.5%
        if volatility > 5:
            buffer_pct = 0.04   # 4%缓冲
        elif volatility >= 3:
            buffer_pct = 0.025  # 2.5%缓冲
        else:
            buffer_pct = 0.015  # 1.5%缓冲

        ma5_val  = float(latest['ma5'])
        ma10_val = float(latest['ma10'])
        ma20_val_sl = float(latest['ma20']) if not pd.isna(latest['ma20']) else None
        ma60_val_sl = float(latest['ma60']) if not pd.isna(latest['ma60']) else None

        # 优先选 MA10/MA20 作为支撑（MA5太近，正常回调就触损）
        support = None
        for ma_val in [ma10_val, ma20_val_sl, ma5_val, ma60_val_sl]:
            if ma_val is not None and ma_val < close:
                support = ma_val
                break

        if support is not None:
            stop_loss_price = round(support * (1 - buffer_pct), 2)
        else:
            # 所有均线均在价格上方（强势股），用近20日低点作为支撑
            stop_loss_price = round(low20 * (1 - buffer_pct / 2), 2)

        # ── 修复：去掉 min(close*0.99) 的错误上限钳制 ──
        # 原 min(stop_loss_price, close*0.99) 会把止损锁死在1%以内，导致快速触损
        # 改为：只保证止损价 < 当前价（合理性检查），允许均线支撑位给出正常缓冲空间
        # 下限：不超过当前价-20%（极端行情保护）
        # 上限：严格小于当前价（止损价不能高于买入价）
        stop_loss_price = min(stop_loss_price, round(close * 0.993, 2))  # 至少0.7%缓冲
        stop_loss_price = max(stop_loss_price, round(close * 0.80, 2))   # 最大亏损20%兜底

        # v2.6新增：逆势抗跌因子（大盘跌>1%时，个股仍上涨）
        counter_trend_resistance = 0.0
        if index_change < -1.0:
            stock_change = float(latest['pct_chg']) if not pd.isna(latest['pct_chg']) else 0.0
            if stock_change > 0:
                counter_trend_resistance = stock_change - index_change  # 相对强度

        # v2.8新增：技术形态识别
        breakout_platform = False  # 突破平台
        volume_wash = False  # 缩量洗盘后放量

        if len(grp) >= 15:
            recent_15 = grp.tail(15)
            # 突破平台：前10天横盘（波动<3%），今天放量突破
            if len(recent_15) >= 11:
                platform = recent_15.iloc[-11:-1]
                price_range = (platform['close'].max() - platform['close'].min()) / platform['close'].mean() * 100
                if price_range < 3 and latest['vol'] > latest['vol_ma5'] * 1.5:
                    breakout_platform = True

            # 缩量洗盘后放量：前5天缩量，今天放量
            if len(recent_15) >= 6:
                wash_period = recent_15.iloc[-6:-1]
                avg_vol_wash = wash_period['vol'].mean()
                if avg_vol_wash < latest['vol_ma20'] * 0.8 and latest['vol'] > latest['vol_ma5'] * 1.3:
                    volume_wash = True

        # ── v3.3新增：尾盘强弱信号（VWAP代理法）──
        # Tushare日线不含分钟级数据，用典型价格近似日内VWAP：
        #   vwap_proxy = (H + L + C) / 3  （经典 Typical Price，是VWAP的日线近似）
        # close > vwap_proxy → 尾盘偏强（价格向上偏离均价，主力护盘/拉升尾盘收集）
        # close < vwap_proxy → 尾盘偏弱（早盘/午盘拉高，尾盘压低或抛售）
        # 参考：Berkowitz et al.(1988) "The Total Cost of Transactions on the NYSE"
        #       Lo & MacKinlay(1990) "When are Contrarian Profits Due to Stock Market Overreaction"
        high_today  = float(latest['high'])
        low_today   = float(latest['low'])
        vwap_proxy  = (high_today + low_today + close) / 3
        # close_vs_vwap: 相对偏离幅度 = (收盘 - VWAP代理) / VWAP代理 × 100%
        close_vs_vwap = (close - vwap_proxy) / vwap_proxy * 100 if vwap_proxy > 0 else 0.0
        # 尾盘强势判定：偏离>+0.3% 且成交量>5日均量（有量的强势更可信）
        eod_strong = bool(close_vs_vwap > 0.3 and latest['vol'] > latest['vol_ma5'] * 1.0)

        # ── ATR（真实波幅均值）计算 ──
        # ATR = 最近14日 True Range（最高-最低、最高-昨收、昨收-最低 三者最大值）的均值
        # 用于动态止盈止损（止损=入场-1.5ATR，目标=入场+2.0ATR，锁住≥1.33:1盈亏比）
        atr_14 = float(volatility * close / 100)  # 默认值：用波动率×价格近似
        if len(grp) >= 15:
            tr_list = []
            for i in range(max(1, len(grp) - 14), len(grp)):
                h = float(grp.iloc[i]['high'])
                l = float(grp.iloc[i]['low'])
                prev_c = float(grp.iloc[i - 1]['close'])
                tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                tr_list.append(tr)
            if tr_list:
                atr_14 = round(sum(tr_list) / len(tr_list), 4)

        # 基于ATR更新止盈止损（替代波动率近似法）
        # v3.3修复：止盈倍数从 2.0×ATR 提升至 3.0×ATR
        # 原因：2.0×ATR 对应 A 股短线股约 4~8% 的目标，止盈太早截断了强势股的利润
        # 3.0×ATR 对应约 6~12% 目标，盈亏比从 ≥1.33 提升至 ≥2.0
        # 参考：Schwager(2012) "Market Wizards" — 截断亏损，让利润奔跑
        atr_stop_loss  = round(close - 1.5 * atr_14, 2)   # 止损：入场 - 1.5×ATR（不变）
        atr_target     = round(close + 3.0 * atr_14, 2)   # 目标：入场 + 3.0×ATR（原2.0→3.0）
        # 合理性修正：止损不能低于当前价-20%；目标不能高于当前价+40%（原30%，配合更高倍数）
        atr_stop_loss = max(atr_stop_loss, round(close * 0.80, 2))
        atr_stop_loss = min(atr_stop_loss, round(close * 0.993, 2))  # 至少0.7%缓冲
        atr_target    = min(atr_target, round(close * 1.40, 2))

        # ── Wyckoff 筹码结构评分 ──
        # 评判"过去N天是否形成了健康的吸筹蓄势结构"，分值0-100
        # 核心三要素：① 横盘整理（价格波动收窄）② 回调期缩量 ③ 今日放量突破
        wyckoff_score = 0.0
        if len(grp) >= 12:
            consolidation_days = min(15, len(grp) - 2)  # 检测过去最多15天
            consol_window = grp.iloc[-(consolidation_days + 1):-1]  # 不含今日

            if len(consol_window) >= 5:
                # 要素①：价格波动收窄（横盘蓄势）
                # 用近N日收盘价标准差 / 均值衡量震荡幅度
                price_cv = consol_window['close'].std() / consol_window['close'].mean() * 100
                if price_cv <= 2.0:        # 极度横盘（波动<2%）
                    price_consolidation_score = 100
                elif price_cv <= 4.0:      # 正常整理（波动2-4%）
                    price_consolidation_score = 50 + (4.0 - price_cv) / 2.0 * 50
                elif price_cv <= 7.0:      # 轻微整理（波动4-7%）
                    price_consolidation_score = (7.0 - price_cv) / 3.0 * 50
                else:
                    price_consolidation_score = 0   # 波动过大，不算筹码结构

                # 要素②：回调期成交量收缩（主力未出货）
                # 过去N天均量 vs 更早期20天均量的比值
                if not pd.isna(latest['vol_ma20']) and float(latest['vol_ma20']) > 0:
                    consol_avg_vol = consol_window['vol'].mean()
                    vol_shrink_ratio = consol_avg_vol / float(latest['vol_ma20'])
                    if vol_shrink_ratio <= 0.7:        # 明显缩量（<70%均量）
                        vol_shrink_score = 100
                    elif vol_shrink_ratio <= 0.9:      # 适度缩量（70-90%）
                        vol_shrink_score = 50 + (0.9 - vol_shrink_ratio) / 0.2 * 50
                    elif vol_shrink_ratio <= 1.1:      # 量能基本持平（90-110%）
                        vol_shrink_score = 30
                    else:
                        vol_shrink_score = 0           # 回调期放量，主力可能出货
                else:
                    vol_shrink_score = 30              # 数据不足，给中性分

                # 要素③：今日放量突破（启动确认）
                # 今日量 / 整理期平均量 的比值
                today_vol = float(latest['vol'])
                consol_avg = consol_window['vol'].mean()
                if consol_avg > 0:
                    breakout_vol_ratio = today_vol / consol_avg
                    if breakout_vol_ratio >= 2.5:      # 强力突破（量能≥2.5倍整理期）
                        breakout_vol_score = 100
                    elif breakout_vol_ratio >= 1.8:    # 明显突破
                        breakout_vol_score = 60 + (breakout_vol_ratio - 1.8) / 0.7 * 40
                    elif breakout_vol_ratio >= 1.3:    # 温和放量
                        breakout_vol_score = 20 + (breakout_vol_ratio - 1.3) / 0.5 * 40
                    else:
                        breakout_vol_score = 0
                else:
                    breakout_vol_score = 0

                # Wyckoff综合分 = 三要素加权（横盘35% + 缩量35% + 突破30%）
                wyckoff_score = round(
                    price_consolidation_score * 0.35 +
                    vol_shrink_score          * 0.35 +
                    breakout_vol_score        * 0.30,
                    1
                )
        wyckoff_score = max(0.0, min(wyckoff_score, 100.0))

        result[ts_code] = {
            "close": close,
            "ma5": float(latest["ma5"]),
            "ma10": float(latest["ma10"]),
            "ma20": ma20_val,
            "ma60": ma60_val,
            "ma20_slope": round(ma20_slope, 2),
            "above_ma5": bool(latest["close"] > latest["ma5"]),
            "above_ma10": bool(latest["close"] > latest["ma10"]),
            "above_ma20": bool(ma20_val and close > ma20_val),
            "ma5_above_ma10": bool(latest["ma5"] > latest["ma10"]),
            "ma20_above_ma60": bool(ma20_val and ma60_val and ma20_val > ma60_val),
            "near_ma20": bool(ma20_val and abs(close - ma20_val) / ma20_val <= 0.05),
            "vol_up": bool(latest["vol"] > latest["vol_ma5"]),
            "vol_trend_up": bool(not pd.isna(latest["vol_ma20"]) and latest["vol_ma5"] > latest["vol_ma20"]),
            "vol_3d_avg": round(vol_3d_avg, 2),
            "vol_accelerating": vol_accelerating,
            "just_broke_ma5": just_broke_ma5,
            "has_limit_up_gene": has_limit_up_gene,
            "drawdown_from_high": round(drawdown_from_high, 1),
            "high20": high20,
            "low20": low20,
            "target_price": target_price,
            "stop_loss_price": stop_loss_price,
            "atr_14": round(atr_14, 4),
            "atr_stop_loss": atr_stop_loss,
            "atr_target": atr_target,
            "wyckoff_score": wyckoff_score,
            "volatility": round(volatility, 2),
            "is_positive_candle": is_positive,
            "is_short_upper_shadow": is_short_upper_shadow,
            "counter_trend_resistance": round(counter_trend_resistance, 2),
            "breakout_platform": breakout_platform,
            "volume_wash": volume_wash,
            "is_sharp_drop": is_sharp_drop,
            "close_vs_vwap": round(close_vs_vwap, 3),   # v3.3新增：收盘相对典型价偏离（%），>0.3%=尾盘强势
            "eod_strong": eod_strong,                    # v3.3新增：尾盘强势布尔值（VWAP代理法）
        }
    logger.info(f"✅ 技术指标计算完成：{len(result)}/{len(codes)}只（有数据/候选总数）")
    return result


def select_stock_pool(stocks: pd.DataFrame, ma_dict: Dict, trade_date: str, financial_dict: Dict = None, sector_ma10: Dict = None, hot_sectors: Dict = None, sector_news_boosts: Dict = None, hot_concepts: List = None, market_style: str = 'sideways', is_caution: bool = False, sector_accel: Dict = None, macro_mode: str = 'cautious', score_threshold: int = 45, atr_multiplier: float = 1.5) -> pd.DataFrame:
    """
    短线选股（1-3天）：根据市场风格自动切换选股模式。
      momentum      → 强动量模式：涨幅1~7% + 站上MA20 + 突破近期高点（追涨强势股）
      weak_momentum → 弱动量模式：涨幅0~5% + 量比≥1.5 + 回撤3-12%（中间模式）
      sideways/bear → 吸筹模式：量比≥1.5 + 涨幅0~5% + 回撤≥8%（现有逻辑优化版）
    is_caution=True时：final_score额外-10，等效提高准入门槛，仅高确定性标的入选
    v3.1+：新增 sector_accel（板块资金流加速）和 macro_mode（周线宏观模式）
    macro_mode='defensive' 时：仅允许宏观防御期安全板块，其他板块加速分不生效
    v3.2+：新增 score_threshold（状态机准入门槛）和 atr_multiplier（状态机ATR止损系数）
    """
    if stocks.empty:
        return pd.DataFrame()

    if financial_dict is None:
        financial_dict = {}
    if sector_ma10 is None:
        sector_ma10 = {}
    if sector_news_boosts is None:
        sector_news_boosts = {}
    if hot_concepts is None:
        hot_concepts = []
    if sector_accel is None:
        sector_accel = {}

    # ── 风格自适应过滤 ──
    # momentum（强动量牛市）：追涨突破模式，放宽涨幅上限，要求站上MA20
    # weak_momentum（弱动量牛市）：中间模式，量比适度降低，涨幅适度放宽
    # sideways/bear（震荡/熊市）：吸筹模式，量比1.5，低涨幅区间
    is_momentum      = (market_style == 'momentum')
    is_weak_momentum = (market_style == 'weak_momentum')

    if is_momentum:
        logger.info("🚀 强动量模式：切换为追涨突破过滤条件")
        st = stocks[
            (stocks['change'] > -9) &          # 过滤跌停
            (stocks['change'] >= 1.0) &        # 至少1%涨幅，确认方向
            (stocks['change'] <= 7.0) &        # 不超过7%，避免追高板前
            (stocks['volume_ratio'] >= 1.5) &  # 动量市量比门槛稍低
            (stocks['amount'] >= config.MIN_STOCK_AMOUNT_SHORT)
        ].copy()
    elif is_weak_momentum:
        logger.info("📈 弱动量模式：使用中间过滤条件（量比1.5+涨幅0-5%）")
        st = stocks[
            (stocks['change'] > -9) &          # 过滤跌停
            (stocks['change'] >= 0) &          # 弱动量不追负收益
            (stocks['change'] <= 5.0) &        # 上限5%，避免追高
            (stocks['volume_ratio'] >= 1.5) &  # 量比适度降低
            (stocks['amount'] >= config.MIN_STOCK_AMOUNT_SHORT)
        ].copy()
    else:
        logger.info("🎯 吸筹模式：使用量价异动过滤条件")
        st = stocks[
            (stocks['change'] > -9) &          # 过滤跌停
            (stocks['change'] >= 0) &           # 吸筹模式不追高
            (stocks['change'] <= 5.0) &         # 上限从4%放宽至5%
            (stocks['volume_ratio'] >= 1.5) &  # 量比从1.8降至1.5
            (stocks['amount'] >= config.MIN_STOCK_AMOUNT_SHORT)
        ].copy()
    if st.empty:
        return pd.DataFrame()

    # ── 预计算行业平均换手率（用于相对换手率评分）──
    # 相对换手率 = 个股换手率 / 行业均值，消除行业本身活跃度差异
    # 参考：Green et al.(2017) "Industry Momentum and Rotation" —— 相对强度比绝对值更有预测力
    industry_turnover_mean = {}
    if 'industry' in st.columns and 'turnover' in st.columns:
        for ind, grp in st.groupby('industry'):
            valid_t = grp['turnover'].replace(0, float('nan')).dropna()
            if len(valid_t) >= 3:  # 至少3只股票才有代表性
                industry_turnover_mean[ind] = float(valid_t.median())  # 用中位数更稳健

    cnt_no_ma = cnt_drawdown = cnt_ma = cnt_vol_weak = cnt_financial = 0
    valid_stocks = []
    for _, row in st.iterrows():
        ts_code = format_code(row["code"])
        code = row["code"]
        ma_data = ma_dict.get(ts_code)
        if not ma_data:
            cnt_no_ma += 1
            continue

        # ===== 财务过滤（方案B优化：短线不看基本面）=====
        if config.ENABLE_FINANCIAL_FILTER_SHORT and financial_dict:
            fin_data = financial_dict.get(code, {})
            roe = fin_data.get('roe')
            debt_ratio = fin_data.get('debt_ratio')
            revenue_growth = fin_data.get('revenue_growth')

            # 过滤条件：ROE、负债率、营收增长
            if roe is not None and roe < config.MIN_ROE:
                cnt_financial += 1
                continue
            if debt_ratio is not None and debt_ratio > config.MAX_DEBT_RATIO:
                cnt_financial += 1
                continue
            if revenue_growth is not None and revenue_growth < config.MIN_REVENUE_GROWTH:
                cnt_financial += 1
                continue
        else:
            fin_data = {}

        # ===== 板块共振过滤（v2.6新增，v2.9降级：sector_ma10为空时用hot_sectors）=====
        industry = row.get("industry", "")
        if sector_ma10:
            if not sector_ma10.get(industry, True):
                continue
        elif hot_sectors:
            median_heat = sorted(hot_sectors.values())[len(hot_sectors) // 2]
            if hot_sectors.get(industry, 0) < median_heat:
                continue

        close = ma_data["close"]
        drawdown = ma_data["drawdown_from_high"]

        # ===== 次日潜力核心条件（风格自适应双模式）=====
        near_ma20_support = ma_data.get("near_ma20", False)
        breakout_platform = ma_data.get("breakout_platform", False)
        is_positive = ma_data.get("is_positive_candle", True)
        is_short_shadow = ma_data.get("is_short_upper_shadow", True)
        kline_ok = is_positive and is_short_shadow
        vol_sustained = ma_data["vol_up"]
        vol_continuous = ma_data.get("vol_3d_avg", 1.0) >= 1.5
        vol_accel = ma_data.get("vol_accelerating", False)
        vol_ok = vol_continuous or vol_accel

        if is_momentum:
            # ── 强动量模式：追涨强势股 ──
            # ① 站上MA20（趋势向上确认）
            # ② 价格在近20日高点附近（<5%，即创近高）
            # ③ 量能放大 + 阳线
            above_ma20 = ma_data.get("above_ma20", False)
            near_high20 = drawdown <= 5  # 距20日高点不超过5%，接近新高
            ma_ok_momentum = above_ma20 and ma_data.get("ma20_above_ma60", False)
            not_at_top = True  # 动量模式不限制位置高低
            ma_ok = ma_ok_momentum
            volume_signal = vol_sustained and kline_ok
            is_potential = above_ma20 and volume_signal and (near_high20 or breakout_platform)

        elif is_weak_momentum:
            # ── 弱动量模式：中间模式，兼顾趋势和位置 ──
            # ① 在MA10上方或站上MA5（不要求MA20，弱动量市场标的可能还在MA20以下）
            # ② 回撤3%-12%（比吸筹模式宽松，比动量模式严格），或板块突破
            # ③ MA10>MA20（短期趋势向上）
            above_ma5  = ma_data.get("above_ma5", False)
            above_ma10 = ma_data.get("above_ma10", False)
            ma5_above_ma10 = ma_data.get("ma5_above_ma10", False)
            # 回撤3%-12%为核心区间（弱动量市场优质标的回撤不大也不过低）
            not_at_top = (3 <= drawdown <= 12) or breakout_platform or (drawdown >= 5 and near_ma20_support)
            ma_ok = (above_ma10 or ma_data.get("just_broke_ma5", False)) and (ma5_above_ma10 or ma_data.get("above_ma20", False))
            volume_signal = vol_ok or vol_sustained
            is_potential = not_at_top and ma_ok and volume_signal and kline_ok

        else:
            # ── 吸筹模式：低位量能异动 ──
            # 1. 非高位判断
            not_at_top = (drawdown >= 8) or (drawdown >= 3 and near_ma20_support) or breakout_platform
            # 2. 均线支撑或突破
            ma_ok = ma_data["above_ma5"] or ma_data["just_broke_ma5"]
            # 3. 量能
            volume_signal = vol_sustained or vol_ok
            is_potential = not_at_top and ma_ok and volume_signal and kline_ok

        # 6. 相对换手率评分（v3.3新增）
        # 用行业中位数归一化，消除行业本身活跃度差异
        # relative_turnover = 个股换手率 / 行业中位数换手率
        #   > 2.0 → 个股异动明显（主力主动介入）→ 高分
        #   0.8~2.0 → 正常范围
        #   < 0.5 → 个股沉寂，可能只是板块普涨带动 → 扣分
        turnover = float(row["turnover"])
        industry_name_for_t = row.get("industry", "")
        ind_median_t = industry_turnover_mean.get(industry_name_for_t, 0.0)
        if ind_median_t > 0:
            relative_turnover = turnover / ind_median_t
            if relative_turnover >= 2.0:
                turnover_score = 1.0   # 异动显著
            elif relative_turnover >= 1.2:
                turnover_score = 0.8   # 略高于均值
            elif relative_turnover >= 0.8:
                turnover_score = 0.65  # 接近均值
            else:
                turnover_score = 0.4   # 低于均值，随大流
        else:
            # 行业样本不足时，回退到绝对阈值评分
            relative_turnover = 1.0
            if 5 <= turnover <= 8:
                turnover_score = 1.0
            elif 3 <= turnover < 5:
                turnover_score = 0.8
            else:
                turnover_score = 0.6

        # 7. 主力资金（评分项，不做硬过滤）
        main_inflow = float(row["main_net_inflow"])
        has_inflow = main_inflow > 0

        # 涨停基因加分项
        has_gene = ma_data["has_limit_up_gene"]

        if not not_at_top:
            cnt_drawdown += 1
        elif not ma_ok:
            cnt_ma += 1
        elif not vol_ok and not is_momentum:
            cnt_vol_weak += 1

        if not is_potential:
            continue

        # 走势标签
        if row["is_limit_up"]:
            trend = "涨停量能启动"
        elif ma_data["just_broke_ma5"] and drawdown >= 10:
            trend = "低位突破MA5"
        elif ma_data["just_broke_ma5"]:
            trend = "突破MA5放量"
        elif has_gene and drawdown >= 10:
            trend = "涨停基因低位吸筹"
        else:
            trend = "量能吸筹启动"

        # 预计持有天数（基于波动率和距目标价距离）
        upside_pct = (ma_data["target_price"] - close) / close * 100
        if upside_pct >= 6:
            hold_days_est = 2
        elif upside_pct >= 3:
            hold_days_est = 1
        else:
            hold_days_est = 1

        # 综合评分（风格自适应权重）
        # 资金流归一化：1000万为满分100
        inflow_score = min(abs(main_inflow) / 100, 100) if has_inflow else 0

        is_sharp_drop = ma_data.get('is_sharp_drop', False)

        # ── 回撤评分（修复：>20%应重扣，牛市创新高股回撤极低应给满分）──
        if is_momentum:
            # 动量模式：回撤越小越好（强势股），反向评分
            if drawdown <= 3:
                drawdown_score = 100   # 创近高，强势
            elif drawdown <= 8:
                drawdown_score = 100 - (drawdown - 3) / 5 * 30   # 70~100
            elif drawdown <= 15:
                drawdown_score = 70 - (drawdown - 8) / 7 * 40    # 30~70
            else:
                drawdown_score = max(30 - (drawdown - 15) / 10 * 30, 0)
        elif is_weak_momentum:
            # 弱动量模式：回撤曲线左移2%，3-12%为满分区间（适配小幅回调的优质标的）
            if is_sharp_drop and drawdown >= 5:
                drawdown_score = 100
            elif 3 <= drawdown <= 12:
                drawdown_score = 100   # 弱动量市场优质标的的核心回撤区间
            elif 1 <= drawdown < 3:
                drawdown_score = 40 + (drawdown - 1) / 2 * 60     # 位置偏高，适度扣分
            elif 12 < drawdown <= 18:
                drawdown_score = 100 - (drawdown - 12) / 6 * 50   # 50~100
            elif 18 < drawdown <= 28:
                drawdown_score = max(50 - (drawdown - 18) / 10 * 50, 0)
            elif drawdown > 28:
                drawdown_score = 0
            else:
                drawdown_score = max(drawdown / 3 * 40, 0)
        else:
            # 吸筹模式：8-15%满分，<5%扣分，>20%重扣（趋势可能已坏）
            if is_sharp_drop and drawdown >= 8:
                drawdown_score = 100
            elif 8 <= drawdown <= 15:
                drawdown_score = 100
            elif 5 <= drawdown < 8:
                drawdown_score = 50 + (drawdown - 5) / 3 * 50
            elif 15 < drawdown <= 20:
                drawdown_score = 100 - (drawdown - 15) / 5 * 50   # 50~100
            elif 20 < drawdown <= 30:
                drawdown_score = max(50 - (drawdown - 20) / 10 * 50, 0)  # 0~50 重扣
            elif drawdown > 30:
                drawdown_score = 0   # 跌了30%以上，基本趋势已坏，不予评分
            else:
                drawdown_score = max(drawdown / 5 * 50, 0)

        # ── 量比归一化（修复：对数曲线，避免高量比虚高）──
        # 使用 log2 映射：量比1→0分，量比2→50分，量比4→100分
        import math
        vr = float(row["volume_ratio"])
        if vr <= 1.0:
            volume_ratio_score = 0
        elif vr >= 4.0:
            volume_ratio_score = 100
        else:
            volume_ratio_score = min(math.log2(vr) / math.log2(4) * 100, 100)

        # 换手率已经是0-1分数，转为0-100
        turnover_norm = turnover_score * 100

        # 逆势抗跌归一化（5%相对强度为满分100）
        counter_trend_score = min(ma_data.get("counter_trend_resistance", 0.0) / 5 * 100, 100)

        # 板块热度归一化（0-100）
        sector_score = hot_sectors.get(row.get("industry", ""), 0) if hot_sectors else 0

        # 技术形态加分
        pattern_bonus = 0
        if ma_data.get("breakout_platform", False):
            pattern_bonus += 5
        if ma_data.get("volume_wash", False):
            pattern_bonus += 5
        # v3.3新增：尾盘强势加分（尾盘收盘价高于典型价，说明尾盘护盘/吸筹）
        eod_strong = ma_data.get("eod_strong", False)
        close_vs_vwap = ma_data.get("close_vs_vwap", 0.0)
        if eod_strong:
            # 偏离越大说明尾盘拉升越强：0.3%加3分，1%加5分（满值）
            eod_bonus = min(int(close_vs_vwap / 0.3) * 1.5, 5)
            pattern_bonus += eod_bonus
        pattern_score = min(pattern_bonus, 15) / 15 * 100  # 调整满分到15分（加入尾盘信号后）

        # ── Wyckoff 筹码结构评分（0-100）──
        wyckoff_score = ma_data.get("wyckoff_score", 0.0)

        # ── 板块资金流加速评分（0-100）──
        # 加速度比 ≥ 2.0 满分，1.5~2.0 线性插值，< 1.0 为0分
        industry_name = row.get("industry", "")
        accel_ratio = sector_accel.get(industry_name, 0.0)
        if accel_ratio >= 2.0:
            accel_score = 100
        elif accel_ratio >= 1.0:
            accel_score = (accel_ratio - 1.0) / 1.0 * 100
        else:
            accel_score = 0.0

        # 宏观防御期：压缩加速分权重（防御时减少追涨板块敞口）
        if macro_mode == 'defensive':
            accel_score = accel_score * 0.3  # 防御期加速分打3折

        # ── 动量/弱动量/吸筹模式权重不同 ──
        if is_momentum:
            # 强动量模式：趋势强度优先，量比次之，资金流重要，回撤权重降低
            score = (
                volume_ratio_score * 0.15 +   # 量比 15%
                drawdown_score     * 0.10 +   # 回撤 10%（创新高才是好信号）
                inflow_score       * 0.20 +   # 资金流 20%
                turnover_norm      * 0.05 +   # 换手率 5%
                sector_score       * 0.20 +   # 板块热度 20%
                pattern_score      * 0.05 +   # 技术形态 5%
                counter_trend_score* 0.05 +   # 逆势抗跌 5%
                wyckoff_score      * 0.10 +   # Wyckoff筹码结构 10%
                accel_score        * 0.10     # 板块资金加速 10%
            )
        elif is_weak_momentum:
            # 弱动量模式：Wyckoff + 板块加速 更重要
            score = (
                volume_ratio_score * 0.15 +   # 量比 15%
                drawdown_score     * 0.12 +   # 回撤 12%
                inflow_score       * 0.18 +   # 资金流 18%
                turnover_norm      * 0.05 +   # 换手率 5%
                sector_score       * 0.15 +   # 板块热度 15%
                pattern_score      * 0.05 +   # 技术形态 5%
                counter_trend_score* 0.05 +   # 逆势抗跌 5%
                wyckoff_score      * 0.15 +   # Wyckoff筹码结构 15%（弱动量最重要）
                accel_score        * 0.10     # 板块资金加速 10%
            )
        else:
            # 吸筹模式：量比回撤优先，Wyckoff重要
            score = (
                volume_ratio_score * 0.22 +   # 量比 22%
                drawdown_score     * 0.22 +   # 回撤 22%
                inflow_score       * 0.12 +   # 资金流 12%
                turnover_norm      * 0.04 +   # 换手率 4%
                sector_score       * 0.15 +   # 板块热度 15%
                pattern_score      * 0.02 +   # 技术形态 2%
                counter_trend_score* 0.03 +   # 逆势抗跌 3%
                wyckoff_score      * 0.12 +   # Wyckoff筹码结构 12%
                accel_score        * 0.08     # 板块资金加速 8%
            )
        score = min(score, 100)  # 基础分最高100分

        # ── 消息面加分（D+A方案，叠加在基础分上，不受100分上限限制）──
        industry = row.get("industry", "")

        # 方案A：AI新闻板块加分（-20到+30）
        news_sector_boost = sector_news_boosts.get(industry, 0.0)

        # 方案D：概念板块热度加分（0到+10）
        concept_boost = 0.0
        from news_analyzer import INDUSTRY_CONCEPT_KEYWORDS
        industry_kws = INDUSTRY_CONCEPT_KEYWORDS.get(industry, [])
        for concept_item in hot_concepts[:10]:
            if industry_kws and any(kw in concept_item["concept"] for kw in industry_kws):
                concept_boost = concept_item["heat"] * 0.1  # heat(0-100) → boost(0-10)
                break

        # 最终分数：基础分 + 消息面（最高130分，最低不限）
        final_score = score + news_sector_boost + concept_boost
        # caution状态：额外-10分惩罚，等效提高准入门槛，只留高确定性标的
        if is_caution:
            final_score -= 10
        final_score = max(0, min(final_score, 130))

        # ── 状态机评分门槛过滤（Regime Filter 核心拦截）──
        # BEAR_BOUNCE 状态下门槛=75，大幅过滤低质量信号
        # BULL_PULLBACK 状态下门槛=60，适度过滤
        # 此处在 append 之前过滤，避免低分垃圾股进入候选池
        if final_score < score_threshold:
            continue

        # ── 状态机ATR止损修正（熊市收紧止损空间）──
        # 原 atr_stop_loss = close - 1.5×ATR，熊市改为 close - atr_multiplier×ATR
        base_atr    = ma_data.get('atr_14', 0.0)
        adj_stop    = round(ma_data['close'] - atr_multiplier * base_atr, 2)
        # 合理性修正：止损不低于-20%，不高于-0.7%
        adj_stop    = max(adj_stop, round(ma_data['close'] * 0.80, 2))
        adj_stop    = min(adj_stop, round(ma_data['close'] * 0.993, 2))
        # 用修正后的止损替换原ATR止损（熊市止损更紧）
        atr_stop_final = adj_stop

        hot_concept_match = concept_boost > 0

        valid_stocks.append({
            "code": row["code"],
            "name": row["name"],
            "industry": row["industry"],
            "close": close,
            "change": round(float(row["change"]), 2),
            "turnover": round(float(row["turnover"]), 2),
            "relative_turnover": round(relative_turnover, 2),   # v3.3新增：相对行业换手率倍数（>2=个股异动）
            "volume_ratio": round(float(row["volume_ratio"]), 2),
            "main_net_inflow": round(float(row["main_net_inflow"]), 2),
            "is_limit_up": bool(row["is_limit_up"]),
            "has_limit_up_gene": has_gene,
            "drawdown_from_high": ma_data["drawdown_from_high"],
            "target_price": ma_data.get("atr_target", ma_data["target_price"]),   # 优先ATR目标价
            "stop_loss_price": atr_stop_final,  # 状态机修正后ATR止损（BEAR_BOUNCE时更紧）
            "atr_14": ma_data.get("atr_14", 0.0),
            "wyckoff_score": round(wyckoff_score, 1),
            "accel_score": round(accel_score, 1),
            "volatility": ma_data["volatility"],
            "hold_days_est": hold_days_est,
            "trend": trend,
            "data_date": trade_date,
            "score": round(final_score, 2),       # 消息面叠加后的最终评分
            "score_base": round(score, 2),         # 纯技术面基础分（调试用）
            "news_boost": round(news_sector_boost, 1),   # 消息面加分（方案A）
            "concept_boost": round(concept_boost, 1),    # 概念热度加分（方案D）
            "hot_concept_match": hot_concept_match,
            # 技术指标（AI分析需要）
            "ma5": ma_data["ma5"],
            "ma10": ma_data["ma10"],
            "ma20": ma_data.get("ma20"),
            "ma60": ma_data.get("ma60"),
            "high20": ma_data["high20"],
            "low20": ma_data["low20"],
            # 尾盘信号（v3.3新增）
            "eod_strong": ma_data.get("eod_strong", False),          # 尾盘强势（VWAP代理法）
            "close_vs_vwap": ma_data.get("close_vs_vwap", 0.0),      # 收盘相对典型价偏离%
            # 财务数据（方案B新增）
            "roe": round(fin_data.get('roe', 0), 2) if fin_data.get('roe') else None,
            "revenue_growth": round(fin_data.get('revenue_growth', 0), 2) if fin_data.get('revenue_growth') else None,
            "debt_ratio": round(fin_data.get('debt_ratio', 0), 2) if fin_data.get('debt_ratio') else None,
        })

    df_pool = pd.DataFrame(valid_stocks)
    if not df_pool.empty:
        # 排序优化：按综合评分排序
        df_pool = df_pool.sort_values(
            by=["score"],
            ascending=[False]
        ).head(20).reset_index(drop=True)

    logger.info(
        f"📊 短线过滤明细：基础候选{len(st)}只 | "
        f"无MA数据{cnt_no_ma} | 高位{cnt_drawdown} | 均线不符{cnt_ma} | 量能不足{cnt_vol_weak} | 财务不符{cnt_financial}"
    )
    logger.info(f"✅ 次日潜力筛选完成：{len(df_pool)}只（数据日期：{trade_date}）")
    return df_pool


def select_longterm_pool(
    stocks: pd.DataFrame,
    ma_dict: Dict,
    trade_date: str,
    financial_dict: Dict = None,
    sector_ma10: Dict = None,
    hot_sectors: Dict = None,
    industry_rs: Dict = None,
    profit_growth_dict: Dict = None,
    regime: str = 'BULL_TREND',
) -> pd.DataFrame:
    """
    波段选股 v4.0（中长线，持仓无固定时限，以技术信号为准）。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    设计依据：
      - Jegadeesh & Titman (1993)：2-12月动量因子在A股有效
      - Liu/Stambaugh/Yuan (2019)：换手率因子（A股特有）
      - O'Shaughnessy：相对强度排名用于选股
      - Minervini VCP 概念：价格从高点适度回落，量能收缩后放量突破
      - Weinstein四阶段（A股改版）：用MA60代替MA150判断第二阶段
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    5维评分体系（总分100）：
      ① 价格动量     30% —— 60日涨幅相对排名 + MA60斜率强度
      ② 资金流       25% —— 主力净流入强度 + 近期成交量趋势
      ③ 行业相对强度 20% —— 行业20日RS超额收益（industry_rs）
      ④ 财务质量     15% —— ROE + 净利润同比增速（netprofit_yoy）+ 增速加速
      ⑤ 入场质量     10% —— 回调幅度适中 + 量能收缩 + 尾盘强势（eod_strong）

    硬过滤条件（任意一条不满足即淘汰）：
      - 状态机：仅在 BULL_TREND / BULL_PULLBACK 时执行
      - 趋势确认：MA20 > MA60（短期均线站上长期均线）
      - MA60斜率：> 0（长期上升趋势，非熊市反弹）
      - 60日RS排名：> 全池第40百分位（动量因子硬门槛）
      - 行业RS：> -5%（不选持续跑输大盘的行业）
      - 距60日高点回调：5% ~ 35%（太浅=没洗盘，太深=趋势受损）
      - 止损空间：MA60需在当前价下方 5% 以内（止损有支撑）

    退出信号（输出字段，由调用方/回测引擎使用）：
      - stop_loss_price = MA60 × 0.98（跌破MA60止损）
      - trailing_stop_pct = 10%（峰值回撤10%移动止损，需+25%后才激活）
      - target_price = 60日高点 × 1.05（目标位：突破前高后再涨5%）
    """
    if stocks.empty:
        return pd.DataFrame()

    # 波段策略只在牛市状态开仓
    if regime not in ('BULL_TREND', 'BULL_PULLBACK',
                       'BULL_PULLBACK_OVERRIDE'):
        logger.info(f"📊 波段选股跳过（当前机制：{regime}，仅牛市执行）")
        return pd.DataFrame()

    if financial_dict is None:
        financial_dict = {}
    if industry_rs is None:
        industry_rs = {}
    if profit_growth_dict is None:
        profit_growth_dict = {}

    # ── 预计算全池动量代理，用于排名过滤 ──
    # 波段动量代理：用 ma20_slope（近5日均线斜率）+ 回调幅度反向（回调少=动量强）
    # 注意：正在回调的股票 ma20_slope 为负数是正常的（短线向下但长线向上），
    # 因此 P40 过滤门槛不使用绝对值，而是相对全池排名，且使用 P20 宽松门槛
    momentum_scores_raw = {}
    for ts_code, mdata in ma_dict.items():
        # 动量代理：MA20斜率（反映近期趋势方向）
        # 在波段候选池中，即使是负斜率（回调中）也可入选，只过滤最弱的20%
        ma60_slope = mdata.get('ma20_slope', 0.0)
        momentum_scores_raw[ts_code] = ma60_slope

    # P20 宽松门槛（只排除最弱的20%，不过严）
    if momentum_scores_raw:
        vals = sorted(momentum_scores_raw.values())
        n_total = len(vals)
        p20_threshold = vals[int(n_total * 0.20)] if n_total >= 5 else -999
    else:
        p20_threshold = -999

    valid_stocks = []
    cnt_no_ma    = 0
    cnt_trend    = 0  # MA趋势不符
    cnt_momentum = 0  # 动量排名不足
    cnt_drawdown = 0  # 回调幅度不符
    cnt_industry = 0  # 行业RS不符
    cnt_fin      = 0  # 财务不符
    cnt_support  = 0  # MA60支撑不够近

    for _, row in stocks.iterrows():
        code     = row["code"]
        ts_code  = format_code(code)
        ma_data  = ma_dict.get(ts_code)
        if not ma_data:
            cnt_no_ma += 1
            continue

        close     = ma_data["close"]
        ma20      = ma_data.get("ma20")
        ma60      = ma_data.get("ma60")
        ma20_slope = ma_data.get("ma20_slope", 0.0)  # 近5日MA20斜率（%/日）

        if ma20 is None or ma60 is None:
            cnt_no_ma += 1
            continue

        # ── 硬过滤①：MA20 > MA60（短线站上长线，趋势结构完整）──
        # 【修复】移除 ma20_slope > 0 的硬过滤：
        # 波段策略的核心是在回调中入场，回调期间 MA20 斜率自然为负，
        # 强制要求斜率正值会把所有正在回调的优质标的都排除掉。
        # 趋势方向由 MA20>MA60（黄金交叉仍有效）来保证，不需要额外斜率约束。
        if not ma_data.get("ma20_above_ma60", False):
            cnt_trend += 1
            continue
        if ma60 <= 0:
            cnt_trend += 1
            continue

        # ── 硬过滤②：动量排名过滤（只排除最弱的20%，宽松门槛）──
        # 【修复】原来用 P40 门槛，且 MA20 斜率负数股票天然低于 P40，等于双重排除回调股。
        # 改为 P20，只排除动量极端弱的股票（MA20 连 P20 都不到 = 几乎全市场最弱）。
        stock_momentum = momentum_scores_raw.get(ts_code, -999)
        if stock_momentum < p20_threshold:
            cnt_momentum += 1
            continue

        # ── 硬过滤③：回调幅度（从20日高点的跌幅）──
        # drawdown_from_high 正数=已回调（8.0=距高点跌了8%），负数=创新高（-2.0=超过高点2%）
        # 只保留上限：超过30%说明趋势结构可能受损；突破新高（<0）正常入选
        drawdown = ma_data.get("drawdown_from_high", 0.0)
        if drawdown > 30.0:
            # 超过30%回调：长期趋势可能已破坏，不宜做波段
            cnt_drawdown += 1
            continue

        # ── 硬过滤④：行业RS > -8%（不选严重跑输大盘的行业）──
        # 【修复】从 -5% 放宽到 -8%，允许轻微跑输行业的个股强势股入选
        industry = row.get("industry", "")
        if industry_rs:
            rs_val = industry_rs.get(industry, 0.0)
            if rs_val < -8.0:
                cnt_industry += 1
                continue

        # ── 硬过滤⑤：MA60支撑有效（价格不能离MA60太远）──
        price_vs_ma60 = (close - ma60) / ma60 * 100
        if price_vs_ma60 > 30.0:
            # 价格高于MA60超过30%：止损位过远，风险收益比极差
            cnt_support += 1
            continue

        # ── 财务过滤（波段策略：ROE >= 0 即可，不要求盈利增长）──
        fin_data = financial_dict.get(code, {})
        roe = fin_data.get('roe')
        debt_ratio = fin_data.get('debt_ratio')
        if roe is not None and roe < 0:
            # 波段策略不选持续亏损股（ROE < 0）
            cnt_fin += 1
            continue
        if debt_ratio is not None and debt_ratio > config.MAX_DEBT_RATIO:
            cnt_fin += 1
            continue

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ── 5维评分体系 ──
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        # ─ ① 价格动量评分（30分） ─
        # 子维度A：MA20斜率强度（日均涨幅 0.5%=满分）
        slope_score = max(0.0, min(ma20_slope / 0.5, 1.0)) * 60  # 最高60分，负斜率=0分而非负分
        # 子维度B：行业RS排名加分（行业RS越高，动量分越高）
        rs_bonus = 0.0
        if industry_rs:
            rs_val_m = industry_rs.get(industry, 0.0)
            rs_bonus = min(max(rs_val_m / 10.0, -1.0), 1.0) * 40  # ±4%→±40分
        momentum_score = max(0.0, min(slope_score + rs_bonus, 100.0))
        dim_momentum = momentum_score * 0.30

        # ─ ② 资金流评分（25分） ─
        main_net_inflow = float(row.get("main_net_inflow", 0))
        # 主力净流入相对于成交额（归一化）
        # 用换手率作分母代理，>0=主力流入，<0=主力流出
        # 以500万为1分、1亿为满分的对数缩放
        if main_net_inflow > 0:
            flow_score = min(100.0, max(0.0, (main_net_inflow / 1000) ** 0.5 * 10))
        elif main_net_inflow < 0:
            flow_score = max(0.0, 50 + main_net_inflow / 500)
        else:
            flow_score = 50.0
        # 量能趋势加分：今日量 > 5日均量且不过热
        vol_accel = ma_data.get("vol_accelerating", False)
        eod_strong = ma_data.get("eod_strong", False)
        if eod_strong:
            flow_score = min(flow_score + 15, 100)
        elif vol_accel:
            flow_score = min(flow_score + 8, 100)
        dim_flow = flow_score * 0.25

        # ─ ③ 行业相对强度评分（20分） ─
        rs_raw = industry_rs.get(industry, 0.0) if industry_rs else 0.0
        # RS区间：-15%~+15% → 0~100分
        rs_score = min(100.0, max(0.0, (rs_raw + 15) / 30 * 100))
        dim_rs = rs_score * 0.20

        # ─ ④ 财务质量评分（15分） ─
        fin_score = 50.0  # 默认中性
        roe_val = fin_data.get('roe')
        if roe_val is not None:
            # ROE：>15%满分，5~15%线性，<5%低分
            if roe_val >= 15:
                roe_score = 100.0
            elif roe_val >= 5:
                roe_score = 50 + (roe_val - 5) / 10 * 50
            elif roe_val >= 0:
                roe_score = roe_val / 5 * 50
            else:
                roe_score = 0.0
            fin_score = roe_score

        # 净利润增速加分
        profit_data = profit_growth_dict.get(code, {})
        yoy = profit_data.get('netprofit_yoy')
        if yoy is not None:
            if yoy >= 30:
                fin_score = min(fin_score + 20, 100)
            elif yoy >= 15:
                fin_score = min(fin_score + 12, 100)
            elif yoy >= 0:
                fin_score = min(fin_score + 5, 100)
            else:
                fin_score = max(fin_score - 10, 0)
        # 增速加速额外奖励
        if profit_data.get('profit_growth_accel', False):
            fin_score = min(fin_score + 10, 100)
        dim_fin = fin_score * 0.15

        # ─ ⑤ 入场质量评分（10分） ─
        # 回调适中：5~15%回调最佳（VCP甜蜜区）
        drawdown_abs = abs(drawdown)  # 正数化
        if 5 <= drawdown_abs <= 15:
            pullback_score = 100.0
        elif drawdown_abs < 5:
            pullback_score = drawdown_abs / 5 * 60      # 回调不足，扣分
        elif drawdown_abs <= 25:
            pullback_score = max(0, 100 - (drawdown_abs - 15) * 5)  # 超出15%开始扣
        else:
            pullback_score = max(0, 100 - (drawdown_abs - 15) * 8)

        # 量能收缩加分（健康回调特征）
        vol_shrinking = not ma_data.get("vol_trend_up", False)
        entry_score = pullback_score
        if vol_shrinking:
            entry_score = min(entry_score + 15, 100)
        if eod_strong:
            entry_score = min(entry_score + 10, 100)
        if ma_data.get("is_positive_candle", False):
            entry_score = min(entry_score + 8, 100)
        if ma_data.get("wyckoff_score", 0) >= 60:
            entry_score = min(entry_score + 7, 100)
        dim_entry = entry_score * 0.10

        # ── 综合评分 ──
        longterm_score = round(dim_momentum + dim_flow + dim_rs + dim_fin + dim_entry, 1)

        # ── 出场价格计算 ──
        high20     = ma_data.get("high20", close * 1.15)
        atr_14     = ma_data.get("atr_14", close * 0.02)
        # 目标价：设为前高×1.5，相当于兜底止盈约+50%（波段策略以移动止损为主要退出机制）
        # 设高一点确保不会过早触发固定止盈，让持仓自然跑到移动止损激活（+25%后）
        target_price = round(max(high20 * 1.5, close * 1.50), 2)
        # 止损价：MA60下方2%（MA60跌破即止损）
        stop_loss_price = round(ma60 * 0.98, 2)
        # 买入区间：当前价 ± 1个ATR（限价单等待合理入场）
        buy_low  = round(close - atr_14 * 0.5, 2)
        buy_high = round(close + atr_14 * 0.3, 2)

        # 板块共振附加验证（不强制，仅记录）
        sector_aligned = True
        if sector_ma10:
            sector_aligned = sector_ma10.get(industry, True)

        valid_stocks.append({
            # ── 基础字段 ──
            "code":             code,
            "name":             row["name"],
            "industry":         industry,
            "close":            close,
            "change":           round(float(row.get("change", 0)), 2),
            "turnover":         round(float(row.get("turnover", 0)), 2),
            "volume_ratio":     round(float(row.get("volume_ratio", 1)), 2),
            "main_net_inflow":  round(main_net_inflow, 2),
            # ── 均线 ──
            "ma20":             round(ma20, 2),
            "ma60":             round(ma60, 2),
            "ma20_slope":       round(ma20_slope, 3),
            "price_vs_ma60":    round(price_vs_ma60, 1),
            # ── 动量 ──
            "drawdown_from_high": drawdown,
            "industry_rs":      round(rs_raw, 2),
            # ── 财务 ──
            "roe":              round(roe_val, 2) if roe_val is not None else None,
            "debt_ratio":       round(fin_data.get('debt_ratio', 0), 2) if fin_data.get('debt_ratio') else None,
            "netprofit_yoy":    round(yoy, 2) if yoy is not None else None,
            "profit_growth_accel": profit_data.get('profit_growth_accel', False),
            # ── 技术 ──
            "eod_strong":       eod_strong,
            "vol_shrinking":    vol_shrinking,
            "wyckoff_score":    ma_data.get("wyckoff_score", 0.0),
            "atr_14":           round(atr_14, 4),
            "high20":           high20,
            "low20":            ma_data.get("low20", close * 0.85),
            "volatility":       ma_data.get("volatility", 0.0),
            "sector_aligned":   sector_aligned,
            # ── 交易参数 ──
            "buy_price_low":    buy_low,
            "buy_price_high":   buy_high,
            "target_price":     target_price,
            "stop_loss_price":  stop_loss_price,
            "trailing_stop_pct": 10.0,    # 峰值回撤10%触发移动止损（需+25%后激活）
            # ── 评分明细 ──
            "longterm_score":   longterm_score,
            "score_momentum":   round(dim_momentum, 1),
            "score_flow":       round(dim_flow, 1),
            "score_rs":         round(dim_rs, 1),
            "score_fin":        round(dim_fin, 1),
            "score_entry":      round(dim_entry, 1),
            # ── 兼容旧字段（AI报告模板用）──
            "trend_strength":   round(min(ma20_slope / 0.5 * 100, 100), 2),
            "hold_weeks_est":   0,   # 波段策略无固定持仓周期，由技术信号决定
            "data_date":        trade_date,
        })

    # ── 按综合评分排序，输出Top20 ──
    df_pool = pd.DataFrame(valid_stocks)
    if not df_pool.empty:
        df_pool = df_pool.sort_values(
            by=["longterm_score", "main_net_inflow"],
            ascending=[False, False]
        ).head(20).reset_index(drop=True)

    logger.info(
        f"✅ 波段选股v4.0完成：{len(df_pool)}只 | "
        f"（数据{trade_date} | 过滤：无MA={cnt_no_ma}, "
        f"趋势={cnt_trend}, 动量={cnt_momentum}, 回调={cnt_drawdown}, "
        f"行业={cnt_industry}, 财务={cnt_fin}, 止损距离={cnt_support}）"
    )
    return df_pool


# ==================== AI接口封装 ====================
def call_ai_api(prompt: str, system: str = "") -> Optional[str]:
    if not prompt:
        return None

    api_key = config.AI_CONFIG["api_key"]
    if not api_key:
        logger.warning(
            "⚠️ 通义千问 API Key 未配置，跳过AI分析\n"
            "请在 config.py 中设置 DASHSCOPE_API_KEY，或设置环境变量 DASHSCOPE_API_KEY"
        )
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": config.AI_CONFIG["model"],
        "messages": messages,
        "temperature": config.AI_CONFIG["temperature"],
        "max_tokens": config.AI_CONFIG["max_tokens"]
    }
    try:
        response = requests.post(
            url=config.AI_CONFIG["base_url"],
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {api_key}"
            },
            json=payload,
            timeout=config.AI_CONFIG["timeout"]
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.Timeout:
        logger.error("❌ AI接口超时")
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ AI接口HTTP错误：{e}")
    except Exception as e:
        logger.error(f"❌ AI接口调用失败：{e}")
    return None


def parse_ai_json(result: str) -> Optional[List[Dict]]:
    if not result:
        return None
    # 先尝试直接解析
    try:
        parsed = json.loads(result)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    # 提取 JSON 数组片段
    m = re.search(r'\[[\s\S]*\]', result)
    if m:
        try:
            parsed = json.loads(m.group())
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    # 显示更多内容用于调试，但限制在1000字符内
    logger.error(f"❌ AI JSON解析失败（长度{len(result)}）：{result[:1000]}")
    return None


def ai_analyze_stock_pool(stock_pool: pd.DataFrame) -> List[Dict]:
    if stock_pool.empty:
        return []
    cols = ["code", "name", "industry", "close", "change", "volume_ratio",
            "main_net_inflow", "is_limit_up", "has_limit_up_gene",
            "ma5", "ma10", "ma20", "ma60", "high20", "low20",
            "drawdown_from_high", "target_price", "stop_loss_price",
            "volatility", "hold_days_est", "trend", "data_date",
            "roe", "revenue_growth", "debt_ratio"]  # 方案B：加入财务数据
    # 只取存在的列
    cols = [c for c in cols if c in stock_pool.columns]
    stock_list = json.dumps(stock_pool[cols].to_dict("records"), ensure_ascii=False)
    data_date = stock_pool['data_date'].iloc[0] if 'data_date' in stock_pool.columns else "未知"
    result = parse_ai_json(
        call_ai_api(
            prompt=ai_prompts.PROMPT_STOCK_ANALYSIS.format(
                stock_list=stock_list,
                data_date=data_date
            ),
            system=ai_prompts.SYSTEM_STOCK_ANALYST
        )
    )
    if not result or not isinstance(result, list):
        logger.warning("❌ AI分析结果无效")
        return []
    valid = []
    for r in result:
        if not all(k in r for k in ["code", "name", "score", "sentiment", "risk", "reason"]):
            continue
        # score 可能是 float，统一转 int
        try:
            r["score"] = int(float(r["score"]))
        except (ValueError, TypeError):
            r["score"] = 0
        valid.append(r)
    logger.info(f"✅ AI分析完成：{len(valid)}条有效建议")
    return valid


def ai_analyze_longterm(stock_pool: pd.DataFrame) -> List[Dict]:
    if stock_pool.empty:
        return []

    # 批量处理：每批最多10只股票，避免超时
    batch_size = 10
    all_results = []

    for i in range(0, len(stock_pool), batch_size):
        batch = stock_pool.iloc[i:i+batch_size]
        logger.info(f"📊 波段AI分析批次 {i//batch_size + 1}/{(len(stock_pool)-1)//batch_size + 1}（{len(batch)}只）")

        cols = ["code", "name", "industry", "close", "change", "volume_ratio",
                "main_net_inflow", "ma20", "ma60", "drawdown_from_high",
                "vol_shrinking", "buy_price_low", "buy_price_high",
                "target_price", "stop_loss_price", "hold_weeks_est", "data_date",
                "roe", "revenue_growth", "debt_ratio"]  # 方案B：加入财务数据
        cols = [c for c in cols if c in batch.columns]
        stock_list = json.dumps(batch[cols].to_dict("records"), ensure_ascii=False)
        data_date = batch['data_date'].iloc[0] if 'data_date' in batch.columns else "未知"

        result = parse_ai_json(
            call_ai_api(
                prompt=ai_prompts.PROMPT_LONGTERM_ANALYSIS.format(
                    stock_list=stock_list,
                    data_date=data_date
                ),
                system=ai_prompts.SYSTEM_STOCK_ANALYST
            )
        )

        if result and isinstance(result, list):
            all_results.extend(result)

    if not all_results:
        logger.warning("❌ 波段AI分析结果无效")
        return []

    valid = []
    for r in all_results:
        if not all(k in r for k in ["code", "name", "score", "sentiment", "risk", "reason"]):
            continue
        try:
            r["score"] = int(float(r["score"]))
        except (ValueError, TypeError):
            r["score"] = 0
        valid.append(r)
    logger.info(f"✅ 波段AI分析完成：{len(valid)}条有效建议")
    return valid


# ai_make_sell_decision 和 ai_review_trades 已删除（v2.2纯选股工具）


# ==================== 个股深度分析 ====================
def analyze_personal_stock(code: str, name: str, trade_date: str,
                          position_info: str, index_change: float,
                          limit_up_count: int) -> str:
    """
    个股深度分析：技术面+资金面+政策面
    """
    try:
        # 获取股票基本信息
        ts_code = format_code(code)
        stock_info = pro.stock_basic(ts_code=ts_code, fields='ts_code,name,industry')
        if stock_info.empty:
            return f"❌ 无法获取{code}的基本信息"

        industry = stock_info.iloc[0]['industry']

        # 获取最新行情
        time.sleep(0.5)
        df_price = pro.daily(ts_code=ts_code, trade_date=trade_date,
                            fields='ts_code,close,pct_chg,vol,amount')
        if df_price.empty:
            return f"❌ {code}在{trade_date}无行情数据"

        current_price = float(df_price.iloc[0]['close'])
        change = float(df_price.iloc[0]['pct_chg'])
        amount = float(df_price.iloc[0]['amount']) / 100000  # 转为亿元

        # 获取换手率和量比
        time.sleep(0.5)
        df_basic = pro.daily_basic(ts_code=ts_code, trade_date=trade_date,
                                   fields='turnover_rate,volume_ratio')
        turnover = float(df_basic.iloc[0]['turnover_rate']) if not df_basic.empty else 0
        volume_ratio = float(df_basic.iloc[0]['volume_ratio']) if not df_basic.empty else 1.0

        # 获取MA数据
        ma_dict = get_ma_data_batch([code], trade_date)
        ma_data = ma_dict.get(ts_code)

        if not ma_data:
            return f"❌ {code}技术指标计算失败"

        # 获取资金流
        time.sleep(0.5)
        mf_df = pro.moneyflow(ts_code=ts_code, trade_date=trade_date,
                             fields='net_mf_amount')
        main_net_inflow = float(mf_df.iloc[0]['net_mf_amount']) if not mf_df.empty else 0

        # 判断价格位置
        if ma_data['above_ma5'] and ma_data['above_ma10']:
            price_position = "强势（MA5/MA10上方）"
        elif ma_data['just_broke_ma5']:
            price_position = "突破MA5"
        elif ma_data['near_ma20']:
            price_position = "MA20附近"
        elif ma_data['above_ma20']:
            price_position = "MA20上方"
        else:
            price_position = "MA20下方（弱势）"

        # 生成操作建议
        if "持仓" in position_info:
            # 已持仓
            if "盈利" in position_info:
                action_suggestion = "持有/减仓/清仓"
                price_suggestions = "建议减仓价：{reduce_price}元\n建议止盈价：{take_profit_price}元\n建议止损价：{stop_loss_price}元"
            else:
                action_suggestion = "持有/止损"
                price_suggestions = "建议止损价：{stop_loss_price}元\n建议补仓价：{add_price}元（如果技术面转强）"
        else:
            # 关注股
            action_suggestion = "买入/观望"
            price_suggestions = "建议买入价：{buy_price}元\n建议止损价：{stop_loss_price}元"

        # 调用AI分析
        prompt = ai_prompts.PROMPT_PERSONAL_STOCK_ANALYSIS.format(
            code=code,
            name=name,
            industry=industry,
            current_price=current_price,
            data_date=trade_date,
            position_info=position_info,
            change=change,
            turnover=turnover,
            volume_ratio=volume_ratio,
            amount=round(amount, 2),
            ma5=ma_data['ma5'],
            ma10=ma_data['ma10'],
            ma20=ma_data.get('ma20', '-'),
            ma60=ma_data.get('ma60', '-'),
            price_position=price_position,
            drawdown=ma_data['drawdown_from_high'],
            has_limit_up="是" if ma_data['has_limit_up_gene'] else "否",
            volatility=ma_data['volatility'],
            main_net_inflow=main_net_inflow,
            vol_3d_avg=ma_data.get('vol_3d_avg', 1.0),
            vol_accelerating="是" if ma_data.get('vol_accelerating', False) else "否",
            index_change=index_change,
            limit_up_count=limit_up_count,
            action_suggestion=action_suggestion,
            price_suggestions=price_suggestions
        )

        result = call_ai_api(prompt=prompt, system=ai_prompts.SYSTEM_PERSONAL_ANALYST)
        return result or f"❌ {code} AI分析失败"

    except Exception as e:
        logger.error(f"❌ 分析{code}失败：{e}", exc_info=True)
        return f"❌ {code}分析出错：{str(e)}"


def analyze_watchlist_stock(code: str, name: str, target_price: float,
                            note: str, trade_date: str) -> str:
    """
    关注股票分析：判断是否到买入时机
    """
    try:
        ts_code = format_code(code)

        # 获取基本信息
        stock_info = pro.stock_basic(ts_code=ts_code, fields='ts_code,name,industry')
        if stock_info.empty:
            return f"❌ 无法获取{code}的基本信息"
        industry = stock_info.iloc[0]['industry']

        # 获取行情
        time.sleep(0.5)
        df_price = pro.daily(ts_code=ts_code, trade_date=trade_date,
                            fields='ts_code,close,pct_chg')
        if df_price.empty:
            return f"❌ {code}在{trade_date}无行情数据"

        current_price = float(df_price.iloc[0]['close'])
        change = float(df_price.iloc[0]['pct_chg'])

        # 获取换手率和量比
        time.sleep(0.5)
        df_basic = pro.daily_basic(ts_code=ts_code, trade_date=trade_date,
                                   fields='turnover_rate,volume_ratio')
        turnover = float(df_basic.iloc[0]['turnover_rate']) if not df_basic.empty else 0
        volume_ratio = float(df_basic.iloc[0]['volume_ratio']) if not df_basic.empty else 1.0

        # 获取MA数据
        ma_dict = get_ma_data_batch([code], trade_date)
        ma_data = ma_dict.get(ts_code)

        if not ma_data:
            return f"❌ {code}技术指标计算失败"

        # 获取资金流
        time.sleep(0.5)
        mf_df = pro.moneyflow(ts_code=ts_code, trade_date=trade_date,
                             fields='net_mf_amount')
        main_net_inflow = float(mf_df.iloc[0]['net_mf_amount']) if not mf_df.empty else 0

        # 判断价格位置
        if ma_data['above_ma5'] and ma_data['above_ma10']:
            price_position = "强势（MA5/MA10上方）"
        elif ma_data['near_ma20']:
            price_position = "MA20附近（支撑位）"
        else:
            price_position = "调整中"

        # 建议买入价和止损价
        ma20 = ma_data.get('ma20')
        if ma20:
            buy_low = round(ma20 * 0.98, 2)
            buy_high = round(ma20 * 1.02, 2)
            buy_price_range = f"{buy_low}-{buy_high}"
        else:
            buy_price_range = f"{round(current_price * 0.97, 2)}-{round(current_price * 1.01, 2)}"

        stop_loss_price = ma_data['stop_loss_price']

        # 调用AI分析
        prompt = ai_prompts.PROMPT_WATCHLIST_ANALYSIS.format(
            code=code,
            name=name,
            industry=industry,
            current_price=current_price,
            target_price=target_price,
            note=note,
            change=change,
            turnover=turnover,
            volume_ratio=volume_ratio,
            ma5=ma_data['ma5'],
            ma10=ma_data['ma10'],
            ma20=ma_data.get('ma20', '-'),
            ma60=ma_data.get('ma60', '-'),
            price_position=price_position,
            drawdown=ma_data['drawdown_from_high'],
            main_net_inflow=main_net_inflow,
            buy_price_range=buy_price_range,
            stop_loss_price=stop_loss_price
        )

        result = call_ai_api(prompt=prompt, system=ai_prompts.SYSTEM_PERSONAL_ANALYST)
        return result or f"❌ {code} AI分析失败"

    except Exception as e:
        logger.error(f"❌ 分析关注股{code}失败：{e}", exc_info=True)
        return f"❌ {code}分析出错：{str(e)}"


# ==================== 交易决策函数已删除（v2.2纯选股工具） ====================

# ==================== 核心选股流程（回测/实盘共用） ====================
def run_daily_selection(trade_date: str, enable_news: bool = True) -> Dict:
    """
    完整的单日选股流程，实盘和回测共用同一套逻辑。
    无论此函数怎么修改，调用方（main() 和 backtest_v2.py）都自动保持一致。

    Args:
        trade_date:   指定交易日期 YYYYMMDD（回测传历史日期，实盘传 None 或最新日期）
        enable_news:  是否拉取实时新闻（回测时传 False，节省时间且无意义）

    Returns:
        {
            'trade_date':     str,          实际数据日期
            'market_state':   str,          大盘状态 normal/rebound/downtrend
            'operation_mode': str,          操作模式 full/short_only/light/stop
            'position_advice':str,          仓位建议文字
            'sentiment_data': dict,         市场情绪数据
            'stock_pool':     pd.DataFrame, 短线候选股（已评分排序）
            'longterm_pool':  pd.DataFrame, 波段候选股
        }
    """
    result = {
        'trade_date':          trade_date,
        'market_state':        'normal',
        'market_style':        'sideways',
        'style_data':          {},
        'macro_mode':          'cautious',
        'macro_data':          {},
        'regime':              'BULL_TREND',   # 四状态机
        'regime_data':         {},
        'operation_mode':      'stop',
        'position_advice':     '未知',
        'position_multiplier': 1.0,            # 仓位乘数（0/0.33/0.67/1.0）
        'score_threshold':     45,             # 评分准入门槛
        'max_hold_days':       8,              # 最大持仓天数
        'atr_multiplier':      1.5,            # ATR止损系数
        'sentiment_data':      {},
        'stock_pool':          pd.DataFrame(),
        'longterm_pool':       pd.DataFrame(),
    }

    # ── 1. 基础候选池（同时拿到全市场 pct_chg，供后续步骤复用）──
    all_stocks, actual_date, _, market_pct_df = get_all_stocks(
        min_change=-3, max_change=6,
        min_turnover=3, max_turnover=12,
        trade_date=trade_date
    )
    result['trade_date'] = actual_date

    if all_stocks.empty:
        logger.warning(f"[{actual_date}] 基础候选池为空")
        return result

    # ── 2. 大盘技术面状态（复用全市场数据，不再重复拉取）──
    market_state, market_msg = check_market_risk(actual_date, market_pct_df)
    logger.info(f"📊 市场状态：{market_msg}")
    result['market_state'] = market_state

    # ── 2.5 市场风格检测（动量牛市 vs 震荡市）──
    logger.info("📊 检测市场风格（动量/震荡）...")
    market_style, style_data = get_market_style(actual_date)
    result['market_style'] = market_style
    result['style_data']   = style_data

    # ── 2.55 四状态市场机制判断（Regime Filter，防熊核心）──
    logger.info("📊 判断四状态市场机制（长期牛熊 × 短期方向）...")
    regime, regime_data = get_market_regime(actual_date)

    # ── 2.56 快速翻转检测（Override，解决MA60约30天滞后问题）──
    # 仅在 BEAR_TREND 时检测：当日微观结构（宽度/情绪/量能）出现极端信号时，
    # 临时将状态上调为 BEAR_BOUNCE_OVERRIDE 或 BULL_PULLBACK_OVERRIDE，
    # 允许极轻仓参与，避免踏空政策驱动的急速反转。
    # market_pct_df 已在步骤1获取，无需重复拉取。
    if regime == 'BEAR_TREND':
        logger.info("📊 BEAR_TREND检测到，运行快速翻转Override...")
        regime, override_info = check_regime_override(actual_date, regime, market_pct_df)
        # Override触发时，用Override参数覆盖状态机参数
        if override_info['triggered']:
            regime_data['position_multiplier'] = override_info['position_multiplier']
            regime_data['score_threshold']     = override_info['score_threshold']
            regime_data['max_hold_days']       = override_info['max_hold_days']
            # atr_multiplier 保持最保守值
            regime_data['atr_multiplier']      = config.REGIME_ATR_MULTIPLIER.get('BEAR_BOUNCE', 1.0)
            regime_data['override_triggered']  = True
            regime_data['override_score']      = override_info['score']
            regime_data['override_reasons']    = override_info['reasons']
        else:
            regime_data['override_triggered'] = False
    else:
        regime_data['override_triggered'] = False

    result['regime']              = regime
    result['regime_data']         = regime_data
    result['position_multiplier'] = regime_data['position_multiplier']
    result['score_threshold']     = regime_data['score_threshold']
    result['max_hold_days']       = regime_data['max_hold_days']
    result['atr_multiplier']      = regime_data['atr_multiplier']

    # BEAR_TREND（且Override未触发）：直接空仓，跳过所有后续选股流程
    if regime == 'BEAR_TREND':
        logger.warning(
            "🔴 BEAR_TREND（长期熊市+短期下跌，Override未触发）→ 强制空仓，跳过选股"
            f"（CSI300价格vsMA60={regime_data['price_vs_ma60_pct']:+.1f}%，"
            f"MA60斜率={regime_data['ma60_slope_pct']:+.4f}%/日）"
        )
        result['operation_mode']  = 'stop'
        result['position_advice'] = '空仓（熊市下跌阶段）'
        return result

    # ── 2.6 一级筛选：周线宏观方向（Elder三重滤网第一重）──
    logger.info("📊 判断周线宏观趋势（三级共振第一级）...")
    macro_mode, macro_data = get_weekly_macro_trend(actual_date)
    result['macro_mode'] = macro_mode
    result['macro_data'] = macro_data

    # ── 3. 技术指标批量计算 ──
    index_change = get_market_index(actual_date)
    if index_change < -1.5:
        logger.warning(f"⚠️ 大盘弱势（{index_change:.2f}%），建议降低仓位或观望")

    logger.info("📊 批量计算技术指标（短线+波段共用）...")
    ma_dict = get_ma_data_batch(all_stocks['code'].tolist(), actual_date, index_change)
    # ✅ 结果由 get_ma_data_batch 内部打印

    # ── 4. 板块共振 ──
    logger.info("📊 获取板块共振状态（申万一级行业指数MA10）...")
    sector_ma10 = get_sector_ma10_status(actual_date)
    if sector_ma10:
        above = sum(1 for v in sector_ma10.values() if v)
        logger.info(f"✅ 板块共振：{above}/{len(sector_ma10)} 个行业站上MA10")
    else:
        # 中转站无申万指数数据时，用个股MA10状态按行业聚合替代
        sector_ma10 = _compute_sector_ma10_from_stocks(all_stocks, ma_dict)
        if sector_ma10:
            above = sum(1 for v in sector_ma10.values() if v)
            logger.info(f"✅ 板块共振（个股聚合）：{above}/{len(sector_ma10)} 个行业站上MA10")

    # ── 5. 财务数据 ──
    logger.info("📊 批量获取财务数据（ROE、营收增长、负债率）...")
    financial_dict = get_financial_data_batch(all_stocks['code'].tolist(), trade_date=actual_date)
    # ✅ 结果由 get_financial_data_batch 内部打印

    # ── 6. 板块热度 + 市场情绪（复用全市场数据，不再重复拉取）──
    logger.info("📊 分析板块热度...")
    hot_sectors = get_hot_sectors_from_stocks(actual_date, all_stocks)

    # ── 6.1 二级筛选：板块资金流加速（三级共振第二级）──
    logger.info("📊 检测板块资金流加速度（三级共振第二级）...")
    sector_accel = get_sector_flow_acceleration(actual_date)

    sentiment_data = get_market_sentiment(actual_date, market_pct_df)

    # ── 6.5 消息面数据（D+A方案，回测时跳过网络请求）──
    if enable_news:
        # 6.5a 方案D：概念板块热度（akshare免费，失败静默）
        logger.info("📊 获取概念板块热度（方案D）...")
        hot_concepts = news_analyzer.get_hot_concepts()
        concept_industry_boosts = news_analyzer.build_concept_industry_boosts(hot_concepts)

        # 6.5b 方案A：AI解读新闻→板块映射
        logger.info("📰 获取政策新闻...")
        policy_news = news_analyzer.get_policy_news()
    else:
        hot_concepts = []
        concept_industry_boosts = {}
        policy_news = pd.DataFrame()

    ai_news_result = []
    if enable_news and not policy_news.empty:
        logger.info("🤖 AI解读新闻→板块映射（方案A）...")
        news_titles = policy_news['title'].tolist()[:15]
        ai_news_result = news_analyzer.ai_parse_news_to_sectors(news_titles, call_ai_api)

    # 构建行业消息面加分字典（AI板块加分 + 概念热度加分合并，AI优先）
    sector_news_boosts = news_analyzer.build_sector_boosts(ai_news_result)
    # 概念热度加分作为补充（已有AI加分的行业不叠加，避免双重计算）
    for industry, concept_boost in concept_industry_boosts.items():
        if industry not in sector_news_boosts:
            sector_news_boosts[industry] = concept_boost

    news_sentiment = news_analyzer.analyze_news_sentiment(policy_news, ai_news_result)

    # 打印消息面摘要
    if sector_news_boosts:
        pos_boosts = [(s, v) for s, v in sector_news_boosts.items() if v > 0]
        neg_boosts = [(s, v) for s, v in sector_news_boosts.items() if v < 0]
        pos_boosts.sort(key=lambda x: -x[1])
        neg_boosts.sort(key=lambda x: x[1])
        if pos_boosts:
            logger.info(f"📰 消息面利好：{' | '.join(f'{s}(+{v:.0f})' for s, v in pos_boosts[:3])}")
        if neg_boosts:
            logger.info(f"📉 消息面利空：{' | '.join(f'{s}({v:.0f})' for s, v in neg_boosts[:3])}")

    sentiment_data['news_sentiment'] = news_sentiment

    # ── 8. 综合决策 ──
    operation_mode, position_advice, reason = market_analyzer.get_market_decision(
        market_state, sentiment_data, news_sentiment, sector_news_boosts
    )
    logger.info(f"📊 综合决策：{operation_mode} | 仓位：{position_advice} | {reason}")
    sentiment_data['operation_mode'] = operation_mode
    sentiment_data['position_advice'] = position_advice
    sentiment_data['decision_reason'] = reason

    result['operation_mode']  = operation_mode
    result['position_advice'] = position_advice
    result['sentiment_data']  = sentiment_data

    # ── 9. 根据操作模式选股 ──
    if operation_mode == 'stop':
        logger.warning("⚠️ 停止选股，空仓观望")
        return result

    # caution状态：记录日志，选股继续但提高准入门槛（score额外-10惩罚）
    is_caution = (market_state == 'caution')
    if is_caution:
        logger.warning("⚠️ 大盘警戒期，仅选高确定性标的（分数门槛提高）")

    # 从状态机取本日有效参数
    score_threshold = result.get('score_threshold', 45)
    atr_multiplier  = result.get('atr_multiplier', 1.5)
    max_hold_days   = result.get('max_hold_days', 8)

    # BEAR_BOUNCE / Override状态额外警告
    if regime in ('BEAR_BOUNCE', 'BEAR_BOUNCE_OVERRIDE', 'BULL_PULLBACK_OVERRIDE'):
        override_flag = "（Override触发）" if regime_data.get('override_triggered') else ""
        regime_labels = {
            'BEAR_BOUNCE':             '🟠 BEAR_BOUNCE（长期熊市+短期反弹）',
            'BEAR_BOUNCE_OVERRIDE':    '⚡ BEAR_BOUNCE_OVERRIDE（熊市翻转信号）',
            'BULL_PULLBACK_OVERRIDE':  '⚡ BULL_PULLBACK_OVERRIDE（熊市强力翻转）',
        }
        logger.warning(
            f"{regime_labels.get(regime, regime)}{override_flag} → 极轻仓模式\n"
            f"   评分门槛≥{score_threshold}  ATR止损×{atr_multiplier}  最大持仓{max_hold_days}天"
        )

    # short_only / light / full 都执行短线选股
    logger.info(f"📊 执行短线选股（模式：{operation_mode}，风格：{market_style}，机制：{regime}）...")
    stock_pool = select_stock_pool(
        all_stocks, ma_dict, actual_date, financial_dict, sector_ma10, hot_sectors,
        sector_news_boosts=sector_news_boosts, hot_concepts=hot_concepts,
        market_style=market_style, is_caution=is_caution,
        sector_accel=sector_accel, macro_mode=macro_mode,
        score_threshold=score_threshold, atr_multiplier=atr_multiplier
    )
    result['stock_pool'] = stock_pool

    # ── 波段选股：在牛市（BULL_TREND / BULL_PULLBACK）时执行，不依赖 operation_mode ──
    # v4.0改动：从 operation_mode=='full' 改为 regime in BULL 系列
    # BULL_TREND 和 BULL_PULLBACK（含Override）都允许波段开仓，熊市状态跳过
    longterm_regime_allowed = regime in ('BULL_TREND', 'BULL_PULLBACK', 'BULL_PULLBACK_OVERRIDE')
    if longterm_regime_allowed:
        logger.info(f"📊 执行波段选股v4.0（机制：{regime}）...")

        # ── 关键修复：波段候选池必须使用宽泛的全市场过滤 ──
        # 短线候选池（all_stocks）已过滤涨跌幅-3%~6%、换手率3%~12%，
        # 会遗漏大量优质波段标的（回调中换手率只有1-2%，当日跌幅-5%的都被排除了）。
        # 波段策略本身的硬过滤（MA20>MA60、回调幅度、动量排名）负责精选，
        # 初始候选池只需保证基本流动性（成交额>2亿），不限日涨跌幅。
        logger.info("📊 获取波段宽泛候选池（不限日涨跌幅，换手率0.5%-50%）...")
        try:
            lt_stocks, _, _, _ = get_all_stocks(
                min_change=-15, max_change=15,      # 不限日涨跌幅（波段关注趋势，不关注单日）
                min_turnover=0.5, max_turnover=50,  # 回调期换手率可以很低
                min_volume_ratio=0,                  # 波段策略不要求今日放量（量能由评分模型判断）
                trade_date=actual_date
            )
            logger.info(f"  波段候选池：{len(lt_stocks)}只  短线池：{len(all_stocks)}只")
        except Exception as e_lt:
            logger.warning(f"波段候选池扩展失败，降级使用短线候选池：{e_lt}")
            lt_stocks = all_stocks

        # ── 为波段候选池中的新增股票补充MA技术指标 ──
        # 离线模式：get_ma_data_batch 读整块日期区间parquet，新增代码几乎无额外I/O成本
        # 在线模式：新增代码会触发API调用，但波段回测建议离线运行
        existing_ts = set(ma_dict.keys())
        new_lt_codes = [
            c for c in lt_stocks['code'].tolist()
            if format_code(c) not in existing_ts
        ]
        if new_lt_codes:
            logger.info(f"📊 补充计算波段新增候选股MA数据：{len(new_lt_codes)}只...")
            extra_ma = get_ma_data_batch(new_lt_codes, actual_date, index_change)
            ma_dict_lt = {**ma_dict, **extra_ma}
        else:
            ma_dict_lt = ma_dict

        # ① 行业RS（20日超额收益）
        industry_rs = get_industry_rs_scores(actual_date)

        # ② 净利润增速（fina_indicator.netprofit_yoy，离线模式读全量parquet，范围扩大几乎无额外成本）
        logger.info("📊 获取净利润增速（波段财务质量评分）...")
        profit_growth_dict = get_net_profit_growth_batch(
            lt_stocks['code'].tolist(), trade_date=actual_date
        )

        longterm_pool = select_longterm_pool(
            lt_stocks, ma_dict_lt, actual_date,
            financial_dict=financial_dict,   # 注：仅含短线候选股财务数据；波段新增股ROE=None时跳过财务过滤
            sector_ma10=sector_ma10,
            hot_sectors=hot_sectors,
            industry_rs=industry_rs,
            profit_growth_dict=profit_growth_dict,
            regime=regime,
        )
        result['longterm_pool'] = longterm_pool
    else:
        logger.info(f"📊 波段选股跳过（机制：{regime}，仅BULL_TREND/BULL_PULLBACK执行）")

    return result


# ==================== 主程序 ====================
def main():
    logger.info("===== 🚀 A股超短线AI选股助手启动 =====")
    start_time = datetime.now()

    logger.info("\n【📈 选股与AI分析】")
    ai_analysis = []
    ai_longterm = []

    # ── 调用统一选股流程（回测/实盘共用同一套逻辑）──
    sel = run_daily_selection(trade_date=None, enable_news=True)
    trade_date     = sel['trade_date']
    sentiment_data = sel['sentiment_data']
    stock_pool     = sel['stock_pool']
    longterm_pool  = sel['longterm_pool']
    macro_mode     = sel.get('macro_mode', 'cautious')
    macro_data     = sel.get('macro_data', {})

    # ── AI 分析 ──
    if not stock_pool.empty:
        ai_analysis = ai_analyze_stock_pool(stock_pool)
        # 把 stock_pool 的量化指标合并进 ai_analysis，供报告展示选股逻辑
        quant_map = stock_pool.set_index('code').to_dict('index')
        price_map = dict(zip(stock_pool['code'].astype(str), stock_pool['close']))
        score_map = dict(zip(stock_pool['code'].astype(str), stock_pool['score']))
        for item in ai_analysis:
            code = str(item.get('code', ''))
            item['close'] = price_map.get(code, 0)
            item['score'] = score_map.get(code, 0)
            # 合并量化字段
            qdata = quant_map.get(code, {})
            item['volume_ratio']      = qdata.get('volume_ratio', '-')
            item['drawdown_from_high']= qdata.get('drawdown_from_high', '-')
            item['main_net_inflow']   = qdata.get('main_net_inflow', 0)
            item['trend']             = qdata.get('trend', '')
            item['industry']          = qdata.get('industry', item.get('industry', ''))
            item['news_boost']        = qdata.get('news_boost', 0)
            item['concept_boost']     = qdata.get('concept_boost', 0)
            item['hot_concept_match'] = qdata.get('hot_concept_match', False)
            item['score_base']        = qdata.get('score_base', 0)
            # 新增字段
            item['wyckoff_score']     = qdata.get('wyckoff_score', '-')
            item['accel_score']       = qdata.get('accel_score', '-')
            item['atr_14']            = qdata.get('atr_14', '-')

    if not longterm_pool.empty:
        ai_longterm = ai_analyze_longterm(longterm_pool)
        quant_map_lt = longterm_pool.set_index('code').to_dict('index')
        price_map_lt = dict(zip(longterm_pool['code'].astype(str), longterm_pool['close']))
        buy_map_lt   = dict(zip(longterm_pool['code'].astype(str),
                                zip(longterm_pool['buy_price_low'], longterm_pool['buy_price_high'])))
        trend_map_lt = dict(zip(longterm_pool['code'].astype(str), longterm_pool['trend_strength']))
        for item in ai_longterm:
            code = str(item.get('code', ''))
            item['close'] = price_map_lt.get(code, 0)
            prices = buy_map_lt.get(code, (0, 0))
            item['buy_price_low']  = prices[0]
            item['buy_price_high'] = prices[1]
            item['trend_strength'] = trend_map_lt.get(code, 0)
            # 合并波段量化字段
            qdata = quant_map_lt.get(code, {})
            item['industry']          = qdata.get('industry', item.get('industry', ''))
            item['ma20']              = qdata.get('ma20', '-')
            item['ma60']              = qdata.get('ma60', '-')
            item['ma20_slope']        = qdata.get('ma20_slope', 0)
            item['drawdown_from_high']= qdata.get('drawdown_from_high', '-')
            item['main_net_inflow']   = qdata.get('main_net_inflow', 0)
            item['vol_shrinking']     = qdata.get('vol_shrinking', False)
            item['roe']               = qdata.get('roe')
            item['revenue_growth']    = qdata.get('revenue_growth')

    # 打印宏观趋势
    macro_label = {'active': '🟢 主动做多', 'cautious': '🟡 谨慎观望', 'defensive': '🔴 防御避险'}.get(macro_mode, macro_mode)
    logger.info(
        f"\n【🌍 三级共振宏观趋势】{macro_label}"
        f" | CSI300 vs MA100={macro_data.get('price_vs_ma100', 0):+.1f}%"
        f" | MA20斜率={macro_data.get('ma20_slope_pct', 0):+.3f}%/日"
    )

    # 打印四状态机信息
    regime      = sel.get('regime', 'BULL_TREND')
    regime_data = sel.get('regime_data', {})
    pos_mult    = sel.get('position_multiplier', 1.0)
    regime_label = {
        'BULL_TREND':    '🟢 牛市趋势',
        'BULL_PULLBACK': '🟡 牛市回调',
        'BEAR_BOUNCE':   '🟠 熊市反弹',
        'BEAR_TREND':    '🔴 熊市下跌',
    }.get(regime, regime)
    top_n_actual = max(1, round(3 * pos_mult)) if pos_mult > 0 else 0
    logger.info(
        f"\n【🛡️ 四状态市场机制】{regime_label}"
        f" | 仓位×{pos_mult}  实际开仓Top{top_n_actual}"
        f" | CSI300 vsMA60={regime_data.get('price_vs_ma60_pct', 0):+.1f}%"
        f" | MA60斜率={regime_data.get('ma60_slope_pct', 0):+.4f}%/日"
    )

    # 打印短线建议（取评分前3）
    logger.info("\n【🚀 短线建议 Top3（1-3天）】")
    short_top3 = sorted(ai_analysis, key=lambda x: x.get("score", 0), reverse=True)[:3]
    if short_top3:
        for item in short_top3:
            buy_low = round(item['close'] * 0.99, 2)
            buy_high = round(item['close'] * 1.01, 2)
            logger.info(
                f"  {item['code']} {item['name']} | AI分:{item.get('score', 0)} | 风险:{item['risk']}\n"
                f"    买入区间：{buy_low}-{buy_high}元  目标价：{item.get('target_price', '-')}元  "
                f"止损：{item.get('stop_loss_price', '-')}元\n"
                f"    理由：{item['reason']}"
            )
    else:
        logger.info("  暂无短线候选")

    # 打印波段建议（取评分前3）
    logger.info("\n【📊 波段建议 Top3（1-8周）】")
    long_top3 = sorted(ai_longterm, key=lambda x: x.get("trend_strength", 0), reverse=True)[:3]
    if long_top3:
        for item in long_top3:
            logger.info(
                f"  {item['code']} {item['name']} | 趋势强度:{item.get('trend_strength', 0)} | AI分:{item.get('score', 0)} | 风险:{item['risk']}\n"
                f"    买入区间：{item.get('buy_price_low', '-')}-{item.get('buy_price_high', '-')}元  "
                f"目标价：{item.get('target_price', '-')}元  止损：{item.get('stop_loss_price', '-')}元\n"
                f"    理由：{item['reason']}"
            )
    else:
        logger.info("  暂无波段候选")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"\n===== 🎯 完成 | 耗时：{elapsed:.1f}秒 =====")

    # 保存实盘选股记录（用于事后IC验证）
    _save_live_selections(trade_date, stock_pool, longterm_pool, sel.get('regime', 'BULL_TREND'))

    # 生成每日报告文件
    _write_daily_report(
        trade_date, ai_analysis, ai_longterm, sentiment_data,
        macro_mode=macro_mode, macro_data=macro_data,
        regime=sel.get('regime', 'BULL_TREND'),
        regime_data=sel.get('regime_data', {}),
        position_multiplier=sel.get('position_multiplier', 1.0),
    )


def _save_live_selections(trade_date: str, stock_pool: pd.DataFrame,
                          longterm_pool: pd.DataFrame, regime: str):
    """
    将每日实盘选股结果追加写入 data/live_selections.csv，
    供事后 IC 分析（用实际价格验证选股质量）。
    每行一只股票，strategy_type 区分短线/波段。
    """
    out_path = os.path.join("data", "live_selections.csv")
    rows = []

    # 短线候选
    for _, row in stock_pool.iterrows():
        rows.append({
            'select_date':      trade_date,
            'ts_code':          str(row.get('code', '')),
            'name':             row.get('name', ''),
            'industry':         row.get('industry', ''),
            'close':            row.get('close', 0),
            'score':            row.get('score', 0),
            'longterm_score':   '',
            'stop_loss_price':  row.get('stop_loss_price', ''),
            'target_price':     row.get('target_price', ''),
            'regime':           regime,
            'strategy_type':    'short',
        })

    # 波段候选
    for _, row in longterm_pool.iterrows():
        rows.append({
            'select_date':      trade_date,
            'ts_code':          str(row.get('code', '')),
            'name':             row.get('name', ''),
            'industry':         row.get('industry', ''),
            'close':            row.get('close', 0),
            'score':            row.get('longterm_score', row.get('score', 0)),
            'longterm_score':   row.get('longterm_score', ''),
            'stop_loss_price':  row.get('stop_loss_price', ''),
            'target_price':     row.get('target_price', ''),
            'regime':           regime,
            'strategy_type':    'longterm',
        })

    if not rows:
        return

    new_df = pd.DataFrame(rows)
    write_header = not os.path.exists(out_path)
    new_df.to_csv(out_path, mode='a', header=write_header, index=False, encoding='utf-8-sig')
    logger.info(f"📝 实盘记录已追加：{len(rows)} 条 → {out_path}")


def _write_daily_report(trade_date: str, ai_analysis: List[Dict], ai_longterm: List[Dict], sentiment_data: Dict = None, macro_mode: str = 'cautious', macro_data: Dict = None, regime: str = 'BULL_TREND', regime_data: Dict = None, position_multiplier: float = 1.0):
    report_path = os.path.join(config.REPORTS_DIR, f"report_{trade_date}.txt")

    def sep(char='─', n=60):
        return char * n + '\n'

    lines = [
        f"{'='*60}\n",
        f"  A股AI选股日报  {trade_date}\n",
        f"{'='*60}\n\n",
    ]

    # ── 一、市场综合分析 ──────────────────────────────────
    lines.append("【一、今日市场环境】\n")
    if sentiment_data:
        sentiment   = sentiment_data.get('sentiment', '未知')
        ratio       = sentiment_data.get('ratio', 0)
        limit_up    = sentiment_data.get('limit_up_count', 0)
        limit_down  = sentiment_data.get('limit_down_count', 0)
        news_sentiment  = sentiment_data.get('news_sentiment', {})
        position_advice = sentiment_data.get('position_advice', '未知')
        decision_reason = sentiment_data.get('decision_reason', '')

        # 情绪图示
        emotion_icon = {'高涨': '🟢', '正常': '🔵', '偏弱': '🟡', '恐慌': '🔴'}.get(sentiment, '⚪')
        lines.append(f"  市场情绪：{emotion_icon} {sentiment}  "
                     f"涨停 {limit_up} 家 / 跌停 {limit_down} 家（比值 {ratio:.1f}）\n")

        # 消息面板块
        top_pos = news_sentiment.get('top_positive_sectors', []) if news_sentiment else []
        top_neg = news_sentiment.get('top_negative_sectors', []) if news_sentiment else []
        if top_pos:
            lines.append(f"  📰 消息面利好板块：{'、'.join(top_pos)}\n")
        if top_neg:
            lines.append(f"  📉 消息面利空板块：{'、'.join(top_neg)}\n")

        # 新闻情绪
        if news_sentiment:
            news_tone  = news_sentiment.get('sentiment', 'neutral')
            news_score = news_sentiment.get('score', 0)
            ai_boost   = news_sentiment.get('ai_boost_total', 0)
            tone_map   = {'positive': '偏多🟢', 'negative': '偏空🔴', 'neutral': '中性⚪'}
            lines.append(f"  政策新闻：{tone_map.get(news_tone, '中性')}  "
                         f"关键词分值 {news_score:+d}  AI消息强度 {ai_boost:+.0f}\n")

        lines.append(f"\n  综合判断：{decision_reason}\n")
        lines.append(f"  建议仓位：{position_advice}\n")

        # 三级共振宏观趋势
        if macro_data is None:
            macro_data = {}
        macro_label = {'active': '🟢 主动做多', 'cautious': '🟡 谨慎观望', 'defensive': '🔴 防御避险'}.get(macro_mode, macro_mode)
        lines.append(
            f"  周线宏观：{macro_label}"
            f"  CSI300 vs MA100={macro_data.get('price_vs_ma100', 0):+.1f}%\n"
        )

        # 四状态市场机制（Regime Filter + Override）
        if regime_data is None:
            regime_data = {}
        regime_label_map = {
            'BULL_TREND':              '🟢 牛市趋势（全力出击）',
            'BULL_PULLBACK':           '🟡 牛市回调（缩仓观望）',
            'BEAR_BOUNCE':             '🟠 熊市反弹（极轻仓超短）',
            'BEAR_TREND':              '🔴 熊市下跌（强制空仓）',
            'BEAR_BOUNCE_OVERRIDE':    '⚡ 熊市翻转信号（Override极轻仓）',
            'BULL_PULLBACK_OVERRIDE':  '⚡ 熊市强力翻转（Override半仓）',
        }
        top_n_actual = max(1, round(3 * position_multiplier)) if position_multiplier > 0 else 0
        regime_str = regime_label_map.get(regime, regime)
        override_triggered = regime_data.get('override_triggered', False)
        lines.append(
            f"  市场机制：{regime_str}\n"
            f"  仓位系数：×{position_multiplier}  实际操作Top{top_n_actual}  "
            f"CSI300 vsMA60={regime_data.get('price_vs_ma60_pct', 0):+.1f}%\n"
        )
        # Override触发时，额外显示触发原因
        if override_triggered:
            override_reasons = regime_data.get('override_reasons', [])
            override_score   = regime_data.get('override_score', 0)
            lines.append(
                f"  ⚡ 快速翻转Override（{override_score}/4分）：{' | '.join(override_reasons)}\n"
                f"  ⚠️  当前为熊市临时反弹，仅参与1-2天，严格执行止损\n"
            )
    else:
        lines.append("  （市场数据获取失败）\n")
    lines.append('\n')

    # ── 二、短线建议 ─────────────────────────────────────
    lines.append("【二、短线建议 Top3（持有 1-3 天）】\n")
    lines.append("  策略逻辑：量能异动但价格未大涨 → 主力悄悄建仓 → 次日启动\n\n")

    short_top3 = sorted(ai_analysis, key=lambda x: x.get("score", 0), reverse=True)[:3]
    if short_top3:
        for rank, item in enumerate(short_top3, 1):
            close      = item.get('close', 0)
            buy_low    = round(close * 0.99, 2)
            buy_high   = round(close * 1.01, 2)
            score      = item.get('score', 0)
            risk       = item.get('risk', '-')
            sentiment  = item.get('sentiment', '-')
            news_boost = item.get('news_boost', 0)
            c_boost    = item.get('concept_boost', 0)
            hot_concept= item.get('hot_concept_match', False)
            reason     = item.get('reason', '')

            # 风险图示
            risk_icon  = {'低': '🟢', '中等': '🟡', '高': '🔴'}.get(risk, '⚪')
            sent_icon  = {'正面': '↑', '中性': '→', '负面': '↓'}.get(sentiment, '')

            # 加分标签
            tags = []
            if news_boost > 0:
                tags.append(f"📰消息面+{news_boost:.0f}分")
            if hot_concept and c_boost > 0:
                tags.append(f"🔥热门概念+{c_boost:.1f}分")
            tag_str = f"  [{' | '.join(tags)}]" if tags else ""

            lines.append(sep('─'))
            lines.append(f"  #{rank}  {item['code']} {item['name']}  ({item.get('industry','')})\n")
            lines.append(f"      综合评分：{score:.0f}分  {risk_icon}风险:{risk}  情绪:{sent_icon}{sentiment}{tag_str}\n")
            lines.append(f"      当前价格：{close}元\n")
            lines.append(f"      买入区间：{buy_low} ~ {buy_high} 元（当前价±1%，分批建仓）\n")
            lines.append(f"      目标价格：{item.get('target_price', '-')} 元  "
                         f"预期涨幅：{item.get('expected_gain_pct', '-')}%\n")
            lines.append(f"      止损价格：{item.get('stop_loss_price', '-')} 元  "
                         f"（跌破止损立即离场，不拖延）\n")
            lines.append('\n')

            # 选股量化依据（直接展示系统打分的关键指标）
            vol_ratio   = item.get('volume_ratio', '-')
            drawdown    = item.get('drawdown_from_high', '-')
            net_inflow  = item.get('main_net_inflow', 0)
            trend_label = item.get('trend', '')
            score_base  = item.get('score_base', 0)
            n_boost     = item.get('news_boost', 0)
            c_boost     = item.get('concept_boost', 0)

            inflow_str = (f"+{net_inflow/10000:.1f}亿（主力净流入）" if net_inflow > 0
                          else f"{net_inflow/10000:.1f}亿（主力净流出）" if net_inflow < 0
                          else "数据缺失")

            lines.append("      【选股量化依据】\n")
            lines.append(f"      走势形态：{trend_label}\n")
            lines.append(f"      量    比：{vol_ratio}（≥1.5 才入选，越大说明资金越主动）\n")
            lines.append(f"      回撤幅度：{drawdown}%（距近20日高点，越大位置越低、空间越大）\n")
            lines.append(f"      主力资金：{inflow_str}\n")
            # 新增 Wyckoff 和板块加速分展示
            wyckoff_s = item.get('wyckoff_score', '-')
            accel_s   = item.get('accel_score', '-')
            atr_val   = item.get('atr_14', '-')
            if wyckoff_s != '-':
                lines.append(f"      Wyckoff筹码结构：{wyckoff_s:.0f}分（满分100，≥60代表健康蓄势）\n")
            if accel_s != '-' and accel_s > 0:
                lines.append(f"      板块加速度：{accel_s:.0f}分（资金流入正在加速）\n")
            if atr_val != '-':
                lines.append(f"      ATR波幅：{atr_val:.2f}元（止损={item.get('stop_loss_price','-')}，目标={item.get('target_price','-')}，1.33:1盈亏比）\n")
            # v3.3新增：相对换手率 + 尾盘强弱
            rel_t = item.get('relative_turnover', 1.0)
            eod_s = item.get('eod_strong', False)
            cvwap = item.get('close_vs_vwap', 0.0)
            if rel_t != '-':
                rel_tag = "个股明显异动 🔥" if rel_t >= 2.0 else ("略高于行业均值" if rel_t >= 1.2 else "接近行业均值")
                lines.append(f"      相对换手率：{rel_t:.1f}倍（行业均值=1.0，{rel_tag}）\n")
            eod_str = f"尾盘偏强 +{cvwap:.2f}% ✅（收盘高于当日典型价）" if eod_s else f"尾盘偏弱 {cvwap:.2f}%（收盘低于当日典型价）"
            lines.append(f"      尾盘信号：{eod_str}\n")
            if n_boost != 0:
                lines.append(f"      消息加分：{n_boost:+.0f}分（AI识别板块利好/利空）\n")
            if c_boost > 0:
                lines.append(f"      概念热度：+{c_boost:.1f}分（命中今日热门概念板块）\n")
            lines.append(f"      技术基础分：{score_base:.0f}分 → 最终综合评分：{score:.0f}分\n")
            lines.append('\n')
            lines.append("      【AI深度分析】\n")
            lines.append(f"      {reason}\n")
            lines.append('\n')
    else:
        lines.append("  暂无短线候选（市场条件不满足或大盘风险较高）\n\n")

    # ── 三、波段建议 ─────────────────────────────────────
    lines.append("【三、波段建议 Top3（持有 1-8 周）】\n")
    lines.append("  策略逻辑：MA20＞MA60 上升趋势 + 缩量回踩支撑位 + 等待企稳再进\n\n")

    long_top3 = sorted(ai_longterm, key=lambda x: x.get("trend_strength", 0), reverse=True)[:3]
    if long_top3:
        for rank, item in enumerate(long_top3, 1):
            risk      = item.get('risk', '-')
            sentiment = item.get('sentiment', '-')
            risk_icon = {'低': '🟢', '中等': '🟡', '高': '🔴'}.get(risk, '⚪')
            sent_icon = {'正面': '↑', '中性': '→', '负面': '↓'}.get(sentiment, '')

            lines.append(sep('─'))
            lines.append(f"  #{rank}  {item['code']} {item['name']}  ({item.get('industry','')})\n")
            lines.append(f"      趋势强度：{item.get('trend_strength', 0):.1f}  "
                         f"综合评分：{item.get('score', 0):.0f}分  "
                         f"{risk_icon}风险:{risk}  情绪:{sent_icon}{sentiment}\n")
            lines.append(f"      当前价格：{item.get('close', '-')}元\n")
            lines.append(f"      建议买入：{item.get('buy_price_low', '-')} ~ "
                         f"{item.get('buy_price_high', '-')} 元（MA20 附近分批进场）\n")
            lines.append(f"      目标价格：{item.get('target_price', '-')} 元  "
                         f"预期涨幅：{item.get('expected_gain_pct', '-')}%  "
                         f"预计持有：{item.get('hold_weeks', '-')} 周\n")
            lines.append(f"      止损价格：{item.get('stop_loss_price', '-')} 元  "
                         f"（跌破MA60止损）\n")
            lines.append('\n')

            # 波段量化依据
            ma20       = item.get('ma20', '-')
            ma60       = item.get('ma60', '-')
            slope      = item.get('ma20_slope', 0)
            drawdown   = item.get('drawdown_from_high', '-')
            net_inflow = item.get('main_net_inflow', 0)
            shrinking  = item.get('vol_shrinking', False)
            roe        = item.get('roe')
            rev_growth = item.get('revenue_growth')

            inflow_str = (f"+{net_inflow/10000:.1f}亿" if net_inflow > 0
                          else f"{net_inflow/10000:.1f}亿" if net_inflow < 0
                          else "数据缺失")

            lines.append("      【选股量化依据】\n")
            lines.append(f"      趋势判断：MA20({ma20}元) > MA60({ma60}元)，上升趋势成立\n")
            lines.append(f"      趋势强度：MA20日均上涨 {slope:.2f}%（越大趋势越强劲）\n")
            lines.append(f"      回踩位置：距近20日高点回撤 {drawdown}%（健康回调区间）\n")
            lines.append(f"      缩量洗盘：{'✅ 是（回调缩量，主力未出货）' if shrinking else '❌ 否（回调放量，需谨慎）'}\n")
            lines.append(f"      主力资金：{inflow_str}\n")
            if roe is not None:
                lines.append(f"      基本面ROE：{roe}%{'（优秀）' if roe > 10 else '（一般）' if roe > 3 else '（较差）'}\n")
            if rev_growth is not None:
                lines.append(f"      营收增长：{rev_growth:+.1f}%\n")
            lines.append('\n')
            lines.append("      【AI深度分析】\n")
            lines.append(f"      {item.get('reason', '')}\n")
            lines.append('\n')
    else:
        lines.append("  暂无波段候选（趋势条件不满足或大盘偏弱）\n\n")

    # ── 四、操作提示 ─────────────────────────────────────
    lines.append(sep('─'))
    lines.append("【四、操作纪律提示】\n")
    lines.append("  ① 买入区间：分2-3次建仓，不要一次满仓\n")
    lines.append("  ② 止损纪律：跌破止损价当日收盘前离场，不抱幻想\n")
    lines.append("  ③ 止盈纪律：短线达到目标价附近先减半仓，剩余跟踪\n")
    lines.append("  ④ 本报告仅供参考，最终决策请结合自身判断\n")
    lines.append(f"\n  报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"{'='*60}\n")

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info(f"📄 每日报告已保存：{report_path}")
    except Exception as e:
        logger.warning(f"报告保存失败：{e}")


# ==================== 批量个股深度分析 ====================
def analyze_batch_stocks(stock_codes: List[str], trade_date: str = None) -> List[Dict]:
    """
    批量分析用户指定的股票列表

    Args:
        stock_codes: 股票代码列表（支持6位代码或带后缀的代码）
        trade_date: 交易日期，默认为最新交易日

    Returns:
        AI分析结果列表
    """
    if not stock_codes:
        logger.warning("股票代码列表为空")
        return []

    if trade_date is None:
        trade_date = get_latest_trade_date()

    logger.info(f"📊 开始批量分析 {len(stock_codes)} 只股票（数据日期：{trade_date}）")

    # 格式化股票代码
    ts_codes = [format_code(code.strip()) for code in stock_codes]

    # ── 1. 批量获取基本信息（一次请求，无需逐股循环）──
    logger.info("📊 批量获取基本信息...")
    try:
        stock_info_df = pro.stock_basic(
            ts_code=",".join(ts_codes),
            fields='ts_code,name,industry'
        )
    except Exception as e:
        logger.error(f"批量获取基本信息失败：{e}")
        return []

    if stock_info_df is None or stock_info_df.empty:
        logger.error("无法获取任何股票的基本信息")
        return []

    # ── 2. 批量获取行情数据（一次请求）──
    logger.info("📊 批量获取行情数据...")
    actual_trade_date = trade_date

    def _fetch_price_batch(date: str, codes: List[str]) -> pd.DataFrame:
        batch_size = 500
        dfs = []
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            try:
                df = pro.daily(
                    ts_code=",".join(batch),
                    trade_date=date,
                    fields='ts_code,close,pct_chg,amount,vol'
                )
                if not df.empty:
                    dfs.append(df)
            except Exception as e:
                logger.warning(f"批量行情第{i // batch_size + 1}批失败：{e}")
            if i + batch_size < len(codes):
                time.sleep(0.5)
        return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

    price_df = _fetch_price_batch(actual_trade_date, ts_codes)

    # 无数据则回退到前一交易日
    if price_df.empty:
        logger.warning(f"⚠️ {trade_date} 无交易数据，尝试回退...")
        try:
            start_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=10)).strftime('%Y%m%d')
            cal_df = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=trade_date, is_open=1)
            cal_df = cal_df.sort_values('cal_date', ascending=False)
            prev_dates = cal_df[cal_df['cal_date'] < trade_date]
            if not prev_dates.empty:
                actual_trade_date = prev_dates.iloc[0]['cal_date']
                logger.info(f"✅ 回退到交易日：{actual_trade_date}")
                price_df = _fetch_price_batch(actual_trade_date, ts_codes)
        except Exception as e:
            logger.error(f"回退交易日失败：{e}")

    if price_df.empty:
        logger.error("无法获取任何股票的行情数据")
        return []

    trade_date = actual_trade_date

    # ── 3. 批量获取换手率和量比（daily_basic 传 trade_date 一次拿全部，再按 ts_code 过滤）──
    logger.info("📊 批量获取换手率和量比...")
    try:
        basic_df = pro.daily_basic(
            trade_date=trade_date,
            fields='ts_code,turnover_rate,volume_ratio'
        )
        if basic_df is not None and not basic_df.empty:
            basic_df = basic_df[basic_df['ts_code'].isin(ts_codes)].drop_duplicates(subset='ts_code')
        else:
            basic_df = pd.DataFrame()
    except Exception as e:
        logger.warning(f"获取换手率失败：{e}")
        basic_df = pd.DataFrame()

    # 合并数据
    result_df = stock_info_df.merge(price_df, on='ts_code', how='inner')
    if not basic_df.empty:
        result_df = result_df.merge(basic_df, on='ts_code', how='left')
    else:
        result_df['turnover_rate'] = 0.0
        result_df['volume_ratio'] = 1.0

    # 获取技术指标
    logger.info("📊 批量计算技术指标...")
    codes = [revert_code(ts_code) for ts_code in result_df['ts_code']]
    ma_dict = get_ma_data_batch(codes, trade_date)

    # 获取资金流数据
    logger.info("📊 获取资金流数据...")
    mf_dict = get_batch_moneyflow(result_df['ts_code'].tolist(), trade_date)

    # 获取财务数据
    logger.info("📊 获取财务数据...")
    financial_dict = get_financial_data_batch(codes, trade_date=trade_date)

    # 组装完整数据
    stock_data_list = []
    for _, row in result_df.iterrows():
        ts_code = row['ts_code']
        code = revert_code(ts_code)
        ma_data = ma_dict.get(ts_code, {})
        mf_data = mf_dict.get(ts_code, 0)
        fin_data = financial_dict.get(code, {})

        if not ma_data:
            logger.warning(f"{code} 技术指标计算失败，跳过")
            continue

        # 判断价格位置
        if ma_data.get('above_ma5') and ma_data.get('above_ma10'):
            price_position = "强势（MA5/MA10上方）"
        elif ma_data.get('near_ma20'):
            price_position = "MA20附近（支撑位）"
        elif ma_data.get('above_ma20'):
            price_position = "MA20上方"
        else:
            price_position = "调整中"

        stock_data = {
            'code': code,
            'name': row['name'],
            'industry': row['industry'],
            'current_price': float(row['close']),
            'change': float(row['pct_chg']),
            'turnover': float(row.get('turnover_rate', 0)),
            'volume_ratio': float(row.get('volume_ratio', 1.0)),
            'amount': float(row['amount']) / 100000,  # 转换为亿元
            'ma5': float(ma_data.get('ma5', 0)),
            'ma10': float(ma_data.get('ma10', 0)),
            'ma20': float(ma_data.get('ma20', 0)),
            'ma60': float(ma_data.get('ma60', 0)),
            'high20': float(ma_data.get('high20', 0)),  # 近20日最高价
            'low20': float(ma_data.get('low20', 0)),    # 近20日最低价
            'price_position': price_position,
            'drawdown_from_high': float(ma_data.get('drawdown_from_high', 0)),
            'has_limit_up_gene': bool(ma_data.get('has_limit_up_gene', False)),
            'volatility': float(ma_data.get('volatility', 0)),
            'main_net_inflow': float(mf_data),
            'vol_3d_avg': float(ma_data.get('vol_3d_avg', 1.0)),
            'vol_accelerating': bool(ma_data.get('vol_accelerating', False)),
            'roe': float(fin_data.get('roe', 0)),
            'revenue_growth': float(fin_data.get('revenue_growth', 0)),
            'debt_ratio': float(fin_data.get('debt_ratio', 0)),
            'data_date': trade_date
        }
        stock_data_list.append(stock_data)

    if not stock_data_list:
        logger.error("没有可分析的股票数据")
        return []

    # 调用AI分析
    logger.info(f"📊 调用AI进行深度分析（共{len(stock_data_list)}只）...")
    stock_list_json = json.dumps(stock_data_list, ensure_ascii=False)

    result = parse_ai_json(
        call_ai_api(
            prompt=ai_prompts.PROMPT_BATCH_STOCK_ANALYSIS.format(
                stock_list=stock_list_json
            ),
            system=ai_prompts.SYSTEM_BATCH_ANALYST
        )
    )

    if not result or not isinstance(result, list):
        logger.error("AI分析失败或返回格式错误")
        return []

    logger.info(f"✅ 批量分析完成：{len(result)}条结果")
    return result


def analyze_from_file(file_path: str, output_path: str = None) -> None:
    """
    从文件读取股票代码并分析，输出到文件

    Args:
        file_path: 输入文件路径（每行一个股票代码）
        output_path: 输出文件路径，默认为 reports/batch_analysis_YYYYMMDD.txt
    """
    logger.info(f"📄 从文件读取股票代码：{file_path}")

    # 读取股票代码
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        logger.error(f"读取文件失败：{e}")
        return

    # 解析股票代码（支持注释和空行）
    stock_codes = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # 支持格式：600000 或 600000.SH 或 600000 贵州茅台
        code = line.split()[0]
        if code.replace('.', '').isdigit() or '.' in code:
            stock_codes.append(code)

    if not stock_codes:
        logger.error("文件中没有有效的股票代码")
        return

    logger.info(f"📊 共读取 {len(stock_codes)} 个股票代码")

    # 批量分析
    results = analyze_batch_stocks(stock_codes)

    if not results:
        logger.error("分析失败，无结果")
        return

    # 生成输出文件
    if output_path is None:
        trade_date = get_latest_trade_date()
        output_path = os.path.join(config.REPORTS_DIR, f"batch_analysis_{trade_date}.txt")

    logger.info(f"📄 生成分析报告：{output_path}")

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"===== 批量个股深度分析报告 =====\n")
            f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"分析股票数：{len(results)}\n\n")

            # 按评分排序
            results_sorted = sorted(results, key=lambda x: x.get('score', 0), reverse=True)

            for i, item in enumerate(results_sorted, 1):
                f.write(f"{'='*80}\n")
                f.write(f"【{i}】{item.get('code')} {item.get('name')}\n")
                f.write(f"{'='*80}\n\n")

                f.write(f"综合评级：{item.get('rating')}  评分：{item.get('score')}/100  风险：{item.get('risk_level')}\n")
                f.write(f"走势预测：{item.get('trend_prediction')}（{item.get('time_horizon')}）\n")
                f.write(f"目标价格：{item.get('target_price')}元  预期涨幅：{item.get('target_gain_pct')}%\n")
                f.write(f"止损价格：{item.get('stop_loss_price')}元\n")
                f.write(f"买入时机：{item.get('buy_timing')}\n\n")

                f.write(f"【技术面分析】\n{item.get('technical_analysis', '无')}\n\n")
                f.write(f"【资金面分析】\n{item.get('capital_analysis', '无')}\n\n")
                f.write(f"【基本面分析】\n{item.get('fundamental_analysis', '无')}\n\n")
                f.write(f"【上涨催化剂】\n{item.get('catalyst', '无')}\n\n")
                f.write(f"【风险提示】\n{item.get('risk_warning', '无')}\n\n")
                f.write(f"【操作建议】\n{item.get('operation_suggestion', '无')}\n\n")

        logger.info(f"✅ 分析报告已保存：{output_path}")

        # 打印摘要
        logger.info("\n【📊 分析摘要】")
        top3 = results_sorted[:3]
        for item in top3:
            logger.info(
                f"  {item.get('code')} {item.get('name')} | "
                f"评级:{item.get('rating')} | 评分:{item.get('score')} | "
                f"目标价:{item.get('target_price')}元 | "
                f"预期涨幅:{item.get('target_gain_pct')}%"
            )

    except Exception as e:
        logger.error(f"保存报告失败：{e}", exc_info=True)


if __name__ == "__main__":
    import sys

    # 支持命令行参数：python main.py analyze watchlist.txt
    if len(sys.argv) >= 3 and sys.argv[1] == 'analyze':
        analyze_from_file(sys.argv[2])
    else:
        main()

