import pandas as pd

import main as stock_main


def test_merge_longterm_financial_data_fetches_only_missing_codes(monkeypatch):
    stocks = pd.DataFrame({"code": ["000001", "000002", "000003"]})
    existing = {"000001": {"roe": 12.0}}
    calls = []

    def fake_get_financial_data_batch(codes, trade_date=""):
        calls.append((list(codes), trade_date))
        return {
            "000002": {"roe": 8.0},
            "000003": {"roe": 9.0},
        }

    monkeypatch.setattr(
        stock_main,
        "get_financial_data_batch",
        fake_get_financial_data_batch,
    )

    result = stock_main._merge_longterm_financial_data(
        stocks,
        existing,
        "20250115",
    )

    assert calls == [(["000002", "000003"], "20250115")]
    assert result == {
        "000001": {"roe": 12.0},
        "000002": {"roe": 8.0},
        "000003": {"roe": 9.0},
    }


def test_merge_longterm_financial_data_skips_fetch_when_coverage_is_complete(monkeypatch):
    stocks = pd.DataFrame({"code": ["000001", "000002"]})
    existing = {
        "000001": {"roe": 12.0},
        "000002": {"roe": 8.0},
    }

    def unexpected_fetch(*args, **kwargs):
        raise AssertionError("覆盖完整时不应重复请求财务数据")

    monkeypatch.setattr(stock_main, "get_financial_data_batch", unexpected_fetch)

    result = stock_main._merge_longterm_financial_data(
        stocks,
        existing,
        "20250115",
    )

    assert result == existing
