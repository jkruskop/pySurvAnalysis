"""Batch runs: discovery, the designated script, and continue-on-error."""

from __future__ import annotations

from pysurvanalysis.domain import Batch, Project, config as cfgmod
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


def test_an_empty_batch_says_so(tmp_path):
    logged: list[str] = []
    result = Batch(tmp_path / "empty").run(log=logged.append)
    assert result.outcomes == []
    assert any("nothing to run" in line for line in logged)
