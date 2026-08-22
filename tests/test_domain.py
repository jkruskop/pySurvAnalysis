"""Discovery, defaults resolution, and the one hard cross-member rule."""

from __future__ import annotations

import pytest

from pysurvanalysis.domain import (
    Project, ProjectError, SurvivalExperiment, config as cfgmod,
    find_project_root, is_experiment_dir, is_project_dir,
)
from tests.conftest import make_experiment_dir


def test_project_discovers_only_configured_subdirs(project, tmp_path):
    (project.directory / "notes").mkdir()
    assert [m.name for m in project.members(reload=True)] == ["rep_a", "rep_b"]
    assert "notes" in [d.name for d in project.candidate_dirs()]


def test_marker_files_define_the_levels(project):
    assert is_project_dir(project.directory)
    assert not is_experiment_dir(project.directory)
    member = project.member("rep_a")
    assert is_experiment_dir(member.directory)
    assert find_project_root(member.directory) == project.directory


def test_defaults_are_inherited_and_overridable(project):
    config = dict(project.config)
    config["defaults"]["global"]["time_unit"] = "days"
    config["defaults"]["global"]["assume_censored"] = False
    cfgmod.write_yaml(project.config_path, config)
    reloaded = Project(project.directory)

    member = reloaded.member("rep_a")
    assert member.config["global"]["time_unit"] == "days"
    assert member.type.resolve_assume_censored(member.config) is False

    own = dict(member.raw_config)
    own["global"] = {"time_unit": "hours"}
    cfgmod.save_config(member.directory, own)
    overridden = Project(project.directory).member("rep_a")
    # The member's own value wins; the sibling key it did not restate survives.
    assert overridden.config["global"]["time_unit"] == "hours"
    assert overridden.config["global"]["assume_censored"] is False


def test_type_mismatch_is_the_only_hard_cross_member_error(project):
    member = project.member("rep_b")
    config = dict(member.raw_config)
    config["experiment_type"] = "standard_lifespan"
    cfgmod.save_config(member.directory, config)

    problems = Project(project.directory).validate()
    assert any("must share the Project's Experiment Type" in p for p in problems)


def test_diverging_levels_are_reported_not_fatal(project):
    assert project.validate() == []
    divergences = project.divergences()
    assert any(d.aspect == "levels" for d in divergences)
    assert "Genotype" in " ".join(d.detail for d in divergences)


def test_data_file_discovery_prefers_data_dir_and_ignores_sidecars(project):
    member = project.member("rep_a")
    assert member.data_file().name == "cohort.csv"

    (member.directory / "qc").mkdir(exist_ok=True)
    (member.directory / "remove_chambers.csv").write_text("group,chamber,note\n")
    assert member.data_file().name == "cohort.csv"


def test_ambiguous_data_is_an_error_naming_the_candidates(tmp_path):
    directory = make_experiment_dir(tmp_path / "amb")
    (directory / "data" / "second.csv").write_text("Age,Event\n1,1\n")
    experiment = SurvivalExperiment(directory)
    with pytest.raises(Exception) as excinfo:
        experiment.data_file()
    assert "second.csv" in str(excinfo.value)


def test_standalone_experiment_needs_no_project(standalone):
    assert standalone.project is None
    assert standalone.validate() == []
    assert standalone.analysis_dir.name == "analysis"


def test_unknown_type_key_is_an_error_not_a_silent_custom(tmp_path):
    directory = make_experiment_dir(tmp_path / "weird")
    config = cfgmod.load_config(directory)
    config["experiment_type"] = "not_a_type"
    cfgmod.save_config(directory, config)
    with pytest.raises(ValueError, match="Unknown experiment_type"):
        SurvivalExperiment(directory)


def test_creating_a_project_writes_a_default_script(tmp_path):
    project = Project.create(tmp_path / "fresh", type_key="standard_lifespan")
    assert [s["name"] for s in project.scripts()] == ["Report pipeline"]
    assert project.type.key == "standard_lifespan"


def test_add_member_scaffolds_from_the_defaults(project):
    member = project.add_member("rep_c")
    assert member.type.key == "interaction"
    assert (member.directory / cfgmod.CONFIG_FILENAME).is_file()
    assert member.directory in project.member_dirs()


def test_missing_project_marker_is_a_helpful_error(tmp_path):
    with pytest.raises(ProjectError, match="not a Project"):
        Project(tmp_path)
