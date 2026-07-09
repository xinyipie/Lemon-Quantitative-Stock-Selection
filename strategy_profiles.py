"""Shared short-strategy score profiles and style gates."""

from __future__ import annotations

from typing import Iterable

import pandas as pd


SHORT_FACTOR_COLUMNS = [
    "factor_volume_ratio",
    "factor_drawdown",
    "factor_inflow",
    "factor_turnover",
    "factor_sector",
    "factor_pattern",
    "factor_counter_trend",
    "factor_wyckoff",
    "factor_accel",
    "change",
    "volume_ratio",
    "drawdown_from_high",
    "turnover",
    "score_base",
    "market_style",
    "macro_mode",
    "market_state",
    "operation_mode",
    "regime",
    "market_index_change",
    "sector_ma10_ratio",
    "sector_ma10_above",
    "sector_ma10_total",
    "limit_up_count",
    "limit_down_count",
    "limit_up_down_ratio",
    "market_sentiment",
    "industry",
    "consensus_profile",
    "consensus_votes",
    "consensus_avg_rank",
    "consensus_avg_score",
    "consensus_profiles",
    "consensus_score",
    "consensus_layer",
    "gap_fill_score",
    "observe_profile",
    "observe_lane",
    "observe_score",
]

VALID_FACTOR_PROFILES = (
    "original",
    "diagnostic_v1",
    "profile_v2",
    "profile_v3",
    "profile_v4",
    "profile_v5",
    "profile_v8_sector_rank",
    "profile_v9_sector_quality_guard",
    "profile_v10_mid_deep_drawdown_guard",
    "profile_v11_mid_deep_drawdown_strict_guard",
    "profile_v12_2026h1_guard",
    "profile_v13_high_win_quality_gate",
    "profile_v14_sector_pattern_gate",
    "profile_v15_dual_lane_quality_gate",
    "profile_v16_window_confidence",
    "profile_v17_followthrough_factor",
    "profile_v18_stable_followthrough",
    "profile_v19_calm_followthrough",
    "profile_v20_low_noise_followthrough",
    "profile_v21_sector_calm_followthrough",
    "profile_v22_two_lane_followthrough",
    "profile_v23_cautious_window",
    "profile_v24_momentum_pullback",
)

VALID_STYLE_GATES = (
    "none",
    "no_momentum",
    "no_active_sideways",
    "weak_only",
    "weak_or_cautious_sideways",
    "adaptive_quality",
    "adaptive_quality_v2",
    "adaptive_quality_v5",
    "adaptive_quality_v6",
    "adaptive_quality_v13",
    "adaptive_quality_v14",
    "adaptive_quality_v15",
    "adaptive_quality_v16",
    "adaptive_quality_v17",
    "adaptive_quality_v18",
    "adaptive_quality_v19",
    "adaptive_quality_v20",
    "adaptive_quality_v21",
    "adaptive_quality_v22",
    "adaptive_quality_v23",
    "adaptive_quality_v24",
    "adaptive_quality_v25",
    "adaptive_quality_v26",
    "adaptive_quality_v27",
    "adaptive_quality_v28",
)

VALID_CONSENSUS_PROFILES = (
    "none",
    "v29",
    "v30",
    "v31",
    "v32",
    "v33",
    "v34",
    "v35",
    "v36",
    "v37",
    "v38",
    "v39",
    "v40",
    "v41",
    "v42",
    "v43",
    "v44",
)

CONSENSUS_PROFILE_CONFIGS = {
    "v29": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v30": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v31": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v32": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v33": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v34": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v35": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v36": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v37": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v38": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v39": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v40": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v41": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v42": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v43": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
    "v44": (
        ("v19", "profile_v19_calm_followthrough", "adaptive_quality_v19"),
        ("v25", "profile_v19_calm_followthrough", "adaptive_quality_v25"),
        ("v27", "profile_v21_sector_calm_followthrough", "adaptive_quality_v27"),
    ),
}


def normalize_factor_profile(factor_profile: str) -> str:
    return factor_profile if factor_profile in VALID_FACTOR_PROFILES else "original"


def normalize_style_gate(style_gate: str) -> str:
    return style_gate if style_gate in VALID_STYLE_GATES else "none"


def normalize_consensus_profile(consensus_profile: str) -> str:
    return consensus_profile if consensus_profile in VALID_CONSENSUS_PROFILES else "none"


def _num_series(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[name], errors="coerce").fillna(default)


