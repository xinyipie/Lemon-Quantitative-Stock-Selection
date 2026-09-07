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
  ├── stock_basic_history/ YYYYMMDD.parquet  ← L/D/P 三种状态的当日精确快照
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
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# ==================== 常量 ====================
CACHE_DIR = os.path.join("data", "cache")

# 申万一级行业指数（28个）+ 沪深300 + 上证指数
INDEX_CODES = [
    '000001.SH', '000016.SH', '000300.SH', '000688.SH', '000852.SH',
    '000905.SH', '399001.SZ', '399006.SZ',
    # 申万一级行业指数（28个）— 用于板块共振过滤
    '801010.SI', '801020.SI', '801030.SI', '801040.SI', '801050.SI',
    '801080.SI', '801110.SI', '801120.SI', '801130.SI', '801140.SI',
    '801150.SI', '801160.SI', '801170.SI', '801180.SI', '801200.SI',
    '801210.SI', '801230.SI', '801710.SI', '801720.SI', '801730.SI',
    '801740.SI', '801750.SI', '801760.SI', '801770.SI', '801780.SI',
    '801790.SI', '801880.SI', '801890.SI',
]

INDEX_NAMES = {
    '000001.SH': '上证指数',
    '000016.SH': '上证50',
    '000300.SH': '沪深300',
    '000688.SH': '科创50',
    '000852.SH': '中证1000',
    '000905.SH': '中证500',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指',
}

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
CHINA_TZ = ZoneInfo("Asia/Shanghai")


# ==================== 工具函数 ====================

def _ensure_dirs():
    """创建所有需要的目录"""
    for sub in ["", "daily", "daily_basic", "moneyflow", "index_daily", "fund_daily",
                "top_list", "top_inst", "margin_detail", "stock_basic_history"]:
        os.makedirs(os.path.join(CACHE_DIR, sub), exist_ok=True)


