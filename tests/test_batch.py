"""Batch runs: discovery, the designated script, and continue-on-error."""

from __future__ import annotations

from pysurvanalysis.domain import Batch, Project, config as cfgmod
from pysurvanalysis.domain.batch import resolve_designated_script
from pysurvanalysis.script_editor.project_actions import DEFAULT_PROJECT_SCRIPT_NAME
from tests.conftest import make_experiment_dir


def _batch(tmp_path, n_projects=2):
    root = tmp_path / "batch"
    for i in range(n_projects):
        project_dir = root / f"proj_{i}"
        Project.create(project_dir, type_key="standard_lifespan")
        make_experiment_dir(project_dir / "rep", type_key="standard_lifespan",
                            minimal=True, seed=i)
    return root


def test_a_batch_is_structural_not_marked(tmp_path):
    root = _batch(tmp_path)
    batch = Batch(root)
    assert [d.name for d in batch.project_dirs()] == ["proj_0", "proj_1"]
    assert not batch.config_path.is_file()      # no batch.yaml needed


def test_non_projects_are_simply_not_members(tmp_path):
    root = _batch(tmp_path)
    (root / "notes").mkdir()
    assert "notes" not in [d.name for d in Batch(root).project_dirs()]


def test_batch_yaml_designates_the_script(tmp_path):
    root = _batch(tmp_path)
    cfgmod.write_yaml(root / cfgmod.BATCH_FILENAME,
                      {"script": "Standard pipeline", "project_scripts": []})
    assert Batch(root).designated_script == "Standard pipeline"


def test_central_project_scripts_serve_every_project(tmp_path):
    root = _batch(tmp_path)
    cfgmod.write_yaml(root / cfgmod.BATCH_FILENAME, {
        "script": "Shared",
        "project_scripts": [
            {"name": "Shared", "steps": [{"action": "validate_project"}]}],
    })
    logged: list[str] = []
    result = Batch(root).run(log=logged.append)
    assert not result.failures
    assert sum("Validate project" in line for line in logged) == 2


def test_one_failing_project_does_not_stop_the_batch(tmp_path):
    root = _batch(tmp_path)
    # Break one member's config so validate_project fails for that Project only.
    broken = root / "proj_0" / "rep"
    config = cfgmod.load_config(broken)
    config["experiment_type"] = "interaction"      # no factors declared
    cfgmod.save_config(broken, config)

    cfgmod.write_yaml(root / cfgmod.BATCH_FILENAME, {
        "script": "Check",
        "project_scripts": [
            {"name": "Check", "steps": [{"action": "validate_project"}]}],
    })
    result = Batch(root).run(log=lambda _m: None)
    assert [o.name for o in result.failures] == ["proj_0"]
    assert "1/2" in result.summary()


def test_an_unresolvable_script_name_is_a_counted_skip(tmp_path):
    root = _batch(tmp_path)
    result = Batch(root).run("no such script", log=lambda _m: None)
    assert len(result.failures) == 2
    assert "no Project Script named" in result.failures[0].message


def test_no_designation_runs_each_projects_own_batch_script(tmp_path):
    root = _batch(tmp_path)
    ## Rewrite one Project's default so the run is identifiable, and prove
    ## the other still runs the seeded one rather than a shared built-in.
    project = Project(root / "proj_0")
    project.config["scripts"] = [{"name": DEFAULT_PROJECT_SCRIPT_NAME,
                                  "steps": [{"action": "validate_project"}]}]
    project.save()

    steps, source, _note = resolve_designated_script(None, [], project)
    assert steps == [{"action": "validate_project"}]
    assert source == "project.yaml scripts"

    other = Project(root / "proj_1")
    steps, _source, _note = resolve_designated_script(None, [], other)
    assert [s["action"] for s in steps] == [s["action"] for s
                                            in other.scripts()[0]["steps"]]


def test_a_project_with_no_script_does_not_run(tmp_path):
    root = _batch(tmp_path)
    for name in ("proj_0", "proj_1"):
        project = Project(root / name)
        project.config["scripts"] = []
        project.save()

    logged: list[str] = []
    result = Batch(root).run(log=logged.append)
    assert len(result.failures) == 2
    ## No implicit built-in fallback: it says what is missing and where to
    ## author it, rather than silently substituting a pipeline.
    assert "Script Editor" in result.failures[0].message
    assert DEFAULT_PROJECT_SCRIPT_NAME in result.failures[0].message


def test_a_renamed_default_still_runs_as_the_projects_own(tmp_path):
    root = _batch(tmp_path)
    project = Project(root / "proj_0")
    project.config["scripts"] = [{"name": "my pipeline",
                                  "steps": [{"action": "validate_project"}]}]
    project.save()
    steps, _source, _note = resolve_designated_script(None, [], project)
    assert steps == [{"action": "validate_project"}]


def test_central_scripts_win_over_a_projects_own_of_the_same_name(tmp_path):
    root = _batch(tmp_path)
    project = Project(root / "proj_0")
    project.config["scripts"] = [{"name": "Shared",
                                  "steps": [{"action": "project_report"}]}]
    project.save()
    central = [{"name": "Shared", "steps": [{"action": "validate_project"}]}]

    steps, source, _note = resolve_designated_script("Shared", central, project)
    assert steps == [{"action": "validate_project"}]
    assert source.endswith("project_scripts")


def test_the_builtin_report_pipeline_drops_uncurated_figures(tmp_path):
    root = _batch(tmp_path)
    project = Project(root / "proj_0")
    steps, source, note = resolve_designated_script("Report pipeline", [], project)
    assert source == "built-in"
    assert "render_publication_figures" not in [s["action"] for s in steps]
    assert "curated" in note


def test_an_empty_batch_says_so(tmp_path):
    logged: list[str] = []
    result = Batch(tmp_path / "empty").run(log=logged.append)
    assert result.outcomes == []
    assert any("nothing to run" in line for line in logged)
