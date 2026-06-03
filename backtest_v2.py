"""
回测框架 v2 - 完整重写版
===========================
设计原则：
  1. 严格避免未来函数：选股只用 T 日收盘前可知信息，买入用 T+1 开盘价
  2. 涨跌停处理：次日开盘涨停则跳过不买，当日跌停按跌停价止损
  3. 按需批量预取：每个回测日一次性批量拉取，不逐股请求
  4. 复现实盘逻辑：直接调用 main.py 的 get_all_stocks / select_stock_pool
  5. 指标完整：胜率、盈亏比、最大回撤、夏普比率、vs 沪深300超额
  6. 输出：控制台摘要 + 逐笔明细 CSV + 资金净值曲线 CSV

接口权限范围（5000积分）：
  - trade_cal / stock_basic / daily / daily_basic：基础
  - moneyflow：可用（net_mf_amount字段）
  - index_daily：传具体 ts_code（申万一级 801xxx.SI，大盘 000001.SH）
  - share_float：可用
  - stk_holdertrade：可用

用法示例：
  python backtest_v2.py                           # 默认回测近60个交易日
  python backtest_v2.py --start 20250101 --end 20250331
  python backtest_v2.py --start 20250101 --end 20250331 --hold 2 --topn 5
"""

import sys
import os
import time
import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

import pandas as pd
from strategy_profiles import (
    SHORT_FACTOR_COLUMNS,
    apply_style_gate,
    available_profiles,
    available_style_gates,
    factor_profile_score,
    normalize_factor_profile,
    normalize_style_gate,
)

# ==================== 路径修复（确保能 import main.py）====================
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Offline backtests inject LocalDataProxy after parsing args, so importing main
# should not require a Tushare token just to reach that point.
if "--offline" in sys.argv:
    os.environ.setdefault("LEMON_SKIP_TUSHARE_INIT", "1")

# 延迟 import main，避免 main 模块级代码（init_tushare）在 import 时副作用干扰日志
import main as stock_main

logger = logging.getLogger("backtest_v2")

# ==================== 常量 ====================
COMMISSION_BUY  = 0.0003  # 买入手续费 0.03%（券商万3）
COMMISSION_SELL = 0.0013  # 卖出手续费 0.03% + 印花税 0.1%
SLIPPAGE_BUY    = 0.001   # 买入滑点 0.1%（中小盘冲击成本）
SLIPPAGE_SELL   = 0.001   # 卖出滑点 0.1%
LIMIT_UP_THRESHOLD   =  9.8  # 涨停判断阈值（%）
LIMIT_DOWN_THRESHOLD = -9.8  # 跌停判断阈值（%）


# ==================== 工具函数 ====================

def get_trade_dates(pro, start_date: str, end_date: str) -> List[str]:
    """获取区间内所有交易日，升序"""
    cal = pro.trade_cal(
        exchange='SSE',
        start_date=start_date,
        end_date=end_date,
        is_open=1,
        fields='cal_date'
    )
    dates = sorted(cal['cal_date'].astype(str).tolist())
    logger.info(f"  交易日历：{len(dates)} 天  [{dates[0] if dates else 'N/A'} ~ {dates[-1] if dates else 'N/A'}]")
    return dates


