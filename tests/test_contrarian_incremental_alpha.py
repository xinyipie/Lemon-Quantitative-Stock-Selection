import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_incremental_alpha import holding_return  # noqa: E402


def test_holding_return_uses_next_open_and_fifth_close():
    assert round(holding_return(100.0, 105.0), 4) == 5.0


def test_holding_return_rejects_invalid_entry():
    assert holding_return(0.0, 105.0) is None

