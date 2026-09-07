import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_reality_check import block_indices, reality_check  # noqa: E402


def test_block_indices_preserve_length_and_bounds() -> None:
    rng = np.random.default_rng(7)
    indices = block_indices(23, block=5, rng=rng)
    assert len(indices) == 23
    assert indices.min() >= 0
    assert indices.max() < 23


def test_reality_check_detects_clear_edge() -> None:
    rng = np.random.default_rng(11)
    matrix = rng.normal(0, 0.2, size=(400, 4))
    matrix[:, 0] += 0.5
    result = reality_check(matrix, candidate_index=0, block=10, repetitions=1000, seed=12)
    assert result["candidate_adjusted_p"] < 0.05
    assert result["best_family_p"] < 0.05

