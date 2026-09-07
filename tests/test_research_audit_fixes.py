from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.all_market_multi_engine_research import _future_path
from research.audit_clean_financial_relative_candidate import simulate_portfolio
from research.clean_limit_event_family import limit_threshold
from research.clean_shsz_bagged_top_decile_classifier_2019_2024 import (
    RANK_TARGET,
    TOP_DECILE_TARGET,
    add_top_decile_target,
)
from research.full_market_contrarian_candidates import build_candidates
from research.high_confidence_abstention_audit import overlap_adjusted_portfolio
from research.no_future_signal_pipeline import apply_next_open_execution


def _write_daily(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_execution_is_separate_from_label_maturity() -> None:
    locked = pd.DataFrame(
        {"entry_open": [10.0], "entry_gap_pct": [0.0], "ret_5d": [np.nan]}
    )

    result = apply_next_open_execution(locked)

    assert bool(result.loc[0, "executed"]) is True
    assert bool(result.loc[0, "label_matured"]) is False
    assert bool(result.loc[0, "evaluable"]) is False
    assert result.loc[0, "execution_reason"] == "executed"
    assert result.loc[0, "evaluation_reason"] == "insufficient_path"
    assert pd.isna(result.loc[0, "net_ret"])


def test_account_simulator_rejects_explicitly_unexecuted_rows(tmp_path: Path) -> None:
    daily = tmp_path / "daily"
    daily.mkdir()
    for date, close, pct in (
        ("20200101", 10.0, 0.0),
        ("20200102", 10.0, 0.0),
        ("20200103", 11.0, 10.0),
    ):
        _write_daily(
            daily / f"{date}.parquet",
            [{"ts_code": "000001.SZ", "open": 10.0, "close": close, "pct_chg": pct}],
        )
    rejected = pd.DataFrame(
        {
            "trade_date": ["20200101"],
            "ts_code": ["000001.SZ"],
            "executed": [False],
            "entry_open": [np.nan],
            "net_ret": [np.nan],
        }
    )

    result = simulate_portfolio(rejected, cache_dir=tmp_path, slots=1, holding_days=2)

    assert result.empty


def test_account_simulator_delays_exit_until_suspended_stock_has_a_quote(tmp_path: Path) -> None:
    daily = tmp_path / "daily"
    daily.mkdir()
    _write_daily(daily / "20200101.parquet", [{"ts_code": "000001.SZ", "open": 10.0, "close": 10.0, "pct_chg": 0.0}])
    _write_daily(daily / "20200102.parquet", [{"ts_code": "000001.SZ", "open": 10.0, "close": 10.0, "pct_chg": 0.0}])
    _write_daily(daily / "20200103.parquet", [{"ts_code": "000002.SZ", "open": 5.0, "close": 5.0, "pct_chg": 0.0}])
    _write_daily(daily / "20200104.parquet", [{"ts_code": "000001.SZ", "open": 10.0, "close": 10.0, "pct_chg": 0.0}])
    trade = pd.DataFrame(
        {"trade_date": ["20200101"], "ts_code": ["000001.SZ"], "executed": [True]}
    )

    result = simulate_portfolio(trade, cache_dir=tmp_path, slots=1, holding_days=2)

    assert result.iloc[-1]["trade_date"] == "20200104"
    assert int(result.iloc[-1]["positions"]) == 0


def test_overlap_portfolio_keeps_missing_stock_weight_in_denominator(tmp_path: Path) -> None:
    daily = tmp_path / "daily"
    daily.mkdir()
    dates = ["20200101", "20200102", "20200103", "20200104", "20200105", "20200106"]
    _write_daily(daily / f"{dates[0]}.parquet", [{"ts_code": "000001.SZ", "close": 10.0}])
    for index, date in enumerate(dates[1:]):
        close = 11.0
        _write_daily(daily / f"{date}.parquet", [{"ts_code": "000001.SZ", "close": close}])
    trades = pd.DataFrame(
        {
            "trade_date": [dates[0], dates[0]],
            "ts_code": ["000001.SZ", "000002.SZ"],
            "entry_open": [10.0, 10.0],
        }
    )

    result = overlap_adjusted_portfolio(trades, tmp_path, cost=0.0)

    assert result.loc[result["trade_date"].eq("20200102"), "net_ret"].iloc[0] == pytest.approx(1.0)


def test_top_decile_target_preserves_missing_future_rank() -> None:
    result = add_top_decile_target(pd.DataFrame({RANK_TARGET: [np.nan, 0.5, 0.95]}))

    assert pd.isna(result.loc[0, TOP_DECILE_TARGET])
    assert result.loc[1:, TOP_DECILE_TARGET].tolist() == [0, 1]


def test_contrarian_candidate_ranking_does_not_use_next_open_fields() -> None:
    common = {
        "name": "正常股票",
        "industry": "行业",
        "trade_date": "20200102",
        "history_count": 200,
        "pct_chg": 0.0,
        "turnover_rate": 2.0,
        "volume_ratio": 1.0,
        "volatility_20": 2.0,
    }
    panel = pd.DataFrame(
        [
            {
                **common,
                "ts_code": "000001.SZ",
                "tradeable": False,
                "entry_gap_pct": 99.0,
                "drawdown_20": 20.0,
                "ret_5": -10.0,
                "ret_10": -10.0,
                "ret_20": -10.0,
                "ret_60": -10.0,
                "rsi_14": 20.0,
                "industry_rs_20": -10.0,
            },
            {
                **common,
                "ts_code": "000002.SZ",
                "tradeable": True,
                "entry_gap_pct": 0.0,
                "drawdown_20": 1.0,
                "ret_5": 10.0,
                "ret_10": 10.0,
                "ret_20": 10.0,
                "ret_60": 10.0,
                "rsi_14": 80.0,
                "industry_rs_20": 10.0,
            },
        ]
    )

    result = build_candidates(panel, topn=1)

    assert result["ts_code"].tolist() == ["000001.SZ"]


def test_eight_day_excursions_require_all_eight_future_sessions() -> None:
    panel = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 3,
            "trade_date": ["20200101", "20200102", "20200103"],
            "open": [10.0, 10.0, 10.0],
            "high": [10.0, 11.0, 12.0],
            "low": [10.0, 9.0, 8.0],
            "close": [10.0, 10.0, 10.0],
            "log_return": [0.0, 0.0, 0.0],
        }
    )

    result = _future_path(panel.copy(), panel.groupby("ts_code", sort=False))

    assert pd.isna(result.loc[0, "mfe_8d"])
    assert pd.isna(result.loc[0, "mae_8d"])


