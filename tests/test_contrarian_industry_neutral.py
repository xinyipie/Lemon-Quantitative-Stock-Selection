import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_industry_neutral import build_industry_neutral_candidates  # noqa: E402


def test_build_industry_neutral_candidates_keeps_one_stock_per_industry_day():
    frame = pd.DataFrame(
        {
            "trade_date": ["20220103"] * 4,
            "ts_code": ["A", "B", "C", "D"],
            "industry": ["电子", "电子", "银行", None],
            "contrarian_score": [80.0, 70.0, 60.0, 50.0],
        }
    )
    result = build_industry_neutral_candidates(frame)
    assert result["ts_code"].tolist() == ["A", "C", "D"]
    assert result.groupby(["trade_date", "industry_bucket"]).size().max() == 1

