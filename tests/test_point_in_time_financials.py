from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.point_in_time_financials import merge_point_in_time, prepare_financial_events  # noqa: E402


def test_merge_never_uses_future_announcement_and_advances_report():
    financial = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "ann_date": "20230420", "end_date": "20230331", "roe": 9, "debt_to_assets": 60, "netprofit_yoy": 20},
            {"ts_code": "000001.SZ", "ann_date": "20230820", "end_date": "20230630", "roe": 10, "debt_to_assets": 58, "netprofit_yoy": 30},
        ]
    )
    panel = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20230419", "close": 10},
            {"ts_code": "000001.SZ", "trade_date": "20230421", "close": 11},
            {"ts_code": "000001.SZ", "trade_date": "20230821", "close": 12},
        ]
    )
    result = merge_point_in_time(panel, prepare_financial_events(financial))
    assert pd.isna(result.iloc[0]["ann_date"])
    assert result.iloc[1]["end_date"] == "20230331"
    assert result.iloc[2]["end_date"] == "20230630"
    assert (result.dropna(subset=["ann_date"])["ann_date"] <= result.dropna(subset=["ann_date"])["trade_date"]).all()


def test_late_old_report_does_not_replace_newer_report():
    financial = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "ann_date": "20230420", "end_date": "20230331", "roe": 9, "debt_to_assets": 60, "netprofit_yoy": 20},
            {"ts_code": "000001.SZ", "ann_date": "20230820", "end_date": "20230630", "roe": 10, "debt_to_assets": 58, "netprofit_yoy": 30},
            {"ts_code": "000001.SZ", "ann_date": "20230901", "end_date": "20221231", "roe": 8, "debt_to_assets": 61, "netprofit_yoy": 5},
        ]
    )
    events = prepare_financial_events(financial)
    assert "20221231" not in events["end_date"].tolist()