def test_chinext_limit_threshold_uses_historical_rule_date() -> None:
    assert limit_threshold("300001.SZ", "20200821") == 9.3
    assert limit_threshold("300001.SZ", "20200824") == 18.5
    assert limit_threshold("688001.SH", "20190722") == 18.5


def test_annual_training_purge_uses_actual_label_exit_date_on_sparse_rows() -> None:
    from research.research_integrity import purge_overlapping_label_tail

    frame = pd.DataFrame(
        {
            "trade_date": ["20201101", "20201201", "20201220"],
            "label_exit_date_5d": ["20201109", "20201231", "20210105"],
            "ret_5d": [1.0, 1.0, 1.0],
        }
    )

    result = purge_overlapping_label_tail(
        frame,
        horizon=5,
        prediction_start_date="20210101",
        label_exit_date_column="label_exit_date_5d",
    )

    assert result["trade_date"].tolist() == ["20201101", "20201201"]
    assert result.attrs["purge_boundary"] == "20210101"
    assert result.attrs["purge_basis"] == "label_exit_date_5d"


def test_annual_training_purge_uses_conservative_calendar_gap_without_exit_dates() -> None:
    from research.research_integrity import purge_overlapping_label_tail

    frame = pd.DataFrame(
        {
            "trade_date": ["20201001", "20201201", "20201220", "20201230"],
            "ret_5d": [1.0, 1.0, 1.0, 1.0],
        }
    )

    result = purge_overlapping_label_tail(
        frame,
        horizon=5,
        prediction_start_date="20210101",
        require_label_exit_date=False,
    )

    assert result["trade_date"].tolist() == ["20201001", "20201201"]
    assert result.attrs["purge_basis"] == "conservative_calendar_embargo"
    assert result.attrs["calendar_embargo_days"] == 20
    assert result.attrs["label_boundary_verified"] is False


