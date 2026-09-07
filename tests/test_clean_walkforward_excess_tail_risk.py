import numpy as np
import pandas as pd

from research.clean_walkforward_excess_tail_risk import class_balanced_weights


def test_class_balanced_weights_give_equal_total_weight():
    labels = pd.Series([0] * 9 + [1])
    weights = class_balanced_weights(labels)
    assert np.isclose(weights[labels.to_numpy() == 0].sum(), weights[labels.to_numpy() == 1].sum())
