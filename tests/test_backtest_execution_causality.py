import pandas as pd
import pytest

from backtest_v2 import BacktestV2
from backtest_v2 import BacktestLongterm
from local_data_proxy import PointInTimeDataError


TS_CODE = "000001.SZ"
BUY_DATE = "20250102"


@pytest.mark.parametrize("engine", [BacktestV2, BacktestLongterm])
def test_missing_historical_snapshot_aborts_selection(engine, monkeypatch):
    bt = engine.__new__(engine)
    bt._is_offline = True
    bt.longterm_profile = "test"
    bt.factor_profile = "test"
    bt.short_filter_profile = "test"
    calls = []
    def fail_snapshot(*args, **kwargs):
        calls.append(kwargs)
        raise PointInTimeDataError("缺少历史快照")
    monkeypatch.setattr("backtest_v2.stock_main.run_daily_selection", fail_snapshot)
    with pytest.raises(PointInTimeDataError, match="历史快照"):
        bt._select_stocks_for_date(BUY_DATE)
    assert len(calls) == 1


def make_backtest(*, hold_days=5):
    bt = BacktestV2.__new__(BacktestV2)
    bt.hold_days = hold_days
    bt.fallback_stop_pct = -7.0
    bt.fallback_profit_pct = 50.0
    bt.trailing_stop_pct = 7.0
    bt.trailing_activate_pct = 3.0
    bt.min_open_ratio = 0.0
    bt.short_time_stop = False
    bt.conditional_lock_enabled = False
    return bt


def daily_row(date, open_, high, low, close, pct_chg, *, pre_close=None, **extra):
    row = {
        "ts_code": TS_CODE,
        "trade_date": date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "pct_chg": pct_chg,
    }
    if pre_close is not None:
        row["pre_close"] = pre_close
    row.update(extra)
    return pd.DataFrame([row])


def simulate(bt, rows, *, target_price=150.0):
    dates = list(rows)
    return bt._simulate_trade(
        TS_CODE,
        BUY_DATE,
        dates,
        rows,
        tech_stop_price=93.0,
        tech_target_price=target_price,
        select_close=100.0,
    )


def buy_day(*, open_=100.0, close=100.0, pct_chg=0.0, pre_close=100.0, **extra):
    return daily_row(
        BUY_DATE,
        open_,
        max(open_, close),
        min(open_, close),
        close,
        pct_chg,
        pre_close=pre_close,
        **extra,
    )


def test_close_raised_trailing_stop_only_applies_from_next_session():
    bt = make_backtest()
    rows = {
        BUY_DATE: buy_day(),
        "20250103": daily_row("20250103", 100.0, 109.0, 99.0, 108.0, 8.0, pre_close=100.0),
        "20250106": daily_row("20250106", 108.0, 110.0, 100.0, 101.0, -6.48, pre_close=108.0),
    }

    result = simulate(bt, rows)

    assert result["sell_date"] == "20250106"
    assert result["sell_price"] == 100.44
    assert result["exit_reason"] == "trailing_stop"


def test_gap_below_known_stop_executes_at_open_not_above_daily_high():
    bt = make_backtest()
    rows = {
        BUY_DATE: buy_day(),
        "20250103": daily_row("20250103", 90.0, 92.0, 88.0, 91.0, -9.0, pre_close=100.0),
    }

    result = simulate(bt, rows)

    assert result["sell_price"] == 90.0
    assert result["sell_price"] <= 92.0
    assert result["exit_reason"] == "stop_loss"


def test_locked_limit_down_defers_stop_until_next_executable_open():
    bt = make_backtest()
    rows = {
        BUY_DATE: buy_day(),
        "20250103": daily_row(
            "20250103", 90.0, 90.0, 90.0, 90.0, -10.0, pre_close=100.0, down_limit=90.0
        ),
        "20250106": daily_row("20250106", 85.0, 87.0, 84.0, 86.0, -4.44, pre_close=90.0),
    }

    result = simulate(bt, rows)

    assert result["sell_date"] == "20250106"
    assert result["sell_price"] == 85.0
    assert result["exit_reason"] == "stop_loss_after_limit_down"
    assert result["is_closed"] is True


