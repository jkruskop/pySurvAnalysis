"""Discovery, defaults resolution, and the one hard cross-member rule."""

from __future__ import annotations

import pytest

from pysurvanalysis.domain import (
    Project, ProjectError, SurvivalExperiment, config as cfgmod,
    find_project_root, is_experiment_dir, is_project_dir,
)
from tests.conftest import make_experiment_dir, write_dlife_workbook


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
    from pysurvanalysis.script_editor.project_actions import (
        DEFAULT_PROJECT_SCRIPT_NAME,
    )

    project = Project.create(tmp_path / "fresh", type_key="standard_lifespan")
    ## Named for what it is — the script a Batch Run executes here — and
    ## carrying its notes into the file, so the default run is visible and
    ## editable rather than hidden in code.
    assert [s["name"] for s in project.scripts()] == [DEFAULT_PROJECT_SCRIPT_NAME]
    assert project.scripts()[0]["notes"]
    assert project.type.key == "standard_lifespan"


def test_a_project_without_scripts_is_seeded_on_the_next_write(tmp_path):
    from pysurvanalysis.script_editor.project_actions import (
        DEFAULT_PROJECT_SCRIPT_NAME,
    )

    project = Project.create(tmp_path / "old", type_key="standard_lifespan")
    project.config.pop("scripts")            # a project.yaml predating the default
    project.save()
    assert [s["name"] for s in Project(project.directory).scripts()] \
        == [DEFAULT_PROJECT_SCRIPT_NAME]

    ## An authored block is never re-seeded: an empty list is a deletion.
    project.config["scripts"] = []
    project.save()
    assert Project(project.directory).scripts() == []


def test_add_member_scaffolds_from_the_defaults(project):
    member = project.add_member("rep_c")
    assert member.type.key == "interaction"
    assert (member.directory / cfgmod.CONFIG_FILENAME).is_file()
    assert member.directory in project.member_dirs()


# ── the three ways a member arrives ────────────────────────────────────────

def test_add_directory_copies_an_outside_directory_in(project, tmp_path):
    source = tmp_path / "elsewhere" / "cohort_x"
    write_dlife_workbook(source / "data" / "cohort_x.xlsx")

    member = project.adopt_directory(source)

    ## Copied, not referenced: analysing a folder outside the Project would
    ## write its outputs outside the Project too.
    assert member.directory == project.directory / "cohort_x"
    assert (member.data_dir / "cohort_x.xlsx").is_file()
    assert (source / "data" / "cohort_x.xlsx").is_file()   # original untouched
    assert member.directory in project.member_dirs()
    assert member.type.key == "interaction"                # from the Project


def test_add_directory_adopts_a_direct_subdirectory_in_place(project):
    source = project.directory / "already_here"
    write_dlife_workbook(source / "data" / "run.xlsx")

    member = project.adopt_directory(source)

    assert member.directory == source                      # no copy
    assert not (project.directory / "already_here" / "already_here").exists()
    assert is_experiment_dir(source)


def test_an_adopted_member_inherits_the_projects_defaults(project, tmp_path):
    source = tmp_path / "cohort_y"
    write_dlife_workbook(source / "data" / "cohort_y.xlsx")

    member = project.adopt_directory(source)

    ## Minimal, like a scaffolded member: only what the file itself says.
    written = cfgmod.read_yaml(member.config_path)
    assert written.get("input") == {"format": "excel"}
    assert "global" not in written
    assert member.config["global"]["time_unit"]            # inherited


def test_an_adopted_directory_keeps_its_own_config(project, tmp_path):
    source = tmp_path / "configured"
    write_dlife_workbook(source / "data" / "configured.xlsx")
    cfgmod.save_config(source, {"experiment_type": "interaction",
                                "notes": "hand written"})

    member = project.adopt_directory(source)

    assert member.config["notes"] == "hand written"


def test_add_directory_refuses_what_is_not_an_experiment(project, tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(ProjectError, match="no data/ subdirectory"):
        project.adopt_directory(bare)

    no_book = tmp_path / "csv_only"
    (no_book / "data").mkdir(parents=True)
    (no_book / "data" / "cohort.csv").write_text("Age,Event\n10,1\n")
    with pytest.raises(ProjectError, match="No .xlsx"):
        project.adopt_directory(no_book)

    broken = tmp_path / "broken"
    write_dlife_workbook(broken / "data" / "broken.xlsx", drop_column="IntDeaths")
    with pytest.raises(ProjectError, match="RawData sheet is missing"):
        project.adopt_directory(broken)


def test_add_directory_refuses_a_container_of_the_project(project):
    ## Copying an ancestor in would copy the Project into itself.
    with pytest.raises(ProjectError, match="contains this Project"):
        project.adopt_directory(project.directory.parent)
    with pytest.raises(ProjectError, match="Project directory itself"):
        project.adopt_directory(project.directory)


def test_add_experiment_copies_a_workbook_from_outside(project, tmp_path):
    book = write_dlife_workbook(tmp_path / "loose" / "cohort_z.xlsx")

    member = project.adopt_data_file(book)

    assert member.directory == project.directory / "cohort_z"
    assert (member.data_dir / "cohort_z.xlsx").is_file()
    assert book.is_file()                                  # copied, not moved
    assert is_experiment_dir(member.directory)


def test_add_experiment_moves_a_workbook_from_inside_the_project(project):
    book = write_dlife_workbook(project.directory / "inbox" / "cohort_w.xlsx")

    member = project.adopt_data_file(book)

    ## Moved: a copy left loose in the tree would make the Project ambiguous
    ## about which file is the member's data.
    assert (member.data_dir / "cohort_w.xlsx").is_file()
    assert not book.exists()


def test_add_experiment_refuses_a_file_that_is_not_dlife(project, tmp_path):
    csv = tmp_path / "cohort.csv"
    csv.write_text("Age,Event\n10,1\n")
    with pytest.raises(ProjectError, match="not an .xlsx workbook"):
        project.adopt_data_file(csv)

    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"not really a workbook")
    with pytest.raises(ProjectError, match="cannot be opened"):
        project.adopt_data_file(junk)


def test_add_experiment_will_not_clobber_an_existing_member(project):
    book = write_dlife_workbook(project.directory / "inbox" / "rep_a.xlsx")
    with pytest.raises(ProjectError, match="already exists"):
        project.adopt_data_file(book)
    assert book.is_file()                                  # nothing moved


def test_missing_project_marker_is_a_helpful_error(tmp_path):
    with pytest.raises(ProjectError, match="not a Project"):
        Project(tmp_path)
