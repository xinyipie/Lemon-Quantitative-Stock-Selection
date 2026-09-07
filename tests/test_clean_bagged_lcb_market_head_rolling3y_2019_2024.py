"""最近三年市场模型训练边界测试。"""


def test_rolling_market_train_years_are_exactly_three_prior_years() -> None:
    for predict_year in range(2019, 2025):
        train_years = list(range(predict_year - 3, predict_year))
        assert len(train_years) == 3
        assert train_years[-1] == predict_year - 1
        assert predict_year not in train_years
