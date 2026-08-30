"""Pipeline behaviour per type, output stamping, and the non-destructive upgrade."""

from __future__ import annotations

import json

import pytest

from pysurvanalysis import exclusions, pipeline
from pysurvanalysis.domain import SurvivalExperiment, config as cfgmod, upgrade
from tests.conftest import make_experiment_dir, write_cohort


def test_the_type_chooses_which_figures_are_rendered(analysed_project):
    project, results = analysed_project
    result = results["rep_a"]
    assert set(result.figure_paths) == set(project.type.plot_ids())
    for path in result.figure_paths.values():
        assert path.is_file()


def test_custom_experiment_renders_the_whole_battery(tmp_path):
    from pysurvanalysis import plot_registry

    directory = make_experiment_dir(tmp_path / "cust", type_key="custom")
    result = SurvivalExperiment(directory).run_analysis()
    # Everything the registry can draw for this data — a Custom Experiment
    # withholds nothing.
    assert len(result.figure_paths) >= len(plot_registry.available()) - 2


def test_interaction_runs_its_factorial_battery(analysed_project):
    _project, results = analysed_project
    titles = [m.get("title") for m in results["rep_a"].cox_analyses]
    assert titles == ["Cox factorial model", "RMST factorial model"]
    cox = results["rep_a"].cox_analyses[0]
    assert cox["lr_interaction"]["p_value"] is not None
    assert "Genotype_mut:Treatment_drug" in " ".join(
        cox["coefficients"]["covariate"].astype(str))


def test_standard_lifespan_does_not_run_the_factorial_battery(tmp_path):
    directory = make_experiment_dir(tmp_path / "std", type_key="standard_lifespan")
    result = SurvivalExperiment(directory).run_analysis()
    assert result.cox_analyses == []


def test_declared_levels_survive_into_the_analysis(analysed_project):
    _project, results = analysed_project
    treatments = list(results["rep_a"].individual_data["treatment"].cat.categories)
    assert treatments[0] == "wt/ctrl"          # both Reference Levels
    assert treatments == ["wt/ctrl", "wt/drug", "mut/ctrl", "mut/drug"]


def test_data_that_contradicts_the_declaration_stops_the_run(tmp_path):
    directory = make_experiment_dir(tmp_path / "bad")
    config = cfgmod.load_config(directory)
    config["factors"] = {"Genotype": ["wt", "other"], "Treatment": ["ctrl", "drug"]}
    cfgmod.save_config(directory, config)
    with pytest.raises(ValueError, match="does not match its Interaction"):
        SurvivalExperiment(directory).run_analysis()


def test_run_summary_stamps_the_exclusion_group_and_count(tmp_path):
    directory = make_experiment_dir(tmp_path / "excl", type_key="standard_lifespan")
    exclusions.write_exclusions(directory, "review", [1, 2, 3])
    config = cfgmod.load_config(directory)
    config["exclusions"] = {"group": "review"}
    cfgmod.save_config(directory, config)

    experiment = SurvivalExperiment(directory)
    assert experiment.exclusion_group == "review"
    experiment.run_analysis()
    payload = json.loads(
        (directory / "analysis" / "run_summary.json").read_text(encoding="utf-8"))
    assert payload["exclusion_group"] == "review"
    # CSV cohorts have no chambers, so nothing is actually removed. The stamp
    # records the group that was in force and does not claim removals.
    assert payload["n_excluded"] == 0
    assert payload["n_excluded_listed"] == 3


def test_exclusions_are_written_into_qc(tmp_path):
    directory = make_experiment_dir(tmp_path / "qc_path")
    path = exclusions.write_exclusions(directory, "default", [7])
    assert path.parent.name == "qc"
    assert exclusions.chambers_for_group(directory, "default") == {7}


def test_a_legacy_root_exclusions_file_is_still_read(tmp_path):
    directory = make_experiment_dir(tmp_path / "legacy_excl")
    (directory / "remove_chambers.csv").write_text(
        "group,chamber,note\ndefault,4,old\n", encoding="utf-8")
    assert exclusions.chambers_for_group(directory, "default") == {4}


def test_direct_file_mode_keeps_the_legacy_output_convention(tmp_path):
    path = write_cohort(tmp_path / "loose" / "cohort.csv")
    result = pipeline.run_analysis(path, factor_cols=["Genotype", "Treatment"])
    assert result.output_dir.name == "cohort_results"
    assert (result.output_dir / "report.md").is_file()


