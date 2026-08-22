"""Experiment Type registry.

``experiment_type`` in ``survival_config.yaml`` names one of these by key; the
absence of the key IS the Custom Experiment.
"""

from __future__ import annotations

from .base import ALL_PLOT_DEFS, ExperimentType, PlotDef, ReportSection
from .interaction import InteractionExperimentType
from .standard import StandardLifespanType

CUSTOM = ExperimentType()

_TYPES: dict[str, ExperimentType] = {
    StandardLifespanType.key: StandardLifespanType(),
    InteractionExperimentType.key: InteractionExperimentType(),
}


def available_types() -> list[ExperimentType]:
    """Selectable types, Custom last."""
    return [_TYPES[k] for k in sorted(_TYPES)] + [CUSTOM]


def type_keys() -> list[str]:
    return sorted(_TYPES)


def get_type(key: str | None) -> ExperimentType:
    """Resolve a type key. ``None``/empty/``"custom"`` → the Custom Experiment.

    An unknown key is an error rather than a silent fallback: a config naming a
    type this build doesn't have must not be analysed as though it were
    freeform.
    """
    if key is None or str(key).strip() == "" or str(key).strip().lower() == "custom":
        return CUSTOM
    try:
        return _TYPES[str(key).strip().lower()]
    except KeyError:
        raise ValueError(
            f"Unknown experiment_type {key!r}. Known types: "
            f"{', '.join(sorted(_TYPES))}, or omit the key for a Custom Experiment."
        ) from None


def type_for_config(config: dict) -> ExperimentType:
    """The Experiment Type a ``survival_config.yaml`` body selects."""
    return get_type((config or {}).get("experiment_type"))


__all__ = [
    "ALL_PLOT_DEFS",
    "CUSTOM",
    "ExperimentType",
    "InteractionExperimentType",
    "PlotDef",
    "ReportSection",
    "StandardLifespanType",
    "available_types",
    "get_type",
    "type_for_config",
    "type_keys",
]
