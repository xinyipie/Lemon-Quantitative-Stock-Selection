"""袋装保守预测下界口径测试。"""

import numpy as np

from research.clean_walkforward_excess_bagged_lcb import conservative_score


def test_conservative_score_penalizes_member_disagreement() -> None:
    low_disagreement = [np.array([1.0]), np.array([1.0]), np.array([1.0])]
    high_disagreement = [np.array([0.0]), np.array([1.0]), np.array([2.0])]
    _, low_std, low_score = conservative_score(low_disagreement)
    mean, high_std, high_score = conservative_score(high_disagreement)
    assert mean[0] == 1.0
    assert low_std[0] == 0.0
    assert high_std[0] > low_std[0]
    assert high_score[0] < low_score[0]