def test_experiment_mode_writes_to_analysis(tmp_path):
    directory = make_experiment_dir(tmp_path / "exp", type_key="standard_lifespan")
    result = SurvivalExperiment(directory).run_analysis()
    assert result.output_dir == directory / "analysis"


# ── upgrade ────────────────────────────────────────────────────────────────

def _legacy_dir(tmp_path):
    directory = tmp_path / "old"
    write_cohort(directory / "cohort.csv")
    (directory / "remove_chambers.csv").write_text(
        "group,chamber,note\nreview,2,noisy\n", encoding="utf-8")
    (directory / "survival_scripts.yaml").write_text(
        "scripts:\n  - name: Quick\n    steps:\n      - {action: load_data}\n",
        encoding="utf-8")
    (directory / "cohort_results").mkdir()
    (directory / "cohort_results" / "report.md").write_text("old", encoding="utf-8")
    return directory


def test_upgrade_is_detected_and_described_before_it_runs(tmp_path):
    directory = _legacy_dir(tmp_path)
    assert upgrade.needs_upgrade(directory)
    plan = upgrade.plan(directory)
    assert any("survival_config.yaml" in a for a in plan.actions)
    assert any("qc/" in a for a in plan.actions)
    # Described, not done.
    assert not cfgmod.config_path(directory).is_file()


def test_upgrade_never_deletes_or_moves(tmp_path):
    directory = _legacy_dir(tmp_path)
    upgrade.apply(upgrade.plan(directory))

    assert (directory / "survival_scripts.yaml").is_file()   # left in place
    assert (directory / "remove_chambers.csv").is_file()     # copied, not moved
    assert (directory / "qc" / "remove_chambers.csv").is_file()
    assert (directory / "cohort_results" / "report.md").read_text() == "old"


def test_upgrade_imports_scripts_and_the_active_group(tmp_path):
    directory = _legacy_dir(tmp_path)
    upgrade.apply(upgrade.plan(directory))
    config = cfgmod.load_config(directory)
    assert [s["name"] for s in cfgmod.scripts_of(config)] == ["Quick"]
    assert config["exclusions"]["group"] == "review"
    assert config["input"]["format"] == "long"


def test_upgrade_seeds_the_default_script_unless_legacy_scripts_are_imported(tmp_path):
    from pysurvanalysis.script_editor.project_actions import (
        DEFAULT_EXPERIMENT_SCRIPT_NAME,
    )

    ## Legacy scripts are an authored block: imported as-is, not appended to.
    legacy = _legacy_dir(tmp_path)
    plan = upgrade.plan(legacy)
    assert [s["name"] for s in plan.proposed_config["scripts"]] == ["Quick"]
    assert not any("seed" in a for a in plan.actions)

    ## No scripts anywhere: the plan shows the seed and the file carries it.
    bare = tmp_path / "bare"
    write_cohort(bare / "cohort.csv")
    plan = upgrade.plan(bare)
    assert any(DEFAULT_EXPERIMENT_SCRIPT_NAME in a for a in plan.actions)
    upgrade.apply(plan)
    config = cfgmod.load_config(bare)
    assert [s["name"] for s in cfgmod.scripts_of(config)] == [DEFAULT_EXPERIMENT_SCRIPT_NAME]


def test_upgrading_an_upgraded_directory_is_a_no_op(tmp_path):
    directory = _legacy_dir(tmp_path)
    upgrade.apply(upgrade.plan(directory))
    assert not upgrade.needs_upgrade(directory)
    assert upgrade.plan(directory).is_noop


def test_the_analysis_figures_raise_no_warnings(tmp_path):
    """The risk-table figure warned that tight_layout 'results might be
    incorrect' on every run — its layout is hand-tuned, so nothing is left
    for tight_layout to guess at."""
    import warnings

    from pysurvanalysis import lifetable, plotting
    from tests.conftest import make_experiment_dir
    from pysurvanalysis.domain import SurvivalExperiment

    directory = make_experiment_dir(tmp_path / "e", type_key="standard_lifespan")
    data, _factors = SurvivalExperiment(directory).load()
    tables = lifetable.compute_lifetables(data)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        figure = plotting.plot_km_with_risk_table(tables)
    assert [str(w.message) for w in caught] == []
    assert figure.axes                       # both panels are really there
