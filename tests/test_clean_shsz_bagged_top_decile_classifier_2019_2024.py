import pandas as pd

from research.clean_shsz_bagged_top_decile_classifier_2019_2024 import (
    TOP_DECILE_BOUNDARY,
    TOP_DECILE_TARGET,
    add_top_decile_target,
    new_top_decile_classifier,
)


def test_top_decile_boundary_is_frozen() -> None:
    assert TOP_DECILE_BOUNDARY == 0.90


def test_add_top_decile_target_marks_only_leading_rows() -> None:
    frame = pd.DataFrame({"ret_5d_cross_section_rank": [0.89, 0.90, 1.0]})

    result = add_top_decile_target(frame)

    assert result[TOP_DECILE_TARGET].tolist() == [0, 1, 1]


def test_classifier_complexity_is_frozen() -> None:
    model = new_top_decile_classifier(1)

    assert model.max_leaf_nodes == 15
    assert model.min_samples_leaf == 50