def test_locked_limit_down_at_horizon_fails_fast_as_unfilled():
    bt = make_backtest()
    rows = {
        BUY_DATE: buy_day(),
        "20250103": daily_row(
            "20250103", 90.0, 90.0, 90.0, 90.0, -10.0, pre_close=100.0, down_limit=90.0
        ),
        "20250106": pd.DataFrame(),
    }

    with pytest.raises(RuntimeError, match="unfilled_limit_down") as exc_info:
        simulate(bt, rows)

    error = exc_info.value
    assert error.ts_code == TS_CODE
    assert error.pending_exit_reason == "stop_loss"
    assert error.pending_since == "20250103"
    assert error.last_price == 90.0


def test_limit_up_take_profit_executes_before_later_limit_down():
    bt = make_backtest()
    rows = {
        BUY_DATE: buy_day(),
        "20250103": daily_row("20250103", 100.0, 110.0, 100.0, 110.0, 10.0, pre_close=100.0),
        "20250106": daily_row(
            "20250106", 99.0, 99.0, 99.0, 99.0, -10.0, pre_close=110.0, down_limit=99.0
        ),
        "20250107": daily_row("20250107", 95.0, 97.0, 94.0, 96.0, -3.03, pre_close=99.0),
    }

    result = simulate(bt, rows, target_price=105.0)

    assert result["sell_date"] == "20250103"
    assert result["sell_price"] == 105.0
    assert result["exit_reason"] == "take_profit"


def test_limit_up_take_profit_does_not_depend_on_future_horizon_data():
    bt = make_backtest()
    rows = {
        BUY_DATE: buy_day(),
        "20250103": daily_row("20250103", 100.0, 110.0, 100.0, 110.0, 10.0, pre_close=100.0),
        "20250106": pd.DataFrame(),
    }

    result = simulate(bt, rows, target_price=105.0)
    assert result["sell_date"] == "20250103"
    assert result["sell_price"] == 105.0
    assert result["exit_reason"] == "take_profit"


def test_suspension_exit_skips_locked_resume_day_until_executable_open():
    bt = make_backtest()
    rows = {
        BUY_DATE: buy_day(),
        "20250103": pd.DataFrame(),
        "20250106": pd.DataFrame(),
        "20250107": daily_row(
            "20250107", 90.0, 90.0, 90.0, 90.0, -10.0, pre_close=100.0, down_limit=90.0
        ),
        "20250108": daily_row("20250108", 85.0, 87.0, 84.0, 86.0, -4.44, pre_close=90.0),
    }

    result = simulate(bt, rows)

    assert result["sell_date"] == "20250108"
    assert result["sell_price"] == 85.0
    assert result["exit_reason"] == "suspended_exit_after_limit_down"


def test_intraday_stop_precedes_same_day_close_based_time_exit():
    bt = make_backtest(hold_days=1)
    rows = {
        BUY_DATE: buy_day(),
        "20250103": daily_row("20250103", 100.0, 101.0, 92.0, 95.0, -5.0, pre_close=100.0),
        "20250106": daily_row("20250106", 95.0, 96.0, 94.0, 95.0, 0.0, pre_close=95.0),
    }

    result = simulate(bt, rows)

    assert result["sell_date"] == "20250103"
    assert result["sell_price"] == 93.0
    assert result["exit_reason"] == "stop_loss"


def test_close_pct_chg_cannot_retroactively_block_an_executable_open():
    bt = make_backtest(hold_days=1)
    rows = {
        BUY_DATE: buy_day(open_=100.0, close=110.0, pct_chg=10.0, pre_close=100.0),
        "20250103": daily_row("20250103", 110.0, 111.0, 109.0, 110.0, 0.0, pre_close=110.0),
    }

    result = simulate(bt, rows)

    assert result is not None
    assert result["buy_price"] == 100.0


def test_open_at_known_limit_price_is_not_assumed_fillable():
    bt = make_backtest(hold_days=1)
    rows = {
        BUY_DATE: buy_day(
            open_=110.0,
            close=105.0,
            pct_chg=5.0,
            pre_close=100.0,
            up_limit=110.0,
        ),
        "20250103": daily_row("20250103", 105.0, 106.0, 104.0, 105.0, 0.0, pre_close=105.0),
    }

    assert simulate(bt, rows) is None


def test_missing_pre_close_does_not_fall_back_to_close_pct_chg_for_entry():
    bt = make_backtest(hold_days=1)
    rows = {
        BUY_DATE: buy_day(open_=100.0, close=110.0, pct_chg=10.0, pre_close=None),
        "20250103": daily_row("20250103", 110.0, 111.0, 109.0, 110.0, 0.0, pre_close=110.0),
    }

    result = simulate(bt, rows)

    assert result is not None
    assert result["buy_price"] == 100.0
