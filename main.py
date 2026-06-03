import tushare as ts
import pandas as pd
import json
import os
import logging
import requests
import re
import time
import math
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import config
import ai_prompts
import news_analyzer
import market_analyzer
from strategy_profiles import apply_short_profile

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
        pro._DataApi__http_url = 'http://14.nat0.cn:32817'  # 买的便宜Tushare接口的中转站
        logger.info("✅ Tushare接口初始化成功")
        return pro
    except Exception as e:
        logger.error(f"❌ Tushare初始化失败：{e}", exc_info=True)
        raise

if os.environ.get("LEMON_SKIP_TUSHARE_INIT") == "1":
    pro = None
    logger.info("跳过 Tushare 初始化：等待离线回测注入 LocalDataProxy")
else:
    pro = init_tushare()

# ── 保存原始 pro 实例，用于 restore_pro() ──
_original_pro = pro

# ── 板块MA10状态进程内内存缓存（key: trade_date → Dict[str, bool]）──
# 离线回测跑全年252个交易日时，每天都调一次 get_sector_ma10_status，
# 有了内存缓存后每个日期只读一次文件，后续直接返回，速度极快。
_sector_ma10_mem_cache: Dict[str, Dict[str, bool]] = {}

# ── stock_basic 行业映射缓存（ts_code → industry）──
# 板块主线防守 guard 每个交易日都需要此映射，通过模块级缓存确保每进程只拉取一次。
# set_pro / restore_pro 切换 pro 实例时会同步清除缓存（见下方函数）。
_sb_industry_cache: Optional[Dict[str, str]] = None


def _get_industry_map() -> Dict[str, str]:
    """
    获取全量 ts_code→industry 映射（带模块级缓存，每 pro 实例只调用一次 stock_basic）。
    离线回测：LocalDataProxy 从 stock_basic.parquet 读取，已有 lru_cache，调用成本极低。
    实盘：每次启动进程只调用一次 Tushare stock_basic 接口，不产生额外积分消耗。
    """
    global _sb_industry_cache
    if _sb_industry_cache is None:
        try:
            _sb = pro.stock_basic(fields='ts_code,industry')
            if not _sb.empty and 'industry' in _sb.columns:
                _sb_industry_cache = _sb.set_index('ts_code')['industry'].to_dict()
                logger.info(f"[_get_industry_map] 行业映射已加载，共 {len(_sb_industry_cache)} 只股票")
            else:
                _sb_industry_cache = {}
                logger.warning("[_get_industry_map] stock_basic 返回空，行业映射为空")
        except Exception as e:
            _sb_industry_cache = {}
            logger.debug(f"[_get_industry_map] stock_basic 获取失败，行业映射为空：{e}")
    return _sb_industry_cache


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
    global pro, _sb_industry_cache
    pro = proxy
    _sb_industry_cache = None  # 切换 pro 时清除行业映射缓存
    logger.info(f"[set_pro] pro 已替换为：{type(proxy).__name__}")


def restore_pro() -> None:
    """恢复 pro 为初始化时的真实 Tushare 实例。"""
    global pro, _sb_industry_cache
    pro = _original_pro
    _sb_industry_cache = None  # 恢复 pro 时清除行业映射缓存
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

    # 验证是否有实际行情数据（用全市场daily接口验证，与get_all_stocks逻辑一致）
    # 注意：上证指数(000001.SH)入库时间早于个股，用指数验证会导致虚报"有数据"但个股实际为空
    for date in open_dates[:5]:  # 最多回退5个交易日
        try:
            test_df = _tushare_query_with_retry(
                pro.daily,
                ts_code='600000.SH,000001.SZ,600036.SH',  # 用几只主流个股测试，更能代表全市场入库状态
                trade_date=date,
                fields='ts_code,close'
            )
            if not test_df.empty and len(test_df) >= 2:  # 至少2只有数据才认为当天数据入库
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


def get_batch_moneyflow_3d(ts_codes: List[str], trade_date: str) -> Dict[str, float]:
    """
    批量获取近3个交易日（T-3~T-1，不含T当日）主力累计净流入（万元）。
    逻辑：板块今日有龙头但个股今日没动 → 今日资金流必然偏小；
         改看T-3~T-1三日累计，衡量是否已有主力提前布局。
    返回：{ts_code: 3日累计净流入万元}（NaN代码不入字典）
    """
    is_offline = type(pro).__name__ == 'LocalDataProxy'
    # 计算T-3交易日（粗算取5日历天，足够覆盖3个交易日）
    dt = datetime.strptime(trade_date, '%Y%m%d')
    start_dt = dt - timedelta(days=7)
    start_date = start_dt.strftime('%Y%m%d')

    batch_size = 200  # 多日查询，批次缩小
    result: Dict[str, float] = {}
    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i:i + batch_size]
        try:
            df = pro.moneyflow(
                ts_code=",".join(batch),
                start_date=start_date,
                end_date=trade_date,
                fields='ts_code,trade_date,net_mf_amount'
            )
            if df.empty:
                continue
            # 只取 T 日之前的3个交易日（排除当日）
            df = df[df['trade_date'] < trade_date].copy()
            df['net_mf_amount'] = pd.to_numeric(df['net_mf_amount'], errors='coerce')
            df = df.dropna(subset=['net_mf_amount'])
            # 每只股票最多取最近3条
            df = df.sort_values('trade_date', ascending=False)
            df = df.groupby('ts_code').head(3)
            for code, grp in df.groupby('ts_code'):
                result[code] = round(float(grp['net_mf_amount'].sum()), 2)
        except Exception as e:
            logger.warning(f"近3日资金流第{i // batch_size + 1}批失败：{e}")
        if not is_offline:
            time.sleep(0.8)
    logger.info(f"✅ 近3日累计资金流获取完成，共{len(result)}只")
    return result


def get_batch_margin_buy(ts_codes: List[str], trade_date: str) -> Dict[str, float]:
    """
    批量获取当日融资净买入额（万元）：融资买入额 - 融资偿还额。
    融资客愿意加杠杆买入 = 强看多信号，是独立于主力资金流的补充确认。
    返回：{ts_code: 融资净买入万元}，缺失代码不入字典
    注意：margin_detail 字段为 rzye(融资余额) / rzmre(融资买入额) / rzche(融资偿还额)
    """
    is_offline = type(pro).__name__ == 'LocalDataProxy'
    batch_size = 200
    result: Dict[str, float] = {}
    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i:i + batch_size]
        try:
            df = pro.margin_detail(
                ts_code=",".join(batch),
                trade_date=trade_date,
                fields='ts_code,rzmre,rzche'
            )
            if df.empty:
                continue
            df['rzmre'] = pd.to_numeric(df['rzmre'], errors='coerce').fillna(0.0)
            df['rzche'] = pd.to_numeric(df['rzche'], errors='coerce').fillna(0.0)
            # 融资净买入（万元）= (买入 - 偿还) / 10000
            df['margin_net'] = (df['rzmre'] - df['rzche']) / 10000.0
            for _, row in df.iterrows():
                result[row['ts_code']] = round(float(row['margin_net']), 2)
        except Exception as e:
            logger.warning(f"融资净买入第{i // batch_size + 1}批失败：{e}")
        if not is_offline:
            time.sleep(0.8)
    logger.info(f"✅ 融资净买入获取完成，共{len(result)}只")
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
            # 中转站通常不支持申万指数，用个股聚合兜底
            logger.debug("板块MA10：申万指数数据不可用（中转站限制），将用个股聚合替代")
            # 空结果也写入内存缓存，避免同一天重复拉取触发多次警告
            _sector_ma10_mem_cache[trade_date] = {}
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


def get_sector_catchup_scores(all_stocks: pd.DataFrame, prev_stocks_list: list = None, today_full_df: pd.DataFrame = None, leader_threshold: float = 8.0, history_leader_threshold: float = None, regime: str = None) -> Dict[str, float]:
    """
    v8.0：板块补涨评分（替代热门板块追涨逻辑）。
    逻辑：行业内有强势股/涨停在领涨，但该行业整体涨幅适中（说明还有滞涨股）。
    评分越高 = 板块启动中 + 仍有滞涨机会。

    补涨分计算逻辑：
      板块动能 = 行业内涨幅≥5%占比×500（上限100分）+ 涨停占比×300（上限30分）
      未过热系数 = 中位数涨幅<1%→1.0；>3%→0.3；中间线性衰减
      补涨分 = 板块动能 × 未过热系数（0~100分）

    全市场无龙头熔断（v8.0+实验2A）在调用方 run_daily_selection 中执行，
    本函数只负责计算各行业补涨分，不含时序乘数。

    参数说明（兼容旧调用接口，以下参数保留但不使用）：
      prev_stocks_list / leader_threshold / history_leader_threshold / regime
      → 保留签名是为了兼容回测引擎的调用，实际均忽略。

    返回：{行业名称: 补涨分(0-100)}
    """
    if all_stocks.empty:
        return {}

    # 使用 change 字段（今日涨幅%）
    change_col = 'change' if 'change' in all_stocks.columns else 'pct_chg'
    if change_col not in all_stocks.columns:
        return {}

    # 按行业统计
    def sector_stats(group):
        changes = group[change_col].dropna()
        if len(changes) == 0:
            return pd.Series({'strong_ratio': 0.0, 'median_change': 0.0, 'limit_up_ratio': 0.0})
        strong_ratio   = (changes >= 5.0).sum() / len(changes)   # 行业内涨≥5%家数占比
        limit_up_ratio = (changes >= 9.5).sum() / len(changes)   # 涨停占比
        median_change  = changes.median()
        return pd.Series({
            'strong_ratio':   strong_ratio,
            'limit_up_ratio': limit_up_ratio,
            'median_change':  median_change,
        })

    stats = all_stocks.groupby('industry').apply(sector_stats, include_groups=False).reset_index()

    # 补涨分 = 板块动能分 × 行业未过热系数
    # 板块动能：strong_ratio 0→0分，10%→60分，20%→100分（线性）+ 涨停加成
    stats['momentum_score'] = (stats['strong_ratio'] * 500).clip(0, 100)
    stats['limit_bonus']    = (stats['limit_up_ratio'] * 300).clip(0, 30)   # 涨停家数加成，最高30

    # 行业未过热系数：行业中位数涨幅越低，说明大部分股还没动（补涨空间大）
    # 中位数涨幅 <1% → 系数1.0（大部分未动）；>3% → 系数0.3（板块已普涨，补涨空间小）
    stats['not_overbought'] = stats['median_change'].apply(
        lambda x: 1.0 if x < 1.0 else max(0.3, 1.0 - (x - 1.0) / 3.0)
    )

    # 综合补涨分：需要行业有至少一点动能，且大部分股还没动
    stats['catchup_score'] = (
        (stats['momentum_score'] + stats['limit_bonus']) * stats['not_overbought']
    ).clip(0, 100)

    result = dict(zip(stats['industry'], stats['catchup_score']))

    # ── 时序乘数（实验1A核心，翻转版）──
    # 补涨的时机是"板块昨天/前天启动，今天大部分股还没动"。
    # prev_stocks_list 非空时激活，对每个行业按以下规则决定乘数：
    #   前1~2天有≥2只龙头 + 今天板块未过热（中位数涨幅<2%）→ ×1.0  补涨黄金窗口
    #   前1~2天有≥2只龙头 + 今天板块已过热                   → ×0.3  窗口关闭
    #   前1~2天无龙头 + 今天刚启动（今日≥2龙头）             → ×0.5  太新，等明天
    #   前1~2天无龙头 + 今天也无龙头                         → ×0.0  无主线，清零
    if prev_stocks_list is not None:
        change_col_today = 'change' if 'change' in all_stocks.columns else 'pct_chg'

        # 今日各行业：涨停龙头数 + 中位数涨幅（判断是否过热）
        today_stats: Dict[str, dict] = {}
        if 'industry' in all_stocks.columns and change_col_today in all_stocks.columns:
            for ind, grp in all_stocks.groupby('industry'):
                chg = grp[change_col_today].dropna()
                today_stats[ind] = {
                    'n_leaders': int((chg >= 9.5).sum()),
                    'median':    float(chg.median()) if len(chg) else 0.0,
                }

        # 前1~2日各行业是否出现过≥2只涨停龙头（OR逻辑）
        prev_had_leaders: set = set()
        for prev_df in prev_stocks_list:
            if prev_df is None or prev_df.empty:
                continue
            prev_chg_col = 'pct_chg' if 'pct_chg' in prev_df.columns else 'change'
            if 'industry' not in prev_df.columns or prev_chg_col not in prev_df.columns:
                continue
            hit = prev_df[prev_df[prev_chg_col] >= 9.5].groupby('industry').size()
            # 要求前几天也达到≥2只才算"有龙头启动"（与今日标准一致）
            prev_had_leaders |= set(hit[hit >= 2].index)

        # 应用乘数
        timed_result: Dict[str, float] = {}
        cnt = {'fresh': 0, 'hot_closed': 0, 'new_launch': 0, 'zero': 0}
        for sector, score in result.items():
            st = today_stats.get(sector, {'n_leaders': 0, 'median': 0.0})
            has_prev   = sector in prev_had_leaders
            today_lead = st['n_leaders'] >= 2
            overheated = st['median'] >= 2.0   # 今日板块整体已普涨

            if has_prev and not overheated:
                mult = 1.0; cnt['fresh'] += 1      # 补涨黄金窗口
            elif has_prev and overheated:
                mult = 0.3; cnt['hot_closed'] += 1  # 前天启动，今天已普涨，窗口关闭
            elif today_lead and not has_prev:
                mult = 0.5; cnt['new_launch'] += 1  # 今天刚启动，太新，等明天
            else:
                mult = 0.0; cnt['zero'] += 1        # 无主线

            timed_result[sector] = score * mult

        result = timed_result
        logger.info(
            f"⏱️ 时序乘数：补涨窗口={cnt['fresh']}板块×1.0，"
            f"窗口关闭={cnt['hot_closed']}板块×0.3，"
            f"新启动={cnt['new_launch']}板块×0.5，"
            f"无主线={cnt['zero']}板块×0.0"
        )

    # 打印补涨机会Top3
    top3_items = sorted(result.items(), key=lambda x: x[1], reverse=True)[:3]
    top3_info = ', '.join(f"{s}({sc:.0f}分)" for s, sc in top3_items)
    logger.info(f"🚀 板块补涨Top3：{top3_info}")

    return result


