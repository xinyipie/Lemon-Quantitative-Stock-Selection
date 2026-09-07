import pandas as pd

from research.defensive_quality_reentry_v16_2019_2026 import apply_defensive_boundary


def test_boundary_excludes_bull_trend_and_requires_positive_flow() -> None:
    frame = pd.DataFrame(
        {
            "regime": ["BULL_TREND", "BEAR_BOUNCE", "BEAR_TREND", "BULL_PULLBACK"],
            "flow_ratio_5d": [0.1, 0.1, 0.0, -0.1],
        }
    )
    result = apply_defensive_boundary(frame)
    assert result.index.tolist() == [1]
