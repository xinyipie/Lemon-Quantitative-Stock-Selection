"""正预测超额弃权规则测试。"""

import pandas as pd

from research.clean_walkforward_excess_positive_abstention import apply_positive_abstention


def test_abstention_keeps_only_strictly_positive_predictions() -> None:
    trades = pd.DataFrame({"prediction": [-0.1, 0.0, 0.1], "ts_code": ["A", "B", "C"]})
    result = apply_positive_abstention(trades)
    assert result["ts_code"].tolist() == ["C"]