def get_sector_catchup_scores_multi(trade_date: str, all_stocks: pd.DataFrame) -> Dict[str, float]:
    """
    实验G：多日板块持续性补涨评分。
    在 get_sector_catchup_scores 基础上，叠加"连续2~3天有领涨股但大部分未动"的持续性乘数。

    持续性乘数：
      - 仅今天满足条件 → ×1.0（与原版相同）
      - 连续2天满足   → ×1.3（板块启动信号更可靠）
      - 连续3天满足   → ×1.5（持续强势，补涨机会最大）

    "满足条件"定义：行业 strong_ratio（≥5%涨幅家数占比）≥ 6%，且行业中位数涨幅 < 2.0%
    数据来源：today = all_stocks（已有），前1~2天 = pro.daily(trade_date=d)（离线parquet）
    无需新接口，零积分消耗。

    返回：{行业名称: 调整后补涨分(0-150)}
    """
    # ── Step 1：计算今日补涨基础分 ──
    today_scores = get_sector_catchup_scores(all_stocks)
    if not today_scores:
        return today_scores

    change_col = 'change' if 'change' in all_stocks.columns else 'pct_chg'
    if change_col not in all_stocks.columns:
        return today_scores

    def _sector_condition(df_day: pd.DataFrame, industry_col: str = 'industry') -> Dict[str, bool]:
        """判断该日各行业是否满足持续性条件（有龙头+大部分未动）"""
        if df_day.empty or industry_col not in df_day.columns:
            return {}
        col = 'change' if 'change' in df_day.columns else 'pct_chg'
        if col not in df_day.columns:
            return {}
        result_day = {}
        for ind, grp in df_day.groupby(industry_col):
            changes = grp[col].dropna()
            if len(changes) < 5:
                continue
            strong_ratio  = (changes >= 5.0).sum() / len(changes)
            median_change = changes.median()
            # 持续性条件：有领涨股且大部分未动
            result_day[ind] = (strong_ratio >= 0.06) and (median_change < 2.0)
        return result_day

    # 今日满足情况
    today_condition = _sector_condition(all_stocks)

    # ── Step 2：获取前2个交易日数据 ──
    prev_conditions = []  # index=0 是昨天，index=1 是前天
    try:
        buf_start = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=10)).strftime('%Y%m%d')
        cal_df = pro.trade_cal(exchange='SSE', start_date=buf_start, end_date=trade_date, is_open=1)
        if not cal_df.empty:
            cal_df = cal_df.sort_values('cal_date', ascending=False)
            prev_dates = cal_df[cal_df['cal_date'] < trade_date]['cal_date'].tolist()[:2]
            # 构建 ts_code→industry 映射（all_stocks.code 是6位，需转为带后缀的 ts_code）
            ts_to_ind = {}
            if 'code' in all_stocks.columns and 'industry' in all_stocks.columns:
                # format_code 将 '000001' → '000001.SZ'，与 daily parquet 的 ts_code 匹配
                ts_to_ind = {
                    format_code(row['code']): row['industry']
                    for _, row in all_stocks[['code', 'industry']].dropna().iterrows()
                }
            for prev_date in prev_dates:
                df_prev = pro.daily(trade_date=prev_date, fields='ts_code,pct_chg')
                if df_prev.empty:
                    prev_conditions.append({})
                    continue
                df_prev['industry'] = df_prev['ts_code'].map(ts_to_ind)
                df_prev = df_prev.dropna(subset=['industry'])
                prev_conditions.append(_sector_condition(df_prev, 'industry'))
    except Exception as e:
        logger.debug(f"[多日板块持续性] 获取历史数据失败：{e}")
        return today_scores  # 降级：等价原版

    # ── Step 3：计算各行业连续天数，应用持续性乘数 ──
    result = {}
    for industry, base_score in today_scores.items():
        if not today_condition.get(industry, False):
            # 今天不满足条件：基础分保留，不加乘数
            result[industry] = base_score
            continue

        # 今天满足，统计连续天数（往前累计）
        consecutive = 1
        for day_cond in prev_conditions:
            if day_cond.get(industry, False):
                consecutive += 1
            else:
                break

        if consecutive >= 3:
            multiplier = 1.5
        elif consecutive == 2:
            multiplier = 1.3
        else:
            multiplier = 1.0

        result[industry] = min(base_score * multiplier, 150)

    # 打印 Top3（含持续天数信息）
    top3 = sorted(result.items(), key=lambda x: -x[1])[:3]
    if top3:
        top3_parts = []
        for ind, score in top3:
            base = today_scores.get(ind, 0)
            mult = score / base if base > 0 else 1.0
            day_str = "3日" if mult >= 1.45 else ("2日" if mult >= 1.25 else "1日")
            top3_parts.append(f"{ind}({score:.0f}分,持续{day_str})")
        logger.info(f"🚀 板块持续补涨Top3：{'  '.join(top3_parts)}")

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

        # ── 新增：IBD分配日计数（作为辅助过滤信号）──
        # 理论依据：O'Neil CANSLIM —— 大盘25日内出现≥5个分配日（放量下跌日）预示顶部
        # 分配日定义：指数下跌≥0.2% 且 成交量 > 前日成交量
        # A股用沪深300代理，仅影响 downtrend 判断
        distrib_days_hs3 = 0
        try:
            df_hs3_v = pro.index_daily(
                ts_code='000300.SH',
                start_date=(datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=40)).strftime('%Y%m%d'),
                end_date=trade_date,
                fields='trade_date,close,pct_chg,vol'
            )
            if not df_hs3_v.empty and 'vol' in df_hs3_v.columns and len(df_hs3_v) >= 5:
                df_hs3_v = df_hs3_v.sort_values('trade_date')
                df_hs3_v['vol_prev'] = df_hs3_v['vol'].shift(1)
                distrib = df_hs3_v[
                    (df_hs3_v['pct_chg'] <= -0.2) &
                    (df_hs3_v['vol'] > df_hs3_v['vol_prev'])
                ].tail(25)
                distrib_days_hs3 = len(distrib)
        except Exception:
            distrib_days_hs3 = 0

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

        # IBD分配日辅助：25日内≥6个分配日且双指数caution → 提前预警主跌浪
        if distrib_days_hs3 >= 6 and (sh_caution or hs3_caution):
            return 'downtrend', (
                f"IBD分配日预警（25日内{distrib_days_hs3}个放量下跌日）+ 大盘回调，建议空仓"
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
        │             │  MA10 > MA30     │  MA10 < MA30     │
        ├─────────────┼──────────────────┼──────────────────┤
        │ 长期牛市     │ BULL_TREND ✅   │ BULL_PULLBACK ⚠️ │
        │ 价格>MA30    │ 全力出击×1.0    │ 缩仓×0.67        │
        ├─────────────┼──────────────────┼──────────────────┤
        │ 长期熊市     │ BEAR_BOUNCE ⚠️  │ BEAR_TREND  ❌   │
        │ 价格<MA30    │ 轻仓×0.33       │ 空仓×0.0         │
        └─────────────┴──────────────────┴──────────────────┘

    长期牛熊判断（April 18基准：MA20 vs MA60，经全段验证稳定）：
      - 使用CSI300日线MA60（约3个月）判断中长期趋势
      - MA20 > MA60（黄金交叉）且 MA60斜率 > 阈值 → 长期牛市
      - MA20 < MA60（死叉）或 MA60斜率 < -阈值 → 长期熊市
      理论依据：Weinstein四阶段 + Faber(2007) 10月SMA规则

    短期方向判断：
      - 收盘价 vs MA20（快于长期信号，捕捉1个月内动量方向）
      - close > MA20 → 短期上涨；close < MA20 → 短期回调
      与长期MA20/MA60交叉独立，使四状态实际均可达

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
        # 拉取CSI300近120个交易日（覆盖MA60 + 斜率计算所需历史）
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
        # EMA60：比SMA60反应更快（滞后约减少1/3），更早捕捉趋势转折
        df['ma60'] = df['close'].ewm(span=60, adjust=False).mean()

        latest = df.iloc[-1]
        close_now = float(latest['close'])
        ma20_now  = float(latest['ma20']) if not pd.isna(latest['ma20']) else None
        ma60_now  = float(latest['ma60']) if not pd.isna(latest['ma60']) else None

        if ma20_now is None or ma60_now is None:
            logger.warning("⚠️ 市场状态机：均线数据不足，默认 BULL_TREND")
            return 'BULL_TREND', regime_data

        # ── 长期方向：MA20 > MA60 + MA60斜率（April 18基准，已验证稳定）──
        # 理论依据：Weinstein四阶段 + Faber(2007) 趋势择时
        # MA60约等于3个月，是区分牛熊的黄金均线，经2023~2025全段验证有效
        price_vs_ma60 = (close_now - ma60_now) / ma60_now * 100

        # MA60近10日斜率（日均涨幅%）
        ma60_slope = 0.0
        if len(df) >= 70:  # 60+10
            ma60_10d_ago = float(df.iloc[-11]['ma60']) if not pd.isna(df.iloc[-11]['ma60']) else ma60_now
            ma60_slope = (ma60_now - ma60_10d_ago) / ma60_now * 100 / 10

        # 长期牛市条件：价格在MA60附近（容忍-3%偏下）且MA60斜率不过度向下
        # 用 price_vs_ma60 >= -3.0 而非 MA20>MA60（金叉条件）：
        #   - 金叉滞后约20~30天，市场已反弹一大截才开仓，或已顶部才死叉
        #   - price_vs_ma60 只看当日收盘，响应比金叉快约1个月
        # 经v4.1验证：此方式2025全年胜率47.5%，MA20>MA60方式退化到33%以下
        is_long_bull = (price_vs_ma60 >= -3.0) and (ma60_slope >= -config.REGIME_MA60_SLOPE_THRESHOLD)

        # ── 短期方向：价格 vs MA20（1个月趋势，快于长期信号）──
        # 用收盘价是否站上MA20来判断短期动量方向
        # 与长期 (MA20 vs MA60) 独立，使四状态实际可达：
        #   MA20>MA60 且 close>MA20 → BULL_TREND
        #   MA20>MA60 且 close<MA20 → BULL_PULLBACK（牛市内部短期回调）
        #   MA20<MA60 且 close>MA20 → BEAR_BOUNCE（熊市内短期反弹）
        #   MA20<MA60 且 close<MA20 → BEAR_TREND
        is_short_up = (close_now > ma20_now)

        # ── 20日收益率快速降级（解决MA60/MA20滞后30~60天的问题）──
        # MA60需要60天数据才能转向，导致市场顶部后仍误判为牛市。
        # 用近20日（约1个月）实际涨跌幅作为快速先行信号：
        #   <-3%  → 短期已转弱，强制 is_short_up=False（防止 BULL_TREND 虚假开仓）
        #   <-8%  → 跌幅较大，长期信号也降级（MA20>MA60 金叉但实际已转头）
        # 阈值选取依据：A股正常回调2~3%，-3%以上多为趋势性下跌
        ret_20d = 0.0
        low_20d = close_now   # 近20日最低收盘价，用于恢复确认
        if len(df) >= 22:
            close_20d_ago = float(df.iloc[-21]['close'])
            ret_20d = (close_now - close_20d_ago) / close_20d_ago * 100
            low_20d = float(df.iloc[-21:]['close'].min())
            if ret_20d < -3.0:
                # 20日跌逾3%，短期已走弱，强制降级为短期下跌
                if is_short_up:
                    logger.info(f"⚡ 20日快速降级：CSI300近20日-{abs(ret_20d):.1f}%，强制 is_short_up=False（防MA20滞后）")
                    is_short_up = False
            if ret_20d < -7.0:
                # 20日跌逾7%，长期均线也滞后了，追加降级 is_long_bull
                # EMA60已加速响应，阈值从原-8%收紧至-7%，避免-5%时正常回调误杀
                if is_long_bull:
                    logger.info(f"⚡ 20日快速降级：CSI300近20日-{abs(ret_20d):.1f}%，强制 is_long_bull=False（防MA60滞后）")
                    is_long_bull = False

        # ── 恢复确认：距近20日低点反弹幅度（解决MA60滞后踏空问题）──
        # MA60在市场反转后需30~60天才能转正，导致快速反弹行情全程空仓踏空。
        # 用"距近20日最低收盘价的反弹幅度"作为快速先行信号：
        #   > 6%  → 中期已显著恢复，即使close<MA20，升级 is_short_up=True
        #   > 12% → 强势反转，长期信号也升级 is_long_bull=True（防MA60滞后踏空）
        # 阈值依据：A股正常技术反弹3~5%，>6%多为趋势性恢复而非死猫跳
        recovery_pct = 0.0
        if low_20d > 0 and close_now > low_20d:
            recovery_pct = (close_now - low_20d) / low_20d * 100
            if recovery_pct > 6.0 and not is_short_up:
                # 从20日低点反弹逾6%，短期已恢复，升级短期方向
                logger.info(f"⚡ 恢复确认升级：CSI300距20日低点反弹{recovery_pct:.1f}%，升级 is_short_up=True（防MA20滞后踏空）")
                is_short_up = True
            if recovery_pct > 11.0 and not is_long_bull:
                # 从20日低点反弹逾11%，强势反转，长期信号也升级
                # EMA60已加速，阈值从原12%微降至11%，防止死猫跳误判
                logger.info(f"⚡ 恢复确认升级：CSI300距20日低点反弹{recovery_pct:.1f}%，升级 is_long_bull=True（防MA60滞后踏空）")
                is_long_bull = True

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
            'ret_20d_pct': round(ret_20d, 2),
            'recovery_pct': round(recovery_pct, 2),
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
            f" | MA20vsMA60={price_vs_ma60:+.1f}%  MA60斜率={ma60_slope:+.4f}%/日"
            f" | 20日涨跌={ret_20d:+.1f}%  距20日低反弹={recovery_pct:+.1f}%"
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

    # ── 持续性确认：连续N日达标才升级（防止熊市单日暴涨误触发）──
    # 使用文件缓存记录连续达标天数，要求连续≥2天score≥2才真正升级
    # 单日4/4分：立即生效（极端强势，如924行情）
    # 单日3/4分且连续2天：升级为BULL_PULLBACK_OVERRIDE
    # 单日2/4分且连续3天：升级为BEAR_BOUNCE_OVERRIDE
    streak_file = os.path.join('data', 'cache', 'regime_override_streak.json')
    streak_data = {'date': '', 'count': 0, 'last_score': 0}
    try:
        if os.path.exists(streak_file):
            import json
            with open(streak_file, 'r') as f:
                streak_data = json.load(f)
    except Exception:
        pass

    # 更新连续天数：若今日score≥2则累加，否则重置
    import json
    if score >= 2:
        if streak_data.get('last_score', 0) >= 2:
            streak_data['count'] = streak_data.get('count', 0) + 1
        else:
            streak_data['count'] = 1
        streak_data['last_score'] = score
        streak_data['date'] = trade_date
    else:
        streak_data = {'date': trade_date, 'count': 0, 'last_score': score}

    try:
        os.makedirs(os.path.dirname(streak_file), exist_ok=True)
        with open(streak_file, 'w') as f:
            json.dump(streak_data, f)
    except Exception:
        pass

    consecutive = streak_data['count']

    # ── 升级决策 ──
    override_info['score'] = score
    override_info['reasons'] = reasons

    if score >= 4 or (score >= 3 and consecutive >= 2):
        # 单日4/4极端强势，或连续2天≥3分 → 升级BULL_PULLBACK_OVERRIDE
        new_regime = 'BULL_PULLBACK_OVERRIDE'
        override_info['triggered']          = True
        override_info['position_multiplier'] = config.REGIME_OVERRIDE_POSITION['BULL_PULLBACK_OVERRIDE']
        override_info['score_threshold']     = config.REGIME_OVERRIDE_SCORE_THRESHOLD['BULL_PULLBACK_OVERRIDE']
        override_info['max_hold_days']       = config.REGIME_OVERRIDE_MAX_HOLD['BULL_PULLBACK_OVERRIDE']
        logger.warning(
            f"⚡ 快速翻转Override触发（{score}/4分，连续{consecutive}天）→ BEAR_TREND 临时升为 BULL_PULLBACK_OVERRIDE\n"
            f"   命中条件：{' | '.join(reasons)}\n"
            f"   参数：仓位×{override_info['position_multiplier']}  "
            f"门槛≥{override_info['score_threshold']}分  "
            f"持仓≤{override_info['max_hold_days']}天"
        )
        return new_regime, override_info

    elif score >= 3 or (score >= 2 and consecutive >= 3):
        # 单日3/4分，或连续3天≥2分 → 升级BEAR_BOUNCE_OVERRIDE
        new_regime = 'BEAR_BOUNCE_OVERRIDE'
        override_info['triggered']          = True
        override_info['position_multiplier'] = config.REGIME_OVERRIDE_POSITION['BEAR_BOUNCE_OVERRIDE']
        override_info['score_threshold']     = config.REGIME_OVERRIDE_SCORE_THRESHOLD['BEAR_BOUNCE_OVERRIDE']
        override_info['max_hold_days']       = config.REGIME_OVERRIDE_MAX_HOLD['BEAR_BOUNCE_OVERRIDE']
        logger.warning(
            f"⚡ 快速翻转Override触发（{score}/4分，连续{consecutive}天）→ BEAR_TREND 临时升为 BEAR_BOUNCE_OVERRIDE\n"
            f"   命中条件：{' | '.join(reasons)}\n"
            f"   参数：仓位×{override_info['position_multiplier']}  "
            f"门槛≥{override_info['score_threshold']}分  "
            f"持仓≤{override_info['max_hold_days']}天"
        )
        return new_regime, override_info

    else:
        if score > 0:
            logger.info(f"📊 Override检测：{score}/4分，连续{consecutive}天（需单日≥3或连续3天≥2），维持BEAR_TREND | 命中：{' | '.join(reasons)}")
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


def _filter_holdertrade_date(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if df.empty:
        return df

    date_col = None
    if 'ann_date' in df.columns:
        date_col = 'ann_date'
    elif 'trade_date' in df.columns:
        date_col = 'trade_date'

    if not date_col:
        return df

    dates = df[date_col].astype(str).str.replace('-', '', regex=False).str[:8]
    return df[(dates >= start_date) & (dates <= end_date)].copy()


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
                holder_type=holder_type,
                fields='ts_code,ann_date,in_de'
            )
            df = _filter_holdertrade_date(df, start_date, trade_date)
            if not df.empty:
                if 'ts_code' not in df.columns or 'in_de' not in df.columns:
                    continue
                sell_df = df[df['in_de'].astype(str).str.upper() == 'DE']
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
            return pd.DataFrame(), latest_trade_date, 0, pd.DataFrame()

        # 修复：过滤特殊股票
        stock_basic = stock_basic[
            ~stock_basic['name'].str.contains(r'ST|＊ST|\*ST|退市', na=False, regex=True) &
            ~stock_basic['symbol'].str.startswith('688') &
            ~stock_basic['symbol'].str.startswith('300') &
            ~stock_basic['symbol'].str.startswith('8')
        ].reset_index(drop=True)
        if stock_basic.empty:
            return pd.DataFrame(), latest_trade_date, 0, pd.DataFrame()

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
                return pd.DataFrame(), latest_trade_date, 0, pd.DataFrame()
            latest_trade_date = prev_trade_dates[0]
            logger.info(f"回退到交易日：{latest_trade_date}")
            df_list = fetch_daily(latest_trade_date)

        if not df_list:
            logger.error("❌ 无法获取任何行情数据")
            return pd.DataFrame(), latest_trade_date, 0, pd.DataFrame()

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

        # volume_ratio 无效时回退到前一交易日（仅当数据日期是今天，盘中数据不完整才需要回退）
        # 历史已完结交易日即使 volume_ratio 有缺失也不回退，中转站可能就是这样
        today_str = datetime.now().strftime('%Y%m%d')
        if has_basic_data and df_basic['volume_ratio'].notna().mean() <= 0.5 and latest_trade_date >= today_str:
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
        df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce').fillna(5.0)
        df['volume_ratio'] = pd.to_numeric(df['volume_ratio'], errors='coerce').fillna(1.0)
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

        df = df[[
            "code", "name", "industry", "close", "change", "turnover",
            "volume_ratio", "main_net_inflow", "is_limit_up", "amount"
        ]].reset_index(drop=True)
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


def _detect_limit_up_event(grp: pd.DataFrame) -> Optional[Dict]:
    """
    从近60日行情中检测最近一次涨停事件及其后续回调质量。
    返回 None 表示无有效涨停事件。
    """
    if len(grp) < 10:
        return None

    # 在近60日内（不含今日）寻找最近一次涨停
    lookback = grp.iloc[:-1].tail(60)
    limit_up_mask = lookback['pct_chg'] >= 9.5
    if not limit_up_mask.any():
        return None

    # 取最近一次涨停（lookback的index就是grp的整数index，可直接使用）
    lu_pos = limit_up_mask[limit_up_mask].index[-1]  # grp的整数行位置
    lu_row = grp.iloc[lu_pos]

    lu_close = float(lu_row['close'])
    lu_high = float(lu_row['high'])
    lu_pct = float(lu_row['pct_chg'])
    prev_close = float(grp.iloc[lu_pos - 1]['close']) if lu_pos > 0 else lu_close
    theoretical_limit = prev_close * 1.10
    # 炸板：最高触及涨停但收盘未涨停
    is_zhaban = (lu_high >= theoretical_limit * 0.999) and (lu_pct < 9.5)
    if is_zhaban:
        return None

    # 换手率代理：涨停日成交量 / 20日均量
    vol_ma20 = float(grp['vol'].iloc[max(0, lu_pos - 20):lu_pos].mean()) if lu_pos >= 5 else float(grp['vol'].mean())
    lu_vol = float(lu_row['vol'])
    lu_turnover_proxy = lu_vol / vol_ma20 if vol_ma20 > 0 else 1.0

    # 涨停分级
    if 1.2 <= lu_turnover_proxy <= 2.8:
        lu_grade = 'A'
    elif lu_turnover_proxy < 1.2:
        lu_grade = 'B'
    else:
        lu_grade = 'C'

    # 回调数据（涨停日之后到今日）
    after_lu = grp.iloc[lu_pos + 1:]
    pullback_days = len(after_lu)
    if pullback_days < 1:
        return None

    today_close = float(grp.iloc[-1]['close'])
    pullback_pct = (lu_close - today_close) / lu_close * 100  # 正数=下跌
    pullback_low = float(after_lu['low'].min()) if not after_lu.empty else today_close

    # 回调期量能收缩（不含今日）
    after_lu_excl_today = after_lu.iloc[:-1]
    if len(after_lu_excl_today) > 0 and lu_vol > 0:
        vol_shrink = float(after_lu_excl_today['vol'].mean()) / lu_vol
    else:
        vol_shrink = 1.0

    is_valid_pullback = (
        2 <= pullback_days <= 15 and      # 放宽到15天，给股票更多整理时间
        1.5 <= pullback_pct <= 25.0 and   # 回调1.5%即可，上限放宽至25%
        vol_shrink < 1.0                  # 回调期均量 < 涨停日量（不需要明显收缩，只需不放量）
    )

    return {
        'lu_date_idx': lu_pos,
        'lu_pct': round(lu_pct, 2),
        'lu_turnover_proxy': round(lu_turnover_proxy, 2),
        'lu_grade': lu_grade,
        'pullback_days': pullback_days,
        'pullback_pct': round(pullback_pct, 2),
        'pullback_low': round(pullback_low, 2),
        'vol_shrink': round(vol_shrink, 3),
        'is_valid_pullback': is_valid_pullback,
    }


def _load_top_list_cache(trade_date: str) -> Dict[str, dict]:
    """
    加载龙虎榜缓存，返回当日上榜股票信息字典。
    key = 纯数字代码；value = {'inst_net_buy': float, 'reason': str}
      inst_net_buy > 0 表示机构席位净买入（万元）
      reason 为上榜原因（如'连续涨停'/'日涨幅偏离值达到7%'等）
    无缓存或异常时返回空字典。
    """
    cache_file = os.path.join('data', 'cache', 'top_list.parquet')
    if not os.path.exists(cache_file):
        return {}
    try:
        df = pd.read_parquet(cache_file)
        if 'trade_date' not in df.columns or 'ts_code' not in df.columns:
            return {}
        day_df = df[df['trade_date'] == trade_date].copy()
        if day_df.empty:
            return {}
        result = {}
        for _, row in day_df.iterrows():
            code = revert_code(row['ts_code'])
            # net_buy = 买入合计 - 卖出合计（万元）；字段名以实际parquet为准，缺失则0
            net_buy = 0.0
            if 'net_buy' in row.index and pd.notna(row['net_buy']):
                net_buy = float(row['net_buy'])
            reason = str(row.get('reason', '')) if 'reason' in row.index else ''
            # 同一股票可能多席位上榜，累加净买额
            if code in result:
                result[code]['inst_net_buy'] += net_buy
            else:
                result[code] = {'inst_net_buy': net_buy, 'reason': reason}
        return result
    except Exception:
        return {}


def _load_top_inst_cache(trade_date: str) -> Dict[str, float]:
    """
    加载龙虎榜机构专用席位买卖明细（top_inst），返回机构净买额字典。
    key = 纯数字代码；value = 机构净买入万元（buy - sell）
    用于补充 _load_top_list_cache 中 inst_net_buy 字段。
    """
    cache_file = os.path.join('data', 'cache', 'top_inst.parquet')
    if not os.path.exists(cache_file):
        return {}
    try:
        df = pd.read_parquet(cache_file)
        if 'trade_date' not in df.columns or 'ts_code' not in df.columns:
            return {}
        day_df = df[df['trade_date'] == trade_date].copy()
        if day_df.empty:
            return {}
        result = {}
        for _, row in day_df.iterrows():
            code = revert_code(row['ts_code'])
            buy  = float(row['buy'])  if ('buy'  in row.index and pd.notna(row['buy']))  else 0.0
            sell = float(row['sell']) if ('sell' in row.index and pd.notna(row['sell'])) else 0.0
            result[code] = result.get(code, 0.0) + (buy - sell)
        return result
    except Exception:
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

        # 近3日/10日累计涨幅 + 上涨天数（连续强度信号）
        # 反映股票是"持续走强"还是"昨天才动"，比单日涨幅更有预测力
        ret_3d = 0.0
        ret_10d = 0.0
        up_days_3d = 0
        if len(grp) >= 4:
            close_3d_ago = float(grp.iloc[-4]['close'])
            if close_3d_ago > 0:
                ret_3d = (float(latest['close']) - close_3d_ago) / close_3d_ago * 100
            recent_pct = grp.iloc[-3:]['pct_chg'].fillna(0)
            up_days_3d = int((recent_pct > 0).sum())
        if len(grp) >= 11:
            close_10d_ago = float(grp.iloc[-11]['close'])
            if close_10d_ago > 0:
                ret_10d = (float(latest['close']) - close_10d_ago) / close_10d_ago * 100

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

        # ── 布林带宽度 + ATR收缩率（VCP入场信号）──
        # 理论依据：Minervini《超级绩效》—— 布林带宽度收缩到近期低位是突破的前置条件
        # ATR收缩率（当前ATR/60日ATR代理）< 0.6 → 波动显著收缩 → 蓄势充分
        bb_width_pct = 0.5   # 默认中性（50%分位）
        atr_ratio    = 0.8   # 默认中性（无显著收缩）
        if len(grp) >= 25:
            # 布林带：20日均线 ± 2倍标准差
            bb_window = grp['close'].tail(20)
            bb_mid_v  = bb_window.mean()
            bb_std_v  = bb_window.std()
            bb_w_now  = (bb_std_v * 4) / bb_mid_v * 100  # 宽度（带宽/中线，%）
            # 近60日布林带宽度序列（滚动20日），取最大值作为基准
            bb_widths = []
            for j in range(max(0, len(grp) - 60), len(grp) - 19):
                w = grp['close'].iloc[j:j+20]
                if len(w) == 20:
                    ww = (w.std() * 4) / w.mean() * 100
                    bb_widths.append(ww)
            if bb_widths:
                bb_max = max(bb_widths)
                bb_width_pct = round(bb_w_now / bb_max if bb_max > 0 else 0.5, 3)
                # bb_width_pct < 0.4 → 带宽处于近60日20%分位以下 → 显著收缩

        if len(grp) >= 60:
            # ATR收缩率：当前14日ATR / 过去60日平均ATR
            tr_all = []
            for j in range(1, min(60, len(grp))):
                h = float(grp['high'].iloc[-j])
                l = float(grp['low'].iloc[-j])
                pc = float(grp['close'].iloc[-j - 1])
                tr_all.append(max(h - l, abs(h - pc), abs(l - pc)))
            atr_60d_avg = sum(tr_all) / len(tr_all) if tr_all else atr_14
            atr_ratio = round(atr_14 / atr_60d_avg if atr_60d_avg > 0 else 0.8, 3)
            # atr_ratio < 0.6 → ATR比近60日均值低40%以上 → 波动显著收缩

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

        # ── VSA量价分析信号（Volume Spread Analysis）──
        # 理论依据：Tom Williams VSA方法论 —— 收盘位置×相对量能识别主力行为
        # 4个核心信号，直接从价量数据计算，无主观成分
        vsa_no_supply  = False   # 供应枯竭（多头信号）：缩量回调且收盘偏低 → 主力未出货
        vsa_no_demand  = False   # 需求枯竭（空头信号）：缩量上涨且收盘偏高 → 量能不支撑涨势
        vsa_absorption = False   # 主力承接（多头信号）：放量下跌但收盘偏高 → 主力在低位买入
        if len(grp) >= 5 and 'high' in grp.columns and 'low' in grp.columns:
            spread     = float(latest['high']) - float(latest['low'])
            if spread > 0:
                close_pos  = (close - float(latest['low'])) / spread   # 0=收最低, 1=收最高
                rel_vol_v  = float(latest['vol']) / float(latest['vol_ma20']) if (
                    not pd.isna(latest['vol_ma20']) and float(latest['vol_ma20']) > 0
                ) else 1.0
                today_ret  = float(latest['pct_chg']) / 100 if 'pct_chg' in grp.columns else 0.0
                # no_supply：缩量（<75%均量）+ 下跌或微涨 + 收盘偏低（<50%位置）
                vsa_no_supply  = (rel_vol_v < 0.75) and (today_ret < 0.01) and (close_pos < 0.5)
                # no_demand：缩量（<75%均量）+ 上涨 + 收盘偏高（>50%位置）
                vsa_no_demand  = (rel_vol_v < 0.75) and (today_ret > 0.01) and (close_pos > 0.5)
                # absorption：放量（>1.5×均量）+ 下跌 + 收盘偏高（>60%位置，主力承接）
                vsa_absorption = (rel_vol_v > 1.5) and (today_ret < -0.005) and (close_pos > 0.6)

        # ── SEPA趋势模板条件数（Minervini，0-5分，A股简化版）──
        # 理论依据：Minervini《超级绩效》SEPA方法论 —— 均线堆栈结构是持续上涨的必要条件
        # A股简化：用MA20/MA60/MA120（代替MA50/MA150/MA200），条件放宽25%→20%
        sepa_score = 0
        if ma20_val and ma60_val:
            ma120_val = float(grp['close'].rolling(120).mean().iloc[-1]) if len(grp) >= 120 else None
            high_52w  = float(grp['high'].rolling(min(252, len(grp))).max().iloc[-1]) if 'high' in grp.columns else close * 1.3
            low_52w   = float(grp['low'].rolling(min(252, len(grp))).min().iloc[-1])  if 'low'  in grp.columns else close * 0.7
            if close > ma20_val:                                sepa_score += 1   # ① 价格>MA20
            if close > ma60_val:                                sepa_score += 1   # ② 价格>MA60
            if ma20_val > ma60_val:                             sepa_score += 1   # ③ MA20>MA60（金叉）
            if ma120_val and close > ma120_val:                 sepa_score += 1   # ④ 价格>MA120（长期趋势）
            if close >= low_52w * 1.20:                         sepa_score += 1   # ⑤ 距52周低点>20%（有充足涨幅空间）

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
            "ret_3d": round(ret_3d, 2),        # 近3日累计涨幅（%）
            "ret_10d": round(ret_10d, 2),       # 近10日累计涨幅（%），用于截面RS排名
            "up_days_3d": up_days_3d,           # 近3日上涨天数（0-3）
            "breakout_platform": breakout_platform,
            "volume_wash": volume_wash,
            "is_sharp_drop": is_sharp_drop,
            "close_vs_vwap": round(close_vs_vwap, 3),   # v3.3新增：收盘相对典型价偏离（%），>0.3%=尾盘强势
            "eod_strong": eod_strong,                    # v3.3新增：尾盘强势布尔值（VWAP代理法）
            "bb_width_pct": bb_width_pct,                # 布林带宽度相对近60日最大宽度的比例（<0.4=显著收缩）
            "atr_ratio":    atr_ratio,                   # ATR收缩率：当前14日ATR/近60日均ATR（<0.6=波动收缩）
            "vsa_no_supply":  vsa_no_supply,             # VSA供应枯竭信号（多头，缩量回调收低位）
            "vsa_no_demand":  vsa_no_demand,             # VSA需求枯竭信号（空头，缩量上涨收高位）
            "vsa_absorption": vsa_absorption,            # VSA主力承接信号（多头，放量下跌收高位）
            "sepa_score":   sepa_score,                  # SEPA趋势模板条件数（0-5，≥4=Stage2上升趋势）
            "limit_up_event": _detect_limit_up_event(grp),  # 涨停回调策略：近60日最近一次涨停事件
            "today_high": float(latest['high']),   # 今日最高价（收盘位置计算用）
            "today_low":  float(latest['low']),    # 今日最低价（收盘位置计算用）
        }
    logger.info(f"✅ 技术指标计算完成：{len(result)}/{len(codes)}只（有数据/候选总数）")
    return result


