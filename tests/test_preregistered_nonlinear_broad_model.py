import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.preregistered_nonlinear_broad_model import (  # noqa: E402
    FEATURE_COLUMNS,
    FORBIDDEN_COLUMNS,
    build_broad_candidates,
    confidence_topn,
)


def test_model_features_have_no_future_columns() -> None:
    assert FORBIDDEN_COLUMNS.isdisjoint(FEATURE_COLUMNS)


def test_broad_pool_caps_industry_and_day() -> None:
    rows = []
    for index in range(20):
        rows.append(
            {
                "trade_date": "20200102",
                "ts_code": f"{index:06d}.SZ",
                "industry": "电子" if index < 10 else "银行",
                "tradeable": True,
                "history_count": 200,
                "pct_chg": 1.0,
                "turnover_rate": 2.0,
                "volume_ratio": 1.0,
                "entry_gap_pct": 0.0,
                "amount": 1000.0 - index,
            }
        )
    result = build_broad_candidates(pd.DataFrame(rows), topn=120, per_industry=4)
    assert result.groupby(["trade_date", "industry_bucket"]).size().max() == 4
    assert len(result) == 8


def test_confidence_topn_uses_cross_sectional_spread() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20200102"] * 4,
            "ts_code": ["A", "B", "C", "D"],
            "prediction": [4.0, 3.0, 1.0, 0.0],
        }
    )
    result = confidence_topn(frame, topn=2)
    assert result["ts_code"].tolist() == ["A", "B"]
    assert result["confidence"].iloc[0] > 0

