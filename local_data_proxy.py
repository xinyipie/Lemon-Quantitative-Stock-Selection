"""
本地数据代理 LocalDataProxy
============================
功能：
  - 完全替代 tushare pro 对象，从本地 Parquet 文件读取数据
  - 暴露与 pro 完全相同的方法签名，支持透明的依赖注入
  - 支持按 ts_code / trade_date / start_date / end_date / fields 过滤
  - 用于离线回测，不依赖网络和 Tushare API

使用方式：
  from local_data_proxy import LocalDataProxy
  import main as stock_main

  proxy = LocalDataProxy(cache_dir="data/cache")
  stock_main.set_pro(proxy)          # 注入代理
  result = stock_main.run_daily_selection(target_date="20250115")
  stock_main.restore_pro()           # 恢复原始 pro

目录结构要求（由 data_downloader.py 生成）：
  data/cache/
  ├── trade_cal.parquet
  ├── stock_basic.parquet
  ├── stock_basic_history/YYYYMMDD.parquet  # 当日 L/D/P 完整快照；严格历史回测必需
  ├── share_float.parquet
  ├── stk_holdertrade.parquet
  ├── fina_indicator.parquet
  ├── income.parquet
  ├── daily/         YYYYMMDD.parquet
  ├── daily_basic/   YYYYMMDD.parquet
  ├── moneyflow/     YYYYMMDD.parquet
  └── index_daily/   YYYYMMDD.parquet
"""

import os
import logging
from functools import lru_cache
from typing import Optional, List, Dict

import pandas as pd

logger = logging.getLogger("local_proxy")

# ── 缓存大小常量（按日文件数量很多，静态文件数量少）──
_LRU_STATIC = 8       # 静态文件缓存（stock_basic / trade_cal 等）
_LRU_DAILY  = 1024    # 日频文件缓存（一年约252天×多个sub，适当放大）


class PointInTimeDataError(ValueError):
    """本地静态资料不足以证明历史截面可靠。"""


def _select_fields(df: pd.DataFrame, fields: Optional[str]) -> pd.DataFrame:
    """
    按 fields 字符串过滤列（与 tushare API 行为一致）。
    fields=None 或 '' 时返回全部列。
    只返回 df 中实际存在的列（容忍字段名拼写差异）。
    若请求字段中有列在 df 中不存在，记录 debug 日志但不报错。
    """
    if not fields:
        return df
    want = [f.strip() for f in fields.split(',') if f.strip()]
    exist = [c for c in want if c in df.columns]
    missing = [c for c in want if c not in df.columns]
    if missing:
        logger.debug(f"[_select_fields] 请求字段在 parquet 中不存在，已忽略：{missing}")
    return df[exist] if exist else df


def _filter_ts_codes(df: pd.DataFrame, ts_code: Optional[str]) -> pd.DataFrame:
    """
    按逗号分隔的 ts_code 字符串过滤行。
    ts_code=None 时返回全部行。
    """
    if not ts_code or 'ts_code' not in df.columns:
        return df
    codes = [c.strip() for c in ts_code.split(',') if c.strip()]
    return df[df['ts_code'].isin(codes)].reset_index(drop=True)


