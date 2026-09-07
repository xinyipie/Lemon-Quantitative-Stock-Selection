import pandas as pd

from research.defensive_quality_reentry_v17_stress_2019_2026 import _all_positive


def test_all_positive_requires_every_requested_year() -> None:
    yearly = pd.DataFrame({"year": [2019, 2021], "avg_net": [1.0, 1.0]})
    assert not _all_positive(yearly, 2019, 2021)
