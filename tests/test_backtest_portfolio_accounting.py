import pandas as pd

from backtest_v2 import BacktestV2


def make_backtest(max_positions=2):
    bt = BacktestV2.__new__(BacktestV2)
    bt.max_positions = max_positions
    bt.top_n = max_positions
    bt.all_trade_dates = ["20250102", "20250103", "20250104"]
    return bt


def test_short_portfolio_rejects_new_buys_when_cross_day_slots_are_full():
    bt = make_backtest(max_positions=2)
    existing = [
        {
            "ts_code": "000001.SZ",
            "buy_date": "20250102",
            "sell_date": "20250104",
            "portfolio_slot": 0,
        },
        {
            "ts_code": "000002.SZ",
            "buy_date": "20250102",
            "sell_date": "20250104",
            "portfolio_slot": 1,
        },
    ]

    allowed = bt._filter_selected_items_for_portfolio(
        [{"ts_code": "000003.SZ"}],
        existing,
        "20250103",
    )

    assert allowed == []


def test_short_portfolio_rejects_duplicate_and_assigns_free_slot():
    bt = make_backtest(max_positions=2)
    existing = [
        {
            "ts_code": "000001.SZ",
            "buy_date": "20250102",
            "sell_date": "20250104",
            "portfolio_slot": 0,
        }
    ]

    allowed = bt._filter_selected_items_for_portfolio(
        [
            {"ts_code": "000001.SZ"},
            {"ts_code": "000003.SZ"},
        ],
        existing,
        "20250103",
    )

    assert allowed == [{"ts_code": "000003.SZ", "portfolio_slot": 1}]


def test_mark_to_market_equity_reflects_unrealized_drawdown_before_exit():
    bt = make_backtest(max_positions=1)
    trades = [
        {
            "ts_code": "000001.SZ",
            "buy_date": "20250102",
            "buy_price": 100.0,
            "sell_date": "20250104",
            "sell_price": 100.0,
            "profit_after_fee": -0.43,
            "portfolio_slot": 0,
        }
    ]
    price_cache = {
        "20250102": pd.DataFrame(
            [{"ts_code": "000001.SZ", "close": 100.0}]
        ),
        "20250103": pd.DataFrame(
            [{"ts_code": "000001.SZ", "close": 80.0}]
        ),
        "20250104": pd.DataFrame(
            [{"ts_code": "000001.SZ", "close": 100.0}]
        ),
    }

    equity = bt._build_mark_to_market_equity(trades, price_cache)
    nav_by_date = equity.set_index("date")["nav"].to_dict()

    assert nav_by_date["20250103"] < 85.0
    assert nav_by_date["20250104"] == 99.57
