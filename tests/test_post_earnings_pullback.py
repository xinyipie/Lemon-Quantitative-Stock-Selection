from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.post_earnings_pullback import FORBIDDEN_COLUMNS, SCORE_COLUMNS  # noqa: E402


def test_score_does_not_use_future_columns():
    assert SCORE_COLUMNS.isdisjoint(FORBIDDEN_COLUMNS)

