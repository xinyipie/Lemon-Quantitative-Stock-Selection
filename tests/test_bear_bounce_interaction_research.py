import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.bear_bounce_interaction_research import select_two_stage_candidates


def _panel() -> pd.DataFrame:
    rows = []
    for date, future_boost in [("20240102", 0), ("20240103", 1000)]:
        for industry, industry_rs in [("弱行业", -10), ("中行业", 0), ("强行业", 10)]:
            for index in range(2):
                rows.append(
                    {
                        "trade_date": date,
                        "year": 2024,
                        "split": "validation",
                        "regime": "BEAR_BOUNCE",
                        "ts_code": f"{industry}{index}",
                        "name": f"股票{index}",
                        "industry": industry,
                        "industry_rs_20": industry_rs,
                        "amount": 200000 + index * 10000 + future_boost,
                        "pct_chg": 1 + index,
                        "drawdown_20": 5 + index,
                        "ret_20": -5 - index,
                        "volume_ratio": 1 + index,
                        "history_count": 100,
                        "tradeable": True,
                        "entry_open": 10.0,
                        "entry_gap_pct": 0.0,
                        "ret_3d": 1.0,
                        "ret_5d": 1.0,
                        "ret_8d": 1.0,
                    }
                )
    return pd.DataFrame(rows)


def test_two_stage_selection_keeps_only_bottom_industries_and_top_factor():
    specs = [{"factor": "amount_confirm", "label": "流动性确认", "column": "amount", "direction": "high"}]
    selected = select_two_stage_candidates(_panel(), specs=specs, top_n=1, industry_fraction=0.30)
    assert set(selected["industry"]) == {"弱行业"}
    assert selected.groupby("trade_date").size().tolist() == [1, 1]
    assert set(selected["ts_code"]) == {"弱行业1"}


def test_future_date_cannot_change_an_earlier_dates_selection():
    specs = [{"factor": "amount_confirm", "label": "流动性确认", "column": "amount", "direction": "high"}]
    panel = _panel()
    first_only = select_two_stage_candidates(panel[panel["trade_date"].eq("20240102")], specs=specs, top_n=1)
    with_future = select_two_stage_candidates(panel, specs=specs, top_n=1)
    earlier = with_future[with_future["trade_date"].eq("20240102")]
    assert first_only["ts_code"].tolist() == earlier["ts_code"].tolist()


def test_non_bear_bounce_rows_are_never_selected():
    panel = _panel()
    panel["regime"] = "BULL_TREND"
    selected = select_two_stage_candidates(panel, top_n=1)
    assert selected.empty


def test_script_can_be_started_directly_from_project_root():
    script = ROOT / "research" / "bear_bounce_interaction_research.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
