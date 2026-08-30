"""Script registries: core ∪ type, the hard error, and the bridge down."""

from __future__ import annotations

import pytest

from pysurvanalysis.experiment_types import get_type
from pysurvanalysis.script_editor import actions, project_actions


def test_core_actions_are_available_to_every_type():
    for key in ("standard_lifespan", "interaction", None):
        registry = actions.registry_for(get_type(key))
        for core in actions.CORE_KEYS:
            assert core in registry


def test_type_actions_are_scoped_to_their_type():
    interaction = actions.registry_for(get_type("interaction"))
    standard = actions.registry_for(get_type("standard_lifespan"))
    assert "cox_interaction" in interaction
    assert "cox_interaction" not in standard
    assert interaction["cox_interaction"].from_type is True


def test_custom_experiment_withholds_nothing():
    registry = actions.registry_for(None)
    assert set(actions.POOL) <= set(registry)


def test_unknown_action_is_a_hard_error_naming_step_and_type():
    problems = actions.validate_steps(
        [{"action": "run_analysis"}, {"action": "cox_interaction"}],
        get_type("standard_lifespan"))
    assert len(problems) == 1
    assert "Step 2" in problems[0] and "Standard Lifespan" in problems[0]


def test_a_valid_script_validates_clean():
    steps = [{"action": "run_analysis"}, {"action": "cox_interaction"}]
    assert actions.validate_steps(steps, get_type("interaction")) == []


def test_a_step_without_an_action_is_flagged():
    assert actions.validate_steps([{}], get_type("interaction"))


def test_project_registry_cannot_see_experiment_actions():
    assert "run_analysis" not in project_actions.PROJECT_ACTIONS
    assert "run_in_experiments" in project_actions.PROJECT_ACTIONS
    problems = project_actions.validate_project_steps([{"action": "run_analysis"}])
    assert problems and "does not exist" in problems[0]


def test_builtin_project_scripts_are_themselves_valid():
    for name in project_actions.builtin_names():
        assert project_actions.validate_project_steps(
            project_actions.builtin_steps(name)) == []


def test_builtin_experiment_script_is_valid_for_every_type():
    for steps in project_actions.BUILTIN_EXPERIMENT_SCRIPTS.values():
        for key in ("standard_lifespan", "interaction", None):
            assert actions.validate_steps(steps, get_type(key)) == []


def test_the_batch_script_names_the_default_experiment_script():
    """The two defaults are a pair: a fresh Project's `batch` script must
    name a script every fresh member's file actually carries."""
    default = project_actions.default_experiment_script()
    assert default["name"] == project_actions.DEFAULT_EXPERIMENT_SCRIPT_NAME
    assert default["notes"]
    named = {step["script"] for step in project_actions.default_project_script()["steps"]
             if step["action"] == "run_in_experiments"}
    assert named == {default["name"]}
    for key in ("standard_lifespan", "interaction", None):
        assert actions.validate_steps(default["steps"], get_type(key)) == []


def test_run_in_experiments_reads_the_members_own_default_script(project):
    """The seeded script is the one that runs — edit it in the file and the
    edit is what run_in_experiments executes, not the in-code built-in."""
    from pysurvanalysis.domain import config as cfgmod

    member = project.members()[0]
    config = cfgmod.load_config(member.directory)
    config["scripts"] = [{"name": project_actions.DEFAULT_EXPERIMENT_SCRIPT_NAME,
                          "steps": [{"action": "not_an_action"}]}]
    cfgmod.save_config(member.directory, config)

    from pysurvanalysis.domain import Project

    reloaded = Project(project.directory)
    with pytest.raises(RuntimeError, match="cannot run as a"):
        project_actions.run_script(
            reloaded, [{"action": "run_in_experiments",
                        "script": project_actions.DEFAULT_EXPERIMENT_SCRIPT_NAME,
                        "only": [member.name]}],
            log=lambda _m: None)


def test_run_in_experiments_refuses_a_script_the_type_cannot_run(project):
    """A hard error, not a skip: a silently skipped step reports as complete."""
    config = dict(project.config)
    config["experiment_scripts"] = [
        {"name": "bad", "steps": [{"action": "not_an_action"}]}]
    from pysurvanalysis.domain import config as cfgmod

    cfgmod.write_yaml(project.config_path, config)

    from pysurvanalysis.domain import Project

    reloaded = Project(project.directory)
    with pytest.raises(RuntimeError, match="cannot run as a"):
        project_actions.run_script(
            reloaded, [{"action": "run_in_experiments", "script": "bad"}],
            log=lambda _m: None)


def test_a_missing_script_name_is_counted_not_raised(project):
    ctx = project_actions.run_script(
        project, [{"action": "run_in_experiments", "script": "nope"}],
        log=lambda _m: None)
    assert sorted(ctx.failures) == ["rep_a", "rep_b"]


def test_only_targets_named_members(project):
    logged: list[str] = []
    ctx = project_actions.run_script(
        project,
        [{"action": "run_in_experiments", "script": "nope", "only": ["rep_a"]}],
        log=logged.append)
    assert ctx.failures == ["rep_a"]
    assert not any("rep_b" in line for line in logged)


def test_an_unknown_member_name_is_logged_and_counted(project):
    ctx = project_actions.run_script(
        project,
        [{"action": "run_in_experiments", "script": "x", "only": ["ghost"]}],
        log=lambda _m: None)
    assert "ghost" in ctx.failures
