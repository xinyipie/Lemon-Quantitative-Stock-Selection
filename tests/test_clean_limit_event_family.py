from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.clean_limit_event_family import EVENT_FEATURES, limit_threshold  # noqa: E402
from research.no_future_signal_pipeline import FUTURE_ONLY_COLUMNS, assert_no_future_features  # noqa: E402


def test_board_specific_limit_thresholds():
    assert limit_threshold("600000.SH") == 9.3
    assert limit_threshold("000001.SZ") == 9.3
    assert limit_threshold("300001.SZ") == 18.5
    assert limit_threshold("688001.SH") == 18.5
    assert limit_threshold("830001.BJ") == 28.0


def test_limit_event_features_are_t_day_only():
    assert set(EVENT_FEATURES).isdisjoint(FUTURE_ONLY_COLUMNS)
    assert_no_future_features(EVENT_FEATURES)
