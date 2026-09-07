from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.clean_archetype_family import ARCHETYPE_FEATURES  # noqa: E402
from research.no_future_signal_pipeline import FUTURE_ONLY_COLUMNS, assert_no_future_features  # noqa: E402


def test_all_archetype_features_are_t_day_only():
    for features in ARCHETYPE_FEATURES.values():
        assert set(features).isdisjoint(FUTURE_ONLY_COLUMNS)
        assert_no_future_features(features)

