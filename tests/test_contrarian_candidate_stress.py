import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_candidate_stress import (
    annual_path_metrics,
    candidate_passes_period_gate,
    max_drawdown,
)


def test_max_drawdown_uses_compounded_path():
    returns = pd.Series([10.0, -20.0, 5.0])
    assert round(max_drawdown(returns), 4) == -20.0


def test_annual_path_metrics_reports_each_year():
    path = pd.DataFrame(
        {
            "trade_date": ["20220103", "20220104", "20230103"],
            "net_ret": [1.0, -0.5, 2.0],
        }
    )
    result = annual_path_metrics(path)
    assert result["year"].tolist() == [2022, 2023]
    assert result.loc[result["year"].eq(2022), "return_pct"].iloc[0] > 0


def test_period_gate_requires_every_year_positive():
    good = {
        "avg_net": 1.0,
        "profit_factor": 1.3,
        "positive_years": 3,
        "years": 3,
        "trades": 120,
    }
    bad = {**good, "positive_years": 2}
    assert candidate_passes_period_gate(good, minimum_trades=100)
    assert not candidate_passes_period_gate(bad, minimum_trades=100)
