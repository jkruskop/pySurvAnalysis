"""Experiment Types: the 2×2 declaration, Plot Sets, and the action union."""

from __future__ import annotations

import pandas as pd
import pytest

from pysurvanalysis import plot_registry
from pysurvanalysis.experiment_types import (
    CUSTOM, available_types, get_type, type_for_config,
)
from pysurvanalysis.experiment_types.interaction import (
    cell_order, factor_block, reference_cell,
)


def test_absent_key_is_the_custom_experiment():
    assert type_for_config({}).is_custom
    assert type_for_config({"experiment_type": "custom"}) is CUSTOM
    assert get_type(None).is_custom


def test_every_plot_in_every_plot_set_has_a_builder():
    for exp_type in available_types():
        missing = [p for p in exp_type.plot_ids() if p not in plot_registry.PLOTS]
        assert not missing, f"{exp_type.key} names unbuildable plots: {missing}"


def test_headline_figure_is_in_its_own_plot_set():
    for exp_type in available_types():
        if exp_type.headline_plot_id:
            assert exp_type.headline_plot_id in exp_type.plot_ids()


@pytest.mark.parametrize("factors,expected", [
    ({"G": ["a", "b"], "T": ["1", "2"]}, 0),
    ({"G": ["a", "b"]}, 1),                        # one factor
    ({"G": ["a", "b", "c"], "T": ["1", "2"]}, 1),  # three levels
    ({"G": ["a", "a"], "T": ["1", "2"]}, 1),       # duplicate level
])
def test_interaction_config_validation(factors, expected):
    problems = get_type("interaction").validate_config({"factors": factors})
    assert len(problems) == expected


def test_interaction_requires_a_factors_block():
    problems = get_type("interaction").validate_config({})
    assert problems and "factors:" in problems[0]


def test_undeclared_level_in_the_data_is_a_problem():
    exp_type = get_type("interaction")
    config = {"factors": {"G": ["a", "b"], "T": ["1", "2"]}}
    data = pd.DataFrame({"G": ["a", "b", "c"], "T": ["1", "2", "1"]})
    problems = exp_type.validate_data(data, config)
    assert any("'c'" in p or "c " in p for p in problems)


def test_declared_level_absent_from_the_data_is_a_problem():
    exp_type = get_type("interaction")
    config = {"factors": {"G": ["a", "b"], "T": ["1", "2"]}}
    data = pd.DataFrame({"G": ["a", "a"], "T": ["1", "2"]})
    problems = exp_type.validate_data(data, config)
    assert any("never appear" in p for p in problems)


def test_reference_level_is_the_first_declared():
    config = {"factors": {"G": ["wt", "mut"], "T": ["ctrl", "drug"]}}
    assert reference_cell(config) == "wt/ctrl"
    assert cell_order(config) == ["wt/ctrl", "wt/drug", "mut/ctrl", "mut/drug"]

    flipped = {"factors": {"G": ["mut", "wt"], "T": ["ctrl", "drug"]}}
    assert reference_cell(flipped) == "mut/ctrl"


def test_prepare_data_imposes_the_declared_order():
    exp_type = get_type("interaction")
    config = {"factors": {"G": ["wt", "mut"], "T": ["ctrl", "drug"]}}
    data = pd.DataFrame({
        "time": [1.0, 2.0, 3.0, 4.0],
        "event": [1, 1, 1, 1],
        "G": ["mut", "wt", "mut", "wt"],
        "T": ["drug", "ctrl", "ctrl", "drug"],
        "treatment": ["mut/drug", "wt/ctrl", "mut/ctrl", "wt/drug"],
    })
    prepared = exp_type.prepare_data(data, config)
    assert list(prepared["treatment"].cat.categories) == cell_order(config)
    assert prepared["treatment"].iloc[0] == "wt/ctrl"     # the reference cell leads
    assert list(prepared["G"].cat.categories) == ["wt", "mut"]


def test_factor_block_stringifies_levels():
    assert factor_block({"factors": {"D": [20, 40]}}) == {"D": ["20", "40"]}


def test_standard_lifespan_validates_its_own_global_key():
    exp_type = get_type("standard_lifespan")
    assert exp_type.validate_config({"global": {"min_n_per_chamber": 5}}) == []
    problems = exp_type.validate_config({"global": {"min_n_per_chamber": -1}})
    assert problems and "min_n_per_chamber" in problems[0]


def test_time_label_falls_back_to_the_unit():
    exp_type = get_type("standard_lifespan")
    assert exp_type.resolve_time_label({"global": {"time_unit": "weeks"}}) \
        == "Age (weeks)"
    assert exp_type.resolve_time_label({"global": {"time_label": "Adult age"}}) \
        == "Adult age"
