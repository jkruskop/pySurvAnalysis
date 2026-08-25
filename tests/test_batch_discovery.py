"""Recursive Batch discovery, and what makes a Member Experiment blocked.

The rules under test are structural, so almost everything here is built out of
directories and one small CSV — no analysis is ever run.
"""

from __future__ import annotations

import os

import pytest

from pysurvanalysis.domain import Batch, Project, config as cfgmod, layout
from pysurvanalysis.domain.batch import discover, project_directory, project_kind
from tests.conftest import make_experiment_dir, write_cohort


def _project(directory, members=("m1",), **kwargs):
    Project.create(directory, type_key="standard_lifespan")
    for i, name in enumerate(members):
        make_experiment_dir(directory / name, type_key="standard_lifespan",
                            minimal=True, seed=i, **kwargs)
    return directory


# ── the walk ──────────────────────────────────────────────────────────────

def test_projects_are_found_at_any_depth(tmp_path):
    """Experimenters keep Sept2026/ProjA, not a flat folder of projects."""
    _project(tmp_path / "Sept2026" / "ProjA")
    _project(tmp_path / "Archive" / "2025" / "ProjB")
    assert [p.key for p in discover(tmp_path)["projects"]] == [
        "Archive/2025/ProjB", "Sept2026/ProjA"]


def test_a_key_is_the_path_relative_to_the_batch_root(tmp_path):
    """A top-level Project is still its bare folder name, so every batch.yaml
    written before discovery went recursive keeps resolving."""
    _project(tmp_path / "Flat")
    _project(tmp_path / "nested" / "Deep")
    keys = [p.key for p in discover(tmp_path)["projects"]]
    assert keys == ["Flat", "nested/Deep"]
    assert project_directory(tmp_path, "nested/Deep") == tmp_path / "nested" / "Deep"


def test_two_projects_with_the_same_leaf_name_do_not_collide(tmp_path):
    """Leaf names were rejected precisely because these two would be one key."""
    _project(tmp_path / "pilot" / "ProjA")
    _project(tmp_path / "final" / "ProjA")
    keys = [p.key for p in discover(tmp_path)["projects"]]
    assert keys == ["final/ProjA", "pilot/ProjA"]


def test_the_walk_never_looks_inside_a_project(tmp_path):
    """A Project's subdirectories are its Member Experiments by definition, so
    an archived copy carrying its own project.yaml cannot become a second
    Project — and no member can be analysed twice in one run."""
    root = _project(tmp_path / "ProjA")
    nested = root / "m1" / "archived_copy"
    _project(nested)
    assert [p.key for p in discover(tmp_path)["projects"]] == ["ProjA"]


def test_a_project_is_never_also_a_batch(tmp_path):
    root = _project(tmp_path / "ProjA")
    assert discover(root)["projects"] == []


def test_a_stray_project_yaml_cannot_hide_the_projects_beneath_it(tmp_path):
    """One file at a grouping level used to empty the whole Batch. The walk
    descends first and reports the marker rather than stopping at it."""
    _project(tmp_path / "Sept2026" / "ProjA")
    (tmp_path / "Sept2026" / cfgmod.PROJECT_FILENAME).write_text("name: stray\n")
    found = discover(tmp_path)
    assert [p.key for p in found["projects"]] == ["Sept2026/ProjA"]
    assert any(key == "Sept2026" and "no member experiment" in why
               for key, why in found["skipped"])


def test_a_stray_survival_config_cannot_hide_them_either(tmp_path):
    """The same rule for the other marker — an experiment directory's children
    are data/ and analysis/, but a grouping folder someone ran the config
    editor on looks identical."""
    _project(tmp_path / "group" / "ProjA")
    cfgmod.save_config(tmp_path / "group", {"experiment_type": "standard_lifespan"})
    assert [p.key for p in discover(tmp_path)["projects"]] == ["group/ProjA"]


def test_a_marker_over_a_junk_subdirectory_still_yields_to_real_projects(tmp_path):
    """`unconfirmed`: project.yaml plus experiment-shaped children none of
    which can run. Indistinguishable from a grouping folder holding one
    template, so the walk descends before deciding."""
    Project.create(tmp_path / "group", type_key="standard_lifespan")
    cfgmod.save_config(tmp_path / "group" / "template",
                       {"experiment_type": "standard_lifespan"})
    _project(tmp_path / "group" / "Real")
    assert [p.key for p in discover(tmp_path)["projects"]] == ["group/Real"]