def apply_style_gate(df: pd.DataFrame, style_gate: str) -> pd.DataFrame:
    """Apply the short-strategy style gate used by backtest and live reports."""
    style_gate = normalize_style_gate(style_gate)
    if df.empty or style_gate == "none":
        return df.copy()

    style = df["market_style"].fillna("").astype(str) if "market_style" in df.columns else pd.Series("", index=df.index)
    macro = df["macro_mode"].fillna("").astype(str) if "macro_mode" in df.columns else pd.Series("", index=df.index)

    if style_gate == "no_momentum":
        mask = style != "momentum"
    elif style_gate == "no_active_sideways":
        mask = ~((style == "sideways") & (macro == "active"))
    elif style_gate == "weak_only":
        mask = style == "weak_momentum"
    elif style_gate == "weak_or_cautious_sideways":
        mask = (style == "weak_momentum") | ((style == "sideways") & (macro == "cautious"))
    elif style_gate in (
        "adaptive_quality",
        "adaptive_quality_v2",
        "adaptive_quality_v5",
        "adaptive_quality_v6",
        "adaptive_quality_v13",
        "adaptive_quality_v14",
        "adaptive_quality_v15",
        "adaptive_quality_v16",
        "adaptive_quality_v17",
        "adaptive_quality_v18",
        "adaptive_quality_v19",
        "adaptive_quality_v20",
        "adaptive_quality_v21",
        "adaptive_quality_v22",
        "adaptive_quality_v23",
        "adaptive_quality_v24",
        "adaptive_quality_v25",
        "adaptive_quality_v26",
        "adaptive_quality_v27",
        "adaptive_quality_v28",
    ):
        pattern = _num_series(df, "factor_pattern", 50.0)
        inflow = _num_series(df, "factor_inflow", 50.0)
        sector = _num_series(df, "factor_sector", 50.0)
        wyckoff = _num_series(df, "factor_wyckoff", 50.0)
        drawdown_score = _num_series(df, "factor_drawdown", 50.0)
        raw_drawdown = _num_series(df, "drawdown_from_high", 0.0)
        raw_volume_ratio = _num_series(df, "volume_ratio", 1.0)
        raw_change = _num_series(df, "change", 0.0)
        regime = df["regime"].fillna("BULL_TREND").astype(str) if "regime" in df.columns else pd.Series("BULL_TREND", index=df.index)
        market_index_change = _num_series(df, "market_index_change", 0.0)
        sector_ma10_ratio = _num_series(df, "sector_ma10_ratio", 0.0)
        limit_up_count = _num_series(df, "limit_up_count", 999.0)
        limit_down_count = _num_series(df, "limit_down_count", 0.0)
        score = _num_series(df, "experiment_score", _num_series(df, "score", _num_series(df, "score_base", 0.0)))

        if style_gate == "adaptive_quality_v13":
            core_quality = (
                (pattern >= 63.0)
                & (inflow >= 70.0)
                & (raw_drawdown <= 7.0)
                & (raw_volume_ratio >= 1.3)
                & (raw_volume_ratio <= 3.0)
                & (raw_change <= 5.0)
                & (style != "bear")
            )
            style_quality = (
                (style == "weak_momentum")
                | ((style == "momentum") & (pattern >= 70.0) & (inflow >= 75.0) & (raw_drawdown <= 5.5))
                | ((style == "sideways") & (macro != "active") & (pattern >= 76.0) & (inflow >= 80.0) & (raw_drawdown <= 5.0))
            )
            mask = core_quality & style_quality
            return df.loc[mask].copy()

        if style_gate == "adaptive_quality_v14":
            core_quality = (
                (pattern >= 70.0)
                & (inflow >= 70.0)
                & (sector >= 65.0)
                & (raw_drawdown <= 5.0)
                & (raw_volume_ratio >= 1.3)
                & (raw_volume_ratio <= 2.8)
                & (raw_change <= 3.0)
                & (style != "bear")
            )
            return df.loc[core_quality].copy()

        if style_gate == "adaptive_quality_v15":
            lane_a = (
                (pattern >= 70.0)
                & (inflow >= 70.0)
                & (sector >= 65.0)
                & (raw_drawdown <= 5.0)
                & (raw_volume_ratio >= 1.3)
                & (raw_volume_ratio <= 2.8)
                & (raw_change <= 3.0)
                & (style != "bear")
            )
            lane_b = (
                (style == "weak_momentum")
                & (pattern >= 76.0)
                & (inflow >= 80.0)
                & (sector >= 35.0)
                & (raw_drawdown <= 5.5)
                & (raw_volume_ratio >= 1.3)
                & (raw_volume_ratio <= 2.6)
                & (raw_change <= 3.0)
            )
            return df.loc[lane_a | lane_b].copy()

        if style_gate == "adaptive_quality_v16":
            calm_entry = (
                (raw_change <= 3.0)
                & (raw_volume_ratio >= 1.3)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown <= 5.5)
                & ~((raw_drawdown >= 9.0) & (raw_drawdown < 12.0))
                & (style != "bear")
            )
            lane_a = (
                calm_entry
                & (pattern >= 70.0)
                & (inflow >= 70.0)
                & (sector >= 60.0)
                & ((style != "weak_momentum") | (sector >= 68.0))
            )
            lane_b = (
                calm_entry
                & (style == "weak_momentum")
                & (pattern >= 80.0)
                & (inflow >= 82.0)
                & (sector >= 58.0)
                & (raw_drawdown <= 5.0)
            )
            return df.loc[lane_a | lane_b].copy()

        if style_gate == "adaptive_quality_v17":
            follow_style = style.isin(("weak_momentum", "momentum"))
            lane_a = (
                follow_style
                & (pattern >= 60.0)
                & (inflow >= 90.0)
                & (sector >= 35.0)
                & (raw_drawdown <= 7.0)
                & (raw_volume_ratio <= 2.8)
                & (raw_change <= 5.0)
                & (wyckoff <= 70.0)
            )
            lane_b = (
                follow_style
                & (pattern >= 60.0)
                & (inflow >= 70.0)
                & (sector >= 35.0)
                & (sector <= 85.0)
                & (raw_drawdown <= 6.0)
                & (raw_volume_ratio <= 2.5)
                & (raw_change <= 5.0)
                & (wyckoff <= 80.0)
            )
            return df.loc[lane_a | lane_b].copy()

        if style_gate == "adaptive_quality_v18":
            stable_followthrough = (
                (style == "weak_momentum")
                & (inflow >= 99.0)
                & (wyckoff >= 60.0)
                & (wyckoff <= 85.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown <= 8.0)
                & (raw_change <= 5.0)
            )
            return df.loc[stable_followthrough].copy()

        if style_gate == "adaptive_quality_v19":
            calm_followthrough = (
                (style == "weak_momentum")
                & (inflow >= 99.0)
                & (wyckoff >= 60.0)
                & (wyckoff <= 75.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 5.0)
            )
            return df.loc[calm_followthrough].copy()

        if style_gate == "adaptive_quality_v25":
            protected_followthrough = (
                (style == "weak_momentum")
                & (inflow >= 99.0)
                & (wyckoff >= 60.0)
                & (wyckoff <= 75.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 5.0)
                & (regime == "BULL_TREND")
                & (sector_ma10_ratio < 95.0)
                & (market_index_change >= -0.6)
            )
            return df.loc[protected_followthrough].copy()

        if style_gate == "adaptive_quality_v26":
            followthrough_base = (
                (style == "weak_momentum")
                & (inflow >= 99.0)
                & (wyckoff >= 60.0)
                & (wyckoff <= 75.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 5.0)
                & (regime == "BULL_TREND")
            )
            protected_followthrough = (
                followthrough_base
                & (sector_ma10_ratio < 95.0)
                & (market_index_change >= -0.6)
                & (limit_up_count >= 70.0)
                & (limit_down_count <= 15.0)
            )
            hot_followthrough = (
                followthrough_base
                & (sector_ma10_ratio >= 95.0)
                & (market_index_change >= 0.3)
                & (limit_up_count >= 80.0)
                & (limit_up_count <= 130.0)
                & (limit_down_count <= 10.0)
                & (raw_drawdown >= 3.0)
                & (raw_drawdown <= 4.2)
                & (raw_volume_ratio >= 1.7)
                & (raw_volume_ratio <= 2.9)
            )
            return df.loc[protected_followthrough | hot_followthrough].copy()

        if style_gate == "adaptive_quality_v27":
            calm_base = (
                (style == "weak_momentum")
                & (inflow >= 99.0)
                & (wyckoff >= 60.0)
                & (wyckoff <= 75.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown >= 3.0)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 4.5)
            )
            sector_calm_lane = calm_base & (sector <= 45.0)
            protected_lane = (
                calm_base
                & (regime == "BULL_TREND")
                & (sector_ma10_ratio < 95.0)
                & (market_index_change >= -0.6)
            )
            return df.loc[sector_calm_lane | protected_lane].copy()

        if style_gate == "adaptive_quality_v28":
            calm_base = (
                (style == "weak_momentum")
                & (inflow >= 99.0)
                & (wyckoff >= 60.0)
                & (wyckoff <= 75.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown >= 3.0)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 4.5)
            )
            market_heat_guard = (limit_up_count >= 70.0) & (limit_down_count <= 15.0)
            sector_calm_lane = calm_base & market_heat_guard & (sector <= 45.0)
            protected_lane = (
                calm_base
                & market_heat_guard
                & (regime == "BULL_TREND")
                & (sector_ma10_ratio < 95.0)
                & (market_index_change >= -0.6)
            )
            return df.loc[sector_calm_lane | protected_lane].copy()

        if style_gate == "adaptive_quality_v20":
            low_noise_followthrough = (
                (style == "weak_momentum")
                & (inflow >= 99.0)
                & (sector <= 85.0)
                & (wyckoff >= 60.0)
                & (wyckoff <= 75.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 4.5)
            )
            return df.loc[low_noise_followthrough].copy()

        if style_gate == "adaptive_quality_v21":
            sector_calm_followthrough = (
                (style == "weak_momentum")
                & (inflow >= 99.0)
                & (sector <= 45.0)
                & (wyckoff >= 60.0)
                & (wyckoff <= 75.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 4.5)
            )
            return df.loc[sector_calm_followthrough].copy()

        if style_gate == "adaptive_quality_v22":
            calm_window = (
                (style == "weak_momentum")
                & (wyckoff >= 60.0)
                & (wyckoff <= 75.0)
                & (raw_volume_ratio >= 1.4)
                & (raw_volume_ratio <= 2.8)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 4.5)
            )
            low_sector_lane = calm_window & (inflow >= 99.0) & (sector <= 45.0)
            active_pattern_lane = (
                calm_window
                & (macro == "active")
                & (inflow >= 90.0)
                & (pattern <= 40.0)
                & (sector <= 65.0)
            )
            return df.loc[low_sector_lane | active_pattern_lane].copy()

        if style_gate == "adaptive_quality_v23":
            cautious_window = (
                (macro != "active")
                & (sector <= 55.0)
                & (wyckoff >= 50.0)
                & (wyckoff <= 80.0)
                & (raw_drawdown <= 7.0)
                & (raw_change <= 5.5)
                & (score >= 15.0)
            )
            return df.loc[cautious_window].copy()

        if style_gate == "adaptive_quality_v24":
            momentum_pullback = (
                (style == "momentum")
                & (raw_drawdown >= 2.0)
                & (raw_drawdown <= 10.0)
                & (raw_volume_ratio >= 1.5)
                & (raw_volume_ratio <= 3.0)
                & (pattern >= 30.0)
                & (raw_change <= 5.5)
            )
            return df.loc[momentum_pullback].copy()

        low_quality_sideways = (
            (pattern < 45.0)
            | ((pattern < 50.0) & (sector > 50.0))
            | ((raw_drawdown > 8.0) & (sector > 50.0))
            | ((raw_drawdown > 9.0) & (pattern < 55.0))
            | ((raw_volume_ratio > 3.2) & (pattern < 55.0))
        )
        quality_sideways = (style == "sideways") & (macro == "active") & ~low_quality_sideways
        mask = (style == "weak_momentum") | quality_sideways

        if style_gate in ("adaptive_quality_v2", "adaptive_quality_v5", "adaptive_quality_v6"):
            high_score_risk = (
                (score >= 70.0)
                & (pattern < 55.0)
                & (raw_drawdown >= 8.0)
                & (
                    (drawdown_score >= 88.0)
                    | (sector >= 55.0)
                    | (raw_volume_ratio >= 3.2)
                )
            )
            weak_momentum_risk = (
                (style == "weak_momentum")
                & (pattern < 52.0)
                & (sector >= 55.0)
                & (raw_drawdown >= 9.0)
            )
            mask = mask & ~(high_score_risk | weak_momentum_risk)

        if style_gate == "adaptive_quality_v5":
            high_score_volume_spike = (score >= 70.0) & (raw_volume_ratio >= 3.2)
            mask = mask & ~high_score_volume_spike

        if style_gate == "adaptive_quality_v6":
            weak_sector_volume_spike = (
                (score >= 70.0)
                & (raw_volume_ratio >= 3.2)
                & (sector < 45.0)
            )
            mask = mask & ~weak_sector_volume_spike
    else:
        mask = pd.Series(True, index=df.index)

    return df.loc[mask].copy()