def get_index_daily(pro, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取指数日线数据（用于基准对比和大盘状态）。
    沪深300：000300.SH  上证：000001.SH
    """
    try:
        df = pro.index_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields='trade_date,open,close,pct_chg'
        )
        return df.sort_values('trade_date').reset_index(drop=True)
    except Exception as e:
        logger.warning(f"获取指数{ts_code}数据失败：{e}")
        return pd.DataFrame()


def fetch_next_day_prices(pro, ts_codes: List[str], trade_date: str) -> pd.DataFrame:
    """
    批量获取指定日期的开盘/最高/最低/收盘/涨跌幅，用于模拟交易。
    返回 DataFrame，列：ts_code, open, high, low, close, pct_chg

    离线模式（LocalDataProxy）：直接读整个日文件，不按 ts_code 过滤，
    避免多个 select_date 共享同一 buy_date/hold_date 时缓存数据残缺。
    在线模式（Tushare）：按 ts_codes 批量请求，节省流量和积分。
    """
    # 离线模式：读全量日文件（LocalDataProxy 无网络成本）
    if type(pro).__name__ == 'LocalDataProxy':
        try:
            df = pro.daily(
                trade_date=trade_date,
                fields='ts_code,open,high,low,close,pct_chg'
            )
            # 防御：某些 parquet 文件可能不含 ts_code 列，导致下游 KeyError
            if not df.empty and 'ts_code' not in df.columns:
                logger.warning(f"离线行情（{trade_date}）缺少 ts_code 列，跳过该日数据")
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.warning(f"离线行情读取失败（{trade_date}）：{e}")
            return pd.DataFrame()

    # 在线模式：按批次请求指定 ts_codes
    batch_size = 500
    all_dfs = []
    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i:i + batch_size]
        try:
            df = pro.daily(
                ts_code=",".join(batch),
                trade_date=trade_date,
                fields='ts_code,open,high,low,close,pct_chg'
            )
            if not df.empty:
                all_dfs.append(df)
        except Exception as e:
            logger.warning(f"批量行情第{i // batch_size + 1}批失败（{trade_date}）：{e}")
        if i + batch_size < len(ts_codes):
            time.sleep(0.5)

    if not all_dfs:
        return pd.DataFrame()

    df_all = pd.concat(all_dfs, ignore_index=True)
    df_all = df_all.drop_duplicates(subset='ts_code').reset_index(drop=True)
    return df_all


# ==================== 核心回测类 ====================

class BacktestV2:
    """
    完整回测框架，复现实盘选股逻辑。

    流程：
      T 日收盘后 → 调用实盘选股函数选出候选股（含大盘择时过滤）
      T+1 日开盘 → 以开盘价买入（涨停则跳过）
      持有期间    → 每日检查止盈止损
      T+hold 日  → 收盘卖出（跌停则按跌停价）
    """

    def __init__(
        self,
        pro,
        start_date: str,
        end_date: str,
        hold_days: int = 8,
        top_n: int = 3,
        fallback_stop_pct:   float = -7.0,
        fallback_profit_pct: float = 15.0,   # v3.3: 从10%提升至15%（配合atr_target 3.0×ATR）
        trailing_stop_pct:   float = 7.0,    # v3.3: 从5%放宽至7%，减少移动止损过早击出
        initial_capital: float = 100_000.0,
        use_market_timing: bool = True,
        min_open_ratio: float = 0.0,    # 低开过滤：默认0.0=关闭（纯验证选股质量）；设0.995可恢复"低开>0.5%跳过"的保守行为
        score_order: str = 'desc',
        factor_profile: str = 'original',
        style_gate: str = 'none',
        short_filter_profile: str = 'baseline',
        conditional_lock_enabled: bool = False,
        conditional_lock_activation_pct: float = 6.0,
        conditional_lock_trailing_pct: float = 4.8,
    ):
        """
        Args:
            pro:                  Tushare pro 接口实例
            start_date:           回测开始日期 YYYYMMDD（选股起始日）
            end_date:             回测结束日期 YYYYMMDD
            hold_days:            最大持有天数（技术位未触发时的兜底）
            top_n:                每日最多买入前 N 只（按综合评分排序）
            fallback_stop_pct:    兜底止损线，如 -7.0 表示 -7%（技术位失效时使用）
            fallback_profit_pct:  兜底止盈线，如 10.0 表示 +10%（技术位失效时使用）
            trailing_stop_pct:    移动止损回撤幅度（盈利≥3%后激活）
            initial_capital:      初始资金（元，仅用于资金曲线展示）
            use_market_timing:    True=复现实盘大盘择时（主跌浪空仓）
                                  False=忽略大盘状态，纯验证选股逻辑
            min_open_ratio:       次日开盘确认比例，T+1开盘 / T收盘 须 >= 此值才买入
                                  默认0.0（关闭，允许低开买入——低开 = 更便宜的买点）
                                  设为0.995可恢复原来"低开超0.5%跳过"的保守行为
            score_order:          desc=高分优先（默认）；asc=低分优先，用于验证评分是否反向
            factor_profile:       original=原始总分；diagnostic_v1=子因子诊断重排实验；
                                  profile_v2=按短线交易逻辑分风格重排；
                                  profile_v3=按路径质量（高MFE/低MAE/不塌）重排；
                                  profile_v4=profile_v3 的弱市防守版；
                                  profile_v5=profile_v4 的 sideways 风险门控版
            style_gate:           independent style exposure filter for experiments.
            conditional_lock_enabled: 是否启用弱质票条件化移动止损收紧实验
            conditional_lock_activation_pct: 条件化收紧的最小浮盈/MFE激活阈值
            conditional_lock_trailing_pct: 条件化收紧后的移动止损回撤幅度
        """
        self.pro = pro
        self.start_date = start_date
        self.end_date = end_date
        self.hold_days = hold_days
        self.top_n = top_n
        self.fallback_stop_pct   = fallback_stop_pct
        self.fallback_profit_pct = fallback_profit_pct
        self.trailing_stop_pct   = trailing_stop_pct
        self.initial_capital = initial_capital
        self.use_market_timing = use_market_timing
        self.min_open_ratio = min_open_ratio   # 路线B新增
        self.score_order = score_order if score_order in ('desc', 'asc') else 'desc'
        self.factor_profile = normalize_factor_profile(factor_profile)
        self.style_gate = normalize_style_gate(style_gate)
        self.short_filter_profile = short_filter_profile
        self.conditional_lock_enabled = conditional_lock_enabled
        self.conditional_lock_activation_pct = conditional_lock_activation_pct
        self.conditional_lock_trailing_pct = conditional_lock_trailing_pct
        self.trailing_activate_pct = 3.0       # 移动止损激活门槛（短线：盈利≥3%后激活）
        # 短线激进时间止损（day2亏1%/day3任何亏损即出）：已被动态出场取代，关闭
        # 现由 time_stop_dynamic（到期亏损出）+ weak_close_exit（弱收盘锁利）替代
        self.short_time_stop = False

        # 离线模式（LocalDataProxy）不需要限速睡眠
        self._is_offline = type(pro).__name__ == 'LocalDataProxy'
        if self._is_offline:
            logger.info("  ℹ 离线模式：跳过所有 API 限速 sleep，回测速度将大幅提升")

        # 预加载：交易日历
        self.all_trade_dates = get_trade_dates(pro, start_date, end_date)

        # 基准（沪深300）日线，用于超额收益计算
        # 注意：不往前推缓冲，直接用回测区间即可（只需首尾收盘价）
        self.benchmark_df = get_index_daily(pro, '000300.SH', start_date, end_date)

    def _apply_style_gate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Filter candidate universe by market style without changing scores."""
        return apply_style_gate(df, self.style_gate)

    def _factor_profile_score(self, row: pd.Series, base_score_col: str) -> float:
        """Experimental short-score profiles built from exported sub-factors."""
        return factor_profile_score(row, self.factor_profile, base_score_col)

    def _conditional_trailing_pct(
        self,
        row: pd.Series,
        current_profit_pct: float,
        mfe_pct: float,
        base_trailing_pct: float,
    ) -> float:
        """弱质票已有明显浮盈后，单笔收紧移动止损；默认保持基线。"""
        if not getattr(self, 'conditional_lock_enabled', False):
            return base_trailing_pct

        activation = getattr(self, 'conditional_lock_activation_pct', 6.0)
        if max(current_profit_pct, mfe_pct) < activation:
            return base_trailing_pct

        pattern = float(row.get('factor_pattern', 100) or 0)
        wyckoff = float(row.get('factor_wyckoff', 100) or 0)
        volume_ratio = float(row.get('factor_volume_ratio', 100) or 0)
        drawdown = float(row.get('factor_drawdown', 0) or 0)
        drawdown_from_high = float(row.get('drawdown_from_high', 0) or 0)

        weak_quality = (
            pattern < 58
            or wyckoff < 62
            or volume_ratio < 58
            or drawdown > 90
            or (drawdown_from_high > 8 and pattern < 58)
        )
        if not weak_quality:
            return base_trailing_pct

        return min(base_trailing_pct, getattr(self, 'conditional_lock_trailing_pct', 4.8))

    def _select_stocks_for_date(self, trade_date: str, retries: int = 2) -> List[Dict]:
        """
        直接调用 main.run_daily_selection()，与实盘选股逻辑完全共用同一套代码。
        main.py 无论怎么修改，这里自动保持一致，无需手动同步。

        - enable_news=False：回测不需要实时新闻，跳过网络请求节省时间
        - use_market_timing=False：关闭时忽略大盘择时，纯验证选股逻辑本身
        - 超时自动重试 retries 次

        返回 List[Dict]，每个 Dict 包含：
            ts_code, stop_loss_price, target_price, volatility,
            ma5, ma10, high20, low20, select_close
        """
        for attempt in range(retries + 1):
            try:
                sel = stock_main.run_daily_selection(
                    trade_date=trade_date,
                    short_filter_profile=self.short_filter_profile,
                    enable_news=False,      # 回测不拉新闻
                    include_longterm=False  # 短线回测不执行波段模块
                )
                actual_date    = sel['trade_date']
                operation_mode = sel['operation_mode']
                sentiment_data = sel['sentiment_data']
                stock_pool     = sel['stock_pool']

                # ── 四状态机仓位乘数（Regime Filter + Override）──
                # Override状态：BEAR_BOUNCE_OVERRIDE / BULL_PULLBACK_OVERRIDE
                # 这两个状态已在 run_daily_selection 中更新了 position_multiplier/max_hold_days
                position_multiplier = sel.get('position_multiplier', 1.0)
                score_threshold     = sel.get('score_threshold', 45)  # 按分数门槛选股，不限top_n
                regime = sel.get('regime', 'BULL_TREND')
                regime_data = sel.get('regime_data', {})
                override_triggered = regime_data.get('override_triggered', False)

                if regime != 'BULL_TREND':
                    override_tag = "⚡Override" if override_triggered else ""
                    logger.info(
                        f"  [{actual_date}] 状态机：{regime}{override_tag}"
                        f"  仓位×{position_multiplier}  分数门槛≥{score_threshold}"
                    )

                # 大盘择时：use_market_timing=False 时所有状态（含BEAR_TREND）都不空仓，
                # 纯验证选股质量本身，不叠加任何宏观过滤
                if self.use_market_timing and regime == 'BEAR_TREND':
                    logger.info(f"  [{actual_date}] 四状态机：BEAR_TREND，强制空仓跳过")
                    return [], []

                if self.use_market_timing and operation_mode == 'stop':
                    logger.info(f"  [{actual_date}] 大盘择时：{sentiment_data.get('decision_reason','空仓')}，跳过")
                    return [], []

                if stock_pool.empty or position_multiplier == 0:
                    logger.info(f"  [{actual_date}] 短线选股结果为空或仓位乘数=0，跳过")
                    return [], []

                # Reconstructed baseline: fixed TopN after regime position multiplier.
                score_col = 'score' if 'score' in stock_pool.columns else stock_pool.columns[0]
                threshold_col = score_col
                stock_pool = stock_pool.copy()
                if self.factor_profile != 'original':
                    stock_pool['original_score'] = stock_pool[score_col]
                    stock_pool['experiment_score'] = stock_pool.apply(
                        lambda row: self._factor_profile_score(row, score_col),
                        axis=1
                    )
                    score_col = 'experiment_score'
                effective_top_n = int(round(self.top_n * position_multiplier)) if position_multiplier > 0 else 0
                effective_top_n = max(1, effective_top_n) if position_multiplier > 0 else 0
                if effective_top_n == 0:
                    logger.info(f"  [{actual_date}] 仓位乘数为0，跳过")
                    return [], []
                # The live strategy score still controls admission; experiment profiles only rerank.
                raw_candidate_rows = stock_pool[stock_pool[threshold_col] >= score_threshold]
                candidate_rows = self._apply_style_gate(raw_candidate_rows).sort_values(
                    score_col,
                    ascending=(self.score_order == 'asc')
                )
                top_rows = candidate_rows.head(effective_top_n)
                gated_out_count = len(raw_candidate_rows) - len(candidate_rows)
                result = []
                # IC分析池：全部候选股（不限top_n，用于评分预测能力验证）
                ic_pool = []
                # 状态机最大持仓天数（Override时可能缩至3天）
                regime_max_hold = sel.get('max_hold_days', self.hold_days)
                for _, row in top_rows.iterrows():
                    ts_code = stock_main.format_code(row['code'])
                    item = {
                        'ts_code':         ts_code,
                        'stop_loss_price': float(row.get('stop_loss_price', 0) or 0),
                        'target_price':    float(row.get('target_price',    0) or 0),
                        'volatility':      float(row.get('volatility',      3.0) or 3.0),
                        'ma5':             float(row.get('ma5',             0) or 0),
                        'ma10':            float(row.get('ma10',            0) or 0),
                        'high20':          float(row.get('high20',          0) or 0),
                        'low20':           float(row.get('low20',           0) or 0),
                        'select_close':    float(row.get('close',           0) or 0),
                        'regime_max_hold': regime_max_hold,  # 状态机动态持仓天数
                        'short_score':     float(row.get(score_col,          0) or 0),  # 短线综合/实验评分
                        'original_score':  float(row.get('original_score', row.get('score', 0)) or 0),
                        'factor_profile':  self.factor_profile,
                        'style_gate':      self.style_gate,
                    }
                    for col in SHORT_FACTOR_COLUMNS:
                        if col in row:
                            item[col] = row.get(col)
                    result.append(item)

                top_codes = [item['ts_code'] for item in result]

                # 构建IC分析池（全部候选股）
                for _, row in stock_pool.iterrows():
                    ic_item = {
                        'ts_code':      stock_main.format_code(row['code']),
                        'score':        float(row.get(score_col, 0) or 0),
                        'original_score': float(row.get('original_score', row.get('score', 0)) or 0),
                        'select_close': float(row.get('close',  0) or 0),
                        'stop_loss_price': float(row.get('stop_loss_price', 0) or 0),
                        'target_price': float(row.get('target_price', 0) or 0),
                        'factor_profile': self.factor_profile,
                        'style_gate': self.style_gate,
                    }
                    for col in SHORT_FACTOR_COLUMNS:
                        if col in row:
                            ic_item[col] = row.get(col)
                    ic_pool.append(ic_item)

                logger.info(
                    f"  [{actual_date}] 模式:{operation_mode}  TopN={effective_top_n} "
                    f"门槛≥{score_threshold}  排序={self.score_order}  profile={self.factor_profile}  "
                    f"style_gate={self.style_gate}  过滤{gated_out_count}只  "
                    f"选出{len(top_codes)}只：{top_codes}"
                )
                return result, ic_pool

            except Exception as e:
                if attempt < retries:
                    wait = 0 if self._is_offline else 10 * (attempt + 1)  # 离线模式不等待
                    logger.warning(f"  [{trade_date}] 选股失败（第{attempt+1}次），{wait}秒后重试：{e}")
                    if wait > 0:
                        time.sleep(wait)
                else:
                    logger.error(f"  [{trade_date}] 选股失败，已重试{retries}次，跳过：{e}")
        return [], []

    # ------------------------------------------------------------------ #
    #  单笔交易模拟                                                        #
    # ------------------------------------------------------------------ #

    def _simulate_trade(
        self,
        ts_code: str,
        buy_date: str,           # T+1 日（买入日）
        future_dates: List[str], # 从 buy_date 开始的后续交易日列表
        price_cache: Dict[str, pd.DataFrame],  # {date: DataFrame} 已预取的行情
        # ── 技术面止盈止损参数（T日已知，无未来函数）──
        tech_stop_price:   float = 0.0,  # 技术止损价（均线支撑位）
        tech_target_price: float = 0.0,  # 技术目标价（high20/波动率）
        volatility:        float = 3.0,  # 近10日波动率（用于trailing stop参数化）
        tech_low20:        float = 0.0,  # 近20日最低价（兜底止损）
        select_close:      float = 0.0,  # T日收盘价（价格比例映射用）
        regime_max_hold:   int   = 0,    # 状态机动态持仓天数（0=使用全局默认）
        track_type:        str   = 'unknown',  # 分轨标记：catchup/pullback/both
        signal_row: Optional[pd.Series] = None,  # 选股日已知的短线子因子，用于条件化出场
    ) -> Optional[Dict]:
        """
        模拟一笔交易，含技术面动态止盈止损、移动止损、涨跌停处理。

        止损策略（三层取最高，最保守）：
          层1：技术均线止损（选股时已算好，按T日收盘→T+1开盘比例映射）
          层2：近20日低点 × 98.5%（结构止损兜底）
          层3：买入价 × 93%（硬底，最大亏损7%）
          + 移动止损：盈利≥3%后激活，随收盘价上升只升不降

        止盈策略：
          技术目标价（high20/波动率），同样按比例映射，最低保3%空间
          + 跳空高开（T+1开盘已超目标价）：直接以开盘价止盈

        涨跌停规则：
          - 买入日开盘涨停（pct_chg >= 9.8）：无法买入，跳过
          - 持有期触止损：用盘中最低价判断，非跌停按止损价成交
          - 持有期触止盈：用盘中最高价判断；若当日涨停封板无法卖出，
            顺延到次日开盘卖出（更贴近实盘）
          - 持有期满：收盘卖出；若当日涨停，同样顺延次日开盘
          - 回测末尾仍在持仓：取可用的最后一日收盘价强制平仓

        返回 None 表示此笔交易无效（无法买入）。
        """
        # ── 1. 获取买入日行情 ──
        buy_day_df = price_cache.get(buy_date)
        if buy_day_df is None or buy_day_df.empty or 'ts_code' not in buy_day_df.columns:
            return None

        row = buy_day_df[buy_day_df['ts_code'] == ts_code]
        if row.empty:
            return None

        row = row.iloc[0]
        buy_open = float(row['open'])
        buy_pct   = float(row['pct_chg'])

        # 买入日开盘已涨停，无法买入
        if buy_pct >= LIMIT_UP_THRESHOLD:
            logger.debug(f"    {ts_code} {buy_date} 开盘涨停，跳过")
            return None

        if buy_open <= 0:
            return None

        # ── 路线B：次日开盘确认过滤 ──
        # T+1开盘 / T日收盘 < min_open_ratio → 低开幅度过大，说明市场不认可选股信号，跳过
        # 过滤"高开低走"和"跳空低开后被动持有"两类亏损来源
        if self.min_open_ratio > 0 and select_close > 0:
            open_ratio = buy_open / select_close
            if open_ratio < self.min_open_ratio:
                logger.debug(
                    f"    {ts_code} {buy_date} 低开过大（开盘/收盘={open_ratio:.3f} < {self.min_open_ratio}），跳过"
                )
                return None

        buy_price = buy_open

        # ── 2. 计算技术止损价（三层取最高）──
        # T日收盘→T+1开盘的比例映射，将T日的技术位平移到买入价基准
        price_ratio = (buy_price / select_close) if select_close > 0 else 1.0

        # 层1：技术均线止损（选股时已算好的均线支撑位）
        if tech_stop_price > 0:
            adjusted_tech_stop = tech_stop_price * price_ratio
        else:
            adjusted_tech_stop = buy_price * (1 + self.fallback_stop_pct / 100)

        # 层2：近20日低点兜底
        low20_stop = tech_low20 * 0.985 * price_ratio if tech_low20 > 0 else 0.0

        # 层3：硬底（最大亏损7%）
        hard_stop = buy_price * (1 + self.fallback_stop_pct / 100)

        # 取三层最高（最保守），且至少留0.7%缓冲（不能紧贴买入价）
        stop_price = max(adjusted_tech_stop, low20_stop, hard_stop)
        # 修复：去掉 buy_price*0.995 的上限钳制，该钳制会让止损过紧（仅0.5%）
        # 正确语义：止损价不能 >= 买入价（合理性保证），留至少0.7%空间
        stop_price = min(stop_price, buy_price * 0.993)

        # ── 3. 计算技术止盈价 ──
        if tech_target_price > 0:
            adjusted_target = tech_target_price * price_ratio
        else:
            adjusted_target = buy_price * (1 + self.fallback_profit_pct / 100)

        # 保底：至少1.5%空间（原3%太高，选股信号当天就有1~4%涨幅，3%止盈下限容易当天触发）
        profit_price = max(adjusted_target, buy_price * 1.015)

        # ── 4. 跳空处理（T+1开盘时立即判断）──
        # 注意：纯选股验证模式下不做低开跳过（min_open_ratio=0），
        # 但仍保留"开盘价已穿越止损"的极端情况处理（避免回测失真）
        if buy_open <= stop_price * 0.97:   # 只有开盘已大幅跌破止损（再跌3%）才放弃
            profit_pct = (buy_open - buy_price) / buy_price * 100
            return self._build_result(
                ts_code, buy_date, buy_price, buy_date, buy_open,
                profit_pct, 0, 'gap_down_stop', track_type
            )
        if buy_open >= profit_price:
            # 跳空高开已超止盈，按开盘价止盈出场
            profit_pct = (buy_open - buy_price) / buy_price * 100
            return self._build_result(
                ts_code, buy_date, buy_price, buy_date, buy_open,
                profit_pct, 0, 'gap_up_exit', track_type
            )

        # ── 5. 持有期逐日检查 ──
        # future_dates 从 buy_date 开始，持有日从第二个元素起
        # 状态机动态持仓天数：regime_max_hold > 0 时覆盖全局 hold_days
        effective_hold = regime_max_hold if regime_max_hold > 0 else self.hold_days
        # 动态出场：最多额外延长3天，盈利时不强平，让移动止损自然出场
        max_hold_extended = effective_hold + 3
        hold_dates = [d for d in future_dates if d > buy_date][:max_hold_extended]

        # 移动止损：初始等于固定止损，盈利≥3%后激活，只升不降
        trailing_stop = stop_price
        base_trailing_pct = self.trailing_stop_pct
        signal_row = signal_row if signal_row is not None else pd.Series(dtype='float64')

        # 用于涨停顺延：标记是否待次日开盘卖出
        pending_sell_open: Optional[str] = None   # 顺延卖出的日期

        # 连续弱收盘计数（close_pos < 0.25，即收盘价在当日区间下1/4以内）
        consecutive_weak_closes = 0
        # 停牌计数：连续N个交易日无数据视为停牌，复牌当日立即出场
        consecutive_no_data = 0

        for day_idx, check_date in enumerate(hold_dates, start=1):

            # ── 涨停顺延：上一日触止盈/持满但涨停，今日开盘卖出 ──
            if pending_sell_open == check_date:
                day_df = price_cache.get(check_date)
                if day_df is not None and not day_df.empty and 'ts_code' in day_df.columns:
                    row_p = day_df[day_df['ts_code'] == ts_code]
                    if not row_p.empty:
                        open_sell = float(row_p.iloc[0]['open'])
                        profit_pct = (open_sell - buy_price) / buy_price * 100
                        return self._build_result(
                            ts_code, buy_date, buy_price, check_date, open_sell,
                            profit_pct, day_idx, 'take_profit_next_open', track_type
                        )
                # 数据缺失时退化：用买入价平仓（保守）
                return self._build_result(
                    ts_code, buy_date, buy_price, check_date, buy_price,
                    0.0, day_idx, 'take_profit_next_open', track_type
                )

            day_df = price_cache.get(check_date)
            if day_df is None or day_df.empty or 'ts_code' not in day_df.columns:
                consecutive_no_data += 1
                continue  # 当天数据缺失（可能非交易日/停牌），继续持有

            row_d = day_df[day_df['ts_code'] == ts_code]
            if row_d.empty:
                consecutive_no_data += 1
                continue  # 停牌，跳过

            row_d = row_d.iloc[0]

            # ── 停牌保护：连续≥2个交易日无数据（停牌），复牌当日立即出场 ──
            # 防止停牌复牌后大幅低开造成灾难性亏损（如百傲化学 -31%）
            if consecutive_no_data >= 2:
                resume_close = float(row_d['close'])
                profit_pct = (resume_close - buy_price) / buy_price * 100
                consecutive_no_data = 0
                return self._build_result(
                    ts_code, buy_date, buy_price, check_date, resume_close,
                    profit_pct, day_idx, 'suspended_exit', track_type
                )
            consecutive_no_data = 0
            day_high  = float(row_d['high'])
            day_low   = float(row_d['low'])
            day_close = float(row_d['close'])
            day_pct   = float(row_d['pct_chg'])
            is_limit_up   = day_pct >= LIMIT_UP_THRESHOLD
            is_limit_down = day_pct <= LIMIT_DOWN_THRESHOLD
            is_last_day   = (day_idx == len(hold_dates))

            # 当日收盘位置：0=收于最低，1=收于最高
            day_range_val = day_high - day_low
            close_pos_val = (day_close - day_low) / day_range_val if day_range_val > 0.001 else 0.5

            # 更新连续弱收盘计数
            if close_pos_val < 0.25 and not is_limit_up and not is_limit_down:
                consecutive_weak_closes += 1
            else:
                consecutive_weak_closes = 0

            # ── 更新移动止损（盈利达 trailing_activate_pct 后激活，只升不降）──
            current_profit_pct = (day_close - buy_price) / buy_price * 100
            if current_profit_pct >= self.trailing_activate_pct:
                mfe_pct = (max(day_high, day_close) - buy_price) / buy_price * 100
                active_trailing_pct = self._conditional_trailing_pct(
                    signal_row,
                    current_profit_pct=current_profit_pct,
                    mfe_pct=mfe_pct,
                    base_trailing_pct=base_trailing_pct,
                )
                trailing_pct = active_trailing_pct / 100
                new_trailing = day_close * (1 - trailing_pct)
                trailing_stop = max(trailing_stop, new_trailing)

            # ── 时间动量止损：持仓N天仍未盈利则认错离场 ──
            # 逻辑：波段策略买入后应该很快启动，持仓20天还在亏损说明选错了方向
            # 在趋势不对的市场（如2024年10-12月震荡），避免慢放血拖满60天
            time_stop_days = getattr(self, 'time_stop_days', 0)   # 0=不启用
            time_stop_threshold = getattr(self, 'time_stop_threshold', -3.0)  # 亏损X%触发
            if (time_stop_days > 0
                    and day_idx >= time_stop_days
                    and current_profit_pct <= time_stop_threshold
                    and not is_limit_up and not is_limit_down):
                actual_sell = day_close
                profit_pct = current_profit_pct
                return self._build_result(
                    ts_code, buy_date, buy_price, check_date, actual_sell,
                    profit_pct, day_idx, 'time_stop', track_type
                )

            # ── 短线时间止损（Track A/B共用，激进版）──
            # 逻辑：短线票如果不快点涨，通常就不该继续拿
            #   持仓满2天，收益仍<-1%：说明入场后直接走弱，认错离场
            #   持仓满3天，收益仍<0%：超过半程还没盈利，期望值已经偏负
            # 不在跌停板时执行（跌停当天无法正常卖出）
            short_time_stop = getattr(self, 'short_time_stop', True)  # 默认开启
            if short_time_stop and not is_limit_up and not is_limit_down:
                if (day_idx >= 2 and current_profit_pct < -1.0) or \
                   (day_idx >= 3 and current_profit_pct < 0.0):
                    actual_sell = day_close
                    profit_pct = current_profit_pct
                    return self._build_result(
                        ts_code, buy_date, buy_price, check_date, actual_sell,
                        profit_pct, day_idx, 'time_stop_short', track_type
                    )

            # ── 连续弱收盘出场：收于日内下1/4区间连续≥2天且当前盈利，锁定利润 ──
            # 逻辑：连续弱收盘说明盘中有持续抛压，动量衰竭，不等止损被动挨打
            if (consecutive_weak_closes >= 2 and day_idx >= 3
                    and current_profit_pct > 0
                    and not is_limit_up and not is_limit_down):
                return self._build_result(
                    ts_code, buy_date, buy_price, check_date, day_close,
                    current_profit_pct, day_idx, 'weak_close_exit', track_type
                )

            # ── 动态到期：到达原定持仓期，盈利则延期，亏损则出场 ──
            # 逻辑：盈利的票让移动止损自然出场（最多延长3天）；亏损的票不强行等延期
            if day_idx == effective_hold and not is_last_day and not is_limit_up and not is_limit_down:
                if current_profit_pct <= 0:
                    # 到期仍亏，立即出场，不做延期
                    return self._build_result(
                        ts_code, buy_date, buy_price, check_date, day_close,
                        current_profit_pct, day_idx, 'time_stop_dynamic', track_type
                    )
                # 盈利则继续循环（进入延长期，靠移动止损或弱收盘出场）

            # 有效止损价：固定止损和移动止损取较高值
            effective_stop = max(stop_price, trailing_stop)

            # ── 止损优先检查（用盘中最低价）──
            # 涨停日不可能触及止损，无需判断
            if not is_limit_up and day_low <= effective_stop:
                if is_limit_down:
                    # 跌停板无法按止损价成交，按跌停价（盘中最低=跌停价）记录
                    actual_sell = day_low
                else:
                    actual_sell = effective_stop
                profit_pct = (actual_sell - buy_price) / buy_price * 100
                exit_reason = 'trailing_stop' if trailing_stop > stop_price else 'stop_loss'
                return self._build_result(
                    ts_code, buy_date, buy_price, check_date, actual_sell,
                    profit_pct, day_idx, exit_reason, track_type
                )

            # ── 止盈检查（用盘中最高价）──
            if day_high >= profit_price:
                if is_limit_up:
                    # 涨停封板，限价单无法成交，顺延到次日开盘卖出
                    if day_idx < len(hold_dates):
                        pending_sell_open = hold_dates[day_idx]  # 下一个持有日
                        continue
                    else:
                        # 已是最后一个持有日且涨停，直接用涨停价（保守）
                        profit_pct = (day_close - buy_price) / buy_price * 100
                        return self._build_result(
                            ts_code, buy_date, buy_price, check_date, day_close,
                            profit_pct, day_idx, 'take_profit', track_type
                        )
                else:
                    actual_sell = profit_price  # 限价单按止盈价成交
                    profit_pct = (actual_sell - buy_price) / buy_price * 100
                    return self._build_result(
                        ts_code, buy_date, buy_price, check_date, actual_sell,
                        profit_pct, day_idx, 'take_profit', track_type
                    )

            # ── 最后一天：收盘卖出 ──
            if is_last_day:
                if is_limit_up:
                    # 持满但涨停，顺延逻辑：超出 hold_dates 范围，用涨停收盘价平仓
                    profit_pct = (day_close - buy_price) / buy_price * 100
                    return self._build_result(
                        ts_code, buy_date, buy_price, check_date, day_close,
                        profit_pct, day_idx, 'hold_complete', track_type
                    )
                elif is_limit_down:
                    actual_sell = day_low   # 跌停按跌停价（保守）
                else:
                    actual_sell = day_close
                profit_pct = (actual_sell - buy_price) / buy_price * 100
                return self._build_result(
                    ts_code, buy_date, buy_price, check_date, actual_sell,
                    profit_pct, day_idx, 'hold_complete', track_type
                )

        # ── 3. 回测末尾仍持仓：用最后一个有数据的日期收盘价强制平仓 ──
        # 遍历已缓存的持有日，找最近一个有数据的日收盘价
        last_close_date = None
        last_close_price = None
        last_idx = 0
        for fallback_idx, fd in enumerate(hold_dates, start=1):
            fd_df = price_cache.get(fd)
            if fd_df is None or fd_df.empty or 'ts_code' not in fd_df.columns:
                continue
            fd_row = fd_df[fd_df['ts_code'] == ts_code]
            if fd_row.empty:
                continue
            fd_close = float(fd_row.iloc[0]['close'])
            fd_pct   = float(fd_row.iloc[0]['pct_chg'])
            if fd_close > 0:
                last_close_date  = fd
                last_close_price = fd_row.iloc[0]['low'] if fd_pct <= LIMIT_DOWN_THRESHOLD else fd_close
                last_idx = fallback_idx

        if last_close_date is not None:
            profit_pct = (last_close_price - buy_price) / buy_price * 100
            return self._build_result(
                ts_code, buy_date, buy_price, last_close_date, last_close_price,
                profit_pct, last_idx, 'forced_close', track_type
            )

        # 确实没有任何持有期数据（整段停牌），放弃该笔交易
        return None

    @staticmethod
    def _build_result(
        ts_code, buy_date, buy_price,
        sell_date, sell_price, profit_pct,
        hold_days, exit_reason, track_type='unknown'
    ) -> Dict:
        # 手续费 + 滑点（买卖双边合计）
        total_cost = COMMISSION_BUY + COMMISSION_SELL + SLIPPAGE_BUY + SLIPPAGE_SELL
        profit_after_fee = profit_pct - total_cost * 100
        return {
            'ts_code':         ts_code,
            'buy_date':        buy_date,
            'buy_price':       round(buy_price,  3),
            'sell_date':       sell_date,
            'sell_price':      round(sell_price, 3),
            'profit_pct':      round(profit_pct,      2),
            'profit_after_fee':round(profit_after_fee, 2),
            'hold_days':       hold_days,
            'exit_reason':     exit_reason,
            'track_type':      track_type,   # 分轨标记：catchup/pullback/both
        }

    def _compute_signal_window_stats(
        self,
        ts_code: str,
        buy_date: str,
        buy_price: float,
        price_cache: Dict[str, pd.DataFrame],
        max_days: int,
        stop_price: float = 0.0,
        target_price: float = 0.0,
    ) -> Dict:
        """
        Signal-quality view, independent from portfolio sizing:
        after the T+1 open entry, measure the best/worst reachable move
        inside the evaluation window.
        """
        if buy_price <= 0 or buy_date not in self.all_trade_dates:
            return {}

        buy_idx = self.all_trade_dates.index(buy_date)
        window_dates = self.all_trade_dates[buy_idx: buy_idx + max_days + 1]

        max_high_pct = None
        min_low_pct = None
        best_close_pct = None
        worst_close_pct = None
        window_end_pct = None
        first_target_day = None
        first_stop_day = None
        ambiguous_hit_days = 0
        observed = 0

        for day_idx, date in enumerate(window_dates):
            day_df = price_cache.get(date)
            if day_df is None or day_df.empty or 'ts_code' not in day_df.columns:
                continue
            row = day_df[day_df['ts_code'] == ts_code]
            if row.empty:
                continue
            row = row.iloc[0]
            high = float(row['high'])
            low = float(row['low'])
            close = float(row['close'])
            high_pct = (high / buy_price - 1) * 100
            low_pct = (low / buy_price - 1) * 100
            close_pct = (close / buy_price - 1) * 100

            max_high_pct = high_pct if max_high_pct is None else max(max_high_pct, high_pct)
            min_low_pct = low_pct if min_low_pct is None else min(min_low_pct, low_pct)
            best_close_pct = close_pct if best_close_pct is None else max(best_close_pct, close_pct)
            worst_close_pct = close_pct if worst_close_pct is None else min(worst_close_pct, close_pct)
            window_end_pct = close_pct
            observed += 1

            hit_target = target_price > 0 and high >= target_price
            hit_stop = stop_price > 0 and low <= stop_price
            if hit_target and first_target_day is None:
                first_target_day = day_idx
            if hit_stop and first_stop_day is None:
                first_stop_day = day_idx
            if hit_target and hit_stop:
                ambiguous_hit_days += 1

        if observed == 0:
            return {}

        return {
            'signal_window_days': observed,
            'mfe_pct': round(max_high_pct, 2),
            'mae_pct': round(min_low_pct, 2),
            'best_close_pct': round(best_close_pct, 2),
            'worst_close_pct': round(worst_close_pct, 2),
            'window_end_pct': round(window_end_pct, 2),
            'hit_3pct': bool(max_high_pct >= 3.0),
            'hit_5pct': bool(max_high_pct >= 5.0),
            'hit_10pct': bool(max_high_pct >= 10.0),
            'first_target_day': first_target_day,
            'first_stop_day': first_stop_day,
            'ambiguous_hit_days': ambiguous_hit_days,
        }

    # ------------------------------------------------------------------ #
    #  主回测循环                                                          #
    # ------------------------------------------------------------------ #

    def run(self) -> Tuple[pd.DataFrame, Dict, pd.DataFrame]:
        """
        运行完整回测。

        返回：
            trades_df:  逐笔交易明细 DataFrame
            metrics:    汇总指标字典
            equity_df:  资金净值曲线 DataFrame（每日）
        """
        if len(self.all_trade_dates) < 2:
            logger.error("回测区间内交易日不足2天")
            return pd.DataFrame(), {}, pd.DataFrame()

        all_trades = []
        ic_records = []   # IC分析数据（选股日/股票/评分/前瞻收益）
        # {buy_date: [ts_code, ...]} 记录每个买入日的实际开仓股票（用于仓位权重）
        buy_date_codes: Dict[str, List[str]] = {}
        # 行情数据缓存（避免同一天重复拉取）
        price_cache: Dict[str, pd.DataFrame] = {}

        # 纯选股验证模式：不设冷静期，不设连续亏损暂停，完全按评分选股
        rolling_top_n = self.top_n  # 保留供日志/兼容用，实际选股改为按分数门槛

        def ensure_price_cached(date: str, ts_codes: List[str]):
            """确保指定日期的行情已缓存"""
            if date not in price_cache:
                df = fetch_next_day_prices(self.pro, ts_codes, date)
                price_cache[date] = df

        # ── 主循环：遍历每个选股日 ──
        # 选股日索引 i，买入日 = all_trade_dates[i+1]
        select_dates = self.all_trade_dates[:-1]  # 最后一天不能选股（没有次日）
        total = len(select_dates)

        logger.info(f"\n{'='*60}")
        logger.info(f"  回测区间：{self.start_date} → {self.end_date}")
        logger.info(f"  交易日共 {len(self.all_trade_dates)} 天，选股日 {total} 天")
        logger.info(f"  持有天数={self.hold_days}  兜底止损={self.fallback_stop_pct}%  兜底止盈={self.fallback_profit_pct}%  移动止损={self.trailing_stop_pct}%  Top={self.top_n}  开盘确认={self.min_open_ratio}  大盘择时={'开启' if self.use_market_timing else '关闭'}")
        logger.info(f"{'='*60}\n")

        for i, select_date in enumerate(select_dates):
            logger.info(f"[{i+1}/{total}] 选股日：{select_date}")

            # ── 步骤1：当日选股 ──
            selected_items, ic_pool = self._select_stocks_for_date(select_date)
            selected_codes = [item['ts_code'] for item in selected_items]  # 兼容行情预取
            ic_codes = [item['ts_code'] for item in ic_pool]               # IC全候选池代码

            # ── 步骤2：确定买入日 ──
            buy_date_idx = i + 1
            buy_date = self.all_trade_dates[buy_date_idx]

            if not selected_items and not ic_pool:
                if not self._is_offline:
                    time.sleep(0.5)
                continue

            selected_codes = [item['ts_code'] for item in selected_items]
            window_codes = sorted(set(selected_codes + ic_codes))

            # ── 步骤3：预取买入日行情 ──
            ensure_price_cached(buy_date, window_codes)

            # 预取持有期行情：交易逻辑最多会延长3天，候选池信号窗口也需要完整行情。
            future_dates = self.all_trade_dates[buy_date_idx:]
            for fd in future_dates[:self.hold_days + 4]:
                ensure_price_cached(fd, window_codes)
                if not self._is_offline:
                    time.sleep(0.3)

            # ── IC分析：预取5/10/20日后行情（基于buy_date索引）──
            IC_FWD_DAYS = [5, 10, 20]
            ic_fwd_date_map: Dict[int, str] = {}
            for n in IC_FWD_DAYS:
                fwd_idx = buy_date_idx + n
                if fwd_idx < len(self.all_trade_dates):
                    fwd_date = self.all_trade_dates[fwd_idx]
                    ic_fwd_date_map[n] = fwd_date
                    ensure_price_cached(fwd_date, ic_codes)

            # 记录IC候选股（select_close用选股日收盘价，次日开盘买入前已知）
            for ic_item in ic_pool:
                buy_open = 0.0
                buy_df = price_cache.get(buy_date)
                if buy_df is not None and not buy_df.empty and 'ts_code' in buy_df.columns:
                    row_buy = buy_df[buy_df['ts_code'] == ic_item['ts_code']]
                    if not row_buy.empty:
                        buy_open = float(row_buy.iloc[0]['open'])

                rec: Dict = {
                    'select_date':  select_date,
                    'buy_date':     buy_date,
                    'ts_code':      ic_item['ts_code'],
                    'score':        ic_item['score'],
                    'original_score': ic_item.get('original_score', ic_item['score']),
                    'factor_profile': ic_item.get('factor_profile', self.factor_profile),
                    'style_gate':   ic_item.get('style_gate', self.style_gate),
                    'select_close': ic_item['select_close'],
                    'buy_open':     round(buy_open, 3) if buy_open > 0 else None,
                    'signal_target_price': ic_item.get('target_price', 0),
                    'signal_stop_price': ic_item.get('stop_loss_price', 0),
                }
                for col in SHORT_FACTOR_COLUMNS:
                    if col in ic_item:
                        rec[col] = ic_item.get(col)
                if buy_open > 0:
                    rec.update(self._compute_signal_window_stats(
                        ts_code=ic_item['ts_code'],
                        buy_date=buy_date,
                        buy_price=buy_open,
                        price_cache=price_cache,
                        max_days=self.hold_days + 3,
                        stop_price=ic_item.get('stop_loss_price', 0),
                        target_price=ic_item.get('target_price', 0),
                    ))
                for n, fd in ic_fwd_date_map.items():
                    rec[f'fwd_date_{n}d'] = fd
                ic_records.append(rec)

            # ── 步骤4：逐股模拟交易 ──
            actual_bought: List[str] = []   # 实际成功买入的股票（涨停跳过后）
            for item in selected_items:
                ts_code = item['ts_code']
                # 从 trend 字段提取轨道标记
                trend_label = item.get('trend', '')
                if '补涨' in trend_label and '回调' in trend_label:
                    item_track = 'both'
                elif '补涨' in trend_label:
                    item_track = 'catchup'
                else:
                    item_track = 'pullback'
                trade = self._simulate_trade(
                    ts_code, buy_date,
                    self.all_trade_dates[buy_date_idx:],
                    price_cache,
                    tech_stop_price   = item['stop_loss_price'],
                    tech_target_price = item['target_price'],
                    volatility        = item['volatility'],
                    tech_low20        = item['low20'],
                    select_close      = item['select_close'],
                    regime_max_hold   = item.get('regime_max_hold', 0),
                    track_type        = item_track,
                    signal_row        = pd.Series(item),
                )
                if trade is not None:
                    trade['select_date'] = select_date
                    trade['longterm_score'] = item.get('longterm_score', 0)  # IC分析用（波段）
                    trade['short_score']    = item.get('short_score',    0)  # IC分析用（短线）
                    trade['original_score'] = item.get('original_score', trade['short_score'])
                    trade['factor_profile'] = item.get('factor_profile', self.factor_profile)
                    trade['style_gate']     = item.get('style_gate', self.style_gate)
                    trade['select_close']   = item.get('select_close',   0)
                    trade['signal_target_price'] = item.get('target_price', 0)
                    trade['signal_stop_price']   = item.get('stop_loss_price', 0)
                    for col in SHORT_FACTOR_COLUMNS:
                        if col in item:
                            trade[col] = item.get(col)
                    trade.update(self._compute_signal_window_stats(
                        ts_code=ts_code,
                        buy_date=buy_date,
                        buy_price=trade['buy_price'],
                        price_cache=price_cache,
                        max_days=self.hold_days + 3,
                        stop_price=item.get('stop_loss_price', 0),
                        target_price=item.get('target_price', 0),
                    ))
                    all_trades.append(trade)
                    actual_bought.append(ts_code)
                    logger.info(
                        f"    {ts_code}  买入{buy_date}@{trade['buy_price']}  "
                        f"卖出{trade['sell_date']}@{trade['sell_price']}  "
                        f"收益{trade['profit_pct']:+.2f}%  {trade['exit_reason']}"
                    )

            # 记录本次实际买入的股票（用于后续仓位权重计算）
            if actual_bought:
                buy_date_codes[buy_date] = actual_bought

            if not self._is_offline:
                time.sleep(0.5)

        # ── 步骤5：按平仓日重建净值曲线（动态等权仓位模型）──
        #
        # 仓位模型说明：
        #   每个买入日实际买入 N 只（由分数门槛决定，无固定top_n上限）。
        #   每只等权分配 1/N 的资金（N = 当日实际买入数量）。
        #   同一天可能有来自不同买入日的多笔平仓，
        #   每笔收益按其在总资金中的占比（weight）加权后更新净值。
        #   若当日买入0只（无股过门槛），该日不占用资金，净值不变。

        # Reconstructed baseline equity model:
        # each valid trade uses the planned fixed slot weight 1/top_n.
        daily_weighted_returns: Dict[str, List[tuple]] = {}
        weight_per_stock = 1.0 / max(self.top_n, 1)

        for trade in all_trades:
            sell_date = trade['sell_date']
            ret       = trade['profit_after_fee']
            weight    = weight_per_stock
            daily_weighted_returns.setdefault(sell_date, []).append((ret, weight))

        nav = 100.0
        equity_curve = []
        for date in self.all_trade_dates:
            weighted_list = daily_weighted_returns.get(date, [])
            if weighted_list:
                # 当日净值变动 = Σ(各笔收益% × 仓位权重)
                delta = sum(ret * w for ret, w in weighted_list)
                nav = nav * (1 + delta / 100)
            equity_curve.append({'date': date, 'nav': round(nav, 4)})

        # ── 整理结果 ──
        trades_df = pd.DataFrame(all_trades)
        equity_df = pd.DataFrame(equity_curve)

        # ── IC分析：填充前瞻收益并输出 ──
        if ic_records:
            for rec in ic_records:
                base = rec.get('select_close', 0)
                if base <= 0:
                    continue
                for n in [5, 10, 20]:
                    fd = rec.get(f'fwd_date_{n}d')
                    if not fd or fd not in price_cache:
                        continue
                    fd_df = price_cache[fd]
                    if fd_df.empty or 'ts_code' not in fd_df.columns:
                        continue
                    row_ic = fd_df[fd_df['ts_code'] == rec['ts_code']]
                    if not row_ic.empty:
                        fwd_close = float(row_ic.iloc[0]['close'])
                        if fwd_close > 0:
                            rec[f'ret_{n}d'] = round((fwd_close / base - 1) * 100, 4)

            ic_df = pd.DataFrame(ic_records)
            try:
                from scipy.stats import spearmanr
                print("\n" + "=" * 60)
                print("  IC分析（短线评分预测能力）")
                print("=" * 60)
                for n in [5, 10, 20]:
                    col = f'ret_{n}d'
                    if col not in ic_df.columns:
                        continue
                    valid = ic_df[['score', col]].dropna()
                    if len(valid) < 10:
                        continue
                    ic_val, pval = spearmanr(valid['score'], valid[col])
                    avg_ret   = valid[col].mean()
                    n3        = max(1, len(valid) // 3)
                    top_ret   = valid.nlargest(n3,  'score')[col].mean()
                    bot_ret   = valid.nsmallest(n3, 'score')[col].mean()
                    print(
                        f"  {n:2d}日  IC={ic_val:+.4f}  p={pval:.3f}  "
                        f"均涨={avg_ret:+.2f}%  高分组={top_ret:+.2f}%  "
                        f"低分组={bot_ret:+.2f}%  高低差={top_ret - bot_ret:+.2f}%  "
                        f"(n={len(valid)})"
                    )
                print("=" * 60)
            except ImportError:
                logger.warning("scipy未安装，跳过IC计算")

            # 保存IC明细CSV
            os.makedirs('backtest_results', exist_ok=True)
            ic_csv = os.path.join(
                'backtest_results',
                f'ic_short_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            )
            ic_df.to_csv(ic_csv, index=False, encoding='utf-8-sig')
            print(f"  IC明细已保存：{ic_csv}\n")

        metrics = self._calculate_metrics(trades_df, equity_df)
        return trades_df, metrics, equity_df

    # ------------------------------------------------------------------ #
    #  指标计算                                                            #
    # ------------------------------------------------------------------ #

    def _calculate_metrics(
        self, trades_df: pd.DataFrame, equity_df: pd.DataFrame
    ) -> Dict:
        if trades_df.empty:
            logger.warning("无有效交易记录，无法计算指标")
            return {}

        total   = len(trades_df)
        wins    = int((trades_df['profit_pct'] > 0).sum())
        losses  = int((trades_df['profit_pct'] < 0).sum())
        flat    = total - wins - losses

        avg_win  = float(trades_df[trades_df['profit_pct'] > 0]['profit_pct'].mean()) if wins  > 0 else 0.0
        avg_loss = float(trades_df[trades_df['profit_pct'] < 0]['profit_pct'].mean()) if losses > 0 else 0.0
        profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        # 最大连续亏损（笔数）—— 按平仓日时序排序后统计
        sorted_profits = trades_df.sort_values('sell_date')['profit_pct'].tolist()
        max_consec_loss = 0
        cur_loss = 0
        for p in sorted_profits:
            if p < 0:
                cur_loss += 1
                max_consec_loss = max(max_consec_loss, cur_loss)
            else:
                cur_loss = 0

        # 出场原因统计
        exit_counts = trades_df['exit_reason'].value_counts().to_dict()

        # ── 最大回撤（基于资金净值曲线）──
        max_drawdown = 0.0
        if not equity_df.empty:
            navs = equity_df['nav'].values
            peak = navs[0]
            for v in navs:
                if v > peak:
                    peak = v
                dd = (peak - v) / peak * 100
                if dd > max_drawdown:
                    max_drawdown = dd

        # ── 夏普比率（年化，无风险利率=2.5%）──
        sharpe = 0.0
        if not equity_df.empty and len(equity_df) > 1:
            nav_series = equity_df['nav']
            daily_ret = nav_series.pct_change().dropna()
            if daily_ret.std() > 0:
                # 年化交易日约252天
                sharpe = float(
                    (daily_ret.mean() - 0.025 / 252) / daily_ret.std() * (252 ** 0.5)
                )

        # ── 总收益率（净值曲线首尾）──
        total_return = 0.0
        if not equity_df.empty:
            total_return = float((equity_df['nav'].iloc[-1] / equity_df['nav'].iloc[0] - 1) * 100)

        # ── 沪深300基准收益 ──
        benchmark_return = 0.0
        if not self.benchmark_df.empty:
            # 找区间内第一个和最后一个交易日的收盘价
            bdf = self.benchmark_df
            bdf_filtered = bdf[
                (bdf['trade_date'] >= self.start_date) &
                (bdf['trade_date'] <= self.end_date)
            ]
            if len(bdf_filtered) >= 2:
                first_close = float(bdf_filtered.iloc[0]['close'])
                last_close  = float(bdf_filtered.iloc[-1]['close'])
                if first_close > 0:
                    benchmark_return = (last_close / first_close - 1) * 100

        alpha = total_return - benchmark_return
        signal_quality = {}
        if 'mfe_pct' in trades_df.columns:
            signal_quality = {
                'avg_mfe_pct': round(float(trades_df['mfe_pct'].mean()), 2),
                'median_mfe_pct': round(float(trades_df['mfe_pct'].median()), 2),
                'avg_mae_pct': round(float(trades_df['mae_pct'].mean()), 2),
                'median_mae_pct': round(float(trades_df['mae_pct'].median()), 2),
                'avg_window_end_pct': round(float(trades_df['window_end_pct'].mean()), 2),
                'hit_3pct_rate': round(float(trades_df['hit_3pct'].mean()) * 100, 2),
                'hit_5pct_rate': round(float(trades_df['hit_5pct'].mean()) * 100, 2),
                'hit_10pct_rate': round(float(trades_df['hit_10pct'].mean()) * 100, 2),
                'ambiguous_hit_days': int(trades_df.get('ambiguous_hit_days', pd.Series(dtype=float)).fillna(0).sum()),
            }

        metrics = {
            # 基础统计
            'total_trades':         total,
            'win_trades':           wins,
            'loss_trades':          losses,
            'flat_trades':          flat,
            'win_rate':             round(wins / total * 100, 2),
            # 收益
            'avg_profit_pct':       round(float(trades_df['profit_pct'].mean()), 2),
            'avg_profit_after_fee': round(float(trades_df['profit_after_fee'].mean()), 2),
            'avg_win_pct':          round(avg_win,  2),
            'avg_loss_pct':         round(avg_loss, 2),
            'profit_loss_ratio':    round(profit_loss_ratio, 2),
            'max_single_profit':    round(float(trades_df['profit_pct'].max()), 2),
            'max_single_loss':      round(float(trades_df['profit_pct'].min()), 2),
            # 风险
            'max_drawdown_pct':     round(max_drawdown, 2),
            'max_consecutive_loss': max_consec_loss,
            'sharpe_ratio':         round(sharpe, 3),
            # 期末绩效
            'total_return_pct':     round(total_return, 2),
            'benchmark_return_pct': round(benchmark_return, 2),
            'alpha_pct':            round(alpha, 2),
            # 信号窗口质量（不按真实钱包建模，只看入选股票买入后窗口表现）
            **signal_quality,
            # 出场原因
            'stop_loss_count':              exit_counts.get('stop_loss',              0),
            'trailing_stop_count':          exit_counts.get('trailing_stop',          0),
            'time_stop_count':              exit_counts.get('time_stop',              0),
            'time_stop_short_count':        exit_counts.get('time_stop_short',        0),
            'take_profit_count':            exit_counts.get('take_profit',            0),
            'take_profit_next_open_count':  exit_counts.get('take_profit_next_open',  0),
            'hold_complete_count':          exit_counts.get('hold_complete',           0),
            'forced_close_count':           exit_counts.get('forced_close',            0),
            'gap_down_stop_count':          exit_counts.get('gap_down_stop',           0),
            'time_stop_dynamic_count':      exit_counts.get('time_stop_dynamic',       0),
            'weak_close_exit_count':        exit_counts.get('weak_close_exit',         0),
            'suspended_exit_count':         exit_counts.get('suspended_exit',          0),
            # 参数记录
            'backtest_start':       self.start_date,
            'backtest_end':         self.end_date,
            'hold_days':            self.hold_days,
            'top_n':                self.top_n,
            'score_order':          self.score_order,
            'factor_profile':        self.factor_profile,
            'style_gate':            self.style_gate,
            'short_filter_profile':  self.short_filter_profile,
            'fallback_stop_pct':    self.fallback_stop_pct,
            'fallback_profit_pct':  self.fallback_profit_pct,
            'trailing_stop_pct':    self.trailing_stop_pct,
            'trailing_activate_pct': self.trailing_activate_pct,
        }
        return metrics



# ==================== 波段回测引擎 ====================

class BacktestLongterm(BacktestV2):
    """
    波段策略回测引擎 v4.0
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    核心差异（vs BacktestV2 短线版）：
      ① 读 longterm_pool（5维评分 + MA60趋势）替代 stock_pool
      ② 无固定持仓期：持仓直到技术信号触发，安全网最长60天
      ③ 移动止损激活门槛：盈利≥25%（短线3%）
      ④ 移动止损回撤幅度：10%（短线7%）
      ⑤ 兜底止损：-12%（MA60止损有一定距离，不能设太紧）
      ⑥ 兜底止盈：30%（波段目标通常在20-40%区间）
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    用法：
      python backtest_v2.py --mode longterm --offline --start 20240101 --end 20251231

    注意：波段回测强烈建议使用离线模式（--offline），因为安全网60天需要
          预取大量历史行情数据，在线模式会极慢且消耗大量API请求。
    """

    def __init__(
        self,
        pro,
        start_date: str,
        end_date: str,
        top_n: int = 3,
        trailing_activate_pct: float = 25.0,   # 盈利≥25%后激活移动止损
        trailing_stop_pct: float = 10.0,        # 峰值回撤10%触发
        fallback_stop_pct: float = -12.0,       # 兜底止损（MA60距离通常8-15%）
        fallback_profit_pct: float = 50.0,      # 兜底止盈50%（主要靠移动止损退出，此为安全网）
        max_hold_days: int = 60,                # 安全网：最长持60天（约3个月）
        time_stop_days: int = 20,               # 时间动量止损：持仓N天后若仍亏损则离场（0=关闭）
        time_stop_threshold: float = -3.0,      # 触发时间止损的亏损阈值（%）
        use_market_timing: bool = True,
        min_open_ratio: float = 0.995,
        initial_capital: float = 100_000.0,
    ):
        super().__init__(
            pro=pro,
            start_date=start_date,
            end_date=end_date,
            hold_days=max_hold_days,
            top_n=top_n,
            fallback_stop_pct=fallback_stop_pct,
            fallback_profit_pct=fallback_profit_pct,
            trailing_stop_pct=trailing_stop_pct,
            initial_capital=initial_capital,
            use_market_timing=use_market_timing,
            min_open_ratio=min_open_ratio,
        )
        # 覆盖父类的移动止损激活门槛（短线3% → 波段25%）
        self.trailing_activate_pct = trailing_activate_pct
        self.max_hold_days = max_hold_days
        # 时间动量止损（防止慢放血）
        self.time_stop_days = time_stop_days
        self.time_stop_threshold = time_stop_threshold

    def _select_stocks_for_date(self, trade_date: str, retries: int = 2) -> List[Dict]:
        """
        从 run_daily_selection() 的 longterm_pool 字段提取波段候选股。
        仅在 BULL_TREND / BULL_PULLBACK 时有候选（已在 select_longterm_pool 内部判断）。
        BEAR_TREND 强制返回空列表。
        """
        for attempt in range(retries + 1):
            try:
                sel = stock_main.run_daily_selection(
                    trade_date=trade_date,
                    enable_news=False   # 回测不拉新闻
                )
                actual_date = sel['trade_date']
                regime      = sel.get('regime', 'BULL_TREND')

                # BEAR_TREND（含Override未触发）：强制空仓
                if regime == 'BEAR_TREND':
                    logger.info(f"  [{actual_date}] 波段：BEAR_TREND 空仓跳过")
                    return [], []   # 与父类签名一致：(selected_items, ic_pool)

                longterm_pool = sel.get('longterm_pool', pd.DataFrame())
                if longterm_pool is None or longterm_pool.empty:
                    logger.info(
                        f"  [{actual_date}] 波段：无候选股（机制:{regime}）"
                        f"  ——可能当日回调幅度/行业RS不符合硬过滤条件"
                    )
                    return [], []   # 与父类签名一致：(selected_items, ic_pool)

                # 按综合评分排序，取前 top_n
                if 'longterm_score' in longterm_pool.columns:
                    longterm_pool = longterm_pool.sort_values(
                        'longterm_score', ascending=False
                    )
                top_rows = longterm_pool.head(self.top_n)

                result = []
                for _, row in top_rows.iterrows():
                    code    = str(row.get('code', ''))
                    ts_code = stock_main.format_code(code)
                    item = {
                        'ts_code':           ts_code,
                        'stop_loss_price':   float(row.get('stop_loss_price',  0) or 0),
                        'target_price':      float(row.get('target_price',     0) or 0),
                        'volatility':        float(row.get('volatility',       3.0) or 3.0),
                        'ma5':               0.0,
                        'ma10':              0.0,
                        'high20':            float(row.get('high20',           0) or 0),
                        'low20':             float(row.get('low20',            0) or 0),
                        'select_close':      float(row.get('close',            0) or 0),
                        'regime_max_hold':   self.max_hold_days,  # 无固定持仓期
                        'longterm_score':    float(row.get('longterm_score',   0) or 0),
                    }
                    result.append(item)

                codes  = [item['ts_code']       for item in result]
                scores = [item['longterm_score'] for item in result]
                logger.info(
                    f"  [{actual_date}] 波段候选：{regime}  {len(codes)}只 {codes}"
                    f"  评分{[f'{s:.1f}' for s in scores]}"
                )
                return result, []   # ic_pool波段不计算，返回空列表与父类签名一致

            except Exception as e:
                if attempt < retries:
                    wait = 0 if self._is_offline else 10 * (attempt + 1)  # 离线模式不等待
                    logger.warning(
                        f"  [{trade_date}] 波段选股失败（第{attempt+1}次），{wait}秒后重试：{e}"
                    )
                    if wait > 0:
                        time.sleep(wait)
                else:
                    logger.error(
                        f"  [{trade_date}] 波段选股失败，已重试{retries}次，跳过：{e}"
                    )
        return [], []   # ic_pool波段不计算，返回空列表与父类签名一致

    def run(self) -> Tuple[pd.DataFrame, Dict, pd.DataFrame]:
        """
        运行波段回测。
        继承父类主循环，仅在日志头部打印"波段模式"标识。
        预取窗口自动扩大至 max_hold_days（60天）。
        """
        logger.info("=" * 60)
        logger.info("  📊 波段策略回测 v4.0")
        logger.info(f"  移动止损：盈利≥{self.trailing_activate_pct}%后激活，峰值回撤{self.trailing_stop_pct}%触发")
        logger.info(f"  安全网最长持仓：{self.max_hold_days}天")
        logger.info("=" * 60)
        return super().run()


# ==================== 输出函数 ====================
def save_and_print(
    trades_df: pd.DataFrame,
    metrics: Dict,
    equity_df: pd.DataFrame,
    output_dir: str = 'backtest_results'
):
    """保存结果文件并打印摘要到控制台"""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')

    # ── 保存逐笔明细 ──
    if not trades_df.empty:
        # 补充股票名称（从 stock_basic 取，失败则跳过不影响保存）
        trades_out = trades_df.copy()
        try:
            sb = stock_main.pro.stock_basic(
                exchange='', list_status='L',
                fields='ts_code,name'
            )
            if not sb.empty and 'name' in sb.columns:
                trades_out = trades_out.merge(sb[['ts_code', 'name']], on='ts_code', how='left')
                # 把 name 列移到 ts_code 右边
                cols = list(trades_out.columns)
                cols.remove('name')
                idx = cols.index('ts_code') + 1
                cols.insert(idx, 'name')
                trades_out = trades_out[cols]
        except Exception as e:
            logger.debug(f"股票名称获取失败（不影响保存）：{e}")

        detail_path = os.path.join(output_dir, f'trades_{ts}.csv')
        trades_out.to_csv(detail_path, index=False, encoding='utf-8-sig')
        logger.info(f"📄 逐笔明细已保存：{detail_path}")

    # ── 保存资金净值曲线 ──
    if not equity_df.empty:
        equity_path = os.path.join(output_dir, f'equity_{ts}.csv')
        equity_df.to_csv(equity_path, index=False, encoding='utf-8-sig')
        logger.info(f"📄 净值曲线已保存：{equity_path}")

    # ── 保存指标 JSON ──
    if metrics:
        metrics_path = os.path.join(output_dir, f'metrics_{ts}.json')
        with open(metrics_path, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
        logger.info(f"📄 指标已保存：{metrics_path}")

    # ── 控制台打印 ──
    sep = '=' * 60
    print(f"\n{sep}")
    print(f"  回测结果摘要")
    print(sep)
    if not metrics:
        print("  无有效交易数据")
        print(sep)
        return

    print(f"  区间：{metrics.get('backtest_start')} → {metrics.get('backtest_end')}")
    print(f"  持仓最多{metrics.get('hold_days')}天  兜底止损{metrics.get('fallback_stop_pct')}%  "
          f"兜底止盈{metrics.get('fallback_profit_pct')}%  移动止损{metrics.get('trailing_stop_pct')}%"
          f"（激活≥{metrics.get('trailing_activate_pct', 3.0)}%）  Top{metrics.get('top_n')}")
    print()
    print(f"  【收益】")
    print(f"    策略总收益：    {metrics['total_return_pct']:+.2f}%")
    print(f"    沪深300收益：   {metrics['benchmark_return_pct']:+.2f}%")
    print(f"    超额收益 α：    {metrics['alpha_pct']:+.2f}%")
    print()
    print(f"  【胜率 & 盈亏】")
    print(f"    总交易笔数：    {metrics['total_trades']}")
    print(f"    胜率：          {metrics['win_rate']:.1f}%  "
          f"（盈{metrics['win_trades']} / 平{metrics['flat_trades']} / 亏{metrics['loss_trades']}）")
    print(f"    平均盈利：      {metrics['avg_win_pct']:+.2f}%")
    print(f"    平均亏损：      {metrics['avg_loss_pct']:+.2f}%")
    print(f"    盈亏比：        {metrics['profit_loss_ratio']:.2f}")
    print(f"    单笔最大盈利：  {metrics['max_single_profit']:+.2f}%")
    print(f"    单笔最大亏损：  {metrics['max_single_loss']:+.2f}%")
    print(f"    平均收益（扣费）:{metrics['avg_profit_after_fee']:+.2f}%")
    print()
    print(f"  【风险】")
    print(f"    最大回撤：      {metrics['max_drawdown_pct']:.2f}%")
    print(f"    最大连续亏损：  {metrics['max_consecutive_loss']} 笔")
    print(f"    夏普比率：      {metrics['sharpe_ratio']:.3f}")
    print()
    if 'avg_mfe_pct' in metrics:
        print(f"  【信号窗口质量】")
        print(f"    平均最大上涨MFE： {metrics['avg_mfe_pct']:+.2f}%")
        print(f"    中位最大上涨MFE： {metrics['median_mfe_pct']:+.2f}%")
        print(f"    平均最大回撤MAE： {metrics['avg_mae_pct']:+.2f}%")
        print(f"    中位最大回撤MAE： {metrics['median_mae_pct']:+.2f}%")
        print(f"    窗口期末均值：    {metrics['avg_window_end_pct']:+.2f}%")
        print(
            f"    触及3/5/10%：    {metrics['hit_3pct_rate']:.1f}% / "
            f"{metrics['hit_5pct_rate']:.1f}% / {metrics['hit_10pct_rate']:.1f}%"
        )
        print(f"    止盈止损同日歧义：{metrics['ambiguous_hit_days']} 次")
        print()
    print(f"  【出场原因】")
    print(f"    止损出场：      {metrics['stop_loss_count']} 次")
    print(f"    移动止损：      {metrics.get('trailing_stop_count', 0)} 次")
    print(f"    时间止损(波段)：{metrics.get('time_stop_count', 0)} 次")
    print(f"    时间止损(短线)：{metrics.get('time_stop_short_count', 0)} 次")
    print(f"    低开放弃：      {metrics.get('gap_down_stop_count', 0)} 次")
    print(f"    动态到期止损：  {metrics.get('time_stop_dynamic_count', 0)} 次")
    print(f"    弱收盘锁利：    {metrics.get('weak_close_exit_count', 0)} 次")
    print(f"    停牌保护出场：  {metrics.get('suspended_exit_count', 0)} 次")
    print(f"    止盈出场：      {metrics['take_profit_count']} 次（含次日开盘 {metrics['take_profit_next_open_count']} 次）")
    print(f"    持满出场：      {metrics['hold_complete_count']} 次")
    print(f"    末尾强平：      {metrics['forced_close_count']} 次")
    print(sep)


# ==================== 入口 ====================

def _setup_logger():
    """配置回测专用日志（控制台+文件）"""
    os.makedirs('backtest_results', exist_ok=True)
    log_path = os.path.join(
        'backtest_results',
        f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S')

    fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    logger.info(f"日志文件：{log_path}")


def _default_date_range() -> Tuple[str, str]:
    """默认回测近60个交易日（约3个月）"""
    end = datetime.now()
    # 结束日往前1天（今天可能还未收盘）
    end = end - timedelta(days=1)
    start = end - timedelta(days=90)
    return start.strftime('%Y%m%d'), end.strftime('%Y%m%d')


def main():
    _setup_logger()

    parser = argparse.ArgumentParser(description='A股策略回测 v2')
    parser.add_argument('--mode',          type=str,   default='short',
                        choices=['short', 'longterm'],
                        help='回测模式：short=短线（默认）  longterm=波段（无固定持仓期）')
    parser.add_argument('--start',      type=str,   default=None,       help='开始日期 YYYYMMDD')
    parser.add_argument('--end',        type=str,   default=None,       help='结束日期 YYYYMMDD')
    parser.add_argument('--hold',            type=int,   default=None,       help='最大持有天数（短线默认8，波段默认60）')
    parser.add_argument('--topn',            type=int,   default=3,          help='每日Top N（默认3）')
    parser.add_argument('--score-order',     type=str,   default='desc',
                        choices=['desc', 'asc'],
                        help='短线评分排序方向：desc=高分优先（默认），asc=低分优先，用于验证评分是否反向')
    parser.add_argument('--factor-profile',  type=str,   default='original',
                        choices=list(available_profiles()),
                        help='短线回测实验评分：original=原始评分；diagnostic_v1=子因子诊断重排；profile_v2=分风格短线逻辑评分；profile_v3=路径质量评分；profile_v4=弱市防守评分；profile_v5=sideways风险门控评分')
    parser.add_argument('--style-gate',      type=str,   default='none',
                        choices=list(available_style_gates()),
                        help='短线风格门控实验：none=不过滤；no_momentum=排除momentum；no_active_sideways=排除active+sideways；weak_only=只保留weak_momentum；weak_or_cautious_sideways=弱动量或谨慎sideways；adaptive_quality=保留weak_momentum和高质量sideways')
    parser.add_argument('--fallback-stop',   type=float, default=None,       help='兜底止损%%（短线默认-7，波段默认-12）')
    parser.add_argument('--fallback-profit', type=float, default=None,       help='兜底止盈%%（短线默认15，波段默认30）')
    parser.add_argument('--trailing-stop',   type=float, default=None,       help='移动止损回撤幅度%%（短线默认7，波段默认10）')
    parser.add_argument('--trailing-activate', type=float, default=None,     help='移动止损激活门槛%%（短线默认3，波段默认25）')
    parser.add_argument('--short-filter-profile', type=str, default='baseline',
                        choices=['baseline', 'sector_penalty_light', 'sector_penalty_strict'],
                        help='短线候选池硬过滤实验：baseline=原硬过滤，sector_penalty_*=板块不符改扣分')
    parser.add_argument('--conditional-lock', action='store_true',           help='启用短线弱质票条件化移动止损收紧实验')
    parser.add_argument('--conditional-lock-activation', type=float, default=6.0, help='条件化收紧激活阈值%%（默认6）')
    parser.add_argument('--conditional-lock-trailing', type=float, default=4.8,    help='条件化收紧后的移动止损回撤幅度%%（默认4.8）')
    parser.add_argument('--min-open-ratio',  type=float, default=0.995,    help='次日开盘确认比例（默认0.995：低开>0.5%%跳过；设0关闭过滤允许低开买入）')
    parser.add_argument('--no-timing',      action='store_true',        help='忽略大盘择时，纯验证选股逻辑')
    parser.add_argument('--no-time-stop',   action='store_true',        help='关闭短线时间止损（用于纯净基准回测）')
    parser.add_argument('--offline',    action='store_true',            help='离线模式：从本地 Parquet 缓存读取数据（需先运行 data_downloader.py）')
    parser.add_argument('--cache-dir',  type=str,   default='data/cache', help='离线缓存目录（默认 data/cache）')
    args = parser.parse_args()

    default_start, default_end = _default_date_range()
    start_date = args.start or default_start
    end_date   = args.end   or default_end
    use_timing = not args.no_timing
    use_short_time_stop = False   # 短线激进时间止损已由动态出场取代，永久关闭
    is_longterm = (args.mode == 'longterm')

    # 根据模式设置默认参数
    if is_longterm:
        hold_days        = args.hold           if args.hold is not None else 60   # 波段默认60天，未指定时不沿用短线8
        fallback_stop    = args.fallback_stop   if args.fallback_stop   else -12.0
        fallback_profit  = args.fallback_profit if args.fallback_profit else  50.0  # 波段兜底止盈50%，主要靠移动止损退出
        trailing_stop    = args.trailing_stop   if args.trailing_stop   else  10.0
        trailing_act     = args.trailing_activate if args.trailing_activate else 25.0
        mode_tag_str     = "【波段模式】"
    else:
        hold_days        = args.hold if args.hold is not None else 8   # 短线默认8天
        fallback_stop    = args.fallback_stop   if args.fallback_stop   else  -7.0
        fallback_profit  = args.fallback_profit if args.fallback_profit else  15.0
        trailing_stop    = args.trailing_stop   if args.trailing_stop   else   7.0
        trailing_act     = args.trailing_activate if args.trailing_activate else  3.0
        mode_tag_str     = "【短线模式】"

    offline_tag = "【离线模式】" if args.offline else "【在线模式】"
    logger.info(f"🚀 回测启动 {mode_tag_str}{offline_tag}  {start_date} → {end_date}")
    logger.info(
        f"   持有最多{hold_days}天  兜底止损{fallback_stop}%  兜底止盈{fallback_profit}%"
        f"  移动止损{trailing_stop}%（激活≥{trailing_act}%）  Top{args.topn}"
        f"  大盘择时={'开启' if use_timing else '关闭'}  评分排序={args.score_order}"
        f"  因子profile={args.factor_profile}  style_gate={args.style_gate}"
    )
    if args.conditional_lock and not is_longterm:
        logger.info(
            f"   条件化出场=开启  激活≥{args.conditional_lock_activation}%"
            f"  收紧移动止损={args.conditional_lock_trailing}%"
        )
    if is_longterm and not args.offline:
        logger.warning(
            "⚠️ 波段回测建议使用 --offline 离线模式！"
            "在线模式需要预取60天行情，每个选股日约18秒，全年回测需数小时。"
        )

    if args.offline:
        from local_data_proxy import LocalDataProxy
        proxy = LocalDataProxy(cache_dir=args.cache_dir)
        logger.info(f"\n{proxy.coverage_report()}\n")
        stock_main.set_pro(proxy)
        pro = proxy
        logger.info("✅ 已注入 LocalDataProxy，将从本地缓存读取所有数据")
    else:
        pro = stock_main.pro
        try:
            pro._DataApi__timeout = 60
        except Exception:
            pass

    try:
        if is_longterm:
            bt = BacktestLongterm(
                pro=pro,
                start_date=start_date,
                end_date=end_date,
                top_n=args.topn,
                trailing_activate_pct=trailing_act,
                trailing_stop_pct=trailing_stop,
                fallback_stop_pct=fallback_stop,
                fallback_profit_pct=fallback_profit,
                max_hold_days=hold_days,
                use_market_timing=use_timing,
                min_open_ratio=args.min_open_ratio,
            )
        else:
            bt = BacktestV2(
                pro=pro,
                start_date=start_date,
                end_date=end_date,
                hold_days=hold_days,
                top_n=args.topn,
                fallback_stop_pct=fallback_stop,
                fallback_profit_pct=fallback_profit,
                trailing_stop_pct=trailing_stop,
                min_open_ratio=args.min_open_ratio,
                use_market_timing=use_timing,
                score_order=args.score_order,
                factor_profile=args.factor_profile,
                style_gate=args.style_gate,
                short_filter_profile=args.short_filter_profile,
                conditional_lock_enabled=args.conditional_lock,
                conditional_lock_activation_pct=args.conditional_lock_activation,
                conditional_lock_trailing_pct=args.conditional_lock_trailing,
            )
            bt.trailing_activate_pct = trailing_act  # 允许用户覆盖短线激活门槛
            bt.short_time_stop = use_short_time_stop  # 控制短线时间止损开关

        trades_df, metrics, equity_df = bt.run()
        save_and_print(trades_df, metrics, equity_df)
    finally:
        if args.offline:
            stock_main.restore_pro()
            logger.info("✅ 已恢复 Tushare pro 实例")


if __name__ == '__main__':
    main()