def test_an_unconfirmed_project_with_nothing_below_it_is_listed(tmp_path):
    """...but when no real Project turns up, it IS the Project — blocked, and
    listed so the preflight can offer to repair it."""
    Project.create(tmp_path / "Broken", type_key="standard_lifespan")
    write_cohort(tmp_path / "Broken" / "m1" / "data" / "c.csv")
    found = discover(tmp_path)["projects"]
    assert [p.key for p in found] == ["Broken"]
    assert not found[0].runnable and len(found[0].blocked) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_symlinked_directories_are_not_followed(tmp_path):
    """A link into an archive share would run its members twice; a link to an
    ancestor is a cycle."""
    _project(tmp_path / "ProjA")
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    found = discover(tmp_path)
    assert [p.key for p in found["projects"]] == ["ProjA"]
    assert any("symlink" in why for _key, why in found["skipped"])


def test_an_unreadable_directory_is_reported_not_silently_dropped(tmp_path):
    """It may hold a whole Project; pruning it quietly understates the Batch."""
    _project(tmp_path / "ProjA")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        found = discover(tmp_path)
        assert [p.key for p in found["projects"]] == ["ProjA"]
        assert any(key == "locked" for key, _why in found["skipped"])
    finally:
        locked.chmod(0o755)


def test_a_structural_predicate_never_raises_on_an_unreadable_directory(tmp_path):
    """The walk runs these over directories nobody owns, so an exception out
    of one takes down the whole scan."""
    from pysurvanalysis.domain import is_experiment_dir, is_project_dir

    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        assert is_project_dir(locked / "inner") is False
        assert is_experiment_dir(locked / "inner") is False
    finally:
        locked.chmod(0o755)


def test_an_escaping_key_is_refused_not_resolved(tmp_path):
    for bad in ("../elsewhere", "/etc", "a/../../b"):
        with pytest.raises(ValueError):
            project_directory(tmp_path, bad)


# ── blocked members ───────────────────────────────────────────────────────

def test_data_at_the_root_is_not_blocked(tmp_path):
    """The deliberate divergence from the sister app: this loader searches
    data/ AND the directory root, so a file at either is already found. There
    is no 'unfiled recording' state here, and nothing to file."""
    directory = tmp_path / "m"
    write_cohort(directory / "cohort.csv")
    cfgmod.save_config(directory, {
        "experiment_type": "standard_lifespan",
        "input": {"format": "long", "time_col": "Age", "event_col": "Event"}})
    assert layout.classify(directory).usable


def test_data_with_no_config_is_blocked_on_the_config(tmp_path):
    write_cohort(tmp_path / "m" / "data" / "c.csv")
    item = layout.classify(tmp_path / "m")
    assert item.status == layout.NO_CONFIG and item.fix == "config"


def test_a_config_with_no_data_is_blocked_with_no_one_click_fix(tmp_path):
    cfgmod.save_config(tmp_path / "m", {"experiment_type": "standard_lifespan"})
    item = layout.classify(tmp_path / "m")
    assert item.status == layout.NO_DATA and item.fix is None


def test_two_data_files_are_ambiguous_and_fixed_by_naming_one(tmp_path):
    """The loader refuses to guess between them, so the classifier must not
    either — but writing the answer down is a real one-click fix."""
    directory = make_experiment_dir(tmp_path / "m", type_key="standard_lifespan",
                                    minimal=True)
    write_cohort(directory / "data" / "second.csv", seed=9)
    item = layout.classify(directory)
    assert item.status == layout.AMBIGUOUS and item.fix == "data_file"
    assert set(item.candidates) == {"cohort.csv", "second.csv"}

    config = cfgmod.load_config(directory)
    config["data_file"] = "data/cohort.csv"
    cfgmod.save_config(directory, config)
    assert layout.classify(directory).usable


def test_a_root_copy_beside_a_filed_one_is_not_ambiguous(tmp_path):
    """data/ wins outright in the loader, so an old copy at the root changes
    nothing — calling it ambiguous would block a run that would succeed."""
    directory = make_experiment_dir(tmp_path / "m", type_key="standard_lifespan",
                                    minimal=True)
    write_cohort(directory / "old.csv", seed=9)
    assert layout.classify(directory).usable


