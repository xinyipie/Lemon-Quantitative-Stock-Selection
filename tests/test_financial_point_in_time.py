import pandas as pd
import pytest

import main as stock_main


def test_filter_announced_rows_rejects_missing_announcement_column():
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "end_date": ["20241231"],
            "roe": [12.0],
        }
    )

    with pytest.raises(stock_main.FinancialDataQualityError, match="ann_date"):
        stock_main._filter_announced_rows(df, "20250115", "fina_indicator")


def test_filter_announced_rows_keeps_only_valid_known_announcements():
    df = pd.DataFrame(
        {
            "row_id": ["past", "same_day", "future", "none", "text"],
            "ann_date": ["20250101", "20250115", "20250116", None, "None"],
        }
    )

    result = stock_main._filter_announced_rows(
        df,
        "20250115",
        "fina_indicator",
    )

    assert result["row_id"].tolist() == ["past", "same_day"]


def test_filter_announced_rows_without_historical_cutoff_keeps_input():
    df = pd.DataFrame({"row_id": ["latest"], "value": [1]})

    result = stock_main._filter_announced_rows(df, "", "fina_indicator")

    pd.testing.assert_frame_equal(result, df)
