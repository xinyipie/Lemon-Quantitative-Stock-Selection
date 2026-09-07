import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.all_market_opportunity_archetypes import (
    apply_acceptance,
    assign_feature_bins,
    build_case_control_sample,
    evaluate_profile,
)


def _sample_panel() -> pd.DataFrame:
    rows = []
    for date in ("20250102", "20250103"):
        for index in range(8):
            rows.append(
                {
                    "trade_date": date,
                    "ts_code": f"00000{index}.SZ",
                    "tradeable": True,
                    "top20_opportunity": index < 2,
                    "regime": "BULL_TREND" if index < 4 else "BEAR_TREND",
                    "ret_5": -12 + index * 4,
                    "ret_10": -18 + index * 6,
                    "ret_20": -25 + index * 10,
                    "ret_60": -30 + index * 15,
                    "drawdown_20": index * 5,
                    "pct_chg": -7 + index * 2,
                    "rsi_14": 20 + index * 10,
                    "turnover_rate": 0.5 + index * 3,
                    "volume_ratio": 0.4 + index * 0.5,
                    "volatility_20": 1 + index,
                    "industry_rs_20": -20 + index * 7,
                    "ret_3d": -3 + index,
                    "ret_5d": -2 + index,
                    "ret_8d": -1 + index,
                    "mfe_8d": 2 + index,
                    "mae_8d": -8 + index,
                }
            )
    return pd.DataFrame(rows)


def test_assign_feature_bins_places_boundaries_once():
    result = assign_feature_bins(_sample_panel())

    expected = {
        "regime_bin",
        "ret_5_bin",
        "ret_10_bin",
        "ret_20_bin",
        "ret_60_bin",
        "drawdown_20_bin",
        "pct_chg_bin",
        "rsi_14_bin",
        "turnover_rate_bin",
        "volume_ratio_bin",
        "volatility_20_bin",
        "industry_rs_20_bin",
    }
    assert expected.issubset(result.columns)
    assert result[list(expected)].notna().all().all()


def test_case_control_sample_keeps_cases_and_is_future_return_independent():
    panel = _sample_panel()
    first = build_case_control_sample(panel, controls_per_day=3)
    changed = panel.copy()
    changed[["ret_3d", "ret_5d", "ret_8d"]] *= -100
    second = build_case_control_sample(changed, controls_per_day=3)

    assert int(first["top20_opportunity"].sum()) == 4
    controls = first[~first["top20_opportunity"]]
    assert controls.groupby("trade_date").size().le(3).all()
    first_keys = set(first.loc[~first["top20_opportunity"], ["trade_date", "ts_code"]].itertuples(index=False, name=None))
    second_keys = set(second.loc[~second["top20_opportunity"], ["trade_date", "ts_code"]].itertuples(index=False, name=None))
    assert first_keys == second_keys


def test_evaluate_profile_uses_case_control_baseline_and_real_returns():
    sample = _sample_panel()
    mask = sample["regime"].eq("BULL_TREND")

    metrics = evaluate_profile(sample, mask)

    assert metrics["support"] == 8
    assert metrics["opportunities"] == 4
    assert metrics["opportunity_rate"] == 0.5
    assert metrics["baseline_rate"] == 0.25
    assert metrics["lift"] == 2.0
    assert metrics["coverage"] == 1.0
    assert metrics["active_days"] == 2
    assert metrics["avg_ret_5d"] == -0.5
    assert metrics["win_5d"] == 0.25


def test_acceptance_requires_every_split_to_pass():
    rows = []
    for split, support, hits in (("train", 700, 70), ("validation", 350, 40), ("sealed", 180, 20)):
        rows.append(
            {
                "profile_id": "profile_a",
                "split": split,
                "support": support,
                "opportunities": hits,
                "lift": 1.35,
                "coverage": 0.01,
                "avg_ret_5d": 0.5,
            }
        )
    passed = apply_acceptance(pd.DataFrame(rows))
    assert bool(passed.iloc[0]["research_pass"])

    rows[-1]["lift"] = 1.1
    failed = apply_acceptance(pd.DataFrame(rows))
    assert not bool(failed.iloc[0]["research_pass"])
    assert "sealed_lift" in failed.iloc[0]["failure_reasons"]