def factor_profile_score(row: pd.Series, factor_profile: str, base_score_col: str = "score") -> float:
    """Score one short candidate using an experimental factor profile."""
    factor_profile = normalize_factor_profile(factor_profile)
    if factor_profile == "original":
        return float(row.get(base_score_col, 0) or 0)

    def f(name: str, default: float = 0.0) -> float:
        val = row.get(name, default)
        try:
            if pd.isna(val):
                return default
        except TypeError:
            pass
        return float(val or default)

    def clipped(value: float, low: float = 0.0, high: float = 100.0) -> float:
        return max(low, min(value, high))

    def band_score(value: float, low: float, mid: float, high: float) -> float:
        if value <= low or value >= high:
            return 0.0
        if value == mid:
            return 100.0
        if value < mid:
            return (value - low) / max(mid - low, 1e-9) * 100.0
        return (high - value) / max(high - mid, 1e-9) * 100.0

    style = str(row.get("market_style", "") or "")
    macro_mode = str(row.get("macro_mode", "") or "")
    score_base = f("score_base", f(base_score_col, 0.0))
    volume = f("factor_volume_ratio")
    drawdown = f("factor_drawdown")
    inflow = f("factor_inflow")
    turnover = f("factor_turnover")
    sector = f("factor_sector")
    pattern = f("factor_pattern")
    counter = f("factor_counter_trend")
    wyckoff = f("factor_wyckoff")
    raw_volume_ratio = f("volume_ratio", 1.0)
    raw_turnover = f("turnover", 0.0)
    raw_drawdown = f("drawdown_from_high", 0.0)
    close = f("close", 0.0)
    target = f("target_price", 0.0)
    stop = f("stop_loss_price", 0.0)
    today_chg = f("change", 0.0)

    target_pct = ((target / close - 1) * 100) if close > 0 and target > 0 else 8.0
    stop_risk_pct = ((close / stop - 1) * 100) if close > 0 and stop > 0 else 7.0

    if factor_profile == "profile_v2":
        volume_fit = band_score(raw_volume_ratio, 0.75, 1.8, 3.2)
        calm_volume_fit = band_score(raw_volume_ratio, 0.65, 1.35, 2.6)
        momentum_volume_fit = band_score(raw_volume_ratio, 1.0, 2.0, 3.8)
        target_space = clipped(target_pct / 12 * 100) if close > 0 and target > 0 else 50.0
        stop_quality = clipped(100 - max(stop_risk_pct - 3.0, 0) / 7.0 * 100)
        shallow_pullback = band_score(raw_drawdown, 0.0, 2.5, 7.0)
        setup_pullback = band_score(raw_drawdown, 1.5, 5.0, 12.0)
        catchup_position = band_score(raw_drawdown, 0.0, 3.0, 9.0)
        not_overheated = clipped(100 - max(today_chg - 3.0, 0) / 4.0 * 100)
        sector_catchup = (100 - sector) * 0.55 + sector * 0.45
        structure = max(pattern, 100 - counter * 0.6, 100 - wyckoff * 0.5)

        if style == "momentum":
            score = (
                inflow * 0.25
                + shallow_pullback * 0.18
                + momentum_volume_fit * 0.16
                + sector * 0.12
                + target_space * 0.12
                + stop_quality * 0.09
                + not_overheated * 0.08
            )
        elif style == "weak_momentum":
            score = (
                inflow * 0.30
                + setup_pullback * 0.20
                + volume_fit * 0.15
                + sector_catchup * 0.12
                + target_space * 0.10
                + stop_quality * 0.08
                + structure * 0.05
            )
        else:
            score = (
                inflow * 0.30
                + sector_catchup * 0.20
                + catchup_position * 0.16
                + calm_volume_fit * 0.12
                + target_space * 0.12
                + stop_quality * 0.06
                + not_overheated * 0.04
            )
        return round(clipped(score), 2)

    if factor_profile == "profile_v8_sector_rank":
        base = factor_profile_score(row, "profile_v4", base_score_col)
        if sector >= 60.0:
            bonus = 3.0
        elif sector >= 45.0:
            bonus = 1.5
        elif sector < 30.0:
            bonus = -1.0
        else:
            bonus = 0.0
        return round(clipped(base + bonus), 2)

    if factor_profile == "profile_v9_sector_quality_guard":
        base = factor_profile_score(row, "profile_v4", base_score_col)
        if sector >= 60.0 and raw_volume_ratio <= 2.6:
            bonus = 3.0
        elif sector >= 45.0 and raw_volume_ratio <= 2.6:
            bonus = 1.5
        elif sector < 30.0 and raw_volume_ratio >= 3.0:
            bonus = -3.0
        elif sector < 30.0:
            bonus = -1.0
        else:
            bonus = 0.0
        return round(clipped(base + bonus), 2)

    if factor_profile == "profile_v10_mid_deep_drawdown_guard":
        base = factor_profile_score(row, "profile_v4", base_score_col)
        penalty = 3.0 if 9.0 <= raw_drawdown < 12.0 else 0.0
        return round(clipped(base - penalty), 2)

    if factor_profile == "profile_v11_mid_deep_drawdown_strict_guard":
        base = factor_profile_score(row, "profile_v4", base_score_col)
        penalty = 6.0 if 9.0 <= raw_drawdown < 12.0 else 0.0
        return round(clipped(base - penalty), 2)

    if factor_profile == "profile_v12_2026h1_guard":
        base = factor_profile_score(row, "profile_v9_sector_quality_guard", base_score_col)
        adjustment = 0.0

        if style == "weak_momentum":
            adjustment += 8.0
            if inflow >= 60.0:
                adjustment += 4.0
            if pattern >= 58.0:
                adjustment += 3.0
            if 1.4 <= raw_volume_ratio <= 2.6:
                adjustment += 4.0
            if 2.0 <= raw_drawdown <= 7.0:
                adjustment += 3.0
            if turnover >= 60.0:
                adjustment += 2.0
        elif style == "momentum":
            adjustment -= 4.0
            if inflow >= 65.0 and pattern >= 60.0 and raw_drawdown <= 5.0:
                adjustment += 6.0
        elif style == "sideways":
            adjustment -= 20.0
            if macro_mode == "active":
                adjustment -= 5.0
            if sector >= 55.0:
                adjustment -= 4.0
        elif style == "bear":
            adjustment -= 25.0

        if raw_volume_ratio > 3.0:
            adjustment -= (raw_volume_ratio - 3.0) * 8.0
        if raw_drawdown > 8.0:
            adjustment -= (raw_drawdown - 8.0) * 2.5
        if pattern < 55.0:
            adjustment -= (55.0 - pattern) * 0.5
        if inflow < 35.0:
            adjustment -= (35.0 - inflow) * 0.35
        if today_chg > 5.5:
            adjustment -= (today_chg - 5.5) * 4.0
        if today_chg < 0.0:
            adjustment -= abs(today_chg) * 2.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v13_high_win_quality_gate":
        base = factor_profile_score(row, "profile_v9_sector_quality_guard", base_score_col)
        adjustment = 0.0

        if style == "weak_momentum":
            adjustment += 10.0
        elif style == "momentum":
            adjustment += 2.0 if pattern >= 70.0 and inflow >= 75.0 and raw_drawdown <= 5.5 else -8.0
        elif style == "sideways":
            adjustment -= 18.0
            if macro_mode != "active" and pattern >= 76.0 and inflow >= 80.0 and raw_drawdown <= 5.0:
                adjustment += 6.0
        elif style == "bear":
            adjustment -= 35.0

        if pattern >= 76.0:
            adjustment += 8.0
        elif pattern >= 63.0:
            adjustment += 4.0
        else:
            adjustment -= (63.0 - pattern) * 0.9

        if inflow >= 80.0:
            adjustment += 8.0
        elif inflow >= 70.0:
            adjustment += 4.0
        else:
            adjustment -= (70.0 - inflow) * 0.7

        if 1.5 <= raw_volume_ratio <= 2.5:
            adjustment += 5.0
        elif 1.3 <= raw_volume_ratio <= 3.0:
            adjustment += 2.0
        elif raw_volume_ratio > 3.0:
            adjustment -= (raw_volume_ratio - 3.0) * 10.0
        else:
            adjustment -= (1.3 - raw_volume_ratio) * 6.0

        if raw_drawdown <= 5.0:
            adjustment += 5.0
        elif raw_drawdown <= 7.0:
            adjustment += 2.0
        else:
            adjustment -= (raw_drawdown - 7.0) * 4.0

        if today_chg > 5.0:
            adjustment -= (today_chg - 5.0) * 5.0
        if today_chg < -1.0:
            adjustment -= abs(today_chg + 1.0) * 2.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v14_sector_pattern_gate":
        base = factor_profile_score(row, "profile_v13_high_win_quality_gate", base_score_col)
        adjustment = 0.0

        if pattern >= 80.0:
            adjustment += 10.0
        elif pattern >= 70.0:
            adjustment += 6.0
        else:
            adjustment -= (70.0 - pattern) * 1.0

        if sector >= 75.0:
            adjustment += 8.0
        elif sector >= 65.0:
            adjustment += 5.0
        else:
            adjustment -= (65.0 - sector) * 0.7

        if raw_drawdown <= 4.0:
            adjustment += 4.0
        elif raw_drawdown <= 5.0:
            adjustment += 2.0
        else:
            adjustment -= (raw_drawdown - 5.0) * 5.0

        if 1.5 <= raw_volume_ratio <= 2.5:
            adjustment += 4.0
        elif 1.3 <= raw_volume_ratio <= 2.8:
            adjustment += 1.5
        elif raw_volume_ratio > 2.8:
            adjustment -= (raw_volume_ratio - 2.8) * 12.0
        else:
            adjustment -= (1.3 - raw_volume_ratio) * 8.0

        if today_chg <= 3.0:
            adjustment += 4.0
        else:
            adjustment -= (today_chg - 3.0) * 8.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v15_dual_lane_quality_gate":
        base = factor_profile_score(row, "profile_v14_sector_pattern_gate", base_score_col)
        adjustment = 0.0

        lane_a = (
            pattern >= 70.0
            and inflow >= 70.0
            and sector >= 65.0
            and raw_drawdown <= 5.0
            and 1.3 <= raw_volume_ratio <= 2.8
            and today_chg <= 3.0
            and style != "bear"
        )
        lane_b = (
            style == "weak_momentum"
            and pattern >= 76.0
            and inflow >= 80.0
            and sector >= 35.0
            and raw_drawdown <= 5.5
            and 1.3 <= raw_volume_ratio <= 2.6
            and today_chg <= 3.0
        )

        if lane_a:
            adjustment += 8.0
        elif lane_b:
            adjustment += 12.0
        else:
            adjustment -= 10.0

        if style == "weak_momentum":
            adjustment += 3.0
        elif style == "sideways":
            adjustment -= 8.0
        elif style == "bear":
            adjustment -= 25.0

        if sector < 35.0:
            adjustment -= (35.0 - sector) * 0.9
        elif sector < 65.0:
            adjustment += 2.0

        if pattern >= 84.0:
            adjustment += 4.0
        elif pattern < 76.0:
            adjustment -= (76.0 - pattern) * 0.7

        if inflow >= 90.0:
            adjustment += 2.0
        elif inflow < 80.0:
            adjustment -= (80.0 - inflow) * 0.5

        if raw_drawdown > 5.5:
            adjustment -= (raw_drawdown - 5.5) * 5.0
        if raw_volume_ratio > 2.6:
            adjustment -= (raw_volume_ratio - 2.6) * 10.0
        if today_chg > 3.0:
            adjustment -= (today_chg - 3.0) * 8.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v16_window_confidence":
        base = factor_profile_score(row, "profile_v14_sector_pattern_gate", base_score_col)
        adjustment = 0.0

        calm_entry = (
            today_chg <= 3.0
            and 1.3 <= raw_volume_ratio <= 2.8
            and raw_drawdown <= 5.5
            and not (9.0 <= raw_drawdown < 12.0)
            and style != "bear"
        )
        strong_sector_lane = (
            calm_entry
            and pattern >= 70.0
            and inflow >= 70.0
            and sector >= 60.0
            and (style != "weak_momentum" or sector >= 68.0)
        )
        confirmed_weak_lane = (
            calm_entry
            and style == "weak_momentum"
            and pattern >= 80.0
            and inflow >= 82.0
            and sector >= 58.0
            and raw_drawdown <= 5.0
        )

        if strong_sector_lane:
            adjustment += 10.0
        if confirmed_weak_lane:
            adjustment += 12.0

        if sector >= 75.0:
            adjustment += 4.0
        elif sector >= 60.0:
            adjustment += 2.0
        elif sector < 60.0:
            adjustment -= (60.0 - sector) * 1.2

        if pattern >= 84.0:
            adjustment += 5.0
        elif pattern >= 70.0:
            adjustment += 2.0
        else:
            adjustment -= (70.0 - pattern) * 0.9

        if inflow >= 88.0:
            adjustment += 4.0
        elif inflow >= 70.0:
            adjustment += 1.5
        else:
            adjustment -= (70.0 - inflow) * 0.6

        if 1.5 <= raw_volume_ratio <= 2.35:
            adjustment += 4.0
        elif not (1.3 <= raw_volume_ratio <= 2.8):
            adjustment -= 8.0 + abs(raw_volume_ratio - 2.0) * 4.0

        if raw_drawdown <= 4.0:
            adjustment += 4.0
        elif raw_drawdown <= 5.5:
            adjustment += 1.0
        elif 9.0 <= raw_drawdown < 12.0:
            adjustment -= 24.0
        else:
            adjustment -= (raw_drawdown - 5.0) * 5.0

        if today_chg > 3.0:
            adjustment -= (today_chg - 3.0) * 8.0
        if style == "weak_momentum" and not confirmed_weak_lane:
            adjustment -= 16.0
        if style == "sideways" and not strong_sector_lane:
            adjustment -= 10.0
        if style == "bear":
            adjustment -= 30.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v17_followthrough_factor":
        base = factor_profile_score(row, "profile_v12_2026h1_guard", base_score_col)
        adjustment = 0.0

        follow_style = style in ("weak_momentum", "momentum")
        lane_a = (
            follow_style
            and pattern >= 60.0
            and inflow >= 90.0
            and sector >= 35.0
            and raw_drawdown <= 7.0
            and raw_volume_ratio <= 2.8
            and today_chg <= 5.0
            and wyckoff <= 70.0
        )
        lane_b = (
            follow_style
            and pattern >= 60.0
            and inflow >= 70.0
            and 35.0 <= sector <= 85.0
            and raw_drawdown <= 6.0
            and raw_volume_ratio <= 2.5
            and today_chg <= 5.0
            and wyckoff <= 80.0
        )

        if lane_a:
            adjustment += 12.0
        if lane_b:
            adjustment += 10.0

        if style == "weak_momentum":
            adjustment += 4.0
        elif style == "momentum":
            adjustment += 1.5 if pattern >= 60.0 and inflow >= 70.0 else -6.0
        elif style == "sideways":
            adjustment -= 22.0
        elif style == "bear":
            adjustment -= 35.0

        if pattern >= 70.0:
            adjustment += 4.0
        elif pattern >= 60.0:
            adjustment += 2.0
        else:
            adjustment -= (60.0 - pattern) * 0.8

        if inflow >= 90.0:
            adjustment += 5.0
        elif inflow >= 70.0:
            adjustment += 2.0
        else:
            adjustment -= (70.0 - inflow) * 0.6

        if 35.0 <= sector <= 85.0:
            adjustment += 3.0
        elif sector > 85.0:
            adjustment -= (sector - 85.0) * 0.7
        else:
            adjustment -= (35.0 - sector) * 0.7

        if 1.4 <= raw_volume_ratio <= 2.5:
            adjustment += 4.0
        elif raw_volume_ratio <= 2.8:
            adjustment += 1.0
        else:
            adjustment -= (raw_volume_ratio - 2.8) * 9.0

        if raw_drawdown <= 6.0:
            adjustment += 3.0
        elif raw_drawdown <= 7.0:
            adjustment += 1.0
        else:
            adjustment -= (raw_drawdown - 7.0) * 4.0

        if wyckoff <= 70.0:
            adjustment += 3.0
        elif wyckoff <= 80.0:
            adjustment += 1.0
        else:
            adjustment -= (wyckoff - 80.0) * 0.5

        if today_chg > 5.0:
            adjustment -= (today_chg - 5.0) * 6.0
        if raw_volume_ratio > 3.0 and sector > 85.0:
            adjustment -= 8.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v18_stable_followthrough":
        base = factor_profile_score(row, "profile_v12_2026h1_guard", base_score_col)
        adjustment = 0.0

        stable_followthrough = (
            style == "weak_momentum"
            and inflow >= 99.0
            and 60.0 <= wyckoff <= 85.0
            and 1.4 <= raw_volume_ratio <= 2.8
            and raw_drawdown <= 8.0
            and today_chg <= 5.0
        )

        if stable_followthrough:
            adjustment += 14.0
        else:
            adjustment -= 8.0

        if style == "weak_momentum":
            adjustment += 3.0
        elif style == "sideways":
            adjustment -= 18.0
        elif style == "bear":
            adjustment -= 30.0
        elif style == "momentum":
            adjustment -= 6.0

        if inflow >= 99.0:
            adjustment += 5.0
        elif inflow >= 95.0:
            adjustment -= 4.0
        else:
            adjustment -= (99.0 - inflow) * 0.6

        if 60.0 <= wyckoff <= 85.0:
            adjustment += 5.0
        elif wyckoff < 60.0:
            adjustment -= (60.0 - wyckoff) * 0.7
        else:
            adjustment -= (wyckoff - 85.0) * 0.8

        if 1.6 <= raw_volume_ratio <= 2.5:
            adjustment += 4.0
        elif 1.4 <= raw_volume_ratio <= 2.8:
            adjustment += 1.5
        elif raw_volume_ratio > 2.8:
            adjustment -= (raw_volume_ratio - 2.8) * 10.0
        else:
            adjustment -= (1.4 - raw_volume_ratio) * 8.0

        if raw_drawdown <= 5.5:
            adjustment += 3.0
        elif raw_drawdown <= 8.0:
            adjustment += 0.5
        else:
            adjustment -= (raw_drawdown - 8.0) * 4.0

        if sector <= 70.0:
            adjustment += 2.0
        elif sector > 90.0:
            adjustment -= (sector - 90.0) * 0.9 + 6.0

        if today_chg > 5.0:
            adjustment -= (today_chg - 5.0) * 7.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v19_calm_followthrough":
        base = factor_profile_score(row, "profile_v18_stable_followthrough", base_score_col)
        adjustment = 0.0

        calm_followthrough = (
            style == "weak_momentum"
            and inflow >= 99.0
            and 60.0 <= wyckoff <= 75.0
            and 1.4 <= raw_volume_ratio <= 2.8
            and raw_drawdown <= 7.0
            and today_chg <= 5.0
        )

        if calm_followthrough:
            adjustment += 8.0
        else:
            adjustment -= 6.0

        if wyckoff > 75.0:
            adjustment -= (wyckoff - 75.0) * 1.5 + 5.0
        if raw_drawdown > 7.0:
            adjustment -= (raw_drawdown - 7.0) * 5.0 + 4.0
        if 2.0 <= raw_drawdown <= 6.0:
            adjustment += 2.0
        if pattern > 85.0:
            adjustment -= (pattern - 85.0) * 0.7

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v20_low_noise_followthrough":
        base = factor_profile_score(row, "profile_v19_calm_followthrough", base_score_col)
        adjustment = 0.0

        low_noise_followthrough = (
            style == "weak_momentum"
            and inflow >= 99.0
            and sector <= 85.0
            and 60.0 <= wyckoff <= 75.0
            and 1.4 <= raw_volume_ratio <= 2.8
            and raw_drawdown <= 7.0
            and today_chg <= 4.5
        )

        if low_noise_followthrough:
            adjustment += 5.0
        else:
            adjustment -= 5.0

        if today_chg > 4.5:
            adjustment -= (today_chg - 4.5) * 7.0 + 4.0
        elif today_chg <= 3.5:
            adjustment += 1.5

        if sector > 85.0:
            adjustment -= (sector - 85.0) * 0.8 + 5.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v21_sector_calm_followthrough":
        base = factor_profile_score(row, "profile_v19_calm_followthrough", base_score_col)
        adjustment = 0.0

        sector_calm_followthrough = (
            style == "weak_momentum"
            and inflow >= 99.0
            and sector <= 45.0
            and 60.0 <= wyckoff <= 75.0
            and 1.4 <= raw_volume_ratio <= 2.8
            and raw_drawdown <= 7.0
            and today_chg <= 4.5
        )

        if sector_calm_followthrough:
            adjustment += 8.0
        else:
            adjustment -= 6.0

        if sector <= 45.0:
            adjustment += 4.0
        elif sector > 60.0:
            adjustment -= (sector - 60.0) * 0.6 + 5.0

        if pattern <= 40.0:
            adjustment += 2.0
        if today_chg > 4.5:
            adjustment -= (today_chg - 4.5) * 7.0 + 4.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v22_two_lane_followthrough":
        base = factor_profile_score(row, "profile_v19_calm_followthrough", base_score_col)
        adjustment = 0.0

        calm_window = (
            style == "weak_momentum"
            and 60.0 <= wyckoff <= 75.0
            and 1.4 <= raw_volume_ratio <= 2.8
            and raw_drawdown <= 7.0
            and today_chg <= 4.5
        )
        low_sector_lane = calm_window and inflow >= 99.0 and sector <= 45.0
        active_pattern_lane = (
            calm_window
            and macro_mode == "active"
            and inflow >= 90.0
            and pattern <= 40.0
            and sector <= 65.0
        )

        if low_sector_lane:
            adjustment += 8.0
        elif active_pattern_lane:
            adjustment += 7.0
        else:
            adjustment -= 5.0

        if sector <= 45.0:
            adjustment += 3.0
        elif sector <= 65.0 and active_pattern_lane:
            adjustment += 1.5
        elif sector > 65.0:
            adjustment -= (sector - 65.0) * 0.8 + 4.0

        if pattern <= 40.0 and macro_mode == "active":
            adjustment += 3.0
        if inflow >= 99.0:
            adjustment += 2.0
        if today_chg > 4.5:
            adjustment -= (today_chg - 4.5) * 7.0 + 4.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v23_cautious_window":
        base = factor_profile_score(row, "profile_v19_calm_followthrough", base_score_col)
        adjustment = 0.0

        cautious_window = (
            macro_mode != "active"
            and sector <= 55.0
            and 50.0 <= wyckoff <= 80.0
            and raw_drawdown <= 7.0
            and today_chg <= 5.5
        )

        if cautious_window:
            adjustment += 10.0
        else:
            adjustment -= 8.0

        if style == "weak_momentum":
            adjustment += 3.0
        if 50.0 <= wyckoff <= 75.0:
            adjustment += 2.0
        if sector <= 55.0:
            adjustment += 2.0
        if raw_drawdown > 7.0:
            adjustment -= (raw_drawdown - 7.0) * 4.0
        if today_chg > 5.5:
            adjustment -= (today_chg - 5.5) * 6.0

        return round(clipped(base + adjustment), 2)

    if factor_profile == "profile_v24_momentum_pullback":
        base = factor_profile_score(row, "profile_v17_followthrough_factor", base_score_col)
        adjustment = 0.0

        momentum_pullback = (
            style == "momentum"
            and 2.0 <= raw_drawdown <= 10.0
            and 1.5 <= raw_volume_ratio <= 3.0
            and pattern >= 30.0
            and today_chg <= 5.5
        )

        if momentum_pullback:
            adjustment += 10.0
        else:
            adjustment -= 8.0

        if style == "momentum":
            adjustment += 3.0
        if 2.0 <= raw_drawdown <= 4.0:
            adjustment += 4.0
        elif 4.0 < raw_drawdown <= 10.0:
            adjustment += 1.5
        elif raw_drawdown > 10.0:
            adjustment -= (raw_drawdown - 10.0) * 4.0 + 5.0

        if 2.0 <= raw_volume_ratio <= 3.0:
            adjustment += 3.0
        elif raw_volume_ratio > 3.0:
            adjustment -= (raw_volume_ratio - 3.0) * 8.0 + 4.0

        if pattern >= 50.0:
            adjustment += 2.0
        elif pattern < 30.0:
            adjustment -= (30.0 - pattern) * 0.8 + 3.0

        if inflow >= 80.0:
            adjustment += 2.0
        elif inflow < 60.0:
            adjustment -= (60.0 - inflow) * 0.25

        if today_chg > 5.5:
            adjustment -= (today_chg - 5.5) * 6.0

        return round(clipped(base + adjustment), 2)

    if factor_profile in ("profile_v3", "profile_v4", "profile_v5"):
        calm_volume_fit = band_score(raw_volume_ratio, 0.65, 1.35, 2.6)
        action_volume_fit = band_score(raw_volume_ratio, 0.9, 1.7, 3.2)
        turnover_fit = band_score(raw_turnover, 2.5, 7.0, 14.0) if raw_turnover > 0 else turnover
        setup_pullback = band_score(raw_drawdown, 0.8, 4.5, 10.5)
        shallow_pullback = band_score(raw_drawdown, 0.0, 2.5, 7.0)
        target_fit = band_score(target_pct, 3.0, 8.0, 18.0)
        stop_quality = clipped(100 - max(stop_risk_pct - 3.5, 0) / 6.5 * 100)
        not_overheated = clipped(100 - max(today_chg - 2.5, 0) / 4.5 * 100)
        anti_score_base = clipped(100 - score_base)
        anti_wyckoff = clipped(100 - wyckoff * 0.75)
        sector_catchup = (100 - sector) * 0.65 + sector * 0.35
        path_stability = pattern * 0.45 + stop_quality * 0.35 + calm_volume_fit * 0.20

        heat_penalty = max(today_chg - 5.0, 0) * 3.0
        stop_penalty = max(stop_risk_pct - 9.0, 0) * 2.0
        volume_penalty = max(raw_volume_ratio - 4.0, 0) * 4.0

        if style == "momentum":
            score = (
                inflow * 0.22
                + turnover_fit * 0.17
                + action_volume_fit * 0.14
                + path_stability * 0.16
                + shallow_pullback * 0.10
                + target_fit * 0.09
                + not_overheated * 0.08
                + anti_score_base * 0.04
            )
        elif style == "weak_momentum":
            score = (
                inflow * 0.23
                + turnover_fit * 0.18
                + setup_pullback * 0.15
                + path_stability * 0.16
                + target_fit * 0.10
                + sector_catchup * 0.08
                + anti_wyckoff * 0.06
                + anti_score_base * 0.04
            )
        else:
            score = (
                inflow * 0.22
                + turnover_fit * 0.20
                + path_stability * 0.18
                + sector_catchup * 0.13
                + setup_pullback * 0.11
                + target_fit * 0.08
                + anti_score_base * 0.05
                + anti_wyckoff * 0.03
            )
        final_score = score - heat_penalty - stop_penalty - volume_penalty

        if factor_profile in ("profile_v4", "profile_v5"):
            is_cautious = macro_mode == "cautious"
            if style == "weak_momentum":
                final_score = final_score * (1.12 if is_cautious else 1.06) + 4.0
            elif style == "momentum":
                final_score = final_score * (0.70 if is_cautious else 0.82) - 8.0
            else:
                final_score = final_score * (0.58 if is_cautious else 0.86) - (12.0 if is_cautious else 4.0)

            if is_cautious and stop_risk_pct > 7.0:
                final_score -= (stop_risk_pct - 7.0) * 2.5
            if style != "weak_momentum" and raw_drawdown > 8.0:
                final_score -= (raw_drawdown - 8.0) * 1.5
            if style != "weak_momentum" and today_chg < -1.0:
                final_score -= abs(today_chg) * 2.0

        if factor_profile == "profile_v5":
            if style == "sideways":
                final_score -= max(45.0 - pattern, 0) * 0.75
                final_score -= max(sector - 55.0, 0) * 0.35
                final_score -= max(drawdown - 88.0, 0) * 0.30
                if macro_mode == "active" and pattern < 45.0 and sector > 50.0:
                    final_score -= 12.0
                if macro_mode == "active" and raw_volume_ratio > 2.8:
                    final_score -= (raw_volume_ratio - 2.8) * 3.0
            elif style == "momentum":
                final_score -= 6.0
            elif style == "weak_momentum":
                final_score += 3.0

        return round(clipped(final_score), 2)

    if style == "momentum":
        score = (
            (100 - score_base) * 0.35
            + (100 - sector) * 0.18
            + (100 - volume) * 0.12
            + (100 - wyckoff) * 0.12
            + pattern * 0.10
            + inflow * 0.08
            + turnover * 0.05
        )
    elif style == "weak_momentum":
        score = (
            sector * 0.25
            + drawdown * 0.20
            + turnover * 0.18
            + inflow * 0.15
            + pattern * 0.10
            + (100 - wyckoff) * 0.07
            + (100 - volume) * 0.05
        )
    else:
        score = (
            inflow * 0.25
            + turnover * 0.22
            + (100 - sector) * 0.16
            + (100 - pattern) * 0.12
            + (100 - counter) * 0.10
            + (100 - wyckoff) * 0.10
            + (100 - volume) * 0.05
        )
    return round(max(0.0, min(score, 100.0)), 2)


