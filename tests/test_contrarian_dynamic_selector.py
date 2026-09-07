import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_dynamic_selector import choose_config  # noqa: E402


def test_choose_config_uses_only_prior_three_years():
    rows = []
    for name, values in {"stable": [0.8, 0.9, 1.0], "spiky": [0.1, 0.2, 4.0]}.items():
        for year, value in zip((2019, 2020, 2021), values):
            rows.append({"name": name, "year": year, "trades": 60, "avg_net": value, "profit_factor": 1.3})
    rows.append({"name": "spiky", "year": 2022, "trades": 60, "avg_net": 99.0, "profit_factor": 9.0})
    chosen, audit = choose_config(pd.DataFrame(rows), target_year=2022)
    assert chosen == "stable"
    assert audit["history_end"] == 2021


def test_choose_config_rejects_a_prior_loss_year():
    rows = []
    for name, values in {"all_positive": [0.4, 0.5, 0.6], "one_loss": [-0.1, 2.0, 3.0]}.items():
        for year, value in zip((2019, 2020, 2021), values):
            rows.append({"name": name, "year": year, "trades": 60, "avg_net": value, "profit_factor": 1.3})
    chosen, _ = choose_config(pd.DataFrame(rows), target_year=2022)
    assert chosen == "all_positive"

