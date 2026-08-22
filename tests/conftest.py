"""Shared fixtures: synthetic cohorts and scaffolded directories.

Everything here is CSV-based and small, so the structural suite runs in
seconds and never depends on a workbook that might move.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pysurvanalysis.domain import Project, config as cfgmod


def write_cohort(path, *, factors=None, n_per_cell=25, seed=0):
    """A long-format CSV cohort with the given factor levels."""
    factors = factors or {"Genotype": ["wt", "mut"], "Treatment": ["ctrl", "drug"]}
    rng = np.random.default_rng(seed)
    names = list(factors)
    rows = []
    for i, level_a in enumerate(factors[names[0]]):
        for j, level_b in enumerate(factors[names[1]]):
            scale = 40.0 + 10.0 * i - 8.0 * j
            times = rng.gamma(shape=6.0, scale=scale / 6.0, size=n_per_cell)
            for k, t in enumerate(times):
                rows.append({
                    "Age": round(float(t), 3),
                    "Event": 0 if k % 20 == 0 else 1,   # a few censored
                    names[0]: level_a,
                    names[1]: level_b,
                })
    frame = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def make_experiment_dir(directory, *, type_key="interaction", factors=None,
                        n_per_cell=25, seed=0, exclusion_group=None,
                        minimal=False):
    """A ready-to-analyse Experiment Directory.

    ``minimal=True`` writes the member config a Project would scaffold — no
    ``global:`` of its own, so the Project's defaults are what is under test.
    """
    from pysurvanalysis.experiment_types import get_type

    factors = factors or {"Genotype": ["wt", "mut"], "Treatment": ["ctrl", "drug"]}
    directory.mkdir(parents=True, exist_ok=True)
    write_cohort(directory / "data" / "cohort.csv", factors=factors,
                 n_per_cell=n_per_cell, seed=seed)
    config = get_type(type_key).scaffold_config(minimal=minimal)
    config["input"] = {"format": "long", "time_col": "Age", "event_col": "Event"}
    if type_key == "interaction":
        config["factors"] = factors
    if exclusion_group:
        config["exclusions"] = {"group": exclusion_group}
    cfgmod.save_config(directory, config)
    return directory


@pytest.fixture
def project(tmp_path):
    """A Project with two Interaction members that diverge in level order."""
    root = tmp_path / "proj"
    Project.create(root, name="Test project", question="Does the drug help?",
                   type_key="interaction")
    make_experiment_dir(root / "rep_a", seed=1, minimal=True)
    make_experiment_dir(root / "rep_b", seed=2, minimal=True,
                        factors={"Genotype": ["mut", "wt"],
                                 "Treatment": ["ctrl", "drug"]})
    return Project(root)


@pytest.fixture
def standalone(tmp_path):
    """A standalone Experiment Directory with no Project above it."""
    from pysurvanalysis.domain import SurvivalExperiment

    directory = make_experiment_dir(tmp_path / "lone", type_key="standard_lifespan")
    return SurvivalExperiment(directory)


@pytest.fixture(scope="session")
def analysed_project(tmp_path_factory):
    """A Project whose members are analysed exactly once for the whole session.

    The factorial battery (Cox + the RMST jackknife) is the slowest thing in
    the suite; sharing one run keeps the report tests fast without weakening
    what they assert.
    """
    root = tmp_path_factory.mktemp("analysed")
    Project.create(root, name="Analysed project",
                   question="Does the drug help?", type_key="interaction")
    make_experiment_dir(root / "rep_a", seed=1, minimal=True)
    make_experiment_dir(root / "rep_b", seed=2, minimal=True,
                        factors={"Genotype": ["mut", "wt"],
                                 "Treatment": ["ctrl", "drug"]})
    project = Project(root)
    results = {m.name: m.run_analysis() for m in project.members()}
    return project, results
