"""每日截面排名特征的无跨日污染测试。"""

import pandas as pd

from research.clean_walkforward_cross_section_rank_hgb import (
    FEATURES,
    RANK_FEATURES,
    add_cross_section_ranks,
)


def test_feature_ranks_are_calculated_within_trade_date() -> None:
    rows = []
    for date, values in [("20200102", [1.0, 2.0]), ("20200103", [100.0, 200.0])]:
        for value in values:
            row = {column: value for column in FEATURES}
            row.update({"trade_date": date, "ret_5d": value})
            rows.append(row)
    result = add_cross_section_ranks(pd.DataFrame(rows))
    first_rank = RANK_FEATURES[0]
    assert result.groupby("trade_date")[first_rank].min().tolist() == [0.0, 0.0]
    assert result.groupby("trade_date")[first_rank].max().tolist() == [0.5, 0.5]


def test_future_target_change_does_not_change_feature_ranks() -> None:
    frame = pd.DataFrame(
        [
            {**{column: 1.0 for column in FEATURES}, "trade_date": "20200102", "ret_5d": 1.0},
            {**{column: 2.0 for column in FEATURES}, "trade_date": "20200102", "ret_5d": 2.0},
        ]
    )
    before = add_cross_section_ranks(frame)[RANK_FEATURES]
    frame["ret_5d"] = [20.0, -20.0]
    after = add_cross_section_ranks(frame)[RANK_FEATURES]
    pd.testing.assert_frame_equal(before, after)