def test_strict_annual_training_purge_rejects_legacy_rows_without_exit_date() -> None:
    from research.research_integrity import purge_overlapping_label_tail

    frame = pd.DataFrame({"trade_date": ["20201201"], "ret_5d": [1.0]})

    with pytest.raises(ValueError, match="label_exit_date_5d"):
        purge_overlapping_label_tail(
            frame,
            horizon=5,
            prediction_start_date="20210101",
        )


def test_strict_annual_training_purge_rejects_missing_exit_date_in_existing_column() -> None:
    from research.research_integrity import purge_overlapping_label_tail

    frame = pd.DataFrame(
        {
            "trade_date": ["20200101", "20201201"],
            "label_exit_date_5d": ["20200109", pd.NA],
        }
    )

    with pytest.raises(ValueError, match="缺失退出日"):
        purge_overlapping_label_tail(
            frame,
            horizon=5,
            prediction_start_date="20210101",
        )


def test_annual_training_purge_parses_integer_yyyymmdd_dates() -> None:
    from research.research_integrity import purge_overlapping_label_tail

    frame = pd.DataFrame(
        {
            "trade_date": [20201201, 20201220],
            "label_exit_date_5d": [20201209, 20210105],
        }
    )

    result = purge_overlapping_label_tail(
        frame,
        horizon=5,
        prediction_start_date=20210101,
    )

    assert result["trade_date"].tolist() == [20201201]
    assert result.attrs["purge_boundary"] == "20210101"


def test_technical_training_sampler_applies_five_day_tail_purge() -> None:
    from research.clean_walkforward_technical_hgb import FEATURES, TARGET, sample_training_rows

    dates = ["20201001", "20201201", "20201220", "20201230"]
    frame = pd.DataFrame(
        {
            "year": 2020,
            "trade_date": dates,
            "label_exit_date_5d": ["20201009", "20201209", "20210105", "20210110"],
            TARGET: 1.0,
        }
    )
    for feature in FEATURES:
        frame[feature] = 0.0

    result = sample_training_rows(frame, (2020,), prediction_start_date="20210101")

    assert result["trade_date"].tolist() == dates[:2]


def test_signal_day_tradeable_does_not_depend_on_next_open() -> None:
    from research.all_market_multi_engine_research import _signal_day_tradeable

    panel = pd.DataFrame(
        {
            "name": ["正常股票"],
            "history_count": [120],
            "turnover_rate": [1.0],
            "close": [10.0],
            "entry_open": [np.nan],
            "entry_gap_pct": [np.nan],
        }
    )

    assert bool(_signal_day_tradeable(panel).iloc[0]) is True


def test_linear_ranker_loader_does_not_drop_future_untradeable_row(tmp_path: Path) -> None:
    from research.walkforward_linear_ranker import load_candidates

    path = tmp_path / "candidates.csv"
    pd.DataFrame(
        {
            "trade_date": ["20200102", "20200102"],
            "ts_code": ["000001.SZ", "000002.SZ"],
            "engine": ["pullback", "pullback"],
            "engine_rank": [1, 2],
            "tradeable": [False, True],
        }
    ).to_csv(path, index=False, encoding="utf-8-sig")

    result = load_candidates(path)

    assert result["ts_code"].tolist() == ["000001.SZ", "000002.SZ"]


