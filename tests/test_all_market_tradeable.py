from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.all_market_multi_engine_research import _signal_day_tradeable


def _base_rows():
    return pd.DataFrame(
        {
            "name": ["样本甲", "样本乙"],
            "history_count": [120, 120],
            "close": [10.0, 10.0],
            "entry_open": [10.0, 10.0],
            "entry_gap_pct": [1.0, 1.0],
            "turnover_rate": [3.0, 3.0],
            "ret_8d": [8.0, np.nan],
        }
    )


def test_future_outcome_availability_does_not_change_signal_day_tradeability():
    mask = _signal_day_tradeable(_base_rows())

    assert mask.tolist() == [True, True]


def test_signal_day_tradeability_rejects_only_known_untradeable_conditions():
    frame = pd.DataFrame(
        {
            "name": ["ST样本", "退市样本", "历史不足", "无次日开盘", "次日涨停", "换手缺失"],
            "history_count": [120, 120, 59, 120, 120, 120],
            "close": [10.0] * 6,
            "entry_open": [10.0, 10.0, 10.0, 0.0, 10.0, 10.0],
            "entry_gap_pct": [1.0, 1.0, 1.0, 1.0, 9.5, 1.0],
            "turnover_rate": [3.0, 3.0, 3.0, 3.0, 3.0, np.nan],
            "ret_8d": [np.nan] * 6,
        }
    )

    assert _signal_day_tradeable(frame).tolist() == [False, False, False, True, True, False]
