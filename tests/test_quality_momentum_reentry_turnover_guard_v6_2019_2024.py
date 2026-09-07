import pandas as pd

from research.quality_momentum_reentry_turnover_guard_v6_2019_2024 import (
    apply_turnover_guard,
)


def test_turnover_guard_keeps_only_lower_half_of_daily_candidate_rank() -> None:
    trades = pd.DataFrame(
        {
            "ts_code": ["A.SH", "B.SZ", "C.SH"],
            "rank_turnover_rate": [0.10, 0.50, 0.51],
        }
    )

    result = apply_turnover_guard(trades, maximum_rank=0.50)

    assert result["ts_code"].tolist() == ["A.SH", "B.SZ"]
