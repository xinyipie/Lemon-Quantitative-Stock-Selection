import pandas as pd

from research.clean_walkforward_technical_hgb_daily_top3_account import account_metrics


def test_account_metrics_detects_drawdown_and_positive_year():
    curve = pd.DataFrame(
        {
            "trade_date": ["20190102", "20190103", "20190104"],
            "nav": [1.01, 0.99, 1.10],
            "cash": [0.5, 0.5, 1.1],
            "positions": [2, 2, 0],
        }
    )
    metrics = account_metrics(curve)
    assert metrics["max_drawdown_pct"] < 0
    assert metrics["yearly_returns_pct"]["2019"] > 0
    assert metrics["maximum_positions"] == 2
