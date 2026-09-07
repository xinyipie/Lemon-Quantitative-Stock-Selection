import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_cross_sectional_audit import add_fixed_partitions, trim_largest_winners  # noqa: E402


def test_fixed_partitions_are_deterministic():
    frame = pd.DataFrame({"ts_code": ["600000.SH", "000001.SZ", "430002.BJ"]})
    result = add_fixed_partitions(frame)
    assert result["code_parity"].tolist() == ["even", "odd", "even"]
    assert result["exchange"].tolist() == ["SH", "SZ", "BJ"]


def test_trim_largest_winners_only_removes_positive_tail():
    frame = pd.DataFrame({"net_ret": [-8.0, -2.0, 1.0, 2.0, 50.0]})
    result = trim_largest_winners(frame, fraction=0.20)
    assert result["net_ret"].max() == 2.0
    assert result["net_ret"].min() == -8.0