def apply_short_profile(
    df: pd.DataFrame,
    factor_profile: str = "original",
    style_gate: str = "none",
    score_order: str = "desc",
    score_col: str = "score",
) -> pd.DataFrame:
    """Rerank and gate short candidates for both backtest and live selection."""
    if df.empty:
        return df.copy()

    factor_profile = normalize_factor_profile(factor_profile)
    style_gate = normalize_style_gate(style_gate)
    out = df.copy()
    active_score_col = score_col if score_col in out.columns else out.columns[0]

    if factor_profile != "original":
        out["original_score"] = out[active_score_col]
        out["experiment_score"] = out.apply(
            lambda row: factor_profile_score(row, factor_profile, active_score_col),
            axis=1,
        )
        active_score_col = "experiment_score"

    out = apply_style_gate(out, style_gate)
    if factor_profile != "original" and not out.empty:
        out["score"] = out["experiment_score"]
    out["factor_profile"] = factor_profile
    out["style_gate"] = style_gate

    return out.sort_values(active_score_col, ascending=(score_order == "asc")).reset_index(drop=True)


def apply_live_short_postprocess(
    df: pd.DataFrame,
    factor_profile: str = "original",
    style_gate: str = "none",
    score_order: str = "desc",
    consensus_profile: str = "none",
    max_rows: int | None = 20,
    score_col: str = "score",
) -> pd.DataFrame:
    """Apply the validated live short-list postprocess, including optional consensus lanes."""
    if df.empty:
        return df.copy()

    consensus_profile = normalize_consensus_profile(consensus_profile)
    if consensus_profile != "none":
        out = build_consensus_candidates(
            df,
            consensus_profile=consensus_profile,
            min_votes=2,
            base_score_col=score_col,
        )
    else:
        out = apply_short_profile(
            df,
            factor_profile=factor_profile,
            style_gate=style_gate,
            score_order=score_order,
            score_col=score_col,
        )

    if max_rows is not None:
        out = out.head(max_rows)
    return out.reset_index(drop=True)


