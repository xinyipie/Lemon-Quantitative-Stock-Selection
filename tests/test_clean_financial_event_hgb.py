from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.clean_financial_event_hgb import FEATURE_COLUMNS  # noqa: E402
from research.no_future_signal_pipeline import FUTURE_ONLY_COLUMNS, assert_no_future_features  # noqa: E402


def test_model_feature_whitelist_has_no_future_fields():
    assert set(FEATURE_COLUMNS).isdisjoint(FUTURE_ONLY_COLUMNS)
    assert_no_future_features(FEATURE_COLUMNS)
    assert "entry_gap_pct" not in FEATURE_COLUMNS
    assert "tradeable" not in FEATURE_COLUMNS