def select_stock_pool(stocks: pd.DataFrame, ma_dict: Dict, trade_date: str, financial_dict: Dict = None, sector_ma10: Dict = None, hot_sectors: Dict = None, sector_news_boosts: Dict = None, hot_concepts: List = None, market_style: str = 'sideways', is_caution: bool = False, sector_accel: Dict = None, macro_mode: str = 'cautious', score_threshold: int = 45, atr_multiplier: float = 1.5, is_backtest: bool = False, sector_avg_change: Dict = None) -> pd.DataFrame:
    """
    短线选股 reconstructed v8 baseline。
    主体恢复 2.0/4.1 的 momentum / weak_momentum / sideways 三风格候选池，
    板块项使用 v8 单日补涨评分，回避 v10 三因子补涨重构。
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
    if hot_sectors is None:
        hot_sectors = {}

    # Reconstructed baseline: restore the v4.1 three-style candidate pool.
    is_momentum      = (market_style == 'momentum')
    is_weak_momentum = (market_style == 'weak_momentum')
    if is_momentum:
        logger.info(f"v8 baseline short mode: momentum ({market_style})")
        st = stocks[
            (stocks['change'] > -9) &
            (stocks['change'] >= 1.0) &
            (stocks['change'] <= 7.0) &
            (stocks['volume_ratio'] >= 1.5) &
            (stocks['amount'] >= config.MIN_STOCK_AMOUNT_SHORT)
        ].copy()
    elif is_weak_momentum:
        logger.info(f"v8 baseline short mode: weak_momentum ({market_style})")
        st = stocks[
            (stocks['change'] > -9) &
            (stocks['change'] >= 0.0) &
            (stocks['change'] <= 5.0) &
            (stocks['volume_ratio'] >= 1.5) &
            (stocks['amount'] >= config.MIN_STOCK_AMOUNT_SHORT)
        ].copy()
    else:
        logger.info(f"v8 baseline short mode: sideways/catchup ({market_style})")
        st = stocks[
            (stocks['change'] > -9) &
            (stocks['change'] >= 0.0) &
            (stocks['change'] <= 5.0) &
            (stocks['volume_ratio'] >= 1.5) &
            (stocks['amount'] >= config.MIN_STOCK_AMOUNT_SHORT)
        ].copy()
    if st.empty:
        return pd.DataFrame()

    # ── 计算各行业今日平均涨幅（滞涨程度因子的基准）──
    # 优先使用传入的sector_avg_change（来自全市场数据更准确），fallback到从stocks计算
    _sector_avg_map: Dict[str, float] = sector_avg_change or {}
    if not _sector_avg_map and 'industry' in stocks.columns and 'change' in stocks.columns:
        for _ind, _grp in stocks.groupby('industry'):
            _sector_avg_map[_ind] = float(_grp['change'].mean())

    # ── 预计算行业平均换手率（用于技术结构因子的相对换手率评分）──
    industry_turnover_mean = {}
    if 'industry' in st.columns and 'turnover' in st.columns:
        for ind, grp in st.groupby('industry'):
            valid_t = grp['turnover'].replace(0, float('nan')).dropna()
            if len(valid_t) >= 3:
                industry_turnover_mean[ind] = float(valid_t.median())

    # 加载龙虎榜缓存（今日上榜为加分项）
    # 龙虎榜缓存：dict {code: {'inst_net_buy': float, 'reason': str}}
    top_list_info = _load_top_list_cache(trade_date)
    top_list_codes = set(top_list_info.keys())  # 兼容旧代码
    # 机构席位净买入补充：用 top_inst 数据覆盖/叠加 inst_net_buy
    inst_buy_map = _load_top_inst_cache(trade_date)
    for code, val in inst_buy_map.items():
        if code in top_list_info:
            top_list_info[code]['inst_net_buy'] = val
        else:
            top_list_info[code] = {'inst_net_buy': val, 'reason': ''}
    # 有效补涨板块集合：hot_sectors中分数>0的行业（今日有强势股且大部分未动）
    catchup_sectors = {ind for ind, score in hot_sectors.items() if score > 0}

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
            fin_data = financial_dict.get(code) or {}
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

        # ── 基础变量提取 ──
        industry = row.get("industry", "")
        close    = ma_data["close"]
        drawdown = ma_data["drawdown_from_high"]
        today_chg = float(row.get("change", row.get("pct_chg", 0.0)))

        # 常用MA信号
        above_ma5      = ma_data.get("above_ma5", False)
        above_ma10     = ma_data.get("above_ma10", False)
        above_ma20     = ma_data.get("above_ma20", False)
        just_broke_ma5 = ma_data.get("just_broke_ma5", False)
        near_ma20_support  = ma_data.get("near_ma20", False)
        breakout_platform  = ma_data.get("breakout_platform", False)
        vol_accel      = ma_data.get("vol_accelerating", False)
        is_positive = ma_data.get("is_positive_candle", True)
        is_short_shadow = ma_data.get("is_short_upper_shadow", True)
        kline_ok = is_positive and is_short_shadow
        vol_sustained = ma_data.get("vol_up", False)
        vol_continuous = ma_data.get("vol_3d_avg", 1.0) >= 1.5
        vol_ok = vol_continuous or vol_accel

        if sector_ma10 and not sector_ma10.get(industry, True):
            continue
        elif hot_sectors:
            sector_values = sorted(hot_sectors.values())
            median_heat = sector_values[len(sector_values) // 2] if sector_values else 0
            if hot_sectors.get(industry, 0) < median_heat:
                continue

        if is_momentum:
            near_high20 = drawdown <= 5
            ma_ok = above_ma20 and ma_data.get("ma20_above_ma60", False)
            not_at_top = True
            volume_signal = vol_sustained and kline_ok
            is_potential = above_ma20 and volume_signal and (near_high20 or breakout_platform)
        elif is_weak_momentum:
            ma5_above_ma10 = ma_data.get("ma5_above_ma10", False)
            not_at_top = (3 <= drawdown <= 12) or breakout_platform or (drawdown >= 5 and near_ma20_support)
            ma_ok = (above_ma10 or just_broke_ma5) and (ma5_above_ma10 or above_ma20)
            volume_signal = vol_ok or vol_sustained
            is_potential = not_at_top and ma_ok and volume_signal and kline_ok
        else:
            not_at_top = (drawdown >= 8) or (drawdown >= 3 and near_ma20_support) or breakout_platform
            ma_ok = above_ma5 or just_broke_ma5
            volume_signal = vol_sustained or vol_ok
            is_potential = not_at_top and ma_ok and volume_signal and kline_ok

        if not not_at_top:
            cnt_drawdown += 1
        elif not ma_ok:
            cnt_ma += 1
        elif not vol_ok and not is_momentum:
            cnt_vol_weak += 1

        if not is_potential:
            continue

        # ── 相对换手率（技术结构因子用）──
        turnover = float(row["turnover"])
        ind_median_t = industry_turnover_mean.get(industry, 0.0)
        relative_turnover = turnover / ind_median_t if ind_median_t > 0 else 1.0

        # ── 资金流变量（降级为过滤器，不参与主评分）──
        main_inflow = float(row["main_net_inflow"])
        mf_3d       = float(row.get("mf_3d", 0.0))
        margin_net  = float(row.get("margin_net_buy", 0.0))

        # 涨停基因
        has_gene = ma_data["has_limit_up_gene"]

        # 走势标签
        if row["is_limit_up"]:
            trend = "涨停量能启动"
        elif just_broke_ma5 and drawdown >= 10:
            trend = "低位突破MA5"
        elif just_broke_ma5:
            trend = "突破MA5放量"
        elif has_gene and drawdown >= 10:
            trend = "涨停基因低位吸筹"
        elif above_ma20:
            trend = "MA20上方蓄势"
        else:
            trend = "量能吸筹启动"

        # 预计持有天数
        upside_pct = (ma_data["target_price"] - close) / close * 100
        if upside_pct >= 6:
            hold_days_est = 2
        elif upside_pct >= 3:
            hold_days_est = 1
        else:
            hold_days_est = 1

        # Reconstructed v4.1/v8 score: keep the older multi-factor weights,
        # while using the v8 catchup sector score as the sector component.
        inflow_score = min(abs(main_inflow) / 100, 100) if main_inflow > 0 else 0
        is_sharp_drop = ma_data.get('is_sharp_drop', False)

        if is_momentum:
            if drawdown <= 3:
                drawdown_score = 100
            elif drawdown <= 8:
                drawdown_score = 100 - (drawdown - 3) / 5 * 30
            elif drawdown <= 15:
                drawdown_score = 70 - (drawdown - 8) / 7 * 40
            else:
                drawdown_score = max(30 - (drawdown - 15) / 10 * 30, 0)
        elif is_weak_momentum:
            if is_sharp_drop and drawdown >= 5:
                drawdown_score = 100
            elif 3 <= drawdown <= 12:
                drawdown_score = 100
            elif 1 <= drawdown < 3:
                drawdown_score = 40 + (drawdown - 1) / 2 * 60
            elif 12 < drawdown <= 18:
                drawdown_score = 100 - (drawdown - 12) / 6 * 50
            elif 18 < drawdown <= 28:
                drawdown_score = max(50 - (drawdown - 18) / 10 * 50, 0)
            elif drawdown > 28:
                drawdown_score = 0
            else:
                drawdown_score = max(drawdown / 3 * 40, 0)
        else:
            if is_sharp_drop and drawdown >= 8:
                drawdown_score = 100
            elif 8 <= drawdown <= 15:
                drawdown_score = 100
            elif 5 <= drawdown < 8:
                drawdown_score = 50 + (drawdown - 5) / 3 * 50
            elif 15 < drawdown <= 20:
                drawdown_score = 100 - (drawdown - 15) / 5 * 50
            elif 20 < drawdown <= 30:
                drawdown_score = max(50 - (drawdown - 20) / 10 * 50, 0)
            elif drawdown > 30:
                drawdown_score = 0
            else:
                drawdown_score = max(drawdown / 5 * 50, 0)

        import math
        vr = float(row["volume_ratio"])
        if vr <= 1.0:
            volume_ratio_score = 0
        elif vr >= 4.0:
            volume_ratio_score = 100
        else:
            volume_ratio_score = min(math.log2(vr) / math.log2(4) * 100, 100)

        if relative_turnover >= 2.0:
            turnover_score = 1.0
        elif relative_turnover >= 1.2:
            turnover_score = 0.8
        elif relative_turnover >= 0.8:
            turnover_score = 0.65
        else:
            turnover_score = 0.4
        turnover_norm = turnover_score * 100

        counter_trend_score = min(ma_data.get("counter_trend_resistance", 0.0) / 5 * 100, 100)
        sector_score = float(hot_sectors.get(industry, 0.0)) if hot_sectors else 0.0
        if macro_mode == 'defensive':
            sector_score *= 0.5
        sector_momentum_score = sector_score

        pattern_bonus = 0
        if breakout_platform:
            pattern_bonus += 5
        if ma_data.get("volume_wash", False):
            pattern_bonus += 5
        eod_strong = ma_data.get("eod_strong", False)
        close_vs_vwap = ma_data.get("close_vs_vwap", 0.0)
        if eod_strong:
            pattern_bonus += min(int(close_vs_vwap / 0.3) * 1.5, 5)
        pattern_score = min(pattern_bonus, 15) / 15 * 100

        wyckoff_score = ma_data.get("wyckoff_score", 0.0)
        accel_ratio = sector_accel.get(industry, 0.0)
        if accel_ratio >= 2.0:
            accel_score = 100
        elif accel_ratio >= 1.0:
            accel_score = (accel_ratio - 1.0) * 100
        else:
            accel_score = 0.0
        if macro_mode == 'defensive':
            accel_score *= 0.3

        if is_momentum:
            score = (
                volume_ratio_score * 0.15 +
                drawdown_score     * 0.10 +
                inflow_score       * 0.20 +
                turnover_norm      * 0.05 +
                sector_score       * 0.20 +
                pattern_score      * 0.05 +
                counter_trend_score * 0.05 +
                wyckoff_score      * 0.10 +
                accel_score        * 0.10
            )
        elif is_weak_momentum:
            score = (
                volume_ratio_score * 0.15 +
                drawdown_score     * 0.12 +
                inflow_score       * 0.18 +
                turnover_norm      * 0.05 +
                sector_score       * 0.15 +
                pattern_score      * 0.05 +
                counter_trend_score * 0.05 +
                wyckoff_score      * 0.15 +
                accel_score        * 0.10
            )
        else:
            score = (
                volume_ratio_score * 0.22 +
                drawdown_score     * 0.22 +
                inflow_score       * 0.12 +
                turnover_norm      * 0.04 +
                sector_score       * 0.15 +
                pattern_score      * 0.02 +
                counter_trend_score * 0.03 +
                wyckoff_score      * 0.12 +
                accel_score        * 0.08
            )
        score = min(score, 100.0)

        # ── 消息面加分（实盘专用）──
        news_sector_boost = sector_news_boosts.get(industry, 0.0) if sector_news_boosts else 0.0
        concept_boost = 0.0
        from news_analyzer import INDUSTRY_CONCEPT_KEYWORDS
        industry_kws = INDUSTRY_CONCEPT_KEYWORDS.get(industry, [])
        for concept_item in (hot_concepts or [])[:10]:
            if not concept_item or not isinstance(concept_item, dict):
                continue
            if industry_kws and any(kw in concept_item.get("concept", "") for kw in industry_kws):
                concept_boost = concept_item.get("heat", 0) * 0.1
                break

        # 龙虎榜加分（实盘用，回测关闭）
        top_list_bonus = 0.0 if is_backtest else (
            10.0 if code in top_list_codes else 0.0
        )

        # caution期降分
        final_score = score + news_sector_boost + concept_boost + top_list_bonus
        if is_caution:
            final_score -= 10.0
        final_score = max(0.0, min(final_score, 110.0))

        # 兼容旧输出字段（供分析用，不参与评分计算）
        catchup_bonus     = round(sector_momentum_score * 0.15, 1)
        mf_3d_bonus       = 0.0
        margin_bonus      = 0.0
        accel_component   = 0.0   # 已合并入sector_momentum_score

        # ── 状态机评分门槛过滤 ──
        if final_score < score_threshold:
            continue

        # ── 状态机ATR止损修正 ──
        base_atr    = ma_data.get('atr_14', 0.0)
        adj_stop    = round(ma_data['close'] - atr_multiplier * base_atr, 2)
        adj_stop    = max(adj_stop, round(ma_data['close'] * 0.80, 2))
        adj_stop    = min(adj_stop, round(ma_data['close'] * 0.993, 2))
        atr_stop_final = adj_stop

        hot_concept_match = concept_boost > 0

        valid_stocks.append({
            "code": row["code"],
            "name": row["name"],
            "industry": row["industry"],
            "close": close,
            "change": round(float(row["change"]), 2),
            "turnover": round(float(row["turnover"]), 2),
            "relative_turnover": round(relative_turnover, 2),
            "volume_ratio": round(float(row["volume_ratio"]), 2),
            "main_net_inflow": round(float(row["main_net_inflow"]), 2),
            "is_limit_up": bool(row["is_limit_up"]),
            "has_limit_up_gene": has_gene,
            "drawdown_from_high": ma_data["drawdown_from_high"],
            "target_price": ma_data.get("atr_target", ma_data["target_price"]),
            "stop_loss_price": atr_stop_final,
            "atr_14": ma_data.get("atr_14", 0.0),
            "wyckoff_score": round(wyckoff_score, 1),
            "accel_score": round(accel_component, 1),
            "volatility": ma_data["volatility"],
            "hold_days_est": hold_days_est,
            "trend": trend,
            "data_date": trade_date,
            "score": round(final_score, 2),
            "score_base": round(score, 2),
            "factor_volume_ratio": round(volume_ratio_score, 2),
            "factor_drawdown": round(drawdown_score, 2),
            "factor_inflow": round(inflow_score, 2),
            "factor_turnover": round(turnover_norm, 2),
            "factor_sector": round(sector_score, 2),
            "factor_pattern": round(pattern_score, 2),
            "factor_counter_trend": round(counter_trend_score, 2),
            "factor_wyckoff": round(wyckoff_score, 2),
            "factor_accel": round(accel_score, 2),
            "market_style": market_style,
            "macro_mode": macro_mode,
            "news_boost": round(news_sector_boost, 1),
            "concept_boost": round(concept_boost, 1),
            "rs_rank": ma_data.get("ret_10d", 0.0),   # 暂存10日涨幅，后面做截面排名回填
            "rs_boost": 0.0,
            "reversal_penalty": 0,
            "hot_concept_match": hot_concept_match,
            "ma5": ma_data["ma5"],
            "ma10": ma_data["ma10"],
            "ma20": ma_data.get("ma20"),
            "ma60": ma_data.get("ma60"),
            "high20": ma_data["high20"],
            "low20": ma_data["low20"],
            "eod_strong": ma_data.get("eod_strong", False),
            "close_vs_vwap": ma_data.get("close_vs_vwap", 0.0),
            "roe": round(fin_data.get('roe', 0), 2) if fin_data.get('roe') else None,
            "revenue_growth": round(fin_data.get('revenue_growth', 0), 2) if fin_data.get('revenue_growth') else None,
            "debt_ratio": round(fin_data.get('debt_ratio', 0), 2) if fin_data.get('debt_ratio') else None,
            # 新增调试字段：便于分析各方案加分贡献
            "top_list_bonus": round(top_list_bonus, 1),
            "catchup_bonus": round(catchup_bonus, 1),
            "mf_3d_bonus": round(mf_3d_bonus, 1),
            "margin_bonus": round(margin_bonus, 1),
            "mf_3d": round(mf_3d, 0),
            "margin_net_buy": round(margin_net, 0),
        })

    df_pool = pd.DataFrame(valid_stocks)
    if not df_pool.empty:
        df_pool = df_pool.sort_values(
            by=["score"],
            ascending=[False]
        ).head(20).reset_index(drop=True)

    logger.info(
        f"📊 reconstructed v8短线过滤明细：基础候选{len(st)}只 | "
        f"无MA数据{cnt_no_ma} | 均线破位{cnt_ma} | 财务不符{cnt_financial}"
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
    score_threshold: float = 70,   # Z-Score分布下的最低准入分（20~95范围，均值60，70≈前25%）
) -> pd.DataFrame:
    """
    波段选股 v4.1（中长线，持仓无固定时限，以技术信号为准）。
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    设计依据：
      - Jegadeesh & Titman (1993)：2-12月动量因子在A股有效
      - Liu/Stambaugh/Yuan (2019)：换手率因子（A股特有）
      - O'Shaughnessy：相对强度排名用于选股
      - Minervini VCP 概念：价格从高点适度回落，量能收缩后放量突破
      - Weinstein四阶段（A股改版）：用MA60代替MA150判断第二阶段
      - Asness et al.(2013) "Value and Momentum Everywhere"：
        截面Z-Score标准化，解决评分区间过窄（53~72分→20~95分）问题
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    5维评分体系（Z-Score截面标准化合成，映射到20~95分区间）：
      ① 价格动量     30% —— MA20斜率 + 行业RS×0.1协同加成
      ② 资金流       25% —— 主力净流入（万元）+ 尾盘/量能信号加成
      ③ 行业相对强度 20% —— 行业20日RS超额收益（industry_rs，%）
      ④ 财务质量     15% —— ROE + netprofit_yoy×0.3 + 增速加速+5
      ⑤ 入场质量     10% —— 回调幅度VCP甜蜜区 + 量缩/尾盘/K线/Wyckoff加成
    评分方法：两轮计算——第一轮硬过滤+收集raw值，第二轮Z-Score合成
    score = clip(composite_z × 10 + 60, 20, 95)，平均股≈60分，±1σ≈±10分

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

    # 波段策略只在持续牛市状态开仓（不含 Override——Override是单日应急机制，不适合60天波段仓）
    if regime not in ('BULL_TREND', 'BULL_PULLBACK'):
        logger.info(f"📊 波段选股跳过（当前机制：{regime}，仅持续牛市执行）")
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
        if not mdata:
            continue
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

    # ── 第一轮：硬过滤 + 收集各维度原始值（用于截面Z-Score）──
    # 设计依据：Asness et al.(2013) "Value and Momentum Everywhere"
    # Z-Score截面标准化使各维度量纲统一，合成评分自然拉开区间（解决53~72分过窄问题）
    raw_records = []  # 通过硬过滤的股票，存储原始维度值

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
        # 波段策略核心：买"在上升趋势中充分回调"的股，而非追"刚创新高"的股
        # 参考：Minervini VCP原则 + CLAUDE.md原始设计（回调5%~35%）
        drawdown = ma_data.get("drawdown_from_high", 0.0)
        if drawdown < 3.0:
            # 回调不足3%（含创新高）：洗盘不充分，不是波段最佳入场点
            cnt_drawdown += 1
            continue
        if drawdown > 35.0:
            # 超过35%回调：长期趋势可能已破坏，不宜做波段
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
        # ── 第一轮：收集各维度原始值（raw），暂不计算最终评分 ──
        # 评分将在第二轮用截面Z-Score统一标准化后合成
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        main_net_inflow = float(row.get("main_net_inflow", 0))
        vol_accel  = ma_data.get("vol_accelerating", False)
        eod_strong = ma_data.get("eod_strong", False)
        vol_shrinking = not ma_data.get("vol_trend_up", False)

        # ① 动量原始值：基础趋势强度（MA60斜率 + MA20站上MA60距离）
        # 理论：波段"在上升趋势中的健康回调买入"，趋势强度 = 底层月线斜率
        # 用 ma20_slope（近5日斜率）反映近期动量辅助，但主权重给长期趋势健康度
        # （避免奖励已经"冲高后顶部"的股，它们MA20斜率很高但不是好入场时机）
        rs_raw = industry_rs.get(industry, 0.0) if industry_rs else 0.0
        # MA20相对MA60的差值（%）：>0=在均线上方（牛市趋势中），值越大=趋势越强
        # 结合MA20斜率：正斜率=趋势继续向上
        ma20_vs_ma60_pct = (ma20 - ma60) / ma60 * 100 if ma60 > 0 else 0.0
        raw_momentum = max(0.0, ma20_vs_ma60_pct) + max(0.0, ma20_slope) * 2

        # ② 资金流原始值：主力净流入（万元），用成交额归一化（解决大市值股票绝对额大的问题）
        # 归一化：净流入比例 = 主力净流入 / 当日成交额（%），消除市值差异
        amount = float(row.get("amount", 1)) or 1.0  # 成交额（千元）
        # 主力净流入占成交额的比例（%），正值=净流入，负值=净流出
        inflow_pct = main_net_inflow / (amount / 10) if amount > 0 else 0.0  # 万元/万元 = 比例
        raw_flow = inflow_pct  # 用比例代替绝对额，消除市值差异
        if eod_strong:
            raw_flow += 0.5    # 尾盘强势：+0.5个百分点等效加成
        elif vol_accel:
            raw_flow += 0.2    # 量能加速：+0.2个百分点加成
        # VSA承接信号额外加成（主力承接=资金流质量极高）
        if ma_data.get("vsa_absorption", False):
            raw_flow += 0.8    # 主力在低位承接，资金流质量最高

        # ③ 行业RS原始值（%，超额收益）
        raw_rs = rs_raw

        # ④ 财务质量原始值：ROE + 净利润增速 + 现金流质量 + 低杠杆
        # 理论依据：AQR QMJ(2019) —— 质量因子三支柱：盈利能力、成长性、安全性
        # fina_indicator 已有字段：roe、netprofit_yoy、ocfps（每股经营现金流）、debt_to_assets
        roe_val     = fin_data.get('roe')
        profit_data = profit_growth_dict.get(code, {})
        yoy         = profit_data.get('netprofit_yoy')
        # 财务合成：ROE(主)+netprofit_yoy×0.3(辅)+现金流质量+低杠杆安全性+增速加速奖励
        raw_fin = 0.0
        if roe_val is not None:
            raw_fin += float(roe_val)           # 盈利能力主项（ROE，%）
        if yoy is not None:
            raw_fin += float(yoy) * 0.3        # 成长性（净利润增速折算，×0.3压缩量纲）
        # 现金流质量：ocf_to_netprofit（经营现金流/净利润，fina_indicator字段）
        # > 1.0 说明利润含金量高；< 0.5 说明应收账款多，利润质量差
        ocf_ratio = fin_data.get('ocf_to_netprofit')
        if ocf_ratio is not None:
            try:
                ocf_val = float(ocf_ratio)
                if ocf_val > 1.5:
                    raw_fin += 8.0              # 现金流充裕，利润含金量极高
                elif ocf_val > 1.0:
                    raw_fin += 5.0              # 现金流健康
                elif ocf_val < 0.3:
                    raw_fin -= 5.0              # 现金流不足，利润质量差
            except (ValueError, TypeError):
                pass
        # 安全性：低杠杆加分（debt_to_assets，资产负债率%，越低越安全）
        debt_ratio = fin_data.get('debt_ratio')
        if debt_ratio is not None:
            try:
                dr = float(debt_ratio)
                if dr < 30:
                    raw_fin += 5.0              # 低杠杆，财务安全
                elif dr < 50:
                    raw_fin += 2.0              # 适中
                elif dr > 75:
                    raw_fin -= 5.0              # 高杠杆，安全性差
            except (ValueError, TypeError):
                pass
        if profit_data.get('profit_growth_accel', False):
            raw_fin += 5.0                      # 增速加速额外加5个百分点等效分

        # ⑤ 入场质量原始值：回调幅度适中性（VCP甜蜜区）
        drawdown_abs = abs(drawdown)
        if 5 <= drawdown_abs <= 15:
            raw_entry = 100.0
        elif drawdown_abs < 5:
            raw_entry = drawdown_abs / 5 * 60
        elif drawdown_abs <= 25:
            raw_entry = max(0.0, 100 - (drawdown_abs - 15) * 5)
        else:
            raw_entry = max(0.0, 100 - (drawdown_abs - 15) * 8)
        # 量能收缩、尾盘强势、K线形态、Wyckoff结构加成
        if vol_shrinking:
            raw_entry += 15
        if eod_strong:
            raw_entry += 10
        if ma_data.get("is_positive_candle", False):
            raw_entry += 8
        if ma_data.get("wyckoff_score", 0) >= 60:
            raw_entry += 7
        # VCP形态加成（Minervini布林带+ATR收缩信号）
        bb_width_pct = ma_data.get("bb_width_pct", 0.5)
        atr_ratio    = ma_data.get("atr_ratio", 0.8)
        if bb_width_pct < 0.4:                      # 布林带显著收缩（处于近期低位20%分位）
            raw_entry += 20
        elif bb_width_pct < 0.6:                    # 布林带中度收缩
            raw_entry += 10
        if atr_ratio < 0.6:                         # ATR显著收缩（波动比近60日均值低40%+）
            raw_entry += 15
        elif atr_ratio < 0.75:                      # ATR中度收缩
            raw_entry += 7
        # VSA信号加成（波段策略，供应枯竭和主力承接是最强入场信号）
        if ma_data.get("vsa_no_supply", False):     # 供应枯竭：缩量回调收低位=主力未出货，最佳波段入场信号
            raw_entry += 18
        if ma_data.get("vsa_absorption", False):    # 主力承接：放量下跌收高位=低位有承接，确认支撑有效
            raw_entry += 12
        # SEPA趋势模板：≥4条=Stage2上升趋势（Minervini最佳入场前提）
        sepa = ma_data.get("sepa_score", 0)
        if sepa >= 4:
            raw_entry += 10   # 结构完整的上升趋势
        elif sepa >= 3:
            raw_entry += 4    # 趋势初步确立

        # ── 出场价格计算（与评分无关，直接计算）──
        high20          = ma_data.get("high20", close * 1.15)
        atr_14          = ma_data.get("atr_14", close * 0.02)
        target_price    = round(max(high20 * 1.5, close * 1.50), 2)
        stop_loss_price = round(ma60 * 0.98, 2)
        buy_low         = round(close - atr_14 * 0.5, 2)
        buy_high        = round(close + atr_14 * 0.3, 2)

        # 板块共振附加验证（不强制，仅记录）
        sector_aligned = sector_ma10.get(industry, True) if sector_ma10 else True

        raw_records.append({
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
            "trailing_stop_pct": 10.0,
            # ── 兼容旧字段 ──
            "trend_strength":   round(min(ma20_slope / 0.5 * 100, 100), 2),
            "hold_weeks_est":   0,
            "data_date":        trade_date,
            # ── 各维度原始值（第二轮Z-Score用）──
            "_raw_momentum":    raw_momentum,
            "_raw_flow":        raw_flow,
            "_raw_rs":          raw_rs,
            "_raw_fin":         raw_fin,
            "_raw_entry":       raw_entry,
        })

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ── 第二轮：截面Z-Score标准化 + 加权合成 longterm_score ──
    # 设计依据：Asness et al.(2013) "Value and Momentum Everywhere"
    # Z-Score使各维度在截面上均值为0、标准差为1，消除量纲差异，
    # 合成后自然拉开评分区间（解决原来53~72分仅19分跨度的问题）。
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if raw_records:
        import numpy as np

        # 提取各维度原始值数组
        arr_momentum = np.array([r["_raw_momentum"] for r in raw_records], dtype=float)
        arr_flow     = np.array([r["_raw_flow"]     for r in raw_records], dtype=float)
        arr_rs       = np.array([r["_raw_rs"]       for r in raw_records], dtype=float)
        arr_fin      = np.array([r["_raw_fin"]      for r in raw_records], dtype=float)
        arr_entry    = np.array([r["_raw_entry"]    for r in raw_records], dtype=float)

        def _zscore(arr: np.ndarray) -> np.ndarray:
            """截面Z-Score，若标准差≈0（全相同值）则返回全零，防止除零"""
            std = arr.std()
            if std < 1e-9:
                return np.zeros_like(arr)
            return (arr - arr.mean()) / std

        z_momentum = _zscore(arr_momentum)
        z_flow     = _zscore(arr_flow)
        z_rs       = _zscore(arr_rs)
        z_fin      = _zscore(arr_fin)
        z_entry    = _zscore(arr_entry)

        # 加权合成（权重调整：降低追涨偏差，强化入场质量）
        # 分析依据：IC分析显示原momentum(30%)+rs(20%)=50%追涨权重导致负IC
        # 波段策略本质是"在健康回调时买入上升趋势股"，不是"追涨已经启动的股"
        # 调整逻辑：
        #   momentum 25%→15%：减少"追涨已动"偏差
        #   entry    10%→25%：提升VCP/回调质量信号权重（这是波段核心入场信号）
        #   flow     25%不变：资金流是有效的领先信号
        #   fin      15%→20%：基本面质量是持续性保证
        #   rs       20%→20%：行业共振保留（相对强度仍有效，但不单独奖励已动的）
        composite_z = (
            0.15 * z_momentum +   # 动量：降低权重，避免买已经冲高的股
            0.25 * z_flow     +   # 资金流：维持，领先指标
            0.20 * z_rs       +   # 行业RS：维持，确保行业顺风
            0.20 * z_fin      +   # 基本面：提高，波段需要基本面支撑
            0.20 * z_entry        # 入场质量：大幅提高，VCP+回调是核心选点信号
        )
        longterm_scores = np.clip(composite_z * 10 + 60, 20, 95)

        for i, rec in enumerate(raw_records):
            z_i = composite_z[i]
            score = float(longterm_scores[i])
            rec["longterm_score"]  = round(score, 1)
            # 各维度贡献分（可视化用，保持与原明细字段名兼容）
            rec["score_momentum"]  = round(float(z_momentum[i]) * 3.0, 2)  # ×3便于观察量级
            rec["score_flow"]      = round(float(z_flow[i])     * 2.5, 2)
            rec["score_rs"]        = round(float(z_rs[i])       * 2.0, 2)
            rec["score_fin"]       = round(float(z_fin[i])      * 1.5, 2)
            rec["score_entry"]     = round(float(z_entry[i])    * 1.0, 2)
            # 清理内部原始值字段（不写入最终输出）
            for k in ("_raw_momentum", "_raw_flow", "_raw_rs", "_raw_fin", "_raw_entry"):
                rec.pop(k, None)
            valid_stocks.append(rec)

    # ── 按综合评分排序，应用最低分门槛后输出Top20 ──
    df_pool = pd.DataFrame(valid_stocks)
    if not df_pool.empty:
        # 应用最低分门槛（过滤低质量股，解决大量93笔中低分股拉低胜率的问题）
        before_threshold = len(df_pool)
        df_pool = df_pool[df_pool["longterm_score"] >= score_threshold]
        filtered_by_threshold = before_threshold - len(df_pool)
        if filtered_by_threshold > 0:
            logger.debug(f"   波段门槛过滤：{filtered_by_threshold}只低于{score_threshold}分被排除")
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
        provider = config.AI_CONFIG.get("provider", "AI")
        env_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "DASHSCOPE_API_KEY"
        logger.warning(
            f"{provider} API key is not configured; skipping AI analysis.\n"
            f"Please set environment variable {env_name}."
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
def run_daily_selection(trade_date: str, enable_news: bool = True, include_longterm: bool = True) -> Dict:
    """
    完整的单日选股流程，实盘和回测共用同一套逻辑。
    无论此函数怎么修改，调用方（main() 和 backtest_v2.py）都自动保持一致。

    Args:
        trade_date:   指定交易日期 YYYYMMDD（回测传历史日期，实盘传 None 或最新日期）
        enable_news:  是否拉取实时新闻（回测时传 False，节省时间且无意义）
        include_longterm: 是否执行波段选股（短线回测传 False，避免混入口径和拖慢速度）

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
    # 短线v7.0（趋势回调+板块补涨）：放宽涨幅范围，回调股(-10%~+3%)和补涨股都需要
    # max_change=11 保留今日涨停股（用于计算板块强势计数，不作为直接买入候选）
    all_stocks, actual_date, _, market_pct_df = get_all_stocks(
        min_change=-5, max_change=7,
        min_turnover=1, max_turnover=20,
        min_volume_ratio=0,
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
        # 提前计算情绪数据，避免报告显示"市场数据获取失败"
        sentiment_data = get_market_sentiment(actual_date, market_pct_df)
        sentiment_data['operation_mode']  = 'stop'
        sentiment_data['position_advice'] = '空仓（熊市下跌阶段）'
        sentiment_data['decision_reason'] = 'BEAR_TREND：MA60斜率向下，强制空仓'
        result['sentiment_data']  = sentiment_data
        result['operation_mode']  = 'stop'
        result['position_advice'] = '空仓（熊市下跌阶段）'
        return result

    # ── 2.6 一级筛选：周线宏观方向（Elder三重滤网第一重）──
    logger.info("📊 判断周线宏观趋势（三级共振第一级）...")
    macro_mode, macro_data = get_weekly_macro_trend(actual_date)
    result['macro_mode'] = macro_mode
    result['macro_data'] = macro_data

    # ── 实验1A：获取前2个交易日涨停数据，用于板块时序乘数 ──
    # 用于 get_sector_catchup_scores 内部判断"板块是新鲜启动还是已热"
    # 离线模式：pro.daily() 读本地 parquet，速度极快；实盘：2次轻量接口调用
    _prev_stocks_list = []
    try:
        _prev_dates_all = get_recent_trade_dates(actual_date, n=3)
        _prev_trade_dates = [d for d in _prev_dates_all if d < actual_date][:2]
        _ind_map_timing = _get_industry_map()
        for _pd in _prev_trade_dates:
            _prev_daily = pro.daily(trade_date=_pd, fields='ts_code,pct_chg')
            if not _prev_daily.empty and _ind_map_timing:
                _prev_daily = _prev_daily.copy()
                _prev_daily['industry'] = _prev_daily['ts_code'].map(_ind_map_timing)
                _prev_stocks_list.append(_prev_daily[['ts_code', 'pct_chg', 'industry']])
    except Exception as _e:
        logger.debug(f"[时序乘数] 获取历史数据失败，时序乘数将降级为无乘数模式：{_e}")
        _prev_stocks_list = None  # None → get_sector_catchup_scores 不启用乘数

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

    # ── 6. 板块补涨评分（reconstructed v8 baseline, no timing multiplier）──
    logger.info("📊 计算板块补涨机会（reconstructed v8 baseline）...")
    # ⚠️ 行业映射用 _get_industry_map()（全量，含涨停股），不用 all_stocks（已截断 max_change=7）
    _catchup_input = all_stocks.copy()
    if market_pct_df is not None and not market_pct_df.empty and 'pct_chg' in market_pct_df.columns:
        _ind_map_catchup = _get_industry_map()
        if _ind_map_catchup:
            _mkt = market_pct_df.copy()
            _mkt['industry'] = _mkt['ts_code'].map(_ind_map_catchup)
            _mkt = _mkt.dropna(subset=['industry']).rename(columns={'pct_chg': 'change'})
            _catchup_input = _mkt[['ts_code', 'industry', 'change']].reset_index(drop=True)
    hot_sectors = get_sector_catchup_scores(_catchup_input, prev_stocks_list=None)

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
    # 计算各行业今日平均涨幅（用于滞涨程度因子，从全市场数据更准确）
    _sector_avg_change: Dict[str, float] = {}
    if 'industry' in all_stocks.columns and 'change' in all_stocks.columns:
        for _ind, _grp in all_stocks.groupby('industry'):
            _sector_avg_change[_ind] = float(_grp['change'].mean())

    logger.info(f"📊 执行短线选股（模式：{operation_mode}，风格：{market_style}，机制：{regime}）...")
    stock_pool = select_stock_pool(
        all_stocks, ma_dict, actual_date, financial_dict, sector_ma10, hot_sectors,
        sector_news_boosts=sector_news_boosts, hot_concepts=hot_concepts,
        market_style=market_style, is_caution=is_caution,
        sector_accel=sector_accel, macro_mode=macro_mode,
        score_threshold=score_threshold, atr_multiplier=atr_multiplier,
        is_backtest=(type(pro).__name__ == 'LocalDataProxy'),
        sector_avg_change=_sector_avg_change
    )
    live_factor_profile = getattr(config, 'SHORT_LIVE_FACTOR_PROFILE', 'original')
    live_style_gate = getattr(config, 'SHORT_LIVE_STYLE_GATE', 'none')
    live_score_order = getattr(config, 'SHORT_LIVE_SCORE_ORDER', 'desc')
    is_offline_backtest = type(pro).__name__ == 'LocalDataProxy'
    if (
        not is_offline_backtest
        and not stock_pool.empty
        and (live_factor_profile != 'original' or live_style_gate != 'none')
    ):
        before_profile_count = len(stock_pool)
        stock_pool = apply_short_profile(
            stock_pool,
            factor_profile=live_factor_profile,
            style_gate=live_style_gate,
            score_order=live_score_order,
        ).head(20).reset_index(drop=True)
        logger.info(
            f"短线实盘基准后处理：profile={live_factor_profile} "
            f"style_gate={live_style_gate}  {before_profile_count}只 → {len(stock_pool)}只"
        )
    result['stock_pool'] = stock_pool

    # ── 波段选股：仅在真正牛市状态（BULL_TREND / BULL_PULLBACK）时执行 ──
    # v4.0改动：从 operation_mode=='full' 改为 regime in BULL 系列
    # v5.1修复：去除 BULL_PULLBACK_OVERRIDE —— 该状态是熊市单日紧急Override，
    #           波段策略持仓长达60天，不应在仅有单日信号的熊市中开仓。
    longterm_regime_allowed = include_longterm and regime in ('BULL_TREND', 'BULL_PULLBACK')
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
            score_threshold=getattr(config, 'LONGTERM_SCORE_THRESHOLD', {}).get(regime, 70),
        )
        result['longterm_pool'] = longterm_pool
    elif include_longterm:
        logger.info(f"📊 波段选股跳过（机制：{regime}，仅BULL_TREND/BULL_PULLBACK执行）")
    else:
        logger.info("📊 波段选股跳过（短线回测 include_longterm=False）")

    return result


# ==================== 主程序 ====================
def main():
    include_longterm = bool(getattr(config, 'ENABLE_LONGTERM_LIVE', False))
    mode_label = "短线 + 波段" if include_longterm else "短线"
    logger.info(f"===== 🚀 A股AI选股助手启动（{mode_label}）=====")
    start_time = datetime.now()

    logger.info("\n【📈 选股与AI分析】")
    ai_analysis = []
    ai_longterm = []

    # ── 调用统一选股流程（回测/实盘共用同一套逻辑）──
    sel = run_daily_selection(
        trade_date=None,
        enable_news=True,
        include_longterm=include_longterm,
    )
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

    # 打印宏观趋势（BEAR_TREND时提前return，get_weekly_macro_trend未执行，macro_data为空）
    macro_label = {'active': '🟢 主动做多', 'cautious': '🟡 谨慎观望', 'defensive': '🔴 防御避险'}.get(macro_mode, macro_mode)
    if macro_data:
        price_vs_ma100 = macro_data.get('price_vs_ma100', 0)
        ma20_slope     = macro_data.get('ma20_slope_pct', 0)
        # 用文字说明斜率含义
        slope_desc = "周线上升" if ma20_slope > 0.05 else ("周线走平" if ma20_slope >= -0.05 else "周线下行")
        logger.info(
            f"\n【🌍 宏观趋势】{macro_label}"
            f" | CSI300距MA100={price_vs_ma100:+.1f}%  周线MA20={slope_desc}（{ma20_slope:+.3f}%/日）"
        )
    else:
        logger.info(f"\n【🌍 宏观趋势】{macro_label}（BEAR_TREND空仓，未计算周线数据）")

    # 打印四状态机信息：结论先行，数据辅助，术语加中文解释
    regime      = sel.get('regime', 'BULL_TREND')
    regime_data = sel.get('regime_data', {})
    pos_mult    = sel.get('position_multiplier', 1.0)
    regime_label = {
        'BULL_TREND':              '🟢 牛市趋势',
        'BULL_PULLBACK':           '🟡 牛市回调',
        'BEAR_BOUNCE':             '🟠 熊市反弹',
        'BEAR_TREND':              '🔴 熊市下跌',
        'BEAR_BOUNCE_OVERRIDE':    '⚡ 熊市翻转信号',
        'BULL_PULLBACK_OVERRIDE':  '⚡ 熊市强力翻转',
    }.get(regime, regime)
    top_n_actual = max(1, round(3 * pos_mult)) if pos_mult > 0 else 0
    # 仓位建议用人话
    pos_desc = {
        0.0:  '空仓，不操作',
        0.33: f'极轻仓，最多选Top{top_n_actual}只',
        0.5:  f'半仓，最多选Top{top_n_actual}只',
        0.67: f'七成仓，选Top{top_n_actual}只',
        1.0:  f'正常仓位，选Top{top_n_actual}只',
    }.get(pos_mult, f'仓位×{pos_mult}，选Top{top_n_actual}只')
    price_vs_ma60 = regime_data.get('price_vs_ma60_pct', 0)
    ma60_slope    = regime_data.get('ma60_slope_pct', 0)
    slope_desc    = "MA60上行" if ma60_slope > 0.01 else ("MA60走平" if ma60_slope >= -0.01 else "MA60下行")
    logger.info(
        f"\n【🛡️ 市场机制】{regime_label} → {pos_desc}"
        f"\n   依据：CSI300距MA60={price_vs_ma60:+.1f}%，{slope_desc}（{ma60_slope:+.4f}%/日）"
    )
    # Override触发时补充说明
    if regime_data.get('override_triggered'):
        reasons = ' | '.join(regime_data.get('override_reasons', []))
        score   = regime_data.get('override_score', 0)
        logger.warning(
            f"   ⚡ Override触发（{score}/4条件）：{reasons}"
            f"\n   ⚠️  属熊市临时反弹，严格控仓，止损不拖延"
        )

    # 打印短线建议（取评分前3）
    logger.info("\n【🚀 短线建议 Top3（1-3天）】")
    short_top3 = sorted(ai_analysis, key=lambda x: x.get("score", 0), reverse=True)[:3]
    if short_top3:
        for rank, item in enumerate(short_top3, 1):
            buy_low  = round(item['close'] * 0.99, 2)
            buy_high = round(item['close'] * 1.01, 2)
            risk_icon = {'低': '🟢', '中等': '🟡', '高': '🔴'}.get(item.get('risk', ''), '⚪')
            logger.info(
                f"  #{rank} {item['code']} {item['name']}  评分{item.get('score', 0)}分  "
                f"{risk_icon}风险:{item.get('risk','-')}  目标{item.get('target_price','-')}元  止损{item.get('stop_loss_price','-')}元\n"
                f"     买入区间：{buy_low}~{buy_high}元\n"
                f"     {item.get('reason','')}"
            )
    else:
        logger.info("  暂无短线候选")

    # 打印波段建议（取评分前3）
    logger.info("\n【📊 波段建议 Top3（1-8周）】")
    long_top3 = sorted(ai_longterm, key=lambda x: x.get("trend_strength", 0), reverse=True)[:3]
    if long_top3:
        for rank, item in enumerate(long_top3, 1):
            risk_icon = {'低': '🟢', '中等': '🟡', '高': '🔴'}.get(item.get('risk', ''), '⚪')
            logger.info(
                f"  #{rank} {item['code']} {item['name']}  评分{item.get('score', 0)}分  "
                f"{risk_icon}风险:{item.get('risk','-')}  目标{item.get('target_price','-')}元  止损{item.get('stop_loss_price','-')}元\n"
                f"     买入区间：{item.get('buy_price_low','-')}~{item.get('buy_price_high','-')}元  "
                f"预计持有{item.get('hold_weeks','-')}周\n"
                f"     {item.get('reason','')}"
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
        regime=regime,
        regime_data=regime_data,
        position_multiplier=pos_mult,
        market_style=sel.get('market_style', ''),
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
            'original_score':   row.get('original_score', ''),
            'experiment_score': row.get('experiment_score', ''),
            'factor_profile':   row.get('factor_profile', ''),
            'style_gate':       row.get('style_gate', ''),
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


def _write_daily_report(trade_date: str, ai_analysis: List[Dict], ai_longterm: List[Dict], sentiment_data: Dict = None, macro_mode: str = 'cautious', macro_data: Dict = None, regime: str = 'BULL_TREND', regime_data: Dict = None, position_multiplier: float = 1.0, market_style: str = ''):
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
        sentiment       = sentiment_data.get('sentiment', '未知')
        ratio           = sentiment_data.get('ratio', 0)
        limit_up        = sentiment_data.get('limit_up_count', 0)
        limit_down      = sentiment_data.get('limit_down_count', 0)
        news_sentiment  = sentiment_data.get('news_sentiment', {})
        decision_reason = sentiment_data.get('decision_reason', '')

        if macro_data is None:
            macro_data = {}
        if regime_data is None:
            regime_data = {}

        # ── 1. 市场情绪
        emotion_icon = {'高涨': '🟢', '正常': '🔵', '偏弱': '🟡', '恐慌': '🔴'}.get(sentiment, '⚪')
        emotion_desc = {
            '高涨': '多头热情高，短线资金活跃',
            '正常': '情绪平稳，无明显方向偏向',
            '偏弱': '多头动能不足，谨慎对待反弹',
            '恐慌': '恐慌性抛售，以防守为主',
        }.get(sentiment, '')
        lines.append(
            f"  市场情绪：{emotion_icon} {sentiment} — {emotion_desc}\n"
            f"  涨停 {limit_up} 家 / 跌停 {limit_down} 家"
            f"（涨跌停比值 {ratio:.1f}，{'比值越高多头越强' if ratio >= 2 else '比值偏低，多头优势不明显'}）\n"
        )

        # ── 2. 消息面（有AI解读结果时才展示）
        if news_sentiment:
            news_tone  = news_sentiment.get('sentiment', 'neutral')
            news_score = news_sentiment.get('score', 0)
            ai_boost   = news_sentiment.get('ai_boost_total', 0)
            tone_map   = {'positive': '偏多🟢', 'negative': '偏空🔴', 'neutral': '中性⚪'}
            top_pos    = news_sentiment.get('top_positive_sectors', [])
            top_neg    = news_sentiment.get('top_negative_sectors', [])
            lines.append(
                f"  消息面：{tone_map.get(news_tone, '中性')}"
                f"（关键词分值{news_score:+d}，AI板块加分合计{ai_boost:+.0f}分）\n"
            )
            if top_pos:
                lines.append(f"  📰 利好板块：{'、'.join(top_pos)}\n")
            if top_neg:
                lines.append(f"  📉 利空板块：{'、'.join(top_neg)}\n")

        # ── 3. 周线宏观趋势
        macro_label = {'active': '🟢 主动做多', 'cautious': '🟡 谨慎观望', 'defensive': '🔴 防御避险'}.get(macro_mode, macro_mode)
        macro_desc  = {
            'active':    'CSI300周线趋势向上，中期看多',
            'cautious':  'CSI300周线方向不明，中期观望',
            'defensive': 'CSI300周线趋势向下，中期防守',
        }.get(macro_mode, '')
        price_vs_ma100 = macro_data.get('price_vs_ma100', None)
        if price_vs_ma100 is not None:
            lines.append(
                f"  周线趋势：{macro_label} — {macro_desc}\n"
                f"  （CSI300距百日均线{price_vs_ma100:+.1f}%，"
                f"{'站上百日线中期趋势完整' if price_vs_ma100 >= 0 else '跌破百日线中期趋势受损'}）\n"
            )
        else:
            lines.append(f"  周线趋势：{macro_label}（空仓期间未计算周线数据）\n")

        # ── 4. 四状态机判断 + 操作决策
        regime_label_map = {
            'BULL_TREND':              '🟢 牛市趋势',
            'BULL_PULLBACK':           '🟡 牛市回调',
            'BEAR_BOUNCE':             '🟠 熊市反弹',
            'BEAR_TREND':              '🔴 熊市下跌',
            'BEAR_BOUNCE_OVERRIDE':    '⚡ 熊市翻转信号',
            'BULL_PULLBACK_OVERRIDE':  '⚡ 熊市强力翻转',
        }
        regime_op_map = {
            'BULL_TREND':              '正常仓位积极操作，趋势明确向上',
            'BULL_PULLBACK':           '牛市中的短暂回调，轻仓参与强势股',
            'BEAR_BOUNCE':             '熊市技术性反弹，极轻仓超短线，务必及时止损',
            'BEAR_TREND':              '熊市下跌阶段，强制空仓，等待趋势反转',
            'BEAR_BOUNCE_OVERRIDE':    '微观结构出现翻转迹象，极轻仓参与1-2天',
            'BULL_PULLBACK_OVERRIDE':  '出现强力翻转信号，可半仓参与，持3-4天',
        }
        top_n_actual       = max(1, round(3 * position_multiplier)) if position_multiplier > 0 else 0
        regime_str         = regime_label_map.get(regime, regime)
        regime_op          = regime_op_map.get(regime, '')
        override_triggered = regime_data.get('override_triggered', False)
        price_vs_ma60      = regime_data.get('price_vs_ma60_pct', 0)
        ma60_slope         = regime_data.get('ma60_slope_pct', 0)
        slope_desc         = "MA60仍在上行" if ma60_slope > 0.01 else ("MA60走平" if ma60_slope >= -0.01 else "MA60正在下行")

        lines.append(
            f"\n  【操作决策】{regime_str} → {regime_op}\n"
            f"  仓位建议：{'空仓' if position_multiplier == 0 else f'×{position_multiplier}仓位，最多参与Top{top_n_actual}只'}\n"
            f"  判断依据：CSI300距MA60={price_vs_ma60:+.1f}%，{slope_desc}（{ma60_slope:+.4f}%/日）\n"
        )
        if override_triggered:
            override_reasons = regime_data.get('override_reasons', [])
            override_score   = regime_data.get('override_score', 0)
            lines.append(
                f"  ⚡ 翻转信号（{override_score}/4条件命中）：{' | '.join(override_reasons)}\n"
                f"  ⚠️  属熊市临时反弹，只做1-2天，止损不拖延\n"
            )

        # ── 5. 综合结论
        if decision_reason:
            lines.append(f"\n  综合结论：{decision_reason}\n")
    else:
        lines.append("  （市场数据获取失败）\n")
    lines.append('\n')

    # ── 二、短线建议 ─────────────────────────────────────
    lines.append("【二、短线建议 Top3（持有 1-3 天）】\n")
    # 策略逻辑随市场风格动态变化
    short_logic_map = {
        'momentum':      '强动量市：追涨突破，选站上MA20且今日量价齐升的强势股',
        'weak_momentum': '弱动量市：量能放大但价格温和，主力低调建仓，等待次日启动',
        'sideways':      '震荡市：低吸策略，选高位回踩支撑、量能收缩后放量企稳的个股',
        'bear':          '熊市：极度谨慎，只选极少数有独立行情的强势标的',
    }
    short_logic  = short_logic_map.get(market_style, '量能异动但价格未大涨 → 主力悄悄建仓 → 次日启动')
    lines.append(f"  当前策略：{short_logic}\n\n")

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
        # 空仓原因用中文说清楚
        no_short_reason = {
            'BEAR_TREND':             '当前处于熊市下跌阶段（MA60斜率向下），系统强制空仓，无短线机会',
            'BEAR_BOUNCE':            '当前处于熊市反弹，候选股未达极高门槛（≥62分），无符合条件标的',
            'BEAR_BOUNCE_OVERRIDE':   '熊市翻转信号触发，候选股未达高门槛（≥80分），无符合条件标的',
            'BULL_PULLBACK_OVERRIDE': '强力翻转信号触发，候选股未达门槛（≥65分），无符合条件标的',
        }.get(regime, '当前市场条件下无满足条件的短线候选')
        lines.append(f"  {no_short_reason}\n\n")

    # ── 三、波段建议 ─────────────────────────────────────
    lines.append("【三、波段建议 Top3（持有 1-8 周）】\n")
    lines.append("  入选条件：MA20＞MA60（中期上升趋势）+ 回调5-35% + 缩量回踩支撑 + 行业RS不弱\n\n")

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
        no_long_reason = {
            'BEAR_TREND':  '熊市下跌阶段，波段策略暂停（需BULL_TREND或BULL_PULLBACK状态才启用）',
            'BEAR_BOUNCE': '熊市反弹，波段策略暂停（MA60趋势未回正，不适合持仓1-8周）',
        }.get(regime, '当前无满足条件的波段候选（趋势未达标或大盘偏弱）')
        lines.append(f"  {no_long_reason}\n\n")

    # ── 四、操作纪律 ─────────────────────────────────────
    lines.append(sep('─'))
    lines.append("【四、操作纪律】\n")
    # 按当前机制给出差异化纪律提示
    if regime in ('BEAR_TREND',):
        lines.append("  ⛔ 当前强制空仓，不参与任何方向，等待MA60斜率转正再说\n")
    elif regime in ('BEAR_BOUNCE', 'BEAR_BOUNCE_OVERRIDE'):
        lines.append("  ⚠️  熊市模式：仓位极轻，1-2天必须出，亏损超止损价立即无条件离场\n")
        lines.append("  ① 建仓：单只≤总仓位10%，绝不加仓\n")
        lines.append("  ② 止损：跌破止损价当日收盘前离场，不等回调\n")
        lines.append("  ③ 止盈：到目标价先全出，不留底仓\n")
    elif regime in ('BULL_PULLBACK', 'BULL_PULLBACK_OVERRIDE'):
        lines.append("  🟡 牛市回调：轻仓参与，优先止损纪律\n")
        lines.append("  ① 建仓：分2次进场，首仓≤50%计划仓位，确认企稳再补\n")
        lines.append("  ② 止损：跌破止损价当日收盘前离场，不拖延\n")
        lines.append("  ③ 止盈：短线到目标价减半，剩余用移动止损跟踪\n")
    else:  # BULL_TREND — 正常仓位
        lines.append("  🟢 牛市趋势：正常仓位操作，重点管好止损\n")
        lines.append("  ① 建仓：分2-3次建仓，不要一次满仓\n")
        lines.append("  ② 止损：跌破止损价当日收盘前离场，不抱幻想\n")
        lines.append("  ③ 止盈：短线到目标价附近先减半仓，剩余跟踪移动止损\n")
        lines.append("  ④ 波段：持有期间跌破MA60止损，峰值回撤>10%后激活移动止损\n")
    lines.append("  ⑤ 本报告仅供参考，最终决策请结合自身判断\n")
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

