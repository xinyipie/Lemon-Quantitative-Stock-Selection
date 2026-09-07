"""袋装预测聚合口径测试。"""

import numpy as np

from research.clean_walkforward_excess_bagged3 import SEEDS, average_predictions


def test_three_fixed_seeds_are_registered() -> None:
    assert SEEDS == (20260808, 20260809, 20260810)


def test_predictions_use_simple_arithmetic_mean() -> None:
    result = average_predictions([np.array([1.0, 2.0]), np.array([2.0, 4.0]), np.array([3.0, 6.0])])
    np.testing.assert_allclose(result, np.array([2.0, 4.0]))
