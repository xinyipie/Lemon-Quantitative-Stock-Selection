import pandas as pd

from research.clean_walkforward_technical_hgb_excess_target import EXCESS_TARGET, add_excess_target


def test_common_market_shift_cancels_from_excess_target():
    frame = pd.DataFrame(
        {
            "trade_date": ["20200101", "20200101", "20200102", "20200102"],
            "ret_5d": [1.0, 3.0, -2.0, 2.0],
        }
    )
    shifted = frame.copy()
    shifted["ret_5d"] = shifted["ret_5d"] + 10.0
    assert add_excess_target(frame)[EXCESS_TARGET].equals(add_excess_target(shifted)[EXCESS_TARGET])