def build_live_observation_candidates(
    df: pd.DataFrame,
    profile: str = "best_balance",
    top_n: int = 2,
    exclude_codes: Iterable[str] | None = None,
    score_col: str = "score",
) -> pd.DataFrame:
    """构建短线观察候选层；该层只用于跟踪，不升级为强推荐。"""
    if df.empty or top_n <= 0:
        return df.iloc[0:0].copy()

    profile = (profile or "none").lower()
    if profile not in {"best_balance"}:
        return df.iloc[0:0].copy()

    key_col = "ts_code" if "ts_code" in df.columns else "code" if "code" in df.columns else None
    excluded = {str(code) for code in (exclude_codes or []) if code}

    lanes: list[pd.DataFrame] = []
    strong_shadow = build_consensus_candidates(
        df,
        consensus_profile="v39",
        min_votes=2,
        base_score_col=score_col,
    )
    if not strong_shadow.empty:
        strong_shadow = strong_shadow.copy()
        strong_shadow["observe_lane"] = "strong_t1_shadow"
        strong_shadow["observe_lane_priority"] = 3
        lanes.append(strong_shadow)

    base = apply_short_profile(
        df,
        factor_profile="profile_v9_sector_quality_guard",
        style_gate="adaptive_quality_v6",
        score_order="desc",
        score_col=score_col,
    )
    if not base.empty:
        market_style = base.get("market_style", pd.Series("", index=base.index)).fillna("").astype(str)
        sector_ma10_ratio = _num_series(base, "sector_ma10_ratio", 0.0)
        factor_sector = _num_series(base, "factor_sector", 0.0)

        expansion_mask = (
            market_style.eq("weak_momentum")
            & (sector_ma10_ratio >= 90.0)
            & (factor_sector >= 30.0)
        )
        readiness_mask = (
            market_style.eq("sideways")
            & (sector_ma10_ratio >= 90.0)
            & (factor_sector >= 35.0)
        )
        for lane_name, priority, mask in (
            ("weak_momentum_breadth", 2, expansion_mask),
            ("sideways_breadth", 1, readiness_mask),
        ):
            lane = base.loc[mask].copy()
            if lane.empty:
                continue
            lane["observe_lane"] = lane_name
            lane["observe_lane_priority"] = priority
            lanes.append(lane)

    if not lanes:
        return df.iloc[0:0].copy()

    out = pd.concat(lanes, ignore_index=True, sort=False)
    if excluded:
        exclude_mask = pd.Series(False, index=out.index)
        for col in ("code", "ts_code"):
            if col in out.columns:
                exclude_mask = exclude_mask | out[col].astype(str).isin(excluded)
        out = out[~exclude_mask].copy()
    if out.empty:
        return out.reset_index(drop=True)

    score = _num_series(out, "experiment_score", 0.0) if "experiment_score" in out.columns else _num_series(out, score_col, 0.0)
    pattern = _num_series(out, "factor_pattern", 50.0)
    sector = _num_series(out, "factor_sector", 50.0)
    inflow = _num_series(out, "factor_inflow", 50.0)
    volume_ratio = _num_series(out, "volume_ratio", 2.0)
    avg_rank = _num_series(out, "consensus_avg_rank", 3.0)
    lane_priority = _num_series(out, "observe_lane_priority", 0.0)
    out["observe_score"] = (
        lane_priority * 100.0
        + score
        + (pattern - 50.0) * 0.25
        + (sector - 50.0) * 0.15
        + (inflow - 50.0) * 0.10
        - (volume_ratio - 2.0).abs() * 2.0
        - avg_rank * 0.5
    ).round(4)
    out["observe_profile"] = profile
    out["recommendation_layer"] = "OBSERVE_CANDIDATE"
    out["observation_version"] = "short_live_observe_best_balance_v1"
    out["observation_action"] = "观察候选，等待盘面确认"
    out["observation_reason"] = out["observe_lane"].map(
        {
            "strong_t1_shadow": "与强信号相邻，保留观察记录",
            "weak_momentum_breadth": "弱动量窗口中板块共振很强",
            "sideways_breadth": "震荡市中板块共振很强",
        }
    ).fillna("短线观察候选")

    if key_col:
        out = out.sort_values("observe_score", ascending=False)
        out = out.drop_duplicates(subset=[key_col], keep="first")

    return out.sort_values("observe_score", ascending=False).head(top_n).reset_index(drop=True)


