"""
回测数据预下载器
================
功能：
  - 一次性把回测区间内所有需要的 Tushare 数据下载到本地 Parquet 文件
  - 支持断点续传：已存在的日期文件自动跳过
  - 按日分文件存储（daily/daily_basic/moneyflow/index_daily/top_list/top_inst/margin_detail），
    其余静态数据存单文件（stock_basic/fina_indicator/income 等）

目录结构：
  data/cache/
  ├── trade_cal.parquet
  ├── stock_basic.parquet
  ├── share_float.parquet
  ├── stk_holdertrade.parquet
  ├── fina_indicator.parquet
  ├── income.parquet
  ├── daily/          YYYYMMDD.parquet  ← A股全市场日线
  ├── daily_basic/    YYYYMMDD.parquet  ← 换手率 / 量比
  ├── moneyflow/      YYYYMMDD.parquet  ← 主力资金流
  ├── index_daily/    YYYYMMDD.parquet  ← 大盘指数 + 28个申万行业
  ├── top_list/       YYYYMMDD.parquet  ← 龙虎榜每日明细（方案D）
  ├── top_inst/       YYYYMMDD.parquet  ← 龙虎榜机构买卖明细（方案D）
  └── margin_detail/  YYYYMMDD.parquet  ← 融资融券交易明细（方案E）

用法：
  python data_downloader.py --start 20250101 --end 20250331
  python data_downloader.py --start 20250101 --end 20250331 --force  # 强制重下已有文件
  python data_downloader.py --start 20250101 --end 20250331 --skip-financial  # 跳过财务数据
  python data_downloader.py --start 20250101 --end 20250331 --only-new  # 只下载新增的三个接口
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# ==================== 常量 ====================
CACHE_DIR = os.path.join("data", "cache")

# 申万一级行业指数（28个）+ 沪深300 + 上证指数
INDEX_CODES = [
    '000001.SH', '000300.SH',  # 上证、沪深300
    # 申万一级行业指数（28个）— 用于板块共振过滤
    '801010.SI', '801020.SI', '801030.SI', '801040.SI', '801050.SI',
    '801080.SI', '801110.SI', '801120.SI', '801130.SI', '801140.SI',
    '801150.SI', '801160.SI', '801170.SI', '801180.SI', '801200.SI',
    '801210.SI', '801230.SI', '801710.SI', '801720.SI', '801730.SI',
    '801740.SI', '801750.SI', '801760.SI', '801770.SI', '801780.SI',
    '801790.SI', '801880.SI', '801890.SI',
]

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join("data", "downloader.log"), encoding='utf-8'),
    ]
)
logger = logging.getLogger("downloader")


# ==================== 工具函数 ====================

def _ensure_dirs():
    """创建所有需要的目录"""
    for sub in ["", "daily", "daily_basic", "moneyflow", "index_daily",
                "top_list", "top_inst", "margin_detail"]:
        os.makedirs(os.path.join(CACHE_DIR, sub), exist_ok=True)


def _daily_path(sub: str, date: str) -> str:
    return os.path.join(CACHE_DIR, sub, f"{date}.parquet")


def _static_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f"{name}.parquet")


def _cache_has_rows(path: str, min_rows: int = 1) -> bool:
    """检查核心行情缓存是否真实有数据，避免空 parquet 卡住同步。"""
    if not os.path.exists(path):
        return False
    try:
        return len(pd.read_parquet(path)) >= min_rows
    except Exception as e:
        logger.warning(f"  缓存读取失败，将重新下载：{path} ({e})")
        return False


def _index_cache_min_rows() -> int:
    return min(20, len(INDEX_CODES))


def _save(df: pd.DataFrame, path: str):
    """保存 DataFrame 为 Parquet，所有字符串列强制 str 类型"""
    df.to_parquet(path, index=False, engine='pyarrow', compression='snappy')


def _retry(fn, retries: int = 3, wait: float = 5.0):
    """带重试的调用包装"""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"  ⚠ 调用失败（{attempt+1}/{retries}）：{e}，{wait}秒后重试...")
                time.sleep(wait)
            else:
                logger.error(f"  ✗ 重试{retries}次仍失败：{e}")
                return None
    return None


def _get_trade_dates(pro, start_date: str, end_date: str) -> List[str]:
    """获取区间内所有交易日（升序）"""
    try:
        cal = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date,
                            is_open=1, fields='cal_date,is_open')
    except Exception as e:
        logger.warning(f"  trade_cal 接口调用失败，尝试使用本地缓存：{e}")
        cal = None

    dates = _extract_trade_dates(cal, start_date, end_date)
    if dates:
        return dates

    path = _static_path("trade_cal")
    if os.path.exists(path):
        try:
            cached = pd.read_parquet(path)
            cached_dates = _extract_trade_dates(cached, start_date, end_date)
            if cached_dates is not None:
                if not dates:
                    logger.warning("  trade_cal 接口返回为空，已回退使用本地交易日历缓存")
                return cached_dates
        except Exception as e:
            logger.warning(f"  本地 trade_cal 缓存读取失败：{e}")

    if dates is None:
        fallback_dates = _weekday_dates(start_date, end_date)
        if fallback_dates:
            logger.warning("  trade_cal 返回缺少 cal_date 字段，且无可用缓存，临时按工作日兜底")
            return fallback_dates
        logger.warning("  trade_cal 返回缺少 cal_date 字段，且无可用缓存，本次交易日列表为空")
    return dates or []


def _extract_trade_dates(cal: Optional[pd.DataFrame], start_date: str, end_date: str) -> Optional[List[str]]:
    if cal is None or 'cal_date' not in cal.columns:
        return None
    if cal.empty:
        return []

    work = cal.copy()
    work['cal_date'] = work['cal_date'].astype(str)
    work = work[(work['cal_date'] >= start_date) & (work['cal_date'] <= end_date)]
    if 'is_open' in work.columns:
        work = work[pd.to_numeric(work['is_open'], errors='coerce').fillna(0).astype(int) == 1]
    return sorted(work['cal_date'].tolist())


def _weekday_dates(start_date: str, end_date: str) -> List[str]:
    start = datetime.strptime(start_date, '%Y%m%d')
    end = datetime.strptime(end_date, '%Y%m%d')
    if start > end:
        return []

    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)
    return dates


# ==================== 各接口下载函数 ====================

def download_trade_cal(pro, start_date: str, end_date: str, force: bool = False):
    """交易日历：覆盖式更新（文件不按日期分割，整个区间存一个文件）"""
    path = _static_path("trade_cal")
    # 如果已存在，检查是否覆盖了所需区间
    if not force and os.path.exists(path):
        try:
            existing = pd.read_parquet(path)
            if not existing.empty:
                dates = existing['cal_date'].astype(str)
                if dates.min() <= start_date and dates.max() >= end_date:
                    logger.info("  ↩ trade_cal 已覆盖所需区间，跳过")
                    return
        except Exception:
            pass

    logger.info(f"  ↓ 下载 trade_cal [{start_date} ~ {end_date}]...")
    # 多下载一些缓冲（MA60需要前100天数据）
    buf_start = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=150)).strftime('%Y%m%d')
    df = _retry(lambda: pro.trade_cal(
        exchange='SSE', start_date=buf_start, end_date=end_date,
        fields='cal_date,is_open'
    ))
    if df is not None:
        if 'cal_date' not in df.columns:
            logger.warning("  trade_cal 返回缺少 cal_date 字段，跳过保存，避免覆盖本地有效缓存")
            return
        _save(df, path)
        logger.info(f"  ✓ trade_cal：{len(df)} 条")


def download_stock_basic(pro, force: bool = False):
    """A股基础信息：静态数据，按需更新"""
    path = _static_path("stock_basic")
    if not force and os.path.exists(path):
        logger.info("  ↩ stock_basic 已存在，跳过（用 --force 强制更新）")
        return

    logger.info("  ↓ 下载 stock_basic...")
    df = _retry(lambda: pro.stock_basic(
        exchange='', list_status='L',
        fields='ts_code,symbol,name,industry,list_date'
    ))
    if df is not None:
        _save(df, path)
        logger.info(f"  ✓ stock_basic：{len(df)} 只")


def download_daily_one_date(pro, date: str, force: bool = False) -> bool:
    """下载单个交易日的全市场日线数据"""
    path = _daily_path("daily", date)
    if not force and _cache_has_rows(path):
        return True  # 跳过

    # 分批拉取：先拿全部 ts_code，再批量请求
    # 实际上 daily 接口传 trade_date 不传 ts_code 可以拿全市场，直接用
    def _fetch():
        df = pro.daily(trade_date=date,
                       fields='ts_code,trade_date,open,high,low,close,pct_chg,vol,amount')
        return df

    df = _retry(_fetch)
    if df is None:
        return False
    _save(df, path)
    logger.info(f"  ✓ daily {date}：{len(df)} 只")
    return True


def download_daily_basic_one_date(pro, date: str, force: bool = False) -> bool:
    """下载单个交易日的换手率/量比"""
    path = _daily_path("daily_basic", date)
    if not force and _cache_has_rows(path):
        return True

    df = _retry(lambda: pro.daily_basic(
        trade_date=date,
        fields='ts_code,turnover_rate,volume_ratio'
    ))
    if df is None:
        return False
    _save(df, path)
    logger.info(f"  ✓ daily_basic {date}：{len(df)} 只")
    return True


def download_moneyflow_one_date(pro, date: str, force: bool = False) -> bool:
    """下载单个交易日的主力资金流"""
    path = _daily_path("moneyflow", date)
    if not force and _cache_has_rows(path):
        return True

    df = _retry(lambda: pro.moneyflow(
        trade_date=date,
        fields='ts_code,net_mf_amount'
    ))
    if df is None:
        return False
    _save(df, path)
    logger.info(f"  ✓ moneyflow {date}：{len(df)} 只")
    return True


def download_index_daily_one_date(pro, date: str, force: bool = False) -> bool:
    """下载单个交易日所有指数（大盘+申万行业）。
    注意：Tushare index_daily 接口不支持多 ts_code 批量查询，须逐个请求再合并。
    """
    path = _daily_path("index_daily", date)
    if not force and _cache_has_rows(path, min_rows=_index_cache_min_rows()):
        return True

    all_dfs = []
    for code in INDEX_CODES:
        df = _retry(lambda c=code: pro.index_daily(
            ts_code=c,
            trade_date=date,
            fields='ts_code,trade_date,open,high,low,close,pct_chg'
        ), retries=2, wait=2.0)
        if df is not None and not df.empty:
            all_dfs.append(df)
        time.sleep(0.2)   # 逐个请求，稍作限速

    combined = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    _save(combined, path)
    logger.info(f"  ✓ index_daily {date}：{len(combined)} 条（{len(all_dfs)}/{len(INDEX_CODES)} 个指数有数据）")
    return True


def download_top_list_one_date(pro, date: str, force: bool = False) -> bool:
    """
    下载单个交易日龙虎榜明细（top_list）。
    关键字段：ts_code, trade_date, reason, buy, sell, net_buy
    龙虎榜数据较少（每日约数十条），一次请求即可。
    """
    path = _daily_path("top_list", date)
    if not force and os.path.exists(path):
        return True

    df = _retry(lambda: pro.top_list(
        trade_date=date,
        fields='ts_code,trade_date,reason,buy,sell,net_buy'
    ))
    if df is None:
        df = pd.DataFrame()
    _save(df, path)
    logger.info(f"  ✓ top_list {date}：{len(df)} 条")
    return True


def download_top_inst_one_date(pro, date: str, force: bool = False) -> bool:
    """
    下载单个交易日龙虎榜机构买卖明细（top_inst）。
    关键字段：ts_code, trade_date, buy, sell（机构席位合计）
    """
    path = _daily_path("top_inst", date)
    if not force and os.path.exists(path):
        return True

    df = _retry(lambda: pro.top_inst(
        trade_date=date,
        fields='ts_code,trade_date,buy,sell'
    ))
    if df is None:
        df = pd.DataFrame()
    _save(df, path)
    logger.info(f"  ✓ top_inst {date}：{len(df)} 条")
    return True


def download_margin_detail_one_date(pro, date: str, force: bool = False) -> bool:
    """
    下载单个交易日融资融券交易明细（margin_detail）。
    关键字段：ts_code, trade_date, rzmre（融资买入额）, rzche（融资偿还额）
    说明：每日全市场融资数据约4000条，一次请求可拿完。
    """
    path = _daily_path("margin_detail", date)
    if not force and os.path.exists(path):
        return True

    df = _retry(lambda: pro.margin_detail(
        trade_date=date,
        fields='ts_code,trade_date,rzmre,rzche'
    ))
    if df is None:
        df = pd.DataFrame()
    _save(df, path)
    logger.info(f"  ✓ margin_detail {date}：{len(df)} 条")
    return True


def download_share_float(pro, start_date: str, end_date: str, force: bool = False):
    """限售股解禁数据：按回测区间下载，多取15天前缀（filter_restricted_stocks需要）"""
    path = _static_path("share_float")
    if not force and os.path.exists(path):
        try:
            existing = pd.read_parquet(path)
            if not existing.empty:
                if existing['ann_date'].min() <= start_date:
                    logger.info("  ↩ share_float 已存在，跳过")
                    return
        except Exception:
            pass

    buf_start = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=20)).strftime('%Y%m%d')
    logger.info(f"  ↓ 下载 share_float [{buf_start} ~ {end_date}]...")
    df = _retry(lambda: pro.share_float(
        start_date=buf_start, end_date=end_date,
        fields='ts_code,ann_date,float_date'
    ))
    if df is None:
        df = pd.DataFrame()
    _save(df, path)
    logger.info(f"  ✓ share_float：{len(df)} 条")


def download_stk_holdertrade(pro, start_date: str, end_date: str, force: bool = False):
    """股东减持数据：分 G/P/C 三类下载"""
    path = _static_path("stk_holdertrade")
    if not force and os.path.exists(path):
        logger.info("  ↩ stk_holdertrade 已存在，跳过")
        return

    buf_start = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=20)).strftime('%Y%m%d')
    logger.info(f"  ↓ 下载 stk_holdertrade [{buf_start} ~ {end_date}]...")

    all_dfs = []
    for holder_type in ['G', 'P', 'C']:
        df = _retry(lambda ht=holder_type: pro.stk_holdertrade(
            holder_type=ht,
            fields='ts_code,ann_date,in_de,holder_type'
        ))
        if df is not None and not df.empty:
            if 'ann_date' in df.columns:
                ann_dates = df['ann_date'].astype(str).str.replace('-', '', regex=False).str[:8]
                df = df[(ann_dates >= buf_start) & (ann_dates <= end_date)].copy()
            all_dfs.append(df)
        time.sleep(0.5)

    combined = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    _save(combined, path)
    logger.info(f"  ✓ stk_holdertrade：{len(combined)} 条")


def download_fina_indicator(pro, force: bool = False):
    """财务指标（ROE、负债率）：全量下载，较大，建议只下载在用的股票"""
    path = _static_path("fina_indicator")
    if not force and os.path.exists(path):
        logger.info("  ↩ fina_indicator 已存在，跳过（季度更新时用 --force）")
        return

    # 先拿股票列表
    stock_basic_path = _static_path("stock_basic")
    if not os.path.exists(stock_basic_path):
        logger.error("  ✗ 请先下载 stock_basic")
        return

    stock_basic = pd.read_parquet(stock_basic_path)
    ts_codes = stock_basic['ts_code'].tolist()

    logger.info(f"  ↓ 下载 fina_indicator（共{len(ts_codes)}只，按批次）...")

    batch_size = 50
    all_dfs = []
    total_batches = (len(ts_codes) + batch_size - 1) // batch_size

    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i:i + batch_size]
        batch_no = i // batch_size + 1
        if batch_no % 20 == 0:
            logger.info(f"    进度：{batch_no}/{total_batches} 批...")

        df = _retry(lambda b=batch: pro.fina_indicator(
            ts_code=",".join(b),
            fields='ts_code,ann_date,end_date,roe,debt_to_assets,netprofit_yoy'
        ), retries=3, wait=3.0)

        if df is not None and not df.empty:
            all_dfs.append(df)
        time.sleep(0.5)

    combined = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    if not combined.empty:
        # 每只股票保留最近8期（约2年的季报），兼顾回测早期日期的截面约束需求
        combined = (combined
                    .sort_values('end_date', ascending=False)
                    .groupby('ts_code').head(8)
                    .reset_index(drop=True))
    _save(combined, path)
    logger.info(f"  ✓ fina_indicator：{len(combined)} 条（{combined['ts_code'].nunique() if not combined.empty else 0} 只）")


def download_income(pro, force: bool = False):
    """利润表（营收）：全量下载，保留近几期用于同比计算"""
    path = _static_path("income")
    if not force and os.path.exists(path):
        logger.info("  ↩ income 已存在，跳过（季度更新时用 --force）")
        return

    stock_basic_path = _static_path("stock_basic")
    if not os.path.exists(stock_basic_path):
        logger.error("  ✗ 请先下载 stock_basic")
        return

    stock_basic = pd.read_parquet(stock_basic_path)
    ts_codes = stock_basic['ts_code'].tolist()

    logger.info(f"  ↓ 下载 income（共{len(ts_codes)}只，按批次）...")

    batch_size = 50
    all_dfs = []
    total_batches = (len(ts_codes) + batch_size - 1) // batch_size

    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i:i + batch_size]
        batch_no = i // batch_size + 1
        if batch_no % 20 == 0:
            logger.info(f"    进度：{batch_no}/{total_batches} 批...")

        df = _retry(lambda b=batch: pro.income(
            ts_code=",".join(b),
            fields='ts_code,ann_date,end_date,revenue'
        ), retries=3, wait=3.0)

        if df is not None and not df.empty:
            # 每只股票只保留最近4期（够做两期同比）
            df = df.sort_values('end_date', ascending=False)
            df = df.groupby('ts_code').head(4).reset_index(drop=True)
            all_dfs.append(df)
        time.sleep(0.5)

    combined = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    _save(combined, path)
    logger.info(f"  ✓ income：{len(combined)} 条")


# ==================== 按日期批量下载（含断点续传进度显示）====================

def download_daily_range(pro, trade_dates: List[str], force: bool = False,
                         only_new: bool = False, core_only: bool = False):
    """
    批量下载每日数据。
    only_new=True 时只下载新增的三个接口（top_list/top_inst/margin_detail），
    跳过已有的 daily/daily_basic/moneyflow/index_daily。
    """
    total = len(trade_dates)
    daily_ok = daily_basic_ok = moneyflow_ok = index_ok = 0
    top_list_ok = top_inst_ok = margin_ok = 0

    for idx, date in enumerate(trade_dates, 1):
        logger.info(f"[{idx:3d}/{total}] 处理 {date}...")

        if not only_new:
            # daily
            need_daily = force or not _cache_has_rows(_daily_path("daily", date))
            if need_daily:
                if download_daily_one_date(pro, date, force):
                    daily_ok += 1
                time.sleep(0.8)
            else:
                daily_ok += 1

            # daily_basic
            need_basic = force or not _cache_has_rows(_daily_path("daily_basic", date))
            if need_basic:
                if download_daily_basic_one_date(pro, date, force):
                    daily_basic_ok += 1
                time.sleep(0.8)
            else:
                daily_basic_ok += 1

            # moneyflow
            need_mf = force or not _cache_has_rows(_daily_path("moneyflow", date))
            if need_mf:
                if download_moneyflow_one_date(pro, date, force):
                    moneyflow_ok += 1
                time.sleep(0.8)
            else:
                moneyflow_ok += 1

            # index_daily
            if not core_only:
                need_idx = force or not _cache_has_rows(_daily_path("index_daily", date), min_rows=_index_cache_min_rows())
                if need_idx:
                    if download_index_daily_one_date(pro, date, force):
                        index_ok += 1
                    time.sleep(0.5)
                else:
                    index_ok += 1

        # ── 新增：top_list ──
        if not core_only:
            need_tl = force or not os.path.exists(_daily_path("top_list", date))
            if need_tl:
                if download_top_list_one_date(pro, date, force):
                    top_list_ok += 1
                time.sleep(0.8)
            else:
                top_list_ok += 1

        # ── 新增：top_inst ──
            need_ti = force or not os.path.exists(_daily_path("top_inst", date))
            if need_ti:
                if download_top_inst_one_date(pro, date, force):
                    top_inst_ok += 1
                time.sleep(0.8)
            else:
                top_inst_ok += 1

        # ── 新增：margin_detail ──
            need_mg = force or not os.path.exists(_daily_path("margin_detail", date))
            if need_mg:
                if download_margin_detail_one_date(pro, date, force):
                    margin_ok += 1
                time.sleep(0.8)
            else:
                margin_ok += 1

        # 每10天打印一次进度摘要
        if idx % 10 == 0 or idx == total:
            if not only_new:
                logger.info(
                    f"  进度摘要：daily={daily_ok}/{idx}  "
                    f"daily_basic={daily_basic_ok}/{idx}  "
                    f"moneyflow={moneyflow_ok}/{idx}  "
                    f"index={index_ok}/{idx}  "
                    f"top_list={top_list_ok}/{idx}  "
                    f"top_inst={top_inst_ok}/{idx}  "
                    f"margin={margin_ok}/{idx}"
                )
            else:
                logger.info(
                    f"  新增数据进度：top_list={top_list_ok}/{idx}  "
                    f"top_inst={top_inst_ok}/{idx}  "
                    f"margin={margin_ok}/{idx}"
                )

    return daily_ok, daily_basic_ok, moneyflow_ok, index_ok, top_list_ok, top_inst_ok, margin_ok


# ==================== 主入口 ====================

def run_download(start_date: str, end_date: str, force: bool = False,
                 skip_financial: bool = False, only_new: bool = False,
                 core_only: bool = False):
    """
    执行完整的数据下载流程

    Args:
        start_date:      回测开始日期 YYYYMMDD
        end_date:        回测结束日期 YYYYMMDD
        force:           True=强制重下已存在文件
        skip_financial:  True=跳过财务数据（fina_indicator/income），适合只测技术面策略
        only_new:        True=只下载新增的三个接口（top_list/top_inst/margin_detail），
                         已有的 daily/daily_basic/moneyflow/index_daily 全部跳过
    """
    import main as stock_main  # 复用已初始化的 pro 实例
    pro = stock_main.pro

    logger.info(f"\n{'='*60}")
    logger.info(f"  数据下载任务：{start_date} → {end_date}  force={force}  only_new={only_new}")
    logger.info(f"{'='*60}")

    _ensure_dirs()
    t0 = datetime.now()

    if not only_new:
        # ── 阶段1：静态数据（不随日期变化）──
        logger.info("\n【阶段1】静态基础数据")
        download_trade_cal(pro, start_date, end_date, force)
        time.sleep(0.5)
        download_stock_basic(pro, force)
        time.sleep(0.5)
        if not core_only:
            download_share_float(pro, start_date, end_date, force)
            time.sleep(0.5)
            download_stk_holdertrade(pro, start_date, end_date, force)
            time.sleep(0.5)
        else:
            logger.info("  -> core-only：跳过 share_float / stk_holdertrade")

        if not skip_financial:
            download_fina_indicator(pro, force)
            time.sleep(0.5)
            download_income(pro, force)
            time.sleep(0.5)
        else:
            logger.info("  ↩ 跳过财务数据（--skip-financial）")
    else:
        logger.info("\n【only-new 模式】跳过静态数据和已有日频数据，只补充新接口")

    # ── 阶段2：获取交易日列表 ──
    logger.info("\n【阶段2】获取回测区间交易日列表...")
    # MA60需要前100天数据，多下载缓冲
    buf_start = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=120)).strftime('%Y%m%d')
    trade_dates = _get_trade_dates(pro, buf_start, end_date)
    logger.info(f"  共 {len(trade_dates)} 个交易日（含前置缓冲期）")

    # ── 阶段3：按日数据 ──
    label = "新增接口（top_list/top_inst/margin_detail）" if only_new else "行情/换手率/资金流/指数/龙虎榜/融资"
    logger.info(f"\n【阶段3】按日下载{label}")
    results = download_daily_range(pro, trade_dates, force, only_new=only_new, core_only=core_only)
    daily_ok, basic_ok, mf_ok, idx_ok, tl_ok, ti_ok, mg_ok = results

    # ── 完成报告 ──
    elapsed = (datetime.now() - t0).total_seconds()
    logger.info(f"\n{'='*60}")
    logger.info(f"  ✅ 下载完成！耗时：{elapsed/60:.1f} 分钟")
    if not only_new:
        logger.info(f"  daily：{daily_ok}/{len(trade_dates)} 天")
        logger.info(f"  daily_basic：{basic_ok}/{len(trade_dates)} 天")
        logger.info(f"  moneyflow：{mf_ok}/{len(trade_dates)} 天")
        logger.info(f"  index_daily：{idx_ok}/{len(trade_dates)} 天")
    logger.info(f"  top_list：{tl_ok}/{len(trade_dates)} 天  ← 龙虎榜明细（方案D）")
    logger.info(f"  top_inst：{ti_ok}/{len(trade_dates)} 天  ← 机构席位明细（方案D）")
    logger.info(f"  margin_detail：{mg_ok}/{len(trade_dates)} 天  ← 融资融券明细（方案E）")
    logger.info(f"  缓存目录：{os.path.abspath(CACHE_DIR)}")
    logger.info(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='Tushare数据预下载器（回测专用）')
    parser.add_argument('--start', type=str, required=True, help='开始日期 YYYYMMDD')
    parser.add_argument('--end',   type=str, required=True, help='结束日期 YYYYMMDD')
    parser.add_argument('--force', action='store_true', help='强制重下已存在的文件')
    parser.add_argument('--skip-financial', action='store_true',
                        help='跳过财务数据下载（fina_indicator/income），首次快速测试时使用')
    parser.add_argument('--only-new', action='store_true',
                        help='只补充新增三个接口（top_list/top_inst/margin_detail），'
                             '已有数据保持不动，适合在已有回测数据基础上补充新信号')
    parser.add_argument('--core-only', action='store_true',
                        help='线上极速同步：只下载 daily/daily_basic/moneyflow/stock_basic，跳过指数、龙虎榜和融资融券')
    args = parser.parse_args()

    run_download(
        start_date=args.start,
        end_date=args.end,
        force=args.force,
        skip_financial=args.skip_financial,
        only_new=args.only_new,
        core_only=args.core_only,
    )


if __name__ == '__main__':
    main()
