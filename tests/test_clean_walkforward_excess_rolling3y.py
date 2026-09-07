"""三年滚动训练窗切分测试。"""

from research.clean_walkforward_excess_rolling3y import rolling_splits


def test_rolling_splits_use_only_prior_three_years() -> None:
    for train_years, predict_year in rolling_splits():
        assert len(train_years) == 3
        assert max(train_years) == predict_year - 1
        assert min(train_years) == predict_year - 3
        assert predict_year not in train_years
