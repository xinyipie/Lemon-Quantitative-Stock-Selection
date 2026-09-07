import pandas as pd

from research.clean_shsz_bagged_cross_section_rank_2019_2024 import (
    RANK_TARGET,
    add_cross_section_rank_target,
)


def test_rank_target_is_daily_and_excludes_north_exchange() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": ["20240102", "20240102", "20240102", "20240103"],
            "ts_code": ["A.SH", "B.SZ", "C.BJ", "D.SH"],
            "ret_5d": [1.0, 3.0, 100.0, -2.0],
        }
    )

    result = add_cross_section_rank_target(frame)

    assert result["ts_code"].tolist() == ["A.SH", "B.SZ", "D.SH"]
    assert result.loc[result["trade_date"] == "20240102", RANK_TARGET].tolist() == [0.5, 1.0]
    assert result.loc[result["trade_date"] == "20240103", RANK_TARGET].tolist() == [1.0]