class LocalDataProxy:
    """
    本地 Parquet 数据代理，接口与 tushare pro 对象完全一致。

    所有方法均返回 pd.DataFrame，与 tushare 原始行为相同。
    普通读取失败时返回空 DataFrame 并记录警告；严格历史 stock_basic 缺少
    精确快照时抛 PointInTimeDataError，禁止静默运行伪时点回测。
    """

    def __init__(self, cache_dir: str = os.path.join("data", "cache"),
                 strict_point_in_time: bool = True):
        self.cache_dir = cache_dir
        self.strict_point_in_time = bool(strict_point_in_time)
        self._check_cache_dir()

        # ── 静态文件读取（带 lru_cache，每进程只读一次）──
        # 用实例方法包装 lru_cache，避免 self 绑定问题
        self._read_static = lru_cache(maxsize=_LRU_STATIC)(self._read_static_impl)
        self._read_daily  = lru_cache(maxsize=_LRU_DAILY)(self._read_daily_impl)

        # ── 目录文件名列表缓存（避免 _read_date_range 每次重扫目录）──
        # key: sub目录名 → sorted list of date strings（已去掉 .parquet 后缀）
        self._dir_dates: Dict[str, List[str]] = {}

    # ==================== 内部读取辅助 ====================

    def _check_cache_dir(self):
        if not os.path.isdir(self.cache_dir):
            raise FileNotFoundError(
                f"[LocalDataProxy] 缓存目录不存在：{self.cache_dir}\n"
                "请先运行 data_downloader.py 下载数据。"
            )

    def _static_path(self, name: str) -> str:
        return os.path.join(self.cache_dir, f"{name}.parquet")

    def _daily_path(self, sub: str, date: str) -> str:
        return os.path.join(self.cache_dir, sub, f"{date}.parquet")

    def _read_static_impl(self, name: str) -> pd.DataFrame:
        """读取静态 parquet 文件（内部实现，被 lru_cache 包装）"""
        path = self._static_path(name)
        if not os.path.exists(path):
            logger.warning(f"[LocalDataProxy] 静态文件不存在：{path}")
            return pd.DataFrame()
        try:
            # 不指定 engine，让 pandas 自动选择已安装的引擎（pyarrow 或 fastparquet）
            return pd.read_parquet(path)
        except Exception as e:
            # 升级为 warning 并打印到根 logger，确保控制台可见
            import logging
            logging.getLogger().warning(f"[LocalDataProxy] 读取静态文件失败 {name}: {e}")
            logger.error(f"[LocalDataProxy] 读取 {path} 失败：{e}")
            return pd.DataFrame()

    def _read_daily_impl(self, sub: str, date: str) -> pd.DataFrame:
        """读取按日 parquet 文件（内部实现，被 lru_cache 包装）"""
        path = self._daily_path(sub, date)
        if not os.path.exists(path):
            logger.debug(f"[LocalDataProxy] 日频文件不存在（可能是非交易日）：{path}")
            return pd.DataFrame()
        try:
            # 不指定 engine，让 pandas 自动选择已安装的引擎（pyarrow 或 fastparquet）
            df = pd.read_parquet(path)
            # Tushare 以 trade_date 为查询参数时，返回数据可能不含 trade_date 列
            # 从文件名补充，确保下游 sort_values('trade_date') 不报 KeyError
            if 'trade_date' not in df.columns and not df.empty:
                df = df.copy()
                df['trade_date'] = date
            return df
        except Exception as e:
            import logging
            logging.getLogger().warning(f"[LocalDataProxy] 读取日频文件失败 {sub}/{date}: {e}")
            logger.error(f"[LocalDataProxy] 读取 {path} 失败：{e}")
            return pd.DataFrame()

    def _get_dir_dates(self, sub: str) -> List[str]:
        """
        获取 sub 目录下所有可用日期列表（升序），结果在进程内缓存，只扫一次目录。
        """
        if sub not in self._dir_dates:
            sub_dir = os.path.join(self.cache_dir, sub)
            if not os.path.isdir(sub_dir):
                self._dir_dates[sub] = []
            else:
                dates = []
                for fname in sorted(os.listdir(sub_dir)):
                    if fname.endswith('.parquet'):
                        dates.append(fname[:-8])  # 去掉 ".parquet"
                self._dir_dates[sub] = dates
        return self._dir_dates[sub]

    def _read_date_range(self, sub: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        读取某个 sub 目录内 [start_date, end_date] 区间的所有日频文件并合并。
        用于 daily(start_date=..., end_date=...) 式的多日请求。
        目录扫描结果已缓存（_get_dir_dates），单文件读取有 lru_cache，避免重复 I/O。
        """
        frames = []
        for date in self._get_dir_dates(sub):
            if date < start_date:
                continue
            if date > end_date:
                break
            df = self._read_daily(sub, date)
            if not df.empty:
                frames.append(df)

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # ==================== 静态数据接口 ====================

    def trade_cal(self,
                  exchange: str = 'SSE',
                  start_date: str = '',
                  end_date: str = '',
                  is_open: Optional[int] = None,
                  fields: str = '') -> pd.DataFrame:
        """
        交易日历。
        等价：pro.trade_cal(exchange='SSE', start_date=..., end_date=..., is_open=1, fields=...)
        """
        df = self._read_static('trade_cal').copy()
        if df.empty:
            return df

        # 区间过滤：统一 cal_date 为字符串（parquet 可能存为 datetime64，与 str 比较会失败）
        if 'cal_date' in df.columns:
            df['cal_date'] = df['cal_date'].astype(str).str.replace('-', '').str[:8]
        if start_date and 'cal_date' in df.columns:
            df = df[df['cal_date'] >= start_date]
        if end_date and 'cal_date' in df.columns:
            df = df[df['cal_date'] <= end_date]

        # is_open 过滤：列值可能是字符串 '0'/'1'（fastparquet 读取时不自动转型），
        # 用 astype(str) 统一后与 str(is_open) 比较，兼容 int/float/str 各种存储格式
        if is_open is not None and 'is_open' in df.columns:
            df = df[df['is_open'].astype(str) == str(is_open)]

        return _select_fields(df.reset_index(drop=True), fields)

    def stock_basic(self,
                    exchange: str = '',
                    list_status: str = 'L',
                    ts_code: str = '',
                    fields: str = '',
                    as_of_date: str = '',
                    strict_point_in_time: Optional[bool] = None) -> pd.DataFrame:
        """
        股票基础信息。
        等价：pro.stock_basic(exchange='', list_status='L', fields=...)

        as_of_date 优先读取 stock_basic_history/YYYYMMDD.parquet 精确快照。
        缺少快照时，非严格模式仅用生命周期字段近似并附不可靠元数据；严格模式拒绝。
        """
        strict = self.strict_point_in_time if strict_point_in_time is None else bool(strict_point_in_time)
        cutoff = ''
        exact_snapshot = False
        if as_of_date:
            cutoff = str(as_of_date).replace('-', '')[:8]
            if len(cutoff) != 8 or not cutoff.isdigit():
                raise ValueError(f"as_of_date 必须是 YYYYMMDD：{as_of_date}")
            snapshot_name = os.path.join('stock_basic_history', cutoff)
            if os.path.exists(self._static_path(snapshot_name)):
                df = self._read_static(snapshot_name).copy()
                exact_snapshot = not df.empty
            else:
                df = self._read_static('stock_basic').copy()
        else:
            df = self._read_static('stock_basic').copy()
        if df.empty:
            if as_of_date and strict:
                raise PointInTimeDataError(
                    f"stock_basic 在 {cutoff} 没有可用数据；"
                    "请提供 stock_basic_history/YYYYMMDD.parquet"
                )
            return df

        if exchange and 'exchange' in df.columns:
            df = df[df['exchange'].astype(str) == str(exchange)]

        audit_columns = []
        if as_of_date:
            has_lifecycle = {'list_date', 'delist_date', 'list_status'}.issubset(df.columns)
            complete_scope = (
                'basic_status_scope' in df.columns
                and df['basic_status_scope'].astype(str).eq('L,D,P').all()
            )
            membership_reliable = bool(exact_snapshot and complete_scope)
            if strict and not exact_snapshot:
                raise PointInTimeDataError(
                    f"stock_basic 缺少 {cutoff} 精确历史快照；"
                    "请提供 stock_basic_history/YYYYMMDD.parquet"
                )
            if not has_lifecycle:
                if strict:
                    raise PointInTimeDataError("stock_basic 缺少 list_date/delist_date/list_status，无法还原历史上市范围")
                logger.warning("[LocalDataProxy] stock_basic 生命周期字段不完整，历史股票范围不可靠")
            else:
                if exact_snapshot:
                    if list_status:
                        df = df[df['list_status'].astype(str) == str(list_status)].copy()
                else:
                    listed = df['list_date'].astype('string').str.replace(r'\.0$', '', regex=True)
                    delisted = df['delist_date'].astype('string').str.replace(r'\.0$', '', regex=True)
                    valid_list = listed.str.fullmatch(r'\d{8}', na=False).astype(bool)
                    valid_delist = delisted.str.fullmatch(r'\d{8}', na=False).astype(bool)
                    if list_status == 'L':
                        # Arrow字符串的缺失比较结果不能直接与布尔数组混算。
                        listed_before = listed.le(cutoff).fillna(False).astype(bool)
                        delisted_after = delisted.gt(cutoff).fillna(False).astype(bool)
                        df = df[valid_list & listed_before & (~valid_delist | delisted_after)].copy()
                    elif list_status:
                        # P 表示暂停上市，生命周期日期不能还原历史暂停状态；仅保留当前标签并标不可靠。
                        df = df[df['list_status'].astype(str) == str(list_status)].copy()

            if strict and not membership_reliable:
                raise PointInTimeDataError("stock_basic 缓存未证明包含 L/D/P 全部状态，历史上市范围不可靠")

            if exact_snapshot and 'basic_snapshot_date' in df.columns:
                snapshots = df['basic_snapshot_date'].astype('string').str.replace(r'\.0$', '', regex=True)
                # 单次快照只能证明快照当日，既不能向过去回填，也不能证明未来未变更。
                name_industry_reliable = snapshots.str.fullmatch(r'\d{8}', na=False) & (snapshots == cutoff)
            else:
                name_industry_reliable = pd.Series(False, index=df.index)

            requested = {item.strip() for item in fields.split(',') if item.strip()} if fields else set(df.columns)
            if strict and requested.intersection({'name', 'industry'}) and not name_industry_reliable.all():
                raise PointInTimeDataError("stock_basic 名称/行业缺少历史时点证据，严格模式拒绝使用")
            if requested.intersection({'name', 'industry'}) and not name_industry_reliable.all():
                logger.warning(
                    "[LocalDataProxy] stock_basic 名称/行业来自缓存快照，早于快照的历史截面不可靠；"
                    "可启用 strict_point_in_time 拒绝使用"
                )

            df['membership_point_in_time_reliable'] = membership_reliable
            df['name_industry_point_in_time_reliable'] = name_industry_reliable.astype(bool)
            df['point_in_time_as_of_date'] = cutoff
            df['point_in_time_source'] = 'exact_snapshot' if exact_snapshot else 'current_static_fallback'
            audit_columns = [
                'membership_point_in_time_reliable',
                'name_industry_point_in_time_reliable',
                'point_in_time_as_of_date',
                'point_in_time_source',
            ]
        elif list_status and 'list_status' in df.columns:
            df = df[df['list_status'].astype(str) == str(list_status)].copy()
            complete_scope = (
                'basic_status_scope' in df.columns
                and df['basic_status_scope'].astype(str).eq('L,D,P').all()
            )
            if 'basic_snapshot_date' in df.columns:
                snapshots = df['basic_snapshot_date'].astype('string').str.replace(r'\.0$', '', regex=True)
                valid_snapshots = snapshots.str.fullmatch(r'\d{8}', na=False)
            else:
                snapshots = pd.Series('', index=df.index, dtype='string')
                valid_snapshots = pd.Series(False, index=df.index)
            df['membership_point_in_time_reliable'] = bool(complete_scope)
            df['name_industry_point_in_time_reliable'] = valid_snapshots.astype(bool)
            df['point_in_time_as_of_date'] = snapshots.where(valid_snapshots, '')
            df['point_in_time_source'] = 'current_static'
            audit_columns = [
                'membership_point_in_time_reliable',
                'name_industry_point_in_time_reliable',
                'point_in_time_as_of_date',
                'point_in_time_source',
            ]

        # 按 ts_code 过滤（批量分析时传入逗号分隔的代码列表）
        df = _filter_ts_codes(df, ts_code if ts_code else None)
        selected = _select_fields(df, fields)
        if audit_columns:
            selected = selected.copy()
            for column in audit_columns:
                selected[column] = df.loc[selected.index, column].values
        return selected.reset_index(drop=True)

    def share_float(self,
                    start_date: str = '',
                    end_date: str = '',
                    ts_code: str = '',
                    fields: str = '') -> pd.DataFrame:
        """
        限售股解禁。
        等价：pro.share_float(start_date=..., end_date=..., fields=...)
        """
        df = self._read_static('share_float').copy()
        if df.empty:
            return df

        date_col = 'ann_date' if 'ann_date' in df.columns else None
        if date_col:
            df[date_col] = df[date_col].astype(str).str.replace('-', '').str[:8]
            if start_date:
                df = df[df[date_col] >= start_date]
            if end_date:
                df = df[df[date_col] <= end_date]

        df = _filter_ts_codes(df, ts_code if ts_code else None)
        return _select_fields(df.reset_index(drop=True), fields)

    def stk_holdertrade(self,
                        start_date: str = '',
                        end_date: str = '',
                        holder_type: str = '',
                        ts_code: str = '',
                        fields: str = '') -> pd.DataFrame:
        """
        股东增减持。
        等价：pro.stk_holdertrade(start_date=..., end_date=..., holder_type='G', fields=...)
        """
        df = self._read_static('stk_holdertrade').copy()
        if df.empty:
            return df

        date_col = 'ann_date' if 'ann_date' in df.columns else None
        if date_col:
            df[date_col] = df[date_col].astype(str).str.replace('-', '').str[:8]
            if start_date:
                df = df[df[date_col] >= start_date]
            if end_date:
                df = df[df[date_col] <= end_date]

        if holder_type and 'holder_type' in df.columns:
            df = df[df['holder_type'] == holder_type]

        df = _filter_ts_codes(df, ts_code if ts_code else None)
        return _select_fields(df.reset_index(drop=True), fields)

    def fina_indicator(self,
                       ts_code: str = '',
                       fields: str = '') -> pd.DataFrame:
        """
        财务指标（ROE、负债率）。
        等价：pro.fina_indicator(ts_code=..., fields=...)
        注意：本地文件保留完整公告历史，下游按 ann_date 做截面过滤。
        """
        df = self._read_static('fina_indicator').copy()
        if df.empty:
            return df

        df = _filter_ts_codes(df, ts_code if ts_code else None)
        return _select_fields(df, fields)

    def income(self,
               ts_code: str = '',
               fields: str = '') -> pd.DataFrame:
        """
        利润表（营收）。
        等价：pro.income(ts_code=..., fields=...)
        注意：本地文件保留完整公告历史（用于历史同比与截面计算）。
        """
        df = self._read_static('income').copy()
        if df.empty:
            return df

        df = _filter_ts_codes(df, ts_code if ts_code else None)
        return _select_fields(df, fields)

    # ==================== 日频数据接口 ====================

    def daily(self,
              ts_code: str = '',
              trade_date: str = '',
              start_date: str = '',
              end_date: str = '',
              fields: str = '') -> pd.DataFrame:
        """
        A股日线行情。
        支持两种调用模式：
          1. 指定 trade_date：返回全市场当日数据（或按 ts_code 过滤）
          2. 指定 start_date / end_date：返回时间区间数据（ts_code 可选）

        等价：
          pro.daily(trade_date='20250115', fields=...)
          pro.daily(ts_code='000001.SZ', start_date='20250101', end_date='20250131', fields=...)
        """
        if trade_date:
            df = self._read_daily('daily', trade_date).copy()
            df = _filter_ts_codes(df, ts_code if ts_code else None)
        elif start_date and end_date:
            df = self._read_date_range('daily', start_date, end_date)
            df = _filter_ts_codes(df, ts_code if ts_code else None)
        elif ts_code and not trade_date:
            # 只传 ts_code 不传日期：尝试读取所有文件（不推荐，成本高）
            logger.warning("[LocalDataProxy] daily() 调用未传 trade_date/start_date/end_date，将扫描全部文件，可能较慢")
            df = self._read_date_range('daily', '19900101', '99991231')
            df = _filter_ts_codes(df, ts_code)
        else:
            logger.warning("[LocalDataProxy] daily() 调用参数不足，返回空 DataFrame")
            return pd.DataFrame()

        return _select_fields(df, fields)

    def daily_basic(self,
                    trade_date: str = '',
                    ts_code: str = '',
                    fields: str = '') -> pd.DataFrame:
        """
        每日基础指标（换手率、量比等）。
        等价：pro.daily_basic(trade_date='20250115', fields=...)
        """
        if not trade_date:
            logger.warning("[LocalDataProxy] daily_basic() 未传 trade_date，返回空 DataFrame")
            return pd.DataFrame()

        df = self._read_daily('daily_basic', trade_date).copy()
        df = _filter_ts_codes(df, ts_code if ts_code else None)
        return _select_fields(df, fields)

    def moneyflow(self,
                  ts_code: str = '',
                  trade_date: str = '',
                  start_date: str = '',
                  end_date: str = '',
                  fields: str = '') -> pd.DataFrame:
        """
        个股资金流向（主力净流入）。
        支持单日（trade_date）和区间（start_date/end_date）两种调用模式。
        等价：pro.moneyflow(trade_date='20250115', fields=...)
             pro.moneyflow(ts_code=..., start_date=..., end_date=..., fields=...)
        """
        if trade_date:
            df = self._read_daily('moneyflow', trade_date).copy()
            df = _filter_ts_codes(df, ts_code if ts_code else None)
        elif start_date and end_date:
            df = self._read_date_range('moneyflow', start_date, end_date)
            df = _filter_ts_codes(df, ts_code if ts_code else None)
        else:
            logger.warning("[LocalDataProxy] moneyflow() 未传 trade_date 或区间，返回空 DataFrame")
            return pd.DataFrame()

        return _select_fields(df, fields)

    def margin_detail(self,
                      ts_code: str = '',
                      trade_date: str = '',
                      start_date: str = '',
                      end_date: str = '',
                      fields: str = '') -> pd.DataFrame:
        """
        融资融券交易明细（margin_detail）。
        离线回测时若无缓存文件则返回空 DataFrame（静默降级，不影响主流程）。
        等价：pro.margin_detail(ts_code=..., trade_date=..., fields=...)
        """
        if trade_date:
            df = self._read_daily('margin_detail', trade_date).copy()
            df = _filter_ts_codes(df, ts_code if ts_code else None)
        elif start_date and end_date:
            df = self._read_date_range('margin_detail', start_date, end_date)
            df = _filter_ts_codes(df, ts_code if ts_code else None)
        else:
            logger.warning("[LocalDataProxy] margin_detail() 参数不足，返回空 DataFrame")
            return pd.DataFrame()

        return _select_fields(df, fields)

    def index_daily(self,
                    ts_code: str = '',
                    trade_date: str = '',
                    start_date: str = '',
                    end_date: str = '',
                    fields: str = '') -> pd.DataFrame:
        """
        指数日线（大盘 + 申万行业）。
        支持 trade_date 单日 或 start_date/end_date 区间。

        等价：
          pro.index_daily(ts_code='000001.SH,...', trade_date='20250115', fields=...)
          pro.index_daily(ts_code='000001.SH', start_date='20250101', end_date='20250131', fields=...)
        """
        if trade_date:
            df = self._read_daily('index_daily', trade_date).copy()
        elif start_date and end_date:
            df = self._read_date_range('index_daily', start_date, end_date)
        else:
            logger.warning("[LocalDataProxy] index_daily() 参数不足，返回空 DataFrame")
            return pd.DataFrame()

        df = _filter_ts_codes(df, ts_code if ts_code else None)
        return _select_fields(df, fields)

    # ==================== 调试辅助 ====================

    def __repr__(self) -> str:
        return f"LocalDataProxy(cache_dir='{self.cache_dir}')"

    def available_dates(self, sub: str = 'daily') -> List[str]:
        """
        返回指定子目录下已下载的所有交易日列表（升序）。
        用于调试和确认数据完整性。
        """
        sub_dir = os.path.join(self.cache_dir, sub)
        if not os.path.isdir(sub_dir):
            return []
        dates = [
            f[:-8] for f in os.listdir(sub_dir)
            if f.endswith('.parquet') and len(f) == 16  # YYYYMMDD.parquet = 16 chars
        ]
        return sorted(dates)

    def coverage_report(self) -> str:
        """
        输出数据覆盖情况摘要，用于验证下载完整性。
        """
        lines = ["[LocalDataProxy] 数据覆盖报告"]
        lines.append(f"  缓存目录：{os.path.abspath(self.cache_dir)}")

        for name in ['trade_cal', 'stock_basic', 'share_float', 'stk_holdertrade',
                     'fina_indicator', 'income']:
            path = self._static_path(name)
            if os.path.exists(path):
                try:
                    df = pd.read_parquet(path)
                    lines.append(f"  {name:20s}: {len(df):6d} 行  ✓")
                except Exception:
                    lines.append(f"  {name:20s}: 读取失败   ✗")
            else:
                lines.append(f"  {name:20s}: 文件缺失   ✗")

        for sub in ['daily', 'daily_basic', 'moneyflow', 'index_daily']:
            dates = self.available_dates(sub)
            if dates:
                lines.append(
                    f"  {sub:20s}: {len(dates):4d} 天  [{dates[0]} ~ {dates[-1]}]  ✓"
                )
            else:
                lines.append(f"  {sub:20s}: 无数据      ✗")

        return "\n".join(lines)
