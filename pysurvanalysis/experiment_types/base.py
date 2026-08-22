"""Experiment Types — the top-level thing a scientist chooses.

An Experiment Type constrains everything below it: the expected input shape,
the time unit and axis label, the censoring policy, the default quality
criteria, the analyses that run, the **Plot Set**, the report sections, and
the **Type Actions** it contributes to the Hub and the script registry
(ADR-0002).

A type declares its Plot Set as plain ids; :mod:`pysurvanalysis.plot_registry`
maps those ids to builders, so this module stays free of matplotlib and can be
imported by config validation and tests without the analysis stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlotDef:
    """One entry in a Plot Set: a registry id plus how to present it."""

    id: str
    label: str
    caption: str = ""


@dataclass(frozen=True)
class ReportSection:
    """One section of a type's report: a title and the block-builder key."""

    key: str
    title: str


class ExperimentType:
    """Base class and the Custom Experiment.

    The *absence* of an ``experiment_type`` key in ``survival_config.yaml`` IS
    a Custom Experiment: every discovered factor gets the full battery, and no
    action is withheld.
    """

    key: str = "custom"
    label: str = "Custom Experiment"
    description: str = (
        "No type chosen — all discovered factors get the full analysis "
        "battery and every action is available."
    )

    #: Default ``global:`` values a scaffolded config starts from.
    default_global: dict[str, Any] = {
        "time_unit": "hours",
        "time_label": "Age (hours)",
        "assume_censored": True,
    }

    #: Plot Set. Custom offers everything the registry knows.
    plot_set: tuple[PlotDef, ...] = ()

    #: The one figure that states the primary result; leads the report and is
    #: the Plot Editor's default. ``None`` means "no distinguished figure".
    headline_plot_id: str | None = None

    #: Keys of pooled/core actions this type re-exports into its registry.
    #: ``None`` means "every action in the pool" (Custom's behaviour).
    action_keys: tuple[str, ...] | None = None

    # ── identity ───────────────────────────────────────────────────────────

    @property
    def is_custom(self) -> bool:
        return self.key == "custom"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ExperimentType {self.key}>"

    # ── configuration ──────────────────────────────────────────────────────

    def scaffold_config(self, minimal: bool = False) -> dict:
        """A fresh ``survival_config.yaml`` body for this type.

        ``minimal=True`` omits everything a Project's ``defaults:`` already
        supplies. A member scaffolded from a Project must stay minimal, or it
        freezes today's defaults into its own config and later edits to the
        Project stop reaching it.
        """
        cfg: dict[str, Any] = {} if minimal else {"global": dict(self.default_global)}
        if not self.is_custom:
            cfg = {"experiment_type": self.key, **cfg}
        return cfg

    def owned_keys(self) -> set[str]:
        """``global:`` keys this type defines defaults for."""
        return set(self.default_global)

    def validate_config(self, config: dict) -> list[str]:
        """Return a list of human-readable problems with *config* (empty = ok)."""
        problems: list[str] = []
        g = config.get("global") or {}
        if not isinstance(g, dict):
            return ["`global:` must be a mapping."]
        unit = g.get("time_unit")
        if unit is not None and not isinstance(unit, str):
            problems.append("`global.time_unit` must be a string (e.g. days).")
        ac = g.get("assume_censored")
        if ac is not None and not isinstance(ac, bool):
            problems.append("`global.assume_censored` must be true or false.")
        return problems

    def validate_data(self, individual_data, config: dict) -> list[str]:
        """Problems visible only once the data is loaded (empty = ok)."""
        return []

    # ── presentation ───────────────────────────────────────────────────────

    def resolve_time_label(self, config: dict) -> str:
        g = config.get("global") or {}
        label = g.get("time_label")
        if label:
            return str(label)
        unit = g.get("time_unit") or self.default_global.get("time_unit", "hours")
        return f"Age ({unit})"

    def resolve_assume_censored(self, config: dict) -> bool:
        g = config.get("global") or {}
        value = g.get("assume_censored")
        if value is None:
            value = self.default_global.get("assume_censored", True)
        return bool(value)

    def plot_ids(self) -> tuple[str, ...]:
        """The Plot Set's ids, in order. Empty tuple = "everything"."""
        return tuple(p.id for p in self.plot_set)

    def report_title(self, experiment_name: str) -> str:
        return f"{experiment_name} — Survival Analysis"

    def report_intro(self) -> str | None:
        return None

    def report_sections(self) -> tuple[ReportSection, ...]:
        """Ordered sections the report builder walks for this type."""
        return (
            ReportSection("summary", "Experiment summary"),
            ReportSection("figures", "Figures"),
            ReportSection("lifespan", "Lifespan statistics"),
            ReportSection("tests", "Statistical tests"),
        )

    def ai_summary_prompt(self) -> str:
        return (
            "Summarize this survival analysis for a research audience. Describe "
            "what was measured, the survival differences between treatments, and "
            "which statistical comparisons reached significance. Summarize only "
            "the numbers given to you — never compute, infer, or speculate "
            "beyond them."
        )

    # ── contributed actions ────────────────────────────────────────────────

    def extra_actions(self) -> tuple:
        """Type Actions defined by this type (beyond the shared pool)."""
        return ()

    # ── analyses ───────────────────────────────────────────────────────────

    def run_extra_analyses(self, result, config: dict) -> list[dict]:
        """Type-specific analyses run as part of the standard battery.

        Returns model dicts shaped like
        :func:`pysurvanalysis.statistics.cox_interaction_analysis`'s output, so
        one report renderer handles them all.
        """
        return []

    # ── data preparation ───────────────────────────────────────────────────

    def prepare_data(self, individual_data, config: dict):
        """Hook to normalise the loaded frame (level ordering, labels…)."""
        return individual_data


#: Every plot id the general battery knows, in report order. Types name a
#: subset; Custom uses all of them.
ALL_PLOT_DEFS: tuple[PlotDef, ...] = (
    PlotDef("km_curves", "Kaplan-Meier curves", "Survivorship by treatment."),
    PlotDef("km_risk_table", "KM curves with at-risk table",
            "Survivorship with the number at risk beneath the axis."),
    PlotDef("nelson_aalen", "Nelson-Aalen cumulative hazard",
            "Cumulative hazard by treatment."),
    PlotDef("log_log", "Log-log diagnostic",
            "Parallel lines support the proportional-hazards assumption."),
    PlotDef("cumulative_events", "Cumulative deaths", "Cumulative event counts."),
    PlotDef("hazard", "Hazard rate", "Interval hazard rate."),
    PlotDef("smoothed_hazard", "Smoothed hazard", "Kernel-smoothed hazard rate."),
    PlotDef("mortality", "Mortality (qx)", "Interval mortality probability."),
    PlotDef("number_at_risk", "Number at risk", "Individuals at risk over time."),
    PlotDef("survival_distribution", "Lifespan distribution",
            "Distribution of individual lifespans by treatment."),
    PlotDef("hazard_ratio_forest", "Hazard-ratio forest",
            "Pairwise hazard ratios with 95% confidence intervals."),
    PlotDef("km_faceted", "Faceted Kaplan-Meier",
            "One panel per level of the first factor, curves coloured by the second."),
    PlotDef("interaction_lifespan", "Lifespan interaction plot",
            "Median lifespan by factor level; non-parallel lines indicate interaction."),
)
