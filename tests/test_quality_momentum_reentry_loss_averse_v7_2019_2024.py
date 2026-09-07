import pandas as pd

from research.quality_momentum_reentry_loss_averse_v7_2019_2024 import (
    loss_averse_utility,
)


def test_loss_averse_utility_doubles_negative_outcome_at_base_penalty() -> None:
    values = pd.Series([5.0, 0.0, -3.0])

    result = loss_averse_utility(values, penalty=1.0)

    assert result.tolist() == [5.0, 0.0, -6.0]