def test_output_directories_are_never_members(tmp_path):
    root = _project(tmp_path / "ProjA")
    write_cohort(root / "analysis" / "leftover.csv")
    (root / "qc").mkdir(exist_ok=True)
    assert [m.name for m in layout.members_in(root)] == ["m1"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_symlinked_copy_of_a_member_is_counted_once(tmp_path):
    """Otherwise the same cohort is analysed twice under two names."""
    root = _project(tmp_path / "ProjA")
    (root / "m1_link").symlink_to(root / "m1", target_is_directory=True)
    assert [m.name for m in layout.members_in(root)] == ["m1"]


def test_blocked_is_a_property_of_the_member_not_the_project(tmp_path):
    """A Project with three healthy members and one blocked member runs the
    three — a stale folder must not stop ten Projects at 2am."""
    root = _project(tmp_path / "ProjA", members=("m1", "m2", "m3"))
    write_cohort(root / "m4" / "data" / "c.csv")
    entry = discover(tmp_path)["projects"][0]
    assert len(entry.usable) == 3 and len(entry.blocked) == 1
    assert entry.runnable


def test_project_kind_is_one_predicate_for_the_library_and_the_ui(tmp_path):
    assert project_kind(tmp_path)[0] == ""
    Project.create(tmp_path / "p", type_key="standard_lifespan")
    assert project_kind(tmp_path / "p")[0] == "marker"
    write_cohort(tmp_path / "p" / "m" / "data" / "c.csv")
    assert project_kind(tmp_path / "p")[0] == "unconfirmed"
    make_experiment_dir(tmp_path / "p" / "m2", type_key="standard_lifespan",
                        minimal=True)
    assert project_kind(tmp_path / "p")[0] == "project"


# ── the run ───────────────────────────────────────────────────────────────

def _shared_script_batch(tmp_path):
    _project(tmp_path / "Sept2026" / "ProjA")
    _project(tmp_path / "Archive" / "ProjB")
    cfgmod.write_yaml(tmp_path / cfgmod.BATCH_FILENAME, {
        "script": "Shared",
        "project_scripts": [{"name": "Shared",
                             "steps": [{"action": "validate_project"}]}]})
    return tmp_path


def test_a_run_is_scoped_to_the_confirmed_target_list(tmp_path):
    """Unchecking a Project means 'do not touch this one', and recursion
    surfaces Projects the user may not have known were there."""
    root = _shared_script_batch(tmp_path)
    result = Batch(root).run(project_names=["Sept2026/ProjA"])
    assert [o.name for o in result.outcomes] == ["Sept2026/ProjA"]


def test_an_unscoped_run_still_visits_every_project(tmp_path):
    root = _shared_script_batch(tmp_path)
    result = Batch(root).run()
    assert [o.name for o in result.outcomes] == ["Archive/ProjB", "Sept2026/ProjA"]
    assert not result.failures


def test_the_summary_says_when_a_project_was_only_partly_analysed(tmp_path):
    """'Succeeded' must not read as 'analysed everything'."""
    root = _shared_script_batch(tmp_path)
    write_cohort(root / "Sept2026" / "ProjA" / "m2" / "data" / "c.csv")
    result = Batch(root).run()
    assert not result.failures
    assert "incomplete: Sept2026/ProjA (1/2 members)" in result.summary()


def test_blocked_members_are_named_before_the_run_reaches_them(tmp_path):
    root = _shared_script_batch(tmp_path)
    write_cohort(root / "Sept2026" / "ProjA" / "m2" / "data" / "c.csv")
    logged: list[str] = []
    Batch(root).run(log=logged.append)
    assert any("1 blocked member(s) will not be analysed" in line
               for line in logged)


def test_a_nested_batch_yaml_is_named_and_ignored(tmp_path):
    """A grouping folder may be a Batch in its own right. Only the selected
    Batch's file governs — a fourth resolution step that depended on where the
    user clicked would be unmemorable."""
    root = _shared_script_batch(tmp_path)
    cfgmod.write_yaml(root / "Sept2026" / cfgmod.BATCH_FILENAME,
                      {"script": "Something else"})
    logged: list[str] = []
    Batch(root).run(log=logged.append)
    assert any("Sept2026/batch.yaml is ignored" in line for line in logged)