def _apply_consensus_market_acceptance_guard(df: pd.DataFrame) -> pd.DataFrame:
    """v30 热度承接保护：过滤低涨停热度和中性板块广度窗口。"""
    required = {"limit_up_count", "sector_ma10_ratio"}
    if df.empty or not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    limit_up_count = pd.to_numeric(df["limit_up_count"], errors="coerce")
    sector_ma10_ratio = pd.to_numeric(df["sector_ma10_ratio"], errors="coerce")
    accepted_heat = limit_up_count >= 60
    neutral_breadth = sector_ma10_ratio.between(46, 70, inclusive="both")
    return df[accepted_heat & ~neutral_breadth].copy()


def _apply_consensus_layered_heat_guard(df: pd.DataFrame) -> pd.DataFrame:
    """v31 分层热度门：低热度和过伸硬过滤，中性广度只降权。"""
    required = {"limit_up_count", "sector_ma10_ratio", "change", "consensus_score"}
    if df.empty or not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    out = df.copy()
    limit_up_count = pd.to_numeric(out["limit_up_count"], errors="coerce")
    sector_ma10_ratio = pd.to_numeric(out["sector_ma10_ratio"], errors="coerce")
    change = pd.to_numeric(out["change"], errors="coerce")
    accepted_heat = limit_up_count >= 70
    controlled_extension = change <= 4.5
    out = out[accepted_heat & controlled_extension].copy()
    if out.empty:
        return out

    sector_ma10_ratio = pd.to_numeric(out["sector_ma10_ratio"], errors="coerce")
    neutral_breadth = sector_ma10_ratio.between(46, 70, inclusive="both")
    out.loc[neutral_breadth, "consensus_score"] = pd.to_numeric(
        out.loc[neutral_breadth, "consensus_score"],
        errors="coerce",
    ).fillna(0) - 35.0
    return out


