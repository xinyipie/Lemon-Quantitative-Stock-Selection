import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.contrarian_consensus_selector import build_consensus_for_year  # noqa: E402


def test_consensus_requires_multiple_config_votes():
    rows = [
        {"trade_date": "20220103", "ts_code": "A", "selected_config": "c1", "ret_5d": 2.0, "rank_prediction": 0.8},
        {"trade_date": "20220103", "ts_code": "A", "selected_config": "c2", "ret_5d": 2.0, "rank_prediction": 0.7},
        {"trade_date": "20220103", "ts_code": "A", "selected_config": "c3", "ret_5d": 2.0, "rank_prediction": 0.6},
        {"trade_date": "20220103", "ts_code": "B", "selected_config": "c1", "ret_5d": 1.0, "rank_prediction": 0.9},
    ]
    selected = build_consensus_for_year(pd.DataFrame(rows), vote_share=0.5, min_votes=3, topn=2, cost=0.25)
    assert selected["ts_code"].tolist() == ["A"]
    assert selected["vote_count"].iloc[0] == 3


def test_consensus_deduplicates_same_config_stock_vote():
    rows = [
        {"trade_date": "20220103", "ts_code": "A", "selected_config": "c1", "ret_5d": 2.0, "rank_prediction": 0.8},
        {"trade_date": "20220103", "ts_code": "A", "selected_config": "c1", "ret_5d": 2.0, "rank_prediction": 0.8},
        {"trade_date": "20220103", "ts_code": "A", "selected_config": "c2", "ret_5d": 2.0, "rank_prediction": 0.7},
    ]
    selected = build_consensus_for_year(pd.DataFrame(rows), vote_share=0.5, min_votes=2, topn=2, cost=0.25)
    assert selected["vote_count"].iloc[0] == 2

