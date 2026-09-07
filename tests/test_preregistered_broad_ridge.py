import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.preregistered_broad_ridge import FROZEN_CONFIG  # noqa: E402


def test_frozen_config_is_high_abstention_long_memory() -> None:
    assert FROZEN_CONFIG["topn"] == 2
    assert FROZEN_CONFIG["gate_window_years"] == 99
    assert FROZEN_CONFIG["gate_quantile"] == 0.8
    assert FROZEN_CONFIG["cost"] == 0.25

