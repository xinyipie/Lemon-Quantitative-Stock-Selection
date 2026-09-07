import pandas as pd

from research.quality_momentum_moneyflow_confirm_v11_2019_2025 import apply_confirmation


def test_flow_ratio_confirmation_requires_strictly_positive_value() -> None:
    frame = pd.DataFrame({"flow_ratio_5d": [-0.01, 0.0, 0.01]})
    result = apply_confirmation(frame, "flow_ratio_5d", 0.0)
    assert result["flow_ratio_5d"].tolist() == [0.01]


def test_positive_day_confirmation_uses_inclusive_threshold() -> None:
    frame = pd.DataFrame({"flow_positive_days_5d": [2, 3, 4]})
    result = apply_confirmation(frame, "flow_positive_days_5d", 3)
    assert result["flow_positive_days_5d"].tolist() == [3, 4]