def _china_date(now: Optional[datetime] = None) -> str:
    """按北京时间生成基础资料快照日期，避免UTC服务器跨日错档。"""
    current = now or datetime.now(CHINA_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=CHINA_TZ)
    return current.astimezone(CHINA_TZ).strftime('%Y%m%d')


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
    """先写同目录临时文件再原子替换，避免直接覆盖异属主缓存失败。"""
    target_path = os.path.abspath(os.fspath(path))
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)
    temp_path = f"{target_path}.tmp.{os.getpid()}.{time.time_ns()}"
    try:
        df.to_parquet(temp_path, index=False, engine='pyarrow', compression='snappy')
        os.replace(temp_path, target_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _read_existing_cache(path: str) -> pd.DataFrame:
    """读取已有缓存；损坏文件按空缓存处理并保留清楚日志。"""
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as e:
        logger.warning(f"  已有缓存读取失败，将用新数据重建：{path} ({e})")
        return pd.DataFrame()


def _financial_increment_start(df: pd.DataFrame, column: str) -> str:
    """取各股票最新公告水位中的最早值，避免落后股票被全局最大值跳过。"""
    if df.empty or column not in df.columns:
        return ''
    work = df.copy()
    work[column] = work[column].astype('string').str.replace(r'\.0$', '', regex=True)
    work = work[work[column].str.fullmatch(r'\d{8}', na=False)]
    if work.empty:
        return ''
    if 'ts_code' not in work.columns:
        return str(work[column].max())
    per_code_watermarks = work.groupby('ts_code', dropna=True)[column].max()
    return str(per_code_watermarks.min()) if not per_code_watermarks.empty else ''


def _merge_financial_history(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """合并财务增量并保留所有历史公告版本，新增记录覆盖同键旧值。"""
    frames = [frame for frame in (existing, incoming) if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    keys = [column for column in ('ts_code', 'ann_date', 'end_date') if column in combined.columns]
    if keys:
        for column in keys:
            combined[column] = combined[column].astype('string').str.replace(r'\.0$', '', regex=True)
        value_columns = [column for column in combined.columns if column not in keys]
        if value_columns:
            # 增量接口偶尔省略字段；同一公告键内用旧值补齐，避免部分响应抹掉有效历史。
            combined[value_columns] = combined.groupby(
                keys, dropna=False, sort=False
            )[value_columns].ffill()
        combined = combined.drop_duplicates(subset=keys, keep='last')
    sort_columns = [column for column in ('ts_code', 'end_date', 'ann_date') if column in combined.columns]
    if sort_columns:
        combined = combined.sort_values(sort_columns, ascending=[True] + [False] * (len(sort_columns) - 1))
    return combined.reset_index(drop=True)


def _financial_query_groups(ts_codes: List[str], existing: pd.DataFrame,
                            incremental_start: str) -> List[tuple[List[str], str]]:
    """已有代码拉公告增量，缓存缺失代码单独拉全量，避免全局水位漏数。"""
    if not incremental_start or existing.empty or 'ts_code' not in existing.columns:
        return [(ts_codes, '')]
    cached_codes = set(existing['ts_code'].dropna().astype(str))
    incremental_codes = [code for code in ts_codes if code in cached_codes]
    missing_codes = [code for code in ts_codes if code not in cached_codes]
    groups = []
    if incremental_codes:
        groups.append((incremental_codes, incremental_start))
    if missing_codes:
        groups.append((missing_codes, ''))
    return groups


def _retry(fn, retries: int = 3, wait: float = 5.0):
    """带重试的调用包装"""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            error_text = str(e).strip().lower()
            if "invalid token" in error_text or "token invalid" in error_text:
                logger.error("  Tushare Token 无效，立即终止下载，避免继续使用旧行情生成报告")
                raise RuntimeError("Tushare Token 无效，请更新 TUSHARE_TOKEN") from e
            if attempt < retries - 1:
                retry_wait = wait * (2 ** attempt)
                logger.warning(f"  ⚠ 调用失败（{attempt+1}/{retries}）：{e}，{retry_wait}秒后重试...")
                time.sleep(retry_wait)
            else:
                logger.error(f"  ✗ 重试{retries}次仍失败：{e}")
                return None
    return None


def _validate_completed_core_downloads(
    trade_dates: List[str],
    start_date: str,
    end_date: str,
    require_index: bool,
    now: Optional[datetime] = None,
) -> None:
    """校验目标窗口内已经收盘的交易日，禁止核心行情残缺时继续生成报告。"""
    current = now or datetime.now()
    today = current.strftime("%Y%m%d")
    completed_cutoff = today if current.hour >= 18 else (current - timedelta(days=1)).strftime("%Y%m%d")
    required_dates = [
        date for date in trade_dates
        if start_date <= date <= end_date and date <= completed_cutoff
    ]
    missing = []
    requirements = [
        ("daily", 1000),
        ("daily_basic", 1000),
        ("moneyflow", 500),
    ]
    if require_index:
        requirements.append(("index_daily", 2))
    for date in required_dates:
        for subdir, min_rows in requirements:
            if not _cache_has_rows(_daily_path(subdir, date), min_rows=min_rows):
                missing.append(f"{date}:{subdir}")
    if missing:
        detail = ", ".join(missing[:12])
        raise RuntimeError(f"核心行情未完整下载：{detail}")


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
                if cached_dates and max(cached_dates) >= end_date:
                    return cached_dates
                fallback_start = start_date
                if cached_dates:
                    fallback_start = (datetime.strptime(max(cached_dates), '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
                fallback_dates = _weekday_dates(fallback_start, end_date)
                if fallback_dates:
                    logger.warning("  本地 trade_cal 缓存未覆盖目标日期，已追加工作日兜底")
                    return sorted(set(cached_dates) | set(fallback_dates))
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
    """下载全部上市状态，供历史截面按上市/退市日期还原股票范围。"""
    path = _static_path("stock_basic")
    logger.info("  ↓ 下载 stock_basic...")
    frames = []
    completed_statuses = []
    for status in ('L', 'D', 'P'):
        df = _retry(lambda s=status: pro.stock_basic(
            exchange='', list_status=s,
            fields='ts_code,symbol,name,industry,list_date,delist_date,list_status'
        ))
        if df is None:
            continue
        completed_statuses.append(status)
        if not df.empty:
            df = df.copy()
            if 'list_status' not in df.columns:
                df['list_status'] = status
            frames.append(df)

    if not frames:
        logger.warning("  stock_basic 所有状态均未返回数据，保留已有缓存")
        return

    incoming = pd.concat(frames, ignore_index=True, sort=False)
    incoming['basic_snapshot_date'] = _china_date()
    incoming['basic_status_scope'] = ','.join(completed_statuses)
    if completed_statuses == ['L', 'D', 'P']:
        snapshot_path = os.path.join(
            CACHE_DIR, 'stock_basic_history',
            f"{incoming['basic_snapshot_date'].iloc[0]}.parquet",
        )
        _save(incoming, snapshot_path)
    else:
        logger.warning("  stock_basic 状态下载不完整，本次不生成历史时点快照")
    existing = _read_existing_cache(path)
    if completed_statuses == ['L', 'D', 'P']:
        combined = incoming
    else:
        combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
    if 'ts_code' in combined.columns:
        combined = combined.drop_duplicates(subset=['ts_code'], keep='last').reset_index(drop=True)
    _save(combined, path)
    logger.info(f"  ✓ stock_basic：{len(combined)} 只（状态范围：{','.join(completed_statuses)}）")


def download_index_basic(force: bool = False):
    """保存当前系统实际维护的指数名称，供统一品种检索使用。"""
    path = _static_path("index_basic")
    if not force and os.path.exists(path):
        return
    rows = [
        {
            "ts_code": code,
            "name": INDEX_NAMES.get(code, code),
            "market": code.rsplit(".", 1)[-1],
            "publisher": "",
            "category": "大盘指数" if code in INDEX_NAMES else "申万一级行业",
        }
        for code in INDEX_CODES
    ]
    _save(pd.DataFrame(rows), path)
    logger.info(f"  ✓ index_basic：{len(rows)} 个")


def download_fund_basic(pro, force: bool = False):
    """批量下载场内基金基础信息，ETF 名称和代码检索依赖该文件。"""
    path = _static_path("fund_basic")
    if not force and _cache_has_rows(path):
        return
    df = _retry(lambda: pro.fund_basic(
        market="E", status="L",
        fields="ts_code,name,management,custodian,fund_type,list_date,delist_date,status,market",
    ))
    if df is not None and not df.empty:
        _save(df, path)
        logger.info(f"  ✓ fund_basic：{len(df)} 只")


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
    if df.empty:
        _save(df, path)
        logger.warning(f"  ⚠ daily {date} 返回0行，未计入有效下载")
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
    if df.empty:
        _save(df, path)
        logger.warning(f"  ⚠ daily_basic {date} 返回0行，未计入有效下载")
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
    if df.empty:
        _save(df, path)
        logger.warning(f"  ⚠ moneyflow {date} 返回0行，未计入有效下载")
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


def download_fund_daily_one_date(pro, date: str, force: bool = False) -> bool:
    """按交易日批量下载全部场内基金行情，禁止逐只基金请求。"""
    path = _daily_path("fund_daily", date)
    if not force and _cache_has_rows(path):
        return True
    df = _retry(lambda: pro.fund_daily(
        trade_date=date,
        fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
    ))
    if df is None:
        return False
    if df.empty:
        logger.warning(f"  ⚠ fund_daily {date} 返回0行，保留为待重试状态")
        return False
    _save(df, path)
    logger.info(f"  ✓ fund_daily {date}：{len(df)} 只")
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
    """增量更新财务指标；依赖供应商支持逗号分隔代码批量查询。"""
    path = _static_path("fina_indicator")
    existing = _read_existing_cache(path)

    # 先拿股票列表
    stock_basic_path = _static_path("stock_basic")
    if not os.path.exists(stock_basic_path):
        logger.error("  ✗ 请先下载 stock_basic")
        return

    stock_basic = pd.read_parquet(stock_basic_path)
    ts_codes = stock_basic['ts_code'].tolist()

    incremental_start = '' if force else _financial_increment_start(existing, 'ann_date')
    mode = "全量刷新" if force or not incremental_start else f"增量公告≥{incremental_start}"
    logger.info(f"  ↓ 下载 fina_indicator（共{len(ts_codes)}只，{mode}）...")

    batch_size = 50
    all_dfs = []
    query_groups = _financial_query_groups(ts_codes, existing, incremental_start)
    total_batches = sum((len(codes) + batch_size - 1) // batch_size for codes, _ in query_groups)
    batch_no = 0
    for group_codes, group_start in query_groups:
        for i in range(0, len(group_codes), batch_size):
            batch = group_codes[i:i + batch_size]
            batch_no += 1
            if batch_no % 20 == 0:
                logger.info(f"    进度：{batch_no}/{total_batches} 批...")

            query = {
                'ts_code': ",".join(batch),
                'fields': 'ts_code,ann_date,end_date,roe,debt_to_assets,netprofit_yoy',
            }
            if group_start:
                query['start_date'] = group_start
            df = _retry(lambda q=query: pro.fina_indicator(**q), retries=3, wait=3.0)

            if df is not None and not df.empty:
                all_dfs.append(df)
            time.sleep(0.5)

    incoming = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    if incoming.empty:
        logger.warning("  fina_indicator 本次未返回数据，保留已有完整缓存")
        return
    combined = _merge_financial_history(existing, incoming)
    _save(combined, path)
    logger.info(f"  ✓ fina_indicator：{len(combined)} 条（{combined['ts_code'].nunique() if not combined.empty else 0} 只）")


def download_income(pro, force: bool = False):
    """增量更新利润表并保留完整公告历史；依赖供应商批量代码契约。"""
    path = _static_path("income")
    existing = _read_existing_cache(path)

    stock_basic_path = _static_path("stock_basic")
    if not os.path.exists(stock_basic_path):
        logger.error("  ✗ 请先下载 stock_basic")
        return

    stock_basic = pd.read_parquet(stock_basic_path)
    ts_codes = stock_basic['ts_code'].tolist()

    incremental_start = '' if force else _financial_increment_start(existing, 'ann_date')
    mode = "全量刷新" if force or not incremental_start else f"增量公告≥{incremental_start}"
    logger.info(f"  ↓ 下载 income（共{len(ts_codes)}只，{mode}）...")

    batch_size = 50
    all_dfs = []
    query_groups = _financial_query_groups(ts_codes, existing, incremental_start)
    total_batches = sum((len(codes) + batch_size - 1) // batch_size for codes, _ in query_groups)
    batch_no = 0
    for group_codes, group_start in query_groups:
        for i in range(0, len(group_codes), batch_size):
            batch = group_codes[i:i + batch_size]
            batch_no += 1
            if batch_no % 20 == 0:
                logger.info(f"    进度：{batch_no}/{total_batches} 批...")

            query = {
                'ts_code': ",".join(batch),
                'fields': 'ts_code,ann_date,end_date,revenue',
            }
            if group_start:
                query['start_date'] = group_start
            df = _retry(lambda q=query: pro.income(**q), retries=3, wait=3.0)

            if df is not None and not df.empty:
                all_dfs.append(df)
            time.sleep(0.5)

    incoming = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    if incoming.empty:
        logger.warning("  income 本次未返回数据，保留已有完整缓存")
        return
    combined = _merge_financial_history(existing, incoming)
    _save(combined, path)
    logger.info(f"  ✓ income：{len(combined)} 条")


# ==================== 按日期批量下载（含断点续传进度显示）====================

def download_daily_range(pro, trade_dates: List[str], force: bool = False,
                         only_new: bool = False, core_only: bool = False,
                         market_core: bool = False):
    """
    批量下载每日数据。
    only_new=True 时只下载新增的三个接口（top_list/top_inst/margin_detail），
    跳过已有的 daily/daily_basic/moneyflow/index_daily。
    market_core=True 时下载回测核心行情和指数，跳过龙虎榜/融资等扩展日频数据。
    """
    total = len(trade_dates)
    daily_ok = daily_basic_ok = moneyflow_ok = index_ok = fund_ok = 0
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

            # ETF 日线使用单日全市场批量接口，不逐只请求。
            need_fund = force or not _cache_has_rows(_daily_path("fund_daily", date))
            if need_fund:
                if download_fund_daily_one_date(pro, date, force):
                    fund_ok += 1
                time.sleep(0.5)
            else:
                fund_ok += 1

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
        if not core_only and not market_core:
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
                    f"fund_daily={fund_ok}/{idx}  "
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

    return daily_ok, daily_basic_ok, moneyflow_ok, index_ok, fund_ok, top_list_ok, top_inst_ok, margin_ok


# ==================== 主入口 ====================

def run_download(start_date: str, end_date: str, force: bool = False,
                 skip_financial: bool = False, only_new: bool = False,
                 core_only: bool = False, market_core: bool = False,
                 financial_only_force: bool = False,
                 cache_dir: str | os.PathLike | None = None):
    """
    执行完整的数据下载流程

    Args:
        start_date:      回测开始日期 YYYYMMDD
        end_date:        回测结束日期 YYYYMMDD
        force:           True=强制重下已存在文件
        skip_financial:  True=跳过财务数据（fina_indicator/income），适合只测技术面策略
        only_new:        True=只下载新增的三个接口（top_list/top_inst/margin_detail），
                         已有的 daily/daily_basic/moneyflow/index_daily 全部跳过
        market_core:     True=十年验证核心行情模式：保留指数，跳过扩展日频和非必要静态数据
        financial_only_force: True=仅财务接口全量刷新；保存时仍与已有历史合并
        cache_dir:       显式缓存目录；日更与离线读取必须传同一目录
    """
    global CACHE_DIR
    if cache_dir is not None:
        CACHE_DIR = os.fspath(cache_dir)
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
        download_index_basic(force)
        download_fund_basic(pro, force)
        time.sleep(0.5)
        if not core_only and not market_core:
            download_share_float(pro, start_date, end_date, force)
            time.sleep(0.5)
            download_stk_holdertrade(pro, start_date, end_date, force)
            time.sleep(0.5)
        else:
            mode = "market-core" if market_core else "core-only"
            logger.info(f"  -> {mode}：跳过 share_float / stk_holdertrade")

        if not skip_financial and not market_core:
            download_fina_indicator(pro, force or financial_only_force)
            time.sleep(0.5)
            download_income(pro, force or financial_only_force)
            time.sleep(0.5)
        else:
            reason = "--market-core" if market_core else "--skip-financial"
            logger.info(f"  ↩ 跳过财务数据（{reason}）")
    else:
        logger.info("\n【only-new 模式】跳过静态数据和已有日频数据，只补充新接口")

    # ── 阶段2：获取交易日列表 ──
    logger.info("\n【阶段2】获取回测区间交易日列表...")
    # MA60需要前100天数据，多下载缓冲
    buf_start = (datetime.strptime(start_date, '%Y%m%d') - timedelta(days=120)).strftime('%Y%m%d')
    trade_dates = _get_trade_dates(pro, buf_start, end_date)
    logger.info(f"  共 {len(trade_dates)} 个交易日（含前置缓冲期）")

    # ── 阶段3：按日数据 ──
    if only_new:
        label = "新增接口（top_list/top_inst/margin_detail）"
    elif market_core:
        label = "核心行情/换手率/资金流/指数"
    else:
        label = "行情/换手率/资金流/指数/龙虎榜/融资"
    logger.info(f"\n【阶段3】按日下载{label}")
    results = download_daily_range(
        pro,
        trade_dates,
        force,
        only_new=only_new,
        core_only=core_only,
        market_core=market_core,
    )
    daily_ok, basic_ok, mf_ok, idx_ok, fund_ok, tl_ok, ti_ok, mg_ok = results
    if not only_new:
        _validate_completed_core_downloads(
            trade_dates,
            start_date,
            end_date,
            require_index=not core_only,
        )

    # ── 完成报告 ──
    elapsed = (datetime.now() - t0).total_seconds()
    logger.info(f"\n{'='*60}")
    logger.info(f"  ✅ 下载完成！耗时：{elapsed/60:.1f} 分钟")
    if not only_new:
        logger.info(f"  daily：{daily_ok}/{len(trade_dates)} 天")
        logger.info(f"  daily_basic：{basic_ok}/{len(trade_dates)} 天")
        logger.info(f"  moneyflow：{mf_ok}/{len(trade_dates)} 天")
        logger.info(f"  fund_daily：{fund_ok}/{len(trade_dates)} 天")
        logger.info(f"  index_daily：{idx_ok}/{len(trade_dates)} 天")
    if not market_core:
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
    parser.add_argument('--market-core', action='store_true',
                        help='十年回测核心同步：下载 daily/daily_basic/moneyflow/index_daily/stock_basic，跳过财务、龙虎榜和融资融券')
    parser.add_argument('--financial-only-force', action='store_true',
                        help='仅对财务接口做全量刷新；旧财务历史仍会合并保留')
    parser.add_argument('--cache-dir', type=str, default=CACHE_DIR,
                        help='缓存目录，必须与后续 LocalDataProxy 使用的目录一致')
    args = parser.parse_args()

    run_download(
        start_date=args.start,
        end_date=args.end,
        force=args.force,
        skip_financial=args.skip_financial,
        only_new=args.only_new,
        core_only=args.core_only,
        market_core=args.market_core,
        financial_only_force=args.financial_only_force,
        cache_dir=args.cache_dir,
    )


if __name__ == '__main__':
    main()
