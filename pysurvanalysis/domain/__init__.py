"""Domain objects: Batch → Project → Experiment Directory.

The one structural divergence from PyTrackingAnalysis: a Project binds
independent analyses and never pools them (ADR-0001).
"""

from .batch import Batch, BatchResult, ProjectOutcome
from .config import (
    BATCH_FILENAME,
    CONFIG_FILENAME,
    PROJECT_FILENAME,
    SPECS_FILENAME,
    exclusion_group,
    input_options,
    is_experiment_dir,
    load_config,
    merge_defaults,
    save_config,
    validate_config,
)
from .experiment import ExperimentError, ExperimentStatus, SurvivalExperiment
from .project import Divergence, Project, ProjectError, find_project_root, is_project_dir
from . import upgrade

__all__ = [
    "BATCH_FILENAME",
    "Batch",
    "BatchResult",
    "CONFIG_FILENAME",
    "Divergence",
    "ExperimentError",
    "ExperimentStatus",
    "PROJECT_FILENAME",
    "Project",
    "ProjectError",
    "ProjectOutcome",
    "SPECS_FILENAME",
    "SurvivalExperiment",
    "exclusion_group",
    "find_project_root",
    "input_options",
    "is_experiment_dir",
    "is_project_dir",
    "load_config",
    "merge_defaults",
    "save_config",
    "upgrade",
    "validate_config",
]
