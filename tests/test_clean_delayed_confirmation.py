from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.clean_delayed_confirmation import confirmation_passes  # noqa: E402


def test_confirmation_definitions_are_deterministic():
    positive = {"pct_chg": 2.0, "open": 10.0, "high": 10.6, "low": 9.9, "close": 10.5}
    pullback = {"pct_chg": -1.0, "open": 10.0, "high": 10.1, "low": 9.7, "close": 9.95}
    assert confirmation_passes(positive, "positive_close")
    assert not confirmation_passes(positive, "shallow_pullback")
    assert confirmation_passes(pullback, "shallow_pullback")
    assert confirmation_passes(pullback, "stable_acceptance")