def test_broad_rank_prediction_universe_retains_unmatured_labels() -> None:
    from research.clean_broad_cross_sectional_rank import BASE_COLUMNS, prepare_year

    rows = []
    for code, outcome in (("000001.SZ", np.nan), ("000002.SZ", 1.0)):
        row = {column: 1.0 for column in BASE_COLUMNS}
        row.update(
            {
                "ts_code": code,
                "name": "正常股票",
                "industry": "行业",
                "trade_date": "20200102",
                "regime": "BULL_TREND",
                "ret_5d": outcome,
                "history_count": 120,
                "close": 10.0,
                "amount": 1000.0,
                "turnover_rate": 1.0,
                "volume_ratio": 1.0,
                "ma_20": 10.0,
                "ma_60": 10.0,
            }
        )
        rows.append(row)

    result = prepare_year(pd.DataFrame(rows))

    assert result["ts_code"].tolist() == ["000001.SZ", "000002.SZ"]
    assert pd.isna(result.loc[result["ts_code"].eq("000001.SZ"), "target_rank_5d"]).all()


def test_observable_topn_uses_code_not_future_return_to_break_ties() -> None:
    from research.research_integrity import lock_observable_topn

    candidates = pd.DataFrame(
        {
            "select_date": ["20200102", "20200102"],
            "ts_code": ["A", "B"],
            "score": [50.0, 50.0],
            "ret": [-5.0, 5.0],
        }
    )

    result = lock_observable_topn(candidates, "select_date", "score", topn=1)

    assert result["ts_code"].tolist() == ["A"]


def test_static_financial_snapshot_fails_strict_point_in_time_validation() -> None:
    from research.point_in_time_financials import prepare_financial_events

    static = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "ann_date": ["20200101"],
            "end_date": ["20191231"],
            "roe": [10.0],
            "debt_to_assets": [40.0],
            "netprofit_yoy": [5.0],
        }
    )

    with pytest.raises(ValueError, match="严格点时验证"):
        prepare_financial_events(static, require_versioned_history=True)


def test_static_security_master_fails_strict_historical_panel_validation(tmp_path: Path) -> None:
    from research.all_market_multi_engine_research import _load_stock_info

    pd.DataFrame(
        {"ts_code": ["000001.SZ"], "name": ["当前名称"], "industry": ["当前行业"]}
    ).to_parquet(tmp_path / "stock_basic.parquet", index=False)

    with pytest.raises(ValueError, match="历史证券主数据"):
        _load_stock_info(tmp_path)


def test_evidence_qualification_never_marks_blocked_research_ready() -> None:
    from research.research_integrity import evidence_qualification

    result = evidence_qualification(
        "same_sample_search",
        blockers=["same_sample_optimization", "consumed_holdout"],
    )

    assert result == {
        "research_id": "same_sample_search",
        "evidence_tier": "exploratory",
        "strict_oos_eligible": False,
        "deployment_ready": False,
        "evidence_blockers": ["consumed_holdout", "same_sample_optimization"],
    }


def test_same_sample_optimizer_registry_is_machine_readable_and_not_ready() -> None:
    from research.research_evidence_registry import qualification_for_script

    result = qualification_for_script("live_readiness_optimizer.py")

    assert result["strict_oos_eligible"] is False
    assert result["deployment_ready"] is False
    assert "same_sample_optimization" in result["evidence_blockers"]


@pytest.mark.parametrize(
    ("script", "expected_blocker"),
    [
        (
            "clean_walkforward_technical_hgb_holdout_calibrated.py",
            "calibration_holdout_not_final_oos",
        ),
        ("quality_momentum_reentry_sealed_2025.py", "consumed_holdout"),
        ("clean_financial_aligned5_sealed_2025.py", "consumed_holdout"),
    ],
)
def test_holdout_and_sealed_evidence_is_never_marked_strict_oos(
    script: str,
    expected_blocker: str,
) -> None:
    from research.research_evidence_registry import qualification_for_script

    result = qualification_for_script(script)

    assert result["strict_oos_eligible"] is False
    assert result["deployment_ready"] is False
    assert expected_blocker in result["evidence_blockers"]


def test_candidate_simulator_uses_retrospective_not_holdout_for_early_period() -> None:
    from research.strategy_candidate_simulator import _phase_for_date

    assert _phase_for_date("20240301") == "retrospective_2024H1"
    assert _phase_for_date("20241001") == "development_2024H2_2025H1"
