"""2026-04-22 历史短线策略的隔离离线复现实验。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


THIS_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = THIS_DIR.parent
REPO_ROOT = THIS_DIR.parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from local_data_proxy import LocalDataProxy  # noqa: E402


HORIZONS = (3, 5, 8)
LIMIT_UP_THRESHOLD = 9.8
MIN_STOCK_AMOUNT = 200_000.0
MIN_STOCK_AMOUNT_SHORT = 150_000.0
TOP_N = 3
WARMUP_CALENDAR_DAYS = 170

SW_MAP = {
    "801010.SI": "农林牧渔", "801020.SI": "采掘", "801030.SI": "化工",
    "801040.SI": "钢铁", "801050.SI": "有色金属", "801080.SI": "电子",
    "801110.SI": "家用电器", "801120.SI": "食品饮料", "801130.SI": "纺织服饰",
    "801140.SI": "轻工制造", "801150.SI": "医药生物", "801160.SI": "公用事业",
    "801170.SI": "交通运输", "801180.SI": "房地产", "801200.SI": "商贸零售",
    "801210.SI": "社会服务", "801230.SI": "综合", "801710.SI": "建筑材料",
    "801720.SI": "建筑装饰", "801730.SI": "电力设备", "801740.SI": "国防军工",
    "801750.SI": "计算机", "801760.SI": "传媒", "801770.SI": "通信",
    "801780.SI": "银行", "801790.SI": "非银金融", "801880.SI": "汽车",
    "801890.SI": "机械设备",
}

REGIME_PARAMS = {
    "BULL_TREND": {"position": 1.0, "threshold": 45.0, "max_hold": 8},
    "BULL_PULLBACK": {"position": 0.67, "threshold": 60.0, "max_hold": 5},
    "BEAR_BOUNCE": {"position": 0.33, "threshold": 75.0, "max_hold": 3},
    "BEAR_TREND": {"position": 0.0, "threshold": 999.0, "max_hold": 0},
    "BEAR_BOUNCE_OVERRIDE": {"position": 0.33, "threshold": 80.0, "max_hold": 3},
    "BULL_PULLBACK_OVERRIDE": {"position": 0.50, "threshold": 65.0, "max_hold": 4},
}

WEIGHTS = {
    "momentum": {
        "volume_ratio": 0.15, "drawdown": 0.10, "inflow": 0.20,
        "turnover": 0.05, "sector": 0.20, "pattern": 0.05,
        "counter_trend": 0.05, "wyckoff": 0.10, "accel": 0.10,
    },
    "weak_momentum": {
        "volume_ratio": 0.15, "drawdown": 0.12, "inflow": 0.18,
        "turnover": 0.05, "sector": 0.15, "pattern": 0.05,
        "counter_trend": 0.05, "wyckoff": 0.15, "accel": 0.10,
    },
    "sideways": {
        "volume_ratio": 0.22, "drawdown": 0.22, "inflow": 0.12,
        "turnover": 0.04, "sector": 0.15, "pattern": 0.02,
        "counter_trend": 0.03, "wyckoff": 0.12, "accel": 0.08,
    },
    "bear": {
        "volume_ratio": 0.22, "drawdown": 0.22, "inflow": 0.12,
        "turnover": 0.04, "sector": 0.15, "pattern": 0.02,
        "counter_trend": 0.03, "wyckoff": 0.12, "accel": 0.08,
    },
}


@dataclass(frozen=True)
class Variant:
    name: str
    volume_ratio_threshold: float
    news_proxy: bool = False
    ablate: str = ""


VARIANTS = (
    Variant("A_recovered_proxy_vr1.5", 1.5, news_proxy=True),
    Variant("B_pure_quant_vr1.5", 1.5),
    Variant("A_recovered_proxy_vr1.2", 1.2, news_proxy=True),
    Variant("D_pure_quant_vr1.2", 1.2),
    Variant("E_ablate_sector_vr1.2", 1.2, ablate="sector"),
    Variant("E_ablate_inflow_vr1.2", 1.2, ablate="inflow"),
    Variant("E_ablate_wyckoff_vr1.2", 1.2, ablate="wyckoff"),
    Variant("E_ablate_accel_vr1.2", 1.2, ablate="accel"),
)


def score_candidate(style: str, factors: Mapping[str, float], variant: Variant) -> float:
    """按历史源码权重计算基础分；消融后不重归一化。"""
    weights = WEIGHTS[style if style in WEIGHTS else "sideways"]
    score = sum(
        float(factors.get(name, 0.0)) * weight
        for name, weight in weights.items()
        if name != variant.ablate
    )
    return min(score, 100.0)


def select_top_n(
    rows: Sequence[Mapping[str, object]],
    position_multiplier: float,
    top_n: int = TOP_N,
) -> List[dict]:
    """复用 backtest_v2 的仓位系数转有效 TopN 规则。"""
    effective = int(round(top_n * position_multiplier)) if position_multiplier > 0 else 0
    effective = max(1, effective) if position_multiplier > 0 else 0
    ordered = sorted(rows, key=lambda row: float(row.get("score", 0.0)), reverse=True)
    return [dict(row) for row in ordered[:effective]]


def usable_signal_dates(
    common_file_dates: Iterable[str],
    open_dates: Iterable[str],
    nonempty_price_dates: Iterable[str],
    start_date: str,
    end_date: str,
) -> List[str]:
    """只保留四类文件齐全、交易日历开市且行情非空的日期。"""
    usable = set(common_file_dates) & set(open_dates) & set(nonempty_price_dates)
    return sorted(date for date in usable if start_date <= date <= end_date)


def value_below_minimum(value: object, minimum: float) -> bool:
    """审计字段把缺失值视为未达到门槛，与历史 fillna(1.0) 后过滤一致。"""
    return bool(pd.isna(value) or float(value) < minimum)


def compute_forward_outcomes(prices: Sequence[Mapping[str, object]]) -> dict:
    """以 prices[0] 为信号日，按 T+1 开盘和 3/5/8 日收盘计算结果。"""
    result = {"failure_reason": ""}
    if len(prices) < 2:
        result["failure_reason"] = "missing_t1"
        return result
    buy = prices[1]
    if float(buy.get("pct_chg", 0.0) or 0.0) >= LIMIT_UP_THRESHOLD:
        result["failure_reason"] = "t1_limit_up"
        return result
    buy_price = float(buy.get("open", 0.0) or 0.0)
    if buy_price <= 0:
        result["failure_reason"] = "invalid_t1_open"
        return result
    result.update({"buy_date": str(buy["trade_date"]), "buy_price": buy_price})
    for horizon in HORIZONS:
        key_ret = f"return_{horizon}d"
        key_mae = f"mae_{horizon}d"
        target_index = horizon
        if len(prices) <= target_index:
            result[key_ret] = np.nan
            result[key_mae] = np.nan
            continue
        holding = prices[1 : target_index + 1]
        exit_row = prices[target_index]
        result[f"exit_date_{horizon}d"] = str(exit_row["trade_date"])
        result[key_ret] = (float(exit_row["close"]) / buy_price - 1.0) * 100.0
        min_low = min(float(row["low"]) for row in holding)
        result[key_mae] = (min_low / buy_price - 1.0) * 100.0
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _rolling(grouped, column: str, window: int, min_periods: Optional[int] = None, op: str = "mean"):
    roll = grouped[column].rolling(window, min_periods=min_periods or window)
    values = getattr(roll, op)()
    return values.reset_index(level=0, drop=True)


def load_price_panel(proxy: LocalDataProxy, start_date: str, end_date: str) -> pd.DataFrame:
    """经 LocalDataProxy 批量读取区间行情，不发起逐股请求。"""
    fields = "ts_code,trade_date,open,high,low,close,pct_chg,vol,amount"
    panel = proxy.daily(start_date=start_date, end_date=end_date, fields=fields)
    if panel.empty:
        raise RuntimeError(f"行情缓存为空：{start_date}~{end_date}")
    panel = panel.drop_duplicates(["ts_code", "trade_date"]).copy()
    panel["trade_date"] = panel["trade_date"].astype(str)
    numeric = ["open", "high", "low", "close", "pct_chg", "vol", "amount"]
    panel[numeric] = panel[numeric].apply(pd.to_numeric, errors="coerce")
    panel = panel.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return panel


def add_technical_features(panel: pd.DataFrame) -> pd.DataFrame:
    """批量计算历史源码使用的技术指标，所有滚动窗只含当日及此前数据。"""
    df = panel.copy()
    g = df.groupby("ts_code", sort=False)
    for window in (5, 10, 20, 60):
        df[f"ma{window}"] = _rolling(g, "close", window)
    df["vol_ma5"] = _rolling(g, "vol", 5)
    df["vol_ma20"] = _rolling(g, "vol", 20)
    df["high20"] = _rolling(g, "high", 20, op="max")
    df["low20"] = _rolling(g, "low", 20, op="min")
    df["volatility"] = _rolling(g, "pct_chg", 10, min_periods=5, op="std")
    df["prev_close"] = g["close"].shift(1)
    df["prev_ma5"] = g["ma5"].shift(1)
    df["close_3ago"] = g["close"].shift(3)
    df["prev_vol"] = g["vol"].shift(1)

    prev5_vol = g["vol"].transform(lambda s: s.shift(1).rolling(5, min_periods=5).mean())
    df["daily_vol_ratio"] = df["vol"] / prev5_vol.replace(0, np.nan)
    g2 = df.groupby("ts_code", sort=False)
    df["vol_3d_avg"] = _rolling(g2, "daily_vol_ratio", 3, min_periods=1)

    prior15_mean = g["close"].transform(lambda s: s.shift(1).rolling(15, min_periods=5).mean())
    prior15_std = g["close"].transform(lambda s: s.shift(1).rolling(15, min_periods=5).std())
    prior15_vol = g["vol"].transform(lambda s: s.shift(1).rolling(15, min_periods=5).mean())
    prior10_max = g["close"].transform(lambda s: s.shift(1).rolling(10, min_periods=10).max())
    prior10_min = g["close"].transform(lambda s: s.shift(1).rolling(10, min_periods=10).min())
    prior10_mean = g["close"].transform(lambda s: s.shift(1).rolling(10, min_periods=10).mean())
    prior5_mean_vol = g["vol"].transform(lambda s: s.shift(1).rolling(5, min_periods=5).mean())

    price_cv = prior15_std / prior15_mean.replace(0, np.nan) * 100.0
    price_score = np.select(
        [price_cv <= 2, price_cv <= 4, price_cv <= 7],
        [100.0, 50.0 + (4.0 - price_cv) / 2.0 * 50.0, (7.0 - price_cv) / 3.0 * 50.0],
        default=0.0,
    )
    shrink_ratio = prior15_vol / df["vol_ma20"].replace(0, np.nan)
    shrink_score = np.select(
        [shrink_ratio <= 0.7, shrink_ratio <= 0.9, shrink_ratio <= 1.1],
        [100.0, 50.0 + (0.9 - shrink_ratio) / 0.2 * 50.0, 30.0],
        default=0.0,
    )
    breakout_ratio = df["vol"] / prior15_vol.replace(0, np.nan)
    breakout_score = np.select(
        [breakout_ratio >= 2.5, breakout_ratio >= 1.8, breakout_ratio >= 1.3],
        [100.0, 60.0 + (breakout_ratio - 1.8) / 0.7 * 40.0,
         20.0 + (breakout_ratio - 1.3) / 0.5 * 40.0],
        default=0.0,
    )
    df["wyckoff_score"] = np.clip(price_score * 0.35 + shrink_score * 0.35 + breakout_score * 0.30, 0, 100)
    platform_range = (prior10_max - prior10_min) / prior10_mean.replace(0, np.nan) * 100.0
    df["breakout_platform"] = (platform_range < 3.0) & (df["vol"] > df["vol_ma5"] * 1.5)
    df["volume_wash"] = (prior5_mean_vol < df["vol_ma20"] * 0.8) & (df["vol"] > df["vol_ma5"] * 1.3)

    vwap_proxy = (df["high"] + df["low"] + df["close"]) / 3.0
    df["close_vs_vwap"] = (df["close"] - vwap_proxy) / vwap_proxy.replace(0, np.nan) * 100.0
    df["eod_strong"] = (df["close_vs_vwap"] > 0.3) & (df["vol"] > df["vol_ma5"])
    df["drawdown_from_high"] = (df["high20"] - df["close"]) / df["high20"].replace(0, np.nan) * 100.0
    drop3 = (df["close_3ago"] - df["close"]) / df["close_3ago"].replace(0, np.nan) * 100.0
    df["is_sharp_drop"] = (df["drawdown_from_high"] > 5) & ((drop3 / df["drawdown_from_high"]) > 0.6)
    df["has_limit_up_gene"] = _rolling(g, "pct_chg", 10, min_periods=1, op="max") >= 9.5
    df["just_broke_ma5"] = (df["close"] > df["ma5"]) & (df["prev_close"] <= df["prev_ma5"])
    df["vol_accelerating"] = df["vol"] > df["prev_vol"]

    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["prev_close"]).abs(),
        (df["low"] - df["prev_close"]).abs(),
    ], axis=1).max(axis=1)
    df["true_range"] = true_range
    df["atr_14"] = _rolling(df.groupby("ts_code", sort=False), "true_range", 14, min_periods=1)
    return df


def load_index_features(proxy: LocalDataProxy, start_date: str, end_date: str) -> pd.DataFrame:
    fields = "ts_code,trade_date,open,high,low,close,pct_chg"
    df = proxy.index_daily(start_date=start_date, end_date=end_date, fields=fields)
    if df.empty:
        raise RuntimeError("指数缓存为空")
    df = df.drop_duplicates(["ts_code", "trade_date"]).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    df["trade_date"] = df["trade_date"].astype(str)
    g = df.groupby("ts_code", sort=False)
    for window in (10, 20, 60, 100):
        df[f"ma{window}"] = _rolling(g, "close", window)
    df["ma20_lag5"] = g["ma20"].shift(5)
    df["ma60_lag10"] = g["ma60"].shift(10)
    df["ma100_lag5"] = g["ma100"].shift(5)
    df["close_lag5"] = g["close"].shift(5)
    df["close_lag20"] = g["close"].shift(20)
    df["pct_5_sum"] = _rolling(g, "pct_chg", 5, min_periods=5, op="sum")
    df["below_ma20"] = df["close"] < df["ma20"]
    return df


def _sector_snapshot(index_features: pd.DataFrame, trade_date: str) -> tuple[dict, dict]:
    today = index_features[index_features["trade_date"] == trade_date]
    status = {}
    for _, row in today[today["ts_code"].isin(SW_MAP)].iterrows():
        if pd.notna(row["ma10"]):
            status[SW_MAP[row["ts_code"]]] = bool(row["close"] > row["ma10"])
    accel = {}
    history = index_features[
        (index_features["trade_date"] <= trade_date) & index_features["ts_code"].isin(SW_MAP)
    ]
    for code, group in history.groupby("ts_code"):
        group = group.tail(20)
        if len(group) < 6:
            continue
        avg5 = float(group.tail(5)["pct_chg"].mean())
        avg20 = float(group["pct_chg"].mean())
        value = avg5 * 10 if abs(avg20) < 0.01 else avg5 / abs(avg20) * (1 if avg20 > 0 else -1)
        accel[SW_MAP[code]] = value
    return status, accel


def _market_context(index_features: pd.DataFrame, market_day: pd.DataFrame, trade_date: str, sector_status: dict) -> dict:
    hs = index_features[(index_features["ts_code"] == "000300.SH") & (index_features["trade_date"] == trade_date)]
    sh = index_features[(index_features["ts_code"] == "000001.SH") & (index_features["trade_date"] == trade_date)]
    if hs.empty:
        return {"style": "sideways", "regime": "BULL_TREND", "market_state": "normal", **REGIME_PARAMS["BULL_TREND"]}
    row = hs.iloc[0]
    trend20 = (row["close"] / row["close_lag20"] - 1) * 100 if pd.notna(row["close_lag20"]) else 0.0
    momentum5 = (row["close"] / row["close_lag5"] - 1) * 100 / 5 if pd.notna(row["close_lag5"]) else 0.0
    breadth = sum(sector_status.values()) / len(sector_status) if sector_status else 0.5
    vm = int(trend20 >= 5) + int(momentum5 >= 0.3) + int(breadth >= 0.55)
    vb = int(trend20 <= -5) + int(momentum5 <= -0.3) + int(breadth <= 0.35)
    style = "momentum" if vm >= 2 else "bear" if vb >= 2 else "weak_momentum" if vm == 1 else "sideways"

    price_vs_ma60 = (row["close"] / row["ma60"] - 1) * 100 if pd.notna(row["ma60"]) else 0.0
    slope60 = (row["ma60"] / row["ma60_lag10"] - 1) * 100 / 10 if pd.notna(row["ma60_lag10"]) else 0.0
    long_bull = price_vs_ma60 >= -3.0 and slope60 >= -0.02
    short_up = bool(pd.notna(row["ma20"]) and pd.notna(row["ma60"]) and row["ma20"] > row["ma60"])
    regime = (
        "BULL_TREND" if long_bull and short_up else
        "BULL_PULLBACK" if long_bull else
        "BEAR_BOUNCE" if short_up else "BEAR_TREND"
    )

    override_score = 0
    if regime == "BEAR_TREND" and not market_day.empty:
        override_score += int(float(market_day["pct_chg"].median()) > 2.0)
        override_score += int(float((market_day["pct_chg"] > 0).mean()) > 0.70)
        override_score += int(int((market_day["pct_chg"] >= LIMIT_UP_THRESHOLD).sum()) > 80)
        if override_score >= 3:
            regime = "BULL_PULLBACK_OVERRIDE"
        elif override_score >= 2:
            regime = "BEAR_BOUNCE_OVERRIDE"

    market_state = "normal"
    if not sh.empty:
        sh_row = sh.iloc[0]
        sh_caution = pd.notna(sh_row["ma20_lag5"]) and (sh_row["ma20"] / sh_row["ma20_lag5"] - 1) * 100 < -0.5 and sh_row["pct_5_sum"] < -2
        hs_caution = pd.notna(row["ma20_lag5"]) and (row["ma20"] / row["ma20_lag5"] - 1) * 100 < -0.5 and row["pct_5_sum"] < -2
        market_state = "caution" if sh_caution or hs_caution else "normal"

    ma20_slope5 = (row["ma20"] / row["ma20_lag5"] - 1) * 100 if pd.notna(row["ma20_lag5"]) else 0.0
    price_vs_ma100 = (row["close"] / row["ma100"] - 1) * 100 if pd.notna(row["ma100"]) else 0.0
    ma100_slope5 = (row["ma100"] / row["ma100_lag5"] - 1) * 100 if pd.notna(row["ma100_lag5"]) else 0.0
    macro = "defensive" if price_vs_ma100 < -3 or ma100_slope5 < -0.5 else "active" if ma20_slope5 > 0.1 and price_vs_ma100 > -1 else "cautious"
    return {
        "style": style, "regime": regime, "market_state": market_state, "macro": macro,
        "index_change": float(row["pct_chg"]), "override_score": override_score,
        "trend20": trend20, "momentum5": momentum5, "breadth": breadth,
        **REGIME_PARAMS[regime],
    }


def _drawdown_score(style: str, drawdown: float, sharp: bool) -> float:
    if style == "momentum":
        if drawdown <= 3: return 100.0
        if drawdown <= 8: return 100 - (drawdown - 3) / 5 * 30
        if drawdown <= 15: return 70 - (drawdown - 8) / 7 * 40
        return max(30 - (drawdown - 15) / 10 * 30, 0)
    if style == "weak_momentum":
        if sharp and drawdown >= 5: return 100.0
        if 3 <= drawdown <= 12: return 100.0
        if 1 <= drawdown < 3: return 40 + (drawdown - 1) / 2 * 60
        if 12 < drawdown <= 18: return 100 - (drawdown - 12) / 6 * 50
        if 18 < drawdown <= 28: return max(50 - (drawdown - 18) / 10 * 50, 0)
        if drawdown > 28: return 0.0
        return max(drawdown / 3 * 40, 0)
    if sharp and drawdown >= 8: return 100.0
    if 8 <= drawdown <= 15: return 100.0
    if 5 <= drawdown < 8: return 50 + (drawdown - 5) / 3 * 50
    if 15 < drawdown <= 20: return 100 - (drawdown - 15) / 5 * 50
    if 20 < drawdown <= 30: return max(50 - (drawdown - 20) / 10 * 50, 0)
    if drawdown > 30: return 0.0
    return max(drawdown / 5 * 50, 0)


def _factor_values(row: pd.Series, style: str, sector_score: float, accel_ratio: float, macro: str, turnover_score: float) -> dict:
    vr = float(row["volume_ratio"])
    vr_score = 0.0 if vr <= 1 else 100.0 if vr >= 4 else math.log2(vr) / math.log2(4) * 100
    main_inflow = float(row.get("main_net_inflow", 0.0) or 0.0)
    inflow_score = min(abs(main_inflow) / 100.0, 100.0) if main_inflow > 0 else 0.0
    pattern_bonus = 5.0 * int(bool(row["breakout_platform"])) + 5.0 * int(bool(row["volume_wash"]))
    if bool(row["eod_strong"]):
        pattern_bonus += min(int(float(row["close_vs_vwap"]) / 0.3) * 1.5, 5)
    accel_score = 100.0 if accel_ratio >= 2 else (accel_ratio - 1) * 100 if accel_ratio >= 1 else 0.0
    if macro == "defensive":
        accel_score *= 0.3
    counter = max(0.0, min(float(row.get("counter_trend_resistance", 0.0)) / 5 * 100, 100))
    return {
        "volume_ratio": vr_score,
        "drawdown": _drawdown_score(style, float(row["drawdown_from_high"]), bool(row["is_sharp_drop"])),
        "inflow": inflow_score,
        "turnover": turnover_score * 100.0,
        "sector": float(sector_score),
        "pattern": min(pattern_bonus, 15.0) / 15.0 * 100.0,
        "counter_trend": counter,
        "wyckoff": float(row["wyckoff_score"]),
        "accel": accel_score,
    }


def _potential(row: pd.Series, style: str) -> tuple[bool, str]:
    drawdown = float(row["drawdown_from_high"])
    kline_ok = bool(row["close"] >= row["open"]) and bool((row["high"] - max(row["close"], row["open"])) < abs(row["close"] - row["open"]) * 1.5 if row["close"] != row["open"] else True)
    vol_sustained = bool(row["vol"] > row["vol_ma5"])
    vol_ok = bool(row["vol_3d_avg"] >= 1.5 or row["vol_accelerating"])
    near_ma20 = bool(pd.notna(row["ma20"]) and abs(row["close"] - row["ma20"]) / row["ma20"] <= 0.05)
    if style == "momentum":
        ma_ok = bool(row["close"] > row["ma20"] and row["ma20"] > row["ma60"])
        near_high = drawdown <= 5
        ok = ma_ok and vol_sustained and kline_ok and (near_high or bool(row["breakout_platform"]))
        return ok, "" if ok else "momentum_technical_gate"
    if style == "weak_momentum":
        position_ok = (3 <= drawdown <= 12) or bool(row["breakout_platform"]) or (drawdown >= 5 and near_ma20)
        ma_ok = bool((row["close"] > row["ma10"] or row["just_broke_ma5"]) and (row["ma5"] > row["ma10"] or row["close"] > row["ma20"]))
        ok = position_ok and ma_ok and (vol_ok or vol_sustained) and kline_ok
        return ok, "" if ok else "weak_momentum_technical_gate"
    position_ok = drawdown >= 8 or (drawdown >= 3 and near_ma20) or bool(row["breakout_platform"])
    ma_ok = bool(row["close"] > row["ma5"] or row["just_broke_ma5"])
    ok = position_ok and ma_ok and (vol_sustained or vol_ok) and kline_ok
    return ok, "" if ok else "sideways_technical_gate"


def _restricted_codes(proxy: LocalDataProxy, trade_date: str) -> set[str]:
    start = (pd.Timestamp(trade_date) - pd.Timedelta(days=15)).strftime("%Y%m%d")
    restricted: set[str] = set()
    share = proxy.share_float(start_date=start, end_date=trade_date, fields="ts_code")
    if not share.empty:
        restricted.update(share["ts_code"].astype(str))
    for holder_type in ("G", "P", "C"):
        trades = proxy.stk_holdertrade(start_date=start, end_date=trade_date, holder_type=holder_type, fields="ts_code,in_de")
        if not trades.empty and "in_de" in trades:
            restricted.update(trades.loc[trades["in_de"] == "DE", "ts_code"].astype(str))
    return restricted


def evaluate_variant(
    day: pd.DataFrame,
    stock_basic: pd.DataFrame,
    context: Mapping[str, object],
    sector_status: Mapping[str, bool],
    sector_accel: Mapping[str, float],
    variant: Variant,
    restricted: set[str],
) -> tuple[List[dict], dict]:
    """计算单日单版本全部过门槛候选及光迅科技审计轨迹。"""
    case_code = "002281.SZ"
    trace = {"failure_reason": "not_in_universe"}
    merged = day.merge(stock_basic, on="ts_code", how="inner")
    merged = merged[merged["list_date"].astype(str) <= str(day["trade_date"].iloc[0])]
    merged = merged[~merged["name"].str.contains(r"ST|＊ST|\*ST|退市", na=False, regex=True)]
    merged = merged[~merged["symbol"].astype(str).str.startswith(("688", "300", "8"))]
    merged = merged[~merged["ts_code"].isin(restricted)]
    money_ok = pd.Series(True, index=merged.index) if variant.ablate == "inflow" else (merged["main_net_inflow"].isna() | (merged["main_net_inflow"] >= 0))
    base_mask = (
        (merged["amount"] >= MIN_STOCK_AMOUNT) & merged["pct_chg"].between(-3, 6) &
        merged["turnover"].between(3, 12) &
        (merged["volume_ratio"] >= variant.volume_ratio_threshold) & money_ok
    )
    base = merged[base_mask].copy()
    if case_code in set(merged["ts_code"]) and case_code not in set(base["ts_code"]):
        row = merged.loc[merged["ts_code"] == case_code].iloc[0]
        reasons = []
        if row["amount"] < MIN_STOCK_AMOUNT: reasons.append("amount")
        if not -3 <= row["pct_chg"] <= 6: reasons.append("change")
        if not 3 <= row["turnover"] <= 12: reasons.append("turnover")
        if value_below_minimum(row["volume_ratio"], variant.volume_ratio_threshold): reasons.append("volume_ratio")
        if variant.ablate != "inflow" and pd.notna(row["main_net_inflow"]) and row["main_net_inflow"] < 0: reasons.append("inflow")
        trace["failure_reason"] = "base_filter:" + ",".join(reasons)
    if base.empty:
        return [], trace

    style = str(context["style"])
    if style == "momentum":
        st = base[base["pct_chg"].between(1.0, 7.0) & (base["volume_ratio"] >= variant.volume_ratio_threshold) & (base["amount"] >= MIN_STOCK_AMOUNT_SHORT)].copy()
    else:
        st = base[base["pct_chg"].between(0.0, 5.0) & (base["volume_ratio"] >= variant.volume_ratio_threshold) & (base["amount"] >= MIN_STOCK_AMOUNT_SHORT)].copy()
    if case_code in set(base["ts_code"]) and case_code not in set(st["ts_code"]):
        trace["failure_reason"] = "style_price_filter"

    heat = st.groupby("industry", dropna=False).agg(change=("pct_chg", "mean"), inflow=("main_net_inflow", "sum"))
    if not heat.empty:
        max_change = max(float(heat["change"].max()), 1.0)
        max_inflow = max(float(heat["inflow"].max()), 1.0)
        heat["sector_score"] = (heat["change"] / max_change * 50).clip(0, 50) + (heat["inflow"] / max_inflow * 50).clip(0, 50)
        top_proxy = set(heat.nlargest(3, "sector_score").index.astype(str))
    else:
        top_proxy = set()

    medians = st.groupby("industry")["turnover"].agg(["median", "count"])
    scored_candidates: List[dict] = []
    for _, row in st.iterrows():
        industry = str(row.get("industry", ""))
        if variant.ablate != "sector" and industry in sector_status and not sector_status[industry]:
            if row["ts_code"] == case_code: trace["failure_reason"] = "sector_ma10"
            continue
        ok, reason = _potential(row, style)
        if not ok:
            if row["ts_code"] == case_code: trace["failure_reason"] = reason
            continue
        median = float(medians.loc[industry, "median"]) if industry in medians.index and medians.loc[industry, "count"] >= 3 else 0.0
        relative = float(row["turnover"] / median) if median > 0 else 1.0
        turnover_score = 1.0 if relative >= 2 else 0.8 if relative >= 1.2 else 0.65 if relative >= 0.8 else 0.4
        if median <= 0:
            turnover_score = 1.0 if 5 <= row["turnover"] <= 8 else 0.8 if 3 <= row["turnover"] < 5 else 0.6
        sector_score = float(heat.loc[industry, "sector_score"]) if industry in heat.index else 0.0
        accel_ratio = float(sector_accel.get(industry, 0.0))
        factors = _factor_values(row, style, sector_score, accel_ratio, str(context["macro"]), turnover_score)
        base_score = score_candidate(style, factors, variant)
        proxy_boost = sector_score * 0.1 if variant.news_proxy and industry in top_proxy else 0.0
        final_score = base_score + proxy_boost - (10.0 if context["market_state"] == "caution" else 0.0)
        final_score = max(0.0, min(final_score, 130.0))
        candidate = {
            "code": str(row["symbol"]), "ts_code": str(row["ts_code"]), "name": str(row["name"]),
            "industry": industry, "select_date": str(row["trade_date"]), "close": float(row["close"]),
            "score": final_score, "score_base": base_score, "news_proxy_boost": proxy_boost,
            "volume_ratio": float(row["volume_ratio"]), "turnover": float(row["turnover"]),
            "main_net_inflow": float(row.get("main_net_inflow", 0.0) or 0.0),
            "drawdown_from_high": float(row["drawdown_from_high"]), "market_style": style,
            "regime": str(context["regime"]), **{f"factor_{k}": float(v) for k, v in factors.items()},
        }
        scored_candidates.append(candidate)
        if row["ts_code"] == case_code and final_score < float(context["threshold"]):
            trace["failure_reason"] = f"score_below_threshold:{final_score:.2f}<{float(context['threshold']):.0f}"
            trace.update(candidate)
    scored_candidates.sort(key=lambda item: item["score"], reverse=True)
    for rank, item in enumerate(scored_candidates, start=1):
        item["pre_threshold_rank"] = rank
        if item["ts_code"] == case_code:
            trace.update(item)
    candidates = [item for item in scored_candidates if item["score"] >= float(context["threshold"])]
    for rank, item in enumerate(candidates, start=1):
        item["candidate_rank"] = rank
        if item["ts_code"] == case_code:
            trace["failure_reason"] = ""
            trace.update(item)
    return candidates, trace


def _attach_outcomes(signals: pd.DataFrame, price_panel: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    by_code = {code: grp.sort_values("trade_date").reset_index(drop=True) for code, grp in price_panel.groupby("ts_code")}
    rows = []
    for _, signal in signals.iterrows():
        history = by_code.get(signal["ts_code"])
        if history is None:
            outcome = {"failure_reason": "missing_code_prices"}
        else:
            positions = history.index[history["trade_date"] == signal["select_date"]].tolist()
            if not positions:
                outcome = {"failure_reason": "missing_signal_day"}
            else:
                window = history.iloc[positions[0] : positions[0] + max(HORIZONS) + 1]
                outcome = compute_forward_outcomes(window.to_dict("records"))
        rows.append({**signal.to_dict(), **outcome})
    return pd.DataFrame(rows)


def _metrics(trades: pd.DataFrame, variant: str, period: str, horizon: int) -> dict:
    col = f"return_{horizon}d"
    signals = trades[trades["variant"] == variant]
    if period != "all":
        signals = signals[signals["select_date"].astype(str).str[:4] == period]
    executed = signals[signals["failure_reason"].fillna("") == ""]
    subset = executed[executed[col].notna()]
    values = subset[col].astype(float)
    wins = values[values > 0]
    losses = values[values < 0]
    pl_ratio = wins.mean() / abs(losses.mean()) if len(wins) and len(losses) else np.nan
    cohort = subset.groupby(f"exit_date_{horizon}d")[col].mean().sort_index() if not subset.empty else pd.Series(dtype=float)
    curve = (1 + cohort / 100).cumprod() if not cohort.empty else pd.Series(dtype=float)
    max_dd = ((curve / curve.cummax()) - 1).min() * 100 if not curve.empty else np.nan
    return {
        "variant": variant, "period": period, "horizon_days": horizon,
        "signal_count": int(len(signals)), "trade_count": int(len(executed)),
        "matured_trade_count": int(len(subset)),
        "win_rate_pct": float((values > 0).mean() * 100) if len(values) else np.nan,
        "avg_return_pct": float(values.mean()) if len(values) else np.nan,
        "median_return_pct": float(values.median()) if len(values) else np.nan,
        "profit_loss_ratio": float(pl_ratio) if pd.notna(pl_ratio) else np.nan,
        "worst_mae_pct": float(subset[f"mae_{horizon}d"].min()) if len(subset) else np.nan,
        "cumulative_cohort_return_pct": float((curve.iloc[-1] - 1) * 100) if not curve.empty else np.nan,
        "max_equal_weight_drawdown_pct": float(max_dd) if pd.notna(max_dd) else np.nan,
    }


def _write_report(summary: pd.DataFrame, case: pd.DataFrame, metadata: dict, output_dir: Path) -> None:
    base = summary[(summary["period"] == "all") & (summary["horizon_days"] == 5)].copy()
    base = base.sort_values("avg_return_pct", ascending=False)
    lines = [
        "# 2026-04-22 光迅科技历史策略复现实验报告", "",
        "> 本报告是离线历史研究，不构成交易承诺；单只成功股票不作为策略有效证据。", "",
        "## 数据覆盖", "",
        f"- 实际信号区间：{metadata['actual_signal_start']} 至 {metadata['actual_signal_end']}。",
        f"- 行情、日基础、资金流、指数共同覆盖交易日：{metadata['common_date_count']} 天。",
        "- 2023、2024、2025 为完整自然交易年；2026 只覆盖到本地缓存末日，末端 8 日收益另受前瞻数据限制。",
        "- 股票基础表是当前静态快照，存在退市股缺失造成的生存者偏差。", "",
        "## 恢复等级", "",
        "### 精确恢复", "",
        "- 历史 `main.py` 文件及 SHA-256、九因子权重、三种市场风格技术门槛、T 日收盘信号、T+1 开盘买入和涨停不可买规则。",
        "- 量比 1.5 与 1.2 两种口径均完整执行。", "",
        "### 合理近似", "",
        "- 历史非敏感 `config.py` 未归档，状态机阈值采用历史源码注释可确认的 45/60/75 分与 1.0/0.67/0.33 仓位系数。",
        "- 恢复版消息/概念层使用同日行业热度 Top3 的 0–10 分离线代理；该层只用于 A 版，不能解释为真实历史新闻。",
        "- 指数缓存没有成交额字段，Override 的第 4 条成交额信号不可计算，按缺失而非未触发处理。",
        "- 累计收益与最大回撤采用按退出日汇总的等权信号批次曲线，不是资金约束下的可交易账户净值。", "",
        "### 无法恢复", "",
        "- 历史新闻标题、AI 新闻到板块的映射、概念热度时序快照及 2026-04-22 的运行时缓存值。",
        "- 报告量比 1.31 与源码初筛 1.5 的具体形成原因。", "",
        "## 全周期 5 日结果", "",
        base.to_markdown(index=False, floatfmt=".3f") if not base.empty else "无可用结果。", "",
        "## 光迅科技 2026-04-22 逐版本审计", "",
        case.to_markdown(index=False, floatfmt=".2f") if not case.empty else "目标日不在可用缓存。", "",
        "## 消融稳定性与重新引入结论", "",
    ]
    baseline_name = "D_pure_quant_vr1.2"
    factor_variants = {
        "板块强度": "E_ablate_sector_vr1.2",
        "主力资金": "E_ablate_inflow_vr1.2",
        "Wyckoff": "E_ablate_wyckoff_vr1.2",
        "板块资金加速": "E_ablate_accel_vr1.2",
    }
    comparison_rows = []
    for factor, ablated_name in factor_variants.items():
        full_base = summary[(summary["variant"] == baseline_name) & (summary["period"] == "all") & (summary["horizon_days"] == 5)]
        full_ablated = summary[(summary["variant"] == ablated_name) & (summary["period"] == "all") & (summary["horizon_days"] == 5)]
        year_deltas = []
        for year in ("2023", "2024", "2025", "2026"):
            b = summary[(summary["variant"] == baseline_name) & (summary["period"] == year) & (summary["horizon_days"] == 5)]
            a = summary[(summary["variant"] == ablated_name) & (summary["period"] == year) & (summary["horizon_days"] == 5)]
            if not b.empty and not a.empty and pd.notna(b.iloc[0]["avg_return_pct"]) and pd.notna(a.iloc[0]["avg_return_pct"]):
                year_deltas.append(float(b.iloc[0]["avg_return_pct"] - a.iloc[0]["avg_return_pct"]))
        delta = np.nan
        if not full_base.empty and not full_ablated.empty:
            delta = float(full_base.iloc[0]["avg_return_pct"] - full_ablated.iloc[0]["avg_return_pct"])
        stable_years = sum(value > 0 for value in year_deltas)
        decision = "值得进入当前策略的独立复验" if pd.notna(delta) and delta > 0 and stable_years >= 3 else "不建议直接重新引入"
        comparison_rows.append({"因子": factor, "全周期5日贡献百分点": delta, "正贡献年份数": f"{stable_years}/{len(year_deltas)}", "结论": decision})
    comparison = pd.DataFrame(comparison_rows)
    lines.extend([comparison.to_markdown(index=False, floatfmt=".3f"), ""])
    quant = base[base["variant"] == baseline_name]
    if quant.empty:
        lines.append("缓存结果不足，不能判断旧因子是否值得重新引入。")
    else:
        lines.append("表中“贡献”定义为完整基准平均收益减去移除该因子后的平均收益；正值才表示因子在该口径下有增益。即使标记为“值得独立复验”，也不等于可以直接并入当前线上策略，仍需在当前策略候选池做样本外验证。")
    lines.extend(["", "所有百分比均为历史样本统计，不代表未来收益。", ""])
    (output_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_experiment(start_date: str, end_date: str, output_dir: Path = THIS_DIR) -> None:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    proxy = LocalDataProxy(str(REPO_ROOT / "data" / "cache"))
    common_dates = sorted(
        set(proxy.available_dates("daily"))
        & set(proxy.available_dates("daily_basic"))
        & set(proxy.available_dates("moneyflow"))
        & set(proxy.available_dates("index_daily"))
    )
    calendar = proxy.trade_cal(start_date=start_date, end_date=end_date, is_open=1, fields="cal_date,is_open")
    open_dates = set(calendar["cal_date"].astype(str)) if not calendar.empty else set(common_dates)
    provisional_dates = sorted(date for date in set(common_dates) & open_dates if start_date <= date <= end_date)
    if not provisional_dates:
        raise RuntimeError("指定区间没有四类缓存共同覆盖的交易日")
    warmup_start = (pd.Timestamp(provisional_dates[0]) - pd.Timedelta(days=WARMUP_CALENDAR_DAYS)).strftime("%Y%m%d")
    forward_end_candidates = [date for date in common_dates if date in open_dates and date >= provisional_dates[-1]][: max(HORIZONS) + 1]
    price_end = forward_end_candidates[-1] if forward_end_candidates else provisional_dates[-1]
    print(f"读取行情面板 {warmup_start}~{price_end} ...", flush=True)
    prices = add_technical_features(load_price_panel(proxy, warmup_start, price_end))
    signal_dates = usable_signal_dates(common_dates, open_dates, prices["trade_date"].unique(), start_date, end_date)
    if not signal_dates:
        raise RuntimeError("交易日历开市日没有非空行情")
    indices = load_index_features(proxy, warmup_start, price_end)
    stock_basic = proxy.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,industry,list_date")

    all_signals: List[dict] = []
    case_rows: List[dict] = []
    active_year = signal_dates[0][:4]
    for number, trade_date in enumerate(signal_dates, start=1):
        if trade_date[:4] != active_year:
            year_frame = pd.DataFrame([row for row in all_signals if row["select_date"].startswith(active_year)])
            year_frame.to_csv(output_dir / f"signals_{active_year}.csv", index=False, encoding="utf-8-sig")
            active_year = trade_date[:4]
        day = prices[prices["trade_date"] == trade_date].copy()
        basic = proxy.daily_basic(trade_date=trade_date, fields="ts_code,turnover_rate,volume_ratio")
        money = proxy.moneyflow(trade_date=trade_date, fields="ts_code,net_mf_amount")
        day = day.merge(basic.rename(columns={"turnover_rate": "turnover"}), on="ts_code", how="left")
        day = day.merge(money.rename(columns={"net_mf_amount": "main_net_inflow"}), on="ts_code", how="left")
        market_day = day[["ts_code", "pct_chg"]]
        sector_status, sector_accel = _sector_snapshot(indices, trade_date)
        context = _market_context(indices, market_day, trade_date, sector_status)
        day["counter_trend_resistance"] = np.where(
            (float(context["index_change"]) < -1.0) & (day["pct_chg"] > 0),
            day["pct_chg"] - float(context["index_change"]), 0.0,
        )
        restricted = _restricted_codes(proxy, trade_date)
        for variant in VARIANTS:
            candidates, trace = evaluate_variant(day, stock_basic, context, sector_status, sector_accel, variant, restricted)
            selected = select_top_n(candidates, float(context["position"]), TOP_N)
            selected_codes = {item["ts_code"] for item in selected}
            for item in selected:
                all_signals.append({**item, "variant": variant.name, "selected": True})
            if trade_date == "20260422":
                target = next((item for item in candidates if item["ts_code"] == "002281.SZ"), None)
                case_rows.append({
                    "variant": variant.name, "volume_ratio_threshold": variant.volume_ratio_threshold,
                    "pre_threshold_rank": target.get("pre_threshold_rank") if target else trace.get("pre_threshold_rank"),
                    "candidate_rank": target.get("candidate_rank") if target else trace.get("candidate_rank"),
                    "score_base": target.get("score_base") if target else trace.get("score_base"),
                    "news_proxy_boost": target.get("news_proxy_boost") if target else trace.get("news_proxy_boost"),
                    "final_score": target.get("score") if target else trace.get("score"),
                    "factor_volume_ratio": target.get("factor_volume_ratio") if target else trace.get("factor_volume_ratio"),
                    "factor_drawdown": target.get("factor_drawdown") if target else trace.get("factor_drawdown"),
                    "factor_sector": target.get("factor_sector") if target else trace.get("factor_sector"),
                    "factor_inflow": target.get("factor_inflow") if target else trace.get("factor_inflow"),
                    "factor_turnover": target.get("factor_turnover") if target else trace.get("factor_turnover"),
                    "factor_pattern": target.get("factor_pattern") if target else trace.get("factor_pattern"),
                    "factor_counter_trend": target.get("factor_counter_trend") if target else trace.get("factor_counter_trend"),
                    "factor_wyckoff": target.get("factor_wyckoff") if target else trace.get("factor_wyckoff"),
                    "factor_accel": target.get("factor_accel") if target else trace.get("factor_accel"),
                    "selected": "002281.SZ" in selected_codes,
                    "failure_reason": "" if "002281.SZ" in selected_codes else ("below_effective_top_n" if target else trace.get("failure_reason", "unknown")),
                    "regime": context["regime"], "market_style": context["style"],
                    "reported_regime": "BEAR_BOUNCE", "reported_score_base": 88,
                    "reported_final_score": 98, "reported_news_concept_boost": 10,
                })
        if number % 20 == 0 or number == len(signal_dates):
            partial = pd.DataFrame(all_signals)
            partial.to_csv(output_dir / "signals.partial.csv", index=False, encoding="utf-8-sig")
            # LocalDataProxy 的日文件 LRU 会保留大块 DataFrame；长周期实验定期清理，避免分页文件耗尽。
            proxy._read_daily.cache_clear()
            print(f"进度 {number}/{len(signal_dates)}，已落盘信号 {len(partial)} 条", flush=True)

    final_year_frame = pd.DataFrame([row for row in all_signals if row["select_date"].startswith(active_year)])
    final_year_frame.to_csv(output_dir / f"signals_{active_year}.csv", index=False, encoding="utf-8-sig")

    signals = pd.DataFrame(all_signals)
    signals.to_csv(output_dir / "signals.csv", index=False, encoding="utf-8-sig")
    trades = _attach_outcomes(signals, prices)
    trades.to_csv(output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    case = pd.DataFrame(case_rows)
    case.to_csv(output_dir / "guangxun_case.csv", index=False, encoding="utf-8-sig")
    (output_dir / "guangxun_case.json").write_text(case.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")

    periods = sorted({date[:4] for date in signal_dates}) + ["all"]
    summary = pd.DataFrame([
        _metrics(trades, variant.name, period, horizon)
        for variant in VARIANTS for period in periods for horizon in HORIZONS
    ])
    summary.to_csv(output_dir / "variant_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "variant_summary.json").write_text(summary.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    metadata = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "python": platform.python_version(), "pandas": pd.__version__,
        "requested_start": start_date, "requested_end": end_date,
        "actual_signal_start": signal_dates[0], "actual_signal_end": signal_dates[-1],
        "common_date_count": len(signal_dates), "price_forward_end": price_end,
        "archive_main_sha256": _sha256(ARCHIVE_DIR / "main_20260420_vscode_history.py"),
        "variants": [asdict(v) for v in VARIANTS], "regime_params": REGIME_PARAMS,
        "limitations": [
            "历史新闻、AI板块映射与概念热度时序不可恢复",
            "静态 stock_basic 存在生存者偏差",
            "指数缓存缺少 amount，Override 成交额条件不可计算",
            "历史 config.py 因含明文密钥未读取或复制，非源码内参数采用注释证据近似",
            "目标日本地缓存按归档源码得到的状态与基础分均无法对齐原报告，视为未闭合证据冲突",
        ],
    }
    (output_dir / "experiment_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(summary, case, metadata, output_dir)
    partial_path = output_dir / "signals.partial.csv"
    if partial_path.exists():
        partial_path.unlink()


def _read_optional_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (pd.errors.EmptyDataError, FileNotFoundError):
        return pd.DataFrame()


def combine_yearly_outputs(yearly_dirs: Sequence[Path], output_dir: Path = THIS_DIR) -> None:
    """合并独立年度进程输出并重新计算分年度与全周期统计。"""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    yearly_dirs = [Path(path).resolve() for path in yearly_dirs]
    signals = pd.concat([_read_optional_csv(path / "signals.csv") for path in yearly_dirs], ignore_index=True)
    trades = pd.concat([_read_optional_csv(path / "trades.csv") for path in yearly_dirs], ignore_index=True)
    cases = [_read_optional_csv(path / "guangxun_case.csv") for path in yearly_dirs]
    case = pd.concat([frame for frame in cases if not frame.empty], ignore_index=True) if any(not frame.empty for frame in cases) else pd.DataFrame()
    metadatas = [json.loads((path / "experiment_metadata.json").read_text(encoding="utf-8")) for path in yearly_dirs]
    periods = sorted({str(date)[:4] for date in signals["select_date"].astype(str)}) + ["all"]
    summary = pd.DataFrame([
        _metrics(trades, variant.name, period, horizon)
        for variant in VARIANTS for period in periods for horizon in HORIZONS
    ])
    signals.to_csv(output_dir / "signals.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    case.to_csv(output_dir / "guangxun_case.csv", index=False, encoding="utf-8-sig")
    (output_dir / "guangxun_case.json").write_text(case.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    summary.to_csv(output_dir / "variant_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "variant_summary.json").write_text(summary.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    for year in periods[:-1]:
        signals[signals["select_date"].astype(str).str.startswith(year)].to_csv(
            output_dir / f"signals_{year}.csv", index=False, encoding="utf-8-sig"
        )
    metadata = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "python": platform.python_version(), "pandas": pd.__version__,
        "requested_start": min(item["actual_signal_start"] for item in metadatas),
        "requested_end": max(item["actual_signal_end"] for item in metadatas),
        "actual_signal_start": min(item["actual_signal_start"] for item in metadatas),
        "actual_signal_end": max(item["actual_signal_end"] for item in metadatas),
        "common_date_count": sum(int(item["common_date_count"]) for item in metadatas),
        "price_forward_end": max(item["price_forward_end"] for item in metadatas),
        "archive_main_sha256": _sha256(ARCHIVE_DIR / "main_20260420_vscode_history.py"),
        "variants": [asdict(v) for v in VARIANTS], "regime_params": REGIME_PARAMS,
        "yearly_process_dirs": [str(path) for path in yearly_dirs],
        "limitations": [
            "历史新闻、AI板块映射与概念热度时序不可恢复",
            "静态 stock_basic 存在生存者偏差",
            "指数缓存缺少 amount，Override 成交额条件不可计算",
            "历史 config.py 因含明文密钥未读取或复制，非源码内参数采用注释证据近似",
            "目标日本地缓存按归档源码得到的状态与基础分均无法对齐原报告，视为未闭合证据冲突",
            "为避免多年特征面板导致 Windows 分页文件压力，四个年份由独立进程计算后合并",
        ],
    }
    (output_dir / "experiment_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(summary, case, metadata, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="20230103")
    parser.add_argument("--end", default="20260630")
    parser.add_argument("--output-dir", default=str(THIS_DIR))
    parser.add_argument("--combine-yearly", nargs="*", default=[])
    args = parser.parse_args()
    if args.combine_yearly:
        combine_yearly_outputs([Path(path) for path in args.combine_yearly], Path(args.output_dir))
    else:
        run_experiment(args.start, args.end, Path(args.output_dir))


if __name__ == "__main__":
    main()