def _apply_consensus_moderate_heat_volume_guard(df: pd.DataFrame) -> pd.DataFrame:
    required = {"limit_up_count", "volume_ratio"}
    if df.empty or not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    accepted_heat = pd.to_numeric(df["limit_up_count"], errors="coerce").fillna(0) >= 50
    controlled_volume = pd.to_numeric(df["volume_ratio"], errors="coerce").fillna(999) <= 2.5
    return df[accepted_heat & controlled_volume].copy()


def _apply_consensus_dual_lane_breadth_guard(df: pd.DataFrame) -> pd.DataFrame:
    required = {"limit_up_count", "limit_down_count", "sector_ma10_ratio", "volume_ratio"}
    if df.empty or not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    limit_up_count = pd.to_numeric(df["limit_up_count"], errors="coerce").fillna(0)
    limit_down_count = pd.to_numeric(df["limit_down_count"], errors="coerce").fillna(999)
    sector_ma10_ratio = pd.to_numeric(df["sector_ma10_ratio"], errors="coerce").fillna(50)
    volume_ratio = pd.to_numeric(df["volume_ratio"], errors="coerce").fillna(999)

    neutral_breadth = sector_ma10_ratio.between(46, 70, inclusive="both")
    defensive_core = (limit_up_count >= 60) & ~neutral_breadth
    selective_mid_lane = (
        neutral_breadth
        & (limit_up_count >= 70)
        & (volume_ratio <= 2.3)
        & ((limit_down_count <= 3) | (limit_down_count >= 20))
    )
    return df[defensive_core | selective_mid_lane].copy()


