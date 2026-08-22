"""Action/parameter primitives shared by the script registries and the
Experiment Types that contribute actions to them.

This module deliberately imports nothing heavy (no pandas, no matplotlib, no
pipeline) so an Experiment Type can declare its **Type Actions** — the Hub
buttons and the script steps mirroring them (ADR-0002) — without dragging the
analysis stack into config validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..ui import Category


@dataclass(frozen=True)
class ParamSpec:
    """Describes one parameter of an action.

    ``kind`` picks the inspector widget:

    * ``"string"`` → QLineEdit
    * ``"int"``    → QSpinBox
    * ``"float"``  → QDoubleSpinBox
    * ``"bool"``   → QCheckBox
    * ``"choice"`` → QComboBox (requires ``choices``)
    * ``"path"``   → QLineEdit + browse button
    * ``"list"``   → QLineEdit (comma-separated)
    * ``"factor"`` → QComboBox of factor names (resolved at runtime)
    * ``"factors"``→ QListWidget multi-select of factor names
    """

    name: str
    kind: str
    label: str
    default: Any = None
    help: str = ""
    choices: tuple[str, ...] | None = None
    min: float | None = None
    max: float | None = None
    enabled_when: str | None = None


@dataclass
class RunContext:
    """State threaded through an *experiment-level* script run.

    Experimental design (time/event columns, factor names) is read from the
    experiment's ``survival_config.yaml``; the context carries the loaded
    experiment and whatever the running script has computed so far.
    """

    project_dir: Any = None          # the Experiment Directory
    experiment: Any = None           # SurvivalExperiment, when one is loaded
    data: Any = None                 # individual-level DataFrame
    factors: list[str] | None = None
    lifetables: Any = None
    result: Any = None               # AnalysisResult from run_analysis
    log: Callable[[str], None] = lambda _msg: None
    figure: Callable[[str, Any], None] = lambda _title, _fig: None
    excluded_chambers: set | None = None
    exclusion_group: str | None = None
    assume_censored: bool = True
    input_format: str = "excel"      # excel | csv | csv_long | csv_wide
    wide_factor_names: list[str] | None = None


@dataclass
class ProjectRunContext:
    """State threaded through a *project-level* script run.

    Holds the loaded Project, never an experiment — the two registries cannot
    mix by construction (ADR-0006 in the sister app; same rule here).
    """

    project: Any = None
    log: Callable[[str], None] = lambda _msg: None
    figure: Callable[[str, Any], None] = lambda _title, _fig: None
    failures: list[str] = field(default_factory=list)


@dataclass
class Action:
    key: str
    title: str
    description: str
    category: Category
    icon_name: str
    params: tuple[ParamSpec, ...] = ()
    execute_fn: Callable[[dict, Any], None] | None = None
    applicable_formats: tuple[str, ...] | None = None
    #: True when this action is contributed by an Experiment Type rather than
    #: living in the core registry (used by the palette to group and label).
    from_type: bool = False

    def execute(self, params: dict, ctx: Any) -> None:
        if self.execute_fn is None:
            raise NotImplementedError(f"Action {self.key!r} has no execute function")
        merged: dict[str, Any] = {}
        for spec in self.params:
            if spec.name in params:
                merged[spec.name] = params[spec.name]
            elif spec.default is not None:
                merged[spec.name] = spec.default
        self.execute_fn(merged, ctx)
