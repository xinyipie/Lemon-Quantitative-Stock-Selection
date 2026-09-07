import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.evaluate_locked_candidate_new_holdout import completed_holdout  # noqa: E402


def test_completed_holdout_requires_start_date_and_realized_return() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20260630", "20260701", "20260702"],
            "ret_5d": [1.0, 2.0, None],
        }
    )
    result = completed_holdout(frame, "20260701")
    assert result["trade_date"].tolist() == ["20260701"]