def _apply_consensus_cautious_down_friction_guard(df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_consensus_dual_lane_breadth_guard(df)
    required = {"macro_mode", "limit_down_count"}
    if out.empty or not required.issubset(out.columns):
        return out

    limit_down_count = pd.to_numeric(out["limit_down_count"], errors="coerce").fillna(999)
    cautious_mode = out["macro_mode"].astype(str).str.lower().eq("cautious")
    mushy_down_friction = cautious_mode & limit_down_count.between(5, 19, inclusive="both")
    return out[~mushy_down_friction].copy()


def _apply_consensus_cautious_high_pattern_exception_guard(df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_consensus_dual_lane_breadth_guard(df)
    required = {"macro_mode", "limit_down_count", "factor_pattern"}
    if out.empty or not required.issubset(out.columns):
        return out

    limit_down_count = pd.to_numeric(out["limit_down_count"], errors="coerce").fillna(999)
    factor_pattern = pd.to_numeric(out["factor_pattern"], errors="coerce").fillna(0)
    cautious_mode = out["macro_mode"].astype(str).str.lower().eq("cautious")
    mushy_down_friction = cautious_mode & limit_down_count.between(5, 19, inclusive="both")
    high_pattern_exception = factor_pattern >= 60
    return out[~mushy_down_friction | high_pattern_exception].copy()


def _apply_consensus_snapshot_top_rule_guard(df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_consensus_cautious_high_pattern_exception_guard(df)
    required = {"limit_up_count", "sector_ma10_ratio", "volume_ratio"}
    if out.empty or not required.issubset(out.columns):
        return out.iloc[0:0].copy()

    limit_up_count = pd.to_numeric(out["limit_up_count"], errors="coerce").fillna(0)
    sector_ma10_ratio = pd.to_numeric(out["sector_ma10_ratio"], errors="coerce").fillna(50)
    volume_ratio = pd.to_numeric(out["volume_ratio"], errors="coerce").fillna(999)
    neutral_breadth = sector_ma10_ratio.between(46, 70, inclusive="both")
    return out[(limit_up_count >= 60) & (volume_ratio <= 2.5) & ~neutral_breadth].copy()


def _apply_consensus_quality_rerank(df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_consensus_cautious_high_pattern_exception_guard(df)
    if out.empty:
        return out

    base = pd.to_numeric(out["consensus_score"], errors="coerce").fillna(0)
    pattern = pd.to_numeric(out.get("factor_pattern", 50.0), errors="coerce").fillna(50)
    sector = pd.to_numeric(out.get("factor_sector", 50.0), errors="coerce").fillna(50)
    volume_ratio = pd.to_numeric(out.get("volume_ratio", 2.0), errors="coerce").fillna(2.0)
    limit_down_count = pd.to_numeric(out.get("limit_down_count", 5.0), errors="coerce").fillna(5.0)

    quality_score = (
        base
        + (pattern - 50.0) * 0.35
        + (50.0 - sector) * 0.25
        - (volume_ratio - 2.0).clip(lower=0.0) * 5.0
        - limit_down_count.clip(lower=0.0, upper=20.0) * 0.18
    )
    out = out.copy()
    out["consensus_score"] = quality_score.round(4)
    return out


def _apply_consensus_rank_protected_quality_rerank(df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_consensus_cautious_high_pattern_exception_guard(df)
    if out.empty:
        return out

    base = pd.to_numeric(out["consensus_score"], errors="coerce").fillna(0)
    avg_rank = pd.to_numeric(out.get("consensus_avg_rank", 3.0), errors="coerce").fillna(3.0)
    pattern = pd.to_numeric(out.get("factor_pattern", 50.0), errors="coerce").fillna(50)
    sector = pd.to_numeric(out.get("factor_sector", 50.0), errors="coerce").fillna(50)
    volume_ratio = pd.to_numeric(out.get("volume_ratio", 2.0), errors="coerce").fillna(2.0)
    limit_down_count = pd.to_numeric(out.get("limit_down_count", 5.0), errors="coerce").fillna(5.0)

    quality_score = (
        base
        - avg_rank * 8.0
        + (pattern - 50.0) * 0.25
        + (50.0 - sector) * 0.12
        - (volume_ratio - 2.0).clip(lower=0.0) * 4.0
        - limit_down_count.clip(lower=0.0, upper=20.0) * 0.12
    )
    out = out.copy()
    out["consensus_score"] = quality_score.round(4)
    return out


def _apply_consensus_strong_rank_guard(df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_consensus_cautious_high_pattern_exception_guard(df)
    if out.empty or "consensus_avg_rank" not in out.columns:
        return out.iloc[0:0].copy()
    avg_rank = pd.to_numeric(out["consensus_avg_rank"], errors="coerce").fillna(999)
    return out[avg_rank <= 1.5].copy()


def _apply_consensus_strong_pattern_breadth_guard(df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_consensus_strong_rank_guard(df)
    required = {"sector_ma10_ratio", "factor_pattern"}
    if out.empty or not required.issubset(out.columns):
        return out.iloc[0:0].copy()

    sector_ma10_ratio = pd.to_numeric(out["sector_ma10_ratio"], errors="coerce").fillna(999)
    factor_pattern = pd.to_numeric(out["factor_pattern"], errors="coerce").fillna(0)
    return out[(sector_ma10_ratio <= 70.0) & (factor_pattern >= 60.0)].copy()


def _apply_consensus_strong_breadth_pattern_rerank(df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_consensus_strong_rank_guard(df)
    required = {"sector_ma10_ratio", "factor_pattern", "consensus_score"}
    if out.empty or not required.issubset(out.columns):
        return out.iloc[0:0].copy()

    sector_ma10_ratio = pd.to_numeric(out["sector_ma10_ratio"], errors="coerce").fillna(999)
    out = out[sector_ma10_ratio <= 70.0].copy()
    if out.empty:
        return out

    base = pd.to_numeric(out["consensus_score"], errors="coerce").fillna(0)
    pattern = pd.to_numeric(out["factor_pattern"], errors="coerce").fillna(50.0)
    breadth = pd.to_numeric(out["sector_ma10_ratio"], errors="coerce").fillna(70.0)
    limit_down_count = pd.to_numeric(out.get("limit_down_count", 5.0), errors="coerce").fillna(5.0)
    out["consensus_score"] = (
        base
        + (pattern - 50.0).clip(lower=-20.0, upper=40.0) * 0.65
        + (70.0 - breadth).clip(lower=0.0, upper=40.0) * 0.25
        - limit_down_count.clip(lower=0.0, upper=20.0) * 0.12
    ).round(4)
    return out


def _apply_consensus_cautious_rank_guard(df: pd.DataFrame) -> pd.DataFrame:
    required = {"consensus_avg_rank", "macro_mode"}
    if df.empty or not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    avg_rank = pd.to_numeric(df["consensus_avg_rank"], errors="coerce").fillna(999)
    cautious = df["macro_mode"].astype(str).str.lower().eq("cautious")
    return df[(avg_rank <= 2.0) & cautious].copy()


def _apply_consensus_pattern_down_guard(df: pd.DataFrame) -> pd.DataFrame:
    required = {"consensus_avg_rank", "factor_pattern", "limit_down_count"}
    if df.empty or not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    avg_rank = pd.to_numeric(df["consensus_avg_rank"], errors="coerce").fillna(999)
    pattern = pd.to_numeric(df["factor_pattern"], errors="coerce").fillna(0)
    limit_down_count = pd.to_numeric(df["limit_down_count"], errors="coerce").fillna(999)
    return df[(avg_rank <= 2.0) & (pattern >= 50.0) & (limit_down_count <= 8.0)].copy()


def _apply_consensus_gap_fill_guard(df: pd.DataFrame) -> pd.DataFrame:
    """v40 gap-fill lane: keep low-MAE consensus candidates without heat overload."""
    required = {
        "consensus_votes",
        "consensus_avg_rank",
        "limit_up_count",
        "limit_down_count",
        "sector_ma10_ratio",
        "volume_ratio",
        "drawdown_from_high",
        "factor_wyckoff",
        "factor_sector",
        "factor_pattern",
        "change",
    }
    if df.empty or not required.issubset(df.columns):
        return df.iloc[0:0].copy()

    out = df.copy()
    votes = pd.to_numeric(out["consensus_votes"], errors="coerce").fillna(0)
    avg_rank = pd.to_numeric(out["consensus_avg_rank"], errors="coerce").fillna(999)
    limit_up_count = pd.to_numeric(out["limit_up_count"], errors="coerce").fillna(0)
    limit_down_count = pd.to_numeric(out["limit_down_count"], errors="coerce").fillna(999)
    sector_ma10_ratio = pd.to_numeric(out["sector_ma10_ratio"], errors="coerce").fillna(50)
    volume_ratio = pd.to_numeric(out["volume_ratio"], errors="coerce").fillna(999)
    drawdown = pd.to_numeric(out["drawdown_from_high"], errors="coerce").fillna(999)
    wyckoff = pd.to_numeric(out["factor_wyckoff"], errors="coerce").fillna(0)
    sector = pd.to_numeric(out["factor_sector"], errors="coerce").fillna(100)
    pattern = pd.to_numeric(out["factor_pattern"], errors="coerce").fillna(0)
    change = pd.to_numeric(out["change"], errors="coerce").fillna(999)
    macro = (
        out["macro_mode"].fillna("").astype(str)
        if "macro_mode" in out.columns
        else pd.Series("", index=out.index)
    )

    low_mae_shape = (
        (votes >= 2)
        & (avg_rank <= 3.0)
        & volume_ratio.between(1.4, 2.8, inclusive="both")
        & drawdown.between(2.0, 7.0, inclusive="both")
        & wyckoff.between(60.0, 75.0, inclusive="both")
        & (change <= 4.5)
    )
    broad_heat_ok = limit_up_count >= 60
    low_friction = limit_down_count <= 12
    not_overheated_breadth = sector_ma10_ratio <= 90.0
    cautious_exception = (
        macro.eq("cautious")
        & (limit_down_count <= 4)
        & (pattern >= 60.0)
    )
    sector_not_overheated = sector <= 60.0
    accepted = low_mae_shape & sector_not_overheated & broad_heat_ok & low_friction & not_overheated_breadth
    accepted = accepted | (low_mae_shape & sector_not_overheated & cautious_exception)
    out = out.loc[accepted].copy()
    if out.empty:
        return out

    wyckoff_fit = (75.0 - pd.to_numeric(out["factor_wyckoff"], errors="coerce").fillna(0)).abs()
    out["gap_fill_score"] = (
        pd.to_numeric(out["consensus_votes"], errors="coerce").fillna(0) * 100.0
        - pd.to_numeric(out["consensus_avg_rank"], errors="coerce").fillna(999) * 8.0
        + (15.0 - wyckoff_fit).clip(lower=0.0)
        + (60.0 - pd.to_numeric(out["factor_sector"], errors="coerce").fillna(100)).clip(lower=0.0) * 0.2
        - (pd.to_numeric(out["volume_ratio"], errors="coerce").fillna(2.0) - 2.0).abs() * 3.0
        - pd.to_numeric(out["limit_down_count"], errors="coerce").fillna(0).clip(lower=0.0, upper=20.0) * 0.3
    ).round(4)
    out["consensus_score"] = out["gap_fill_score"]
    return out


def _build_v40_dual_layer_gap_fill(
    df: pd.DataFrame,
    min_votes: int,
    base_score_col: str,
) -> pd.DataFrame:
    primary = build_consensus_candidates(
        df,
        consensus_profile="v35",
        min_votes=min_votes,
        base_score_col=base_score_col,
    )
    if not primary.empty:
        out = primary.copy()
        out["consensus_profile"] = "v40"
        out["consensus_layer"] = "primary_v35"
        return out

    gap = build_consensus_candidates(
        df,
        consensus_profile="v29",
        min_votes=min_votes,
        base_score_col=base_score_col,
    )
    gap = _apply_consensus_gap_fill_guard(gap)
    if gap.empty:
        return gap
    gap = gap.copy()
    gap["consensus_profile"] = "v40"
    gap["consensus_layer"] = "gap_fill"
    return gap.sort_values(
        ["consensus_votes", "gap_fill_score", "consensus_avg_rank"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def build_consensus_candidates(
    df: pd.DataFrame,
    consensus_profile: str = "v29",
    min_votes: int = 2,
    base_score_col: str = "score",
) -> pd.DataFrame:
    """构建短线研究用共识候选池，至少命中多条历史强策略路线才放行。"""
    consensus_profile = normalize_consensus_profile(consensus_profile)
    if df.empty or consensus_profile == "none":
        return df.copy()

    if consensus_profile == "v40":
        return _build_v40_dual_layer_gap_fill(
            df,
            min_votes=min_votes,
            base_score_col=base_score_col,
        )

    configs = CONSENSUS_PROFILE_CONFIGS.get(consensus_profile, ())
    if not configs:
        return df.copy()

    key_col = "code" if "code" in df.columns else "ts_code" if "ts_code" in df.columns else None
    active_score_col = base_score_col if base_score_col in df.columns else df.columns[0]
    candidates = {}

    for label, factor_profile, style_gate in configs:
        scored = df.copy()
        if "original_score" not in scored.columns:
            scored["original_score"] = scored[active_score_col]
        scored["experiment_score"] = scored.apply(
            lambda row: factor_profile_score(row, factor_profile, active_score_col),
            axis=1,
        )
        gated = apply_style_gate(scored, style_gate).sort_values("experiment_score", ascending=False)
        for rank, (_, row) in enumerate(gated.iterrows(), start=1):
            key = row.get(key_col) if key_col else row.name
            bucket = candidates.setdefault(
                key,
                {
                    "row": row.copy(),
                    "votes": 0,
                    "rank_sum": 0.0,
                    "score_sum": 0.0,
                    "profiles": [],
                },
            )
            bucket["votes"] += 1
            bucket["rank_sum"] += rank
            bucket["score_sum"] += float(row.get("experiment_score", 0) or 0)
            bucket["profiles"].append(label)

    rows = []
    for bucket in candidates.values():
        votes = bucket["votes"]
        if votes < min_votes:
            continue
        row = bucket["row"].copy()
        avg_rank = bucket["rank_sum"] / votes
        avg_score = bucket["score_sum"] / votes
        row["consensus_profile"] = consensus_profile
        row["consensus_votes"] = votes
        row["consensus_avg_rank"] = round(avg_rank, 4)
        row["consensus_avg_score"] = round(avg_score, 4)
        row["consensus_profiles"] = ",".join(bucket["profiles"])
        row["consensus_score"] = round(votes * 100.0 + avg_score - avg_rank * 0.01, 4)
        rows.append(row)

    if not rows:
        empty = df.iloc[0:0].copy()
        for col in (
            "consensus_profile",
            "consensus_votes",
            "consensus_avg_rank",
            "consensus_avg_score",
            "consensus_profiles",
            "consensus_score",
        ):
            empty[col] = pd.Series(dtype="float64" if col != "consensus_profiles" else "object")
        return empty

    out = pd.DataFrame(rows)
    if consensus_profile == "v30":
        out = _apply_consensus_market_acceptance_guard(out)
    elif consensus_profile == "v31":
        out = _apply_consensus_layered_heat_guard(out)
    elif consensus_profile == "v32":
        out = _apply_consensus_moderate_heat_volume_guard(out)
    elif consensus_profile == "v33":
        out = _apply_consensus_dual_lane_breadth_guard(out)
    elif consensus_profile == "v34":
        out = _apply_consensus_cautious_down_friction_guard(out)
    elif consensus_profile == "v35":
        out = _apply_consensus_cautious_high_pattern_exception_guard(out)
    elif consensus_profile == "v36":
        out = _apply_consensus_snapshot_top_rule_guard(out)
    elif consensus_profile == "v37":
        out = _apply_consensus_quality_rerank(out)
    elif consensus_profile == "v38":
        out = _apply_consensus_rank_protected_quality_rerank(out)
    elif consensus_profile == "v39":
        out = _apply_consensus_strong_rank_guard(out)
    elif consensus_profile == "v41":
        out = _apply_consensus_strong_pattern_breadth_guard(out)
    elif consensus_profile == "v42":
        out = _apply_consensus_strong_breadth_pattern_rerank(out)
    elif consensus_profile == "v43":
        out = _apply_consensus_cautious_rank_guard(out)
    elif consensus_profile == "v44":
        out = _apply_consensus_pattern_down_guard(out)

    if consensus_profile in ("v37", "v38", "v42"):
        return out.sort_values("consensus_score", ascending=False).reset_index(drop=True)

    return out.sort_values(
        ["consensus_votes", "consensus_avg_rank", "consensus_avg_score"],
        ascending=[False, True, False],
    ).reset_index(drop=True)


def available_profiles() -> Iterable[str]:
    return VALID_FACTOR_PROFILES


def available_style_gates() -> Iterable[str]:
    return VALID_STYLE_GATES


def available_consensus_profiles() -> Iterable[str]:
    return VALID_CONSENSUS_PROFILES
