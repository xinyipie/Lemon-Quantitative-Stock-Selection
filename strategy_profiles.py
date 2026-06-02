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
    "industry",
]

VALID_FACTOR_PROFILES = (
    "original",
    "diagnostic_v1",
    "profile_v2",
    "profile_v3",
    "profile_v4",
    "profile_v5",
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
)


def normalize_factor_profile(factor_profile: str) -> str:
    return factor_profile if factor_profile in VALID_FACTOR_PROFILES else "original"


def normalize_style_gate(style_gate: str) -> str:
    return style_gate if style_gate in VALID_STYLE_GATES else "none"


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
    elif style_gate in ("adaptive_quality", "adaptive_quality_v2", "adaptive_quality_v5"):
        pattern = _num_series(df, "factor_pattern", 50.0)
        sector = _num_series(df, "factor_sector", 50.0)
        drawdown_score = _num_series(df, "factor_drawdown", 50.0)
        raw_drawdown = _num_series(df, "drawdown_from_high", 0.0)
        raw_volume_ratio = _num_series(df, "volume_ratio", 1.0)
        score = _num_series(df, "experiment_score", _num_series(df, "score", _num_series(df, "score_base", 0.0)))

        low_quality_sideways = (
            (pattern < 45.0)
            | ((pattern < 50.0) & (sector > 50.0))
            | ((raw_drawdown > 8.0) & (sector > 50.0))
            | ((raw_drawdown > 9.0) & (pattern < 55.0))
            | ((raw_volume_ratio > 3.2) & (pattern < 55.0))
        )
        quality_sideways = (style == "sideways") & (macro == "active") & ~low_quality_sideways
        mask = (style == "weak_momentum") | quality_sideways

        if style_gate in ("adaptive_quality_v2", "adaptive_quality_v5"):
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


def available_profiles() -> Iterable[str]:
    return VALID_FACTOR_PROFILES


def available_style_gates() -> Iterable[str]:
    return VALID_STYLE_GATES
