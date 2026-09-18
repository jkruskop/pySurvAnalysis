"""Publication Figures — plotnine renderings of survivorship from a Spec+Style.

Two files, split by what varies (ADR-0005): the **Project's**
``plot_specs.yaml`` owns ``styles:`` and ``default_style:`` — the shared look —
and each **Experiment Directory's** ``plot_specs.yaml`` owns ``plots:``, whose
style names resolve upward (member → project → built-in).

The at-risk counts are a ``geom_text`` layer in a reserved band below the curves
rather than a second axes (ADR-0004: the **At-Risk Band**), so a figure stays
one grammar object and faceting, theming and vector export need no composition
step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .domain import config as cfgmod

#: Brand-neutral, colour-blind-safe default cycle.
DEFAULT_PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52",
    "#8172B3", "#937860", "#DA8BC3", "#8C8C8C",
]

THEMES = ("theme_classic", "theme_bw", "theme_minimal", "theme_light", "theme_matplotlib")


# ---------------------------------------------------------------------------
# Style and Spec
# ---------------------------------------------------------------------------

@dataclass
class PlotStyle:
    """A named, reusable look shared by every figure that references it."""

    name: str = "default"

    # ── canvas ─────────────────────────────────────────────────────────────
    width_mm: float = 120.0
    height_mm: float = 90.0
    theme: str = "theme_classic"
    #: Empty = the theme's own panel fill. A colour overrides it.
    panel_bg: str = ""
    panel_border: bool = False
    #: Gridlines the survival themes suppress by default: none | y | both.
    grid: str = "none"

    # ── type ───────────────────────────────────────────────────────────────
    font_family: str = "DejaVu Sans"
    #: The size every unset size below is derived from.
    base_size: float = 9.0
    #: Per-element font sizes in points. 0 = derive from ``base_size``, so a
    #: style that only sets the base still scales as a whole — the override is
    #: for the one element that has to differ (a long title, cramped ticks).
    title_pt: float = 0.0
    axis_title_pt: float = 0.0
    tick_pt: float = 0.0
    legend_pt: float = 0.0
    strip_pt: float = 0.0
    #: Colour for ALL text — title, axis titles, ticks, legend, strips.
    text_color: str = "#000000"

    # ── curves ─────────────────────────────────────────────────────────────
    line_width: float = 0.9
    #: How the knots are joined: ``auto`` follows the plot kind (a KM curve
    #: IS a step function; a smoothed hazard is not), ``step`` and ``line``
    #: override it either way.
    line_style: str = "auto"          # auto | step | line
    #: Weight (pt) of axis lines, ticks and panel/strip borders — the figure's
    #: furniture, which is not the same decision as the curve's own weight.
    line_pt: float = 0.8

    # ── points on the curve ────────────────────────────────────────────────
    #: Markers on the step curve. Off by default: a lifespan cohort has an
    #: event at nearly every day, and a marker per event buries the curve.
    show_points: bool = False
    #: Which knots get one: events | censored | all.
    point_at: str = "events"
    point_shape: str = "o"
    point_size: float = 2.0
    point_alpha: float = 1.0
    #: Outline weight around each point. 0 = no outline (drawn solid in the
    #: curve colour); >0 = an edge of this weight with ``point_fill`` inside.
    point_stroke: float = 0.0
    #: Outline colour. Empty = the curve's own colour.
    point_stroke_color: str = "#000000"
    #: Interior. Empty = the curve's colour; "none" = hollow; else a hex.
    point_fill: str = ""

    # ── censor ticks ───────────────────────────────────────────────────────
    #: Kaplan-Meier censor ticks, drawn as short vertical marks on the curve.
    censor_ticks: bool = True
    censor_size: float = 2.0
    censor_shape: str = "|"
    #: Empty = the curve's own colour.
    censor_color: str = ""

    # ── confidence band ────────────────────────────────────────────────────
    ci_band: bool = False
    ci_alpha: float = 0.15

    # ── facet strips ───────────────────────────────────────────────────────
    #: Bare text ("plain") or ggplot's bordered title box ("boxed").
    strip_style: str = "plain"
    strip_bg: str = "#d9d9d9"

    legend_position: str = "right"

    #: The At-Risk Band: counts as text in reserved space below the curves.
    risk_table: bool = True
    risk_table_times: list[float] = field(default_factory=list)
    risk_row_height: float = 0.075
    risk_font_size: float = 7.0

    # ── colour ─────────────────────────────────────────────────────────────
    #: treatment (or curve label) → hex colour; unlisted labels take the cycle.
    palette: dict[str, str] = field(default_factory=dict)
    #: The cycle unlisted labels take, in order. Editable, so a style can
    #: carry a journal's palette without naming every treatment in advance.
    palette_cycle: list[str] = field(default_factory=lambda: list(DEFAULT_PALETTE))

    @classmethod
    def from_dict(cls, name: str, data: dict | None) -> "PlotStyle":
        known = {f.name for f in fields(cls)}
        payload = {k: v for k, v in (data or {}).items() if k in known}
        payload["name"] = name
        return cls(**payload)

    def to_dict(self) -> dict:
        out = asdict(self)
        out.pop("name", None)
        return out

    def colour_for(self, labels: list[str]) -> dict[str, str]:
        """Resolve every label to a colour, honouring explicit assignments."""
        out: dict[str, str] = {}
        cycle = [c for c in (self.palette_cycle or DEFAULT_PALETTE)]
        for i, label in enumerate(labels):
            out[label] = self.palette.get(label) or cycle[i % len(cycle)]
        return out

    def size_of(self, element: str) -> float:
        """The point size for one text element, falling back to ``base_size``.

        Each override is 0 by default and 0 means "follow the base", so a
        style that only sets ``base_size`` still scales as one thing — which
        is the common case, and the reason these are not simply five
        independent numbers.
        """
        offsets = {"title": 2.0, "strip": 1.0}
        explicit = float(getattr(self, f"{element}_pt", 0.0) or 0.0)
        if explicit > 0:
            return explicit
        return float(self.base_size) + offsets.get(element, 0.0)


@dataclass
class PlotSpec:
    """One figure's content decisions, plus the Style it uses."""

    plot_id: str = "km"
    style: str = "default"
    title: str = ""
    x_label: str = "Age"
    y_label: str = "Survival probability"
    #: Curves to include, in order. Empty = every treatment in the data.
    treatments: list[str] = field(default_factory=list)
    #: treatment → display name shown in the legend.
    display_names: dict[str, str] = field(default_factory=dict)
    #: Legend title for the curves. Faceting splits by factor 1, so the
    #: curves are factor 2 — naming it "Treatment" would be wrong.
    series_label: str = "Treatment"
    #: Facet the panel by a factor column (the Interaction Experiment's
    #: headline figure facets by its first factor).
    facet_by: str = ""
    facet_order: list[str] = field(default_factory=list)
    x_limits: list[float] = field(default_factory=list)
    y_limits: list[float] = field(default_factory=list)
    #: Horizontal reference line, e.g. 0.5 for median survival.
    reference_line: float | None = None

    @classmethod
    def from_dict(cls, plot_id: str, data: dict | None) -> "PlotSpec":
        known = {f.name for f in fields(cls)}
        payload = {k: v for k, v in (data or {}).items() if k in known}
        payload["plot_id"] = plot_id
        return cls(**payload)

    def to_dict(self) -> dict:
        out = asdict(self)
        out.pop("plot_id", None)
        return out


BUILTIN_STYLE = PlotStyle()


def default_spec(plot_id: str = "km", time_label: str = "Age") -> PlotSpec:
    """A sensible starting Spec for one figure.

    The median-survival reference (0.5) is seeded only where the y axis is a
    survival probability — on a hazard rate or a count it marks nothing, and
    the checkbox that now governs the line should start unchecked there.
    """
    kind = PLOT_KINDS.get(plot_id, PLOT_KINDS["km_curves"])
    survivalish = kind.y == "km_lx"
    ## Axis labels come from the KIND, not the PlotSpec class default: a
    ## mortality spec born saying "Survival probability" renders with the
    ## wrong axis, and the class default is a KM label.
    x_label = f"log({time_label})" if kind.x == "log_time" else time_label
    return PlotSpec(plot_id=plot_id, x_label=x_label,
                    y_label=kind.y_label or "Survival probability", title="",
                    reference_line=0.5 if survivalish else None)


# ---------------------------------------------------------------------------
# Reading and writing the two files
# ---------------------------------------------------------------------------

@dataclass
class ProjectSpecs:
    """The parsed ``plot_specs.yaml``: the Style library, the default Style,
    and the per-plot Specs.

    **Both halves live in one file at the container** — the Project when there
    is one, the Experiment Directory itself for a standalone (ADR-0003). That
    is the sister app's model, adopted here: a Spec is as much a shared
    editorial decision as a Style (the same axis labels, the same treatment
    order, the same reference line across every member), and splitting them
    meant curating one figure per member by hand.
    """

    default_style: str = "default"
    styles: dict[str, PlotStyle] = field(default_factory=dict)
    plots: dict[str, PlotSpec] = field(default_factory=dict)

    def style_for(self, spec: PlotSpec) -> PlotStyle:
        return (self.styles.get(spec.style)
                or self.styles.get(self.default_style)
                or BUILTIN_STYLE)

    def ensure_default_style(self) -> None:
        if not self.styles:
            self.styles["default"] = PlotStyle()
        if self.default_style not in self.styles:
            self.default_style = next(iter(self.styles))


def specs_root(experiment) -> Path:
    """Where *experiment*'s ``plot_specs.yaml`` lives.

    The Project, so every member shares one library — or the experiment's own
    directory when it has no Project, which the sister app never has to
    handle because a replicate there cannot exist outside one (ADR-0003).
    """
    project = getattr(experiment, "project", None)
    if project is not None:
        return Path(project.directory)
    return Path(experiment.directory)


def load_project_specs(root: str | Path | None) -> ProjectSpecs:
    """Read a container's ``plot_specs.yaml``."""
    if root is None:
        specs = ProjectSpecs()
        specs.ensure_default_style()
        return specs
    raw = cfgmod.read_yaml(Path(root) / cfgmod.SPECS_FILENAME)
    specs = ProjectSpecs(
        default_style=str(raw.get("default_style") or "default"),
        styles={str(k): PlotStyle.from_dict(str(k), v)
                for k, v in (raw.get("styles") or {}).items()
                if isinstance(v, dict)},
        plots={str(k): PlotSpec.from_dict(str(k), v)
               for k, v in (raw.get("plots") or {}).items()
               if isinstance(v, dict) and str(k) in PLOT_TYPES},
    )
    specs.plots = migrate_specs(specs.plots)
    specs.ensure_default_style()
    return specs


def save_project_specs(root: str | Path, specs: ProjectSpecs) -> Path:
    """Write both halves back to the container's ``plot_specs.yaml``.

    Unknown top-level keys are preserved, the way a config write is: this file
    is hand-editable and a future version may add to it.
    """
    specs.ensure_default_style()
    path = Path(root) / cfgmod.SPECS_FILENAME
    data = cfgmod.read_yaml(path)
    data["default_style"] = specs.default_style
    data["styles"] = {k: v.to_dict() for k, v in specs.styles.items()}
    data["plots"] = {k: v.to_dict() for k, v in specs.plots.items()}
    return cfgmod.write_yaml(path, data)


def adopt_legacy_member_specs(experiment) -> ProjectSpecs:
    """The container's specs, plus any a member curated under the old layout.

    Specs used to be written into the *member's* own ``plot_specs.yaml``.
    Those are real curation, so they are lifted into the container rather
    than ignored — but only for plot ids the container has no Spec for, since
    a Spec chosen for the whole Project outranks one inherited from whichever
    member happens to be opened first.
    """
    root = specs_root(experiment)
    specs = load_project_specs(root)
    own_dir = Path(experiment.directory)
    if own_dir == root:
        return specs
    legacy = load_project_specs(own_dir).plots
    for plot_id, spec in legacy.items():
        specs.plots.setdefault(plot_id, spec)
    return specs


# ── the older, narrower API, kept for callers that ask one question ────────

def load_styles(root: str | Path | None) -> tuple[dict[str, PlotStyle], str]:
    """A container's Style library and the name of its default."""
    specs = load_project_specs(root)
    return specs.styles, specs.default_style


def save_styles(root: str | Path, styles: dict[str, PlotStyle],
                default_style: str = "default") -> Path:
    specs = load_project_specs(root)
    specs.styles = dict(styles)
    specs.default_style = default_style
    return save_project_specs(root, specs)


def load_specs(root: str | Path) -> dict[str, PlotSpec]:
    """A container's Specs, keyed by plot id."""
    return load_project_specs(root).plots


def save_specs(root: str | Path, specs: dict[str, PlotSpec]) -> Path:
    project_specs = load_project_specs(root)
    project_specs.plots = dict(specs)
    return save_project_specs(root, project_specs)


def migrate_specs(specs: dict[str, PlotSpec]) -> dict[str, PlotSpec]:
    """Fold retired Spec ids onto the ones that replaced them.

    A Spec saved under a retired id still holds the labels and treatment
    order somebody curated; dropping it would silently discard that work, and
    keeping it would show the duplicate this rename exists to remove. It is
    only adopted when the surviving id has no Spec of its own — an explicit
    one always wins over an inherited alias.
    """
    out = dict(specs)
    for old_id, new_id in _SPEC_ALIASES.items():
        spec = out.pop(old_id, None)
        if spec is not None and new_id not in out:
            spec.plot_id = new_id
            out[new_id] = spec
    return out


def resolve_style(name: str, experiment) -> PlotStyle:
    """Resolve a style name at the container, then the built-in.

    One lookup now, not two: with both halves in the container's file there is
    no member-level library to fall back from.
    """
    specs = load_project_specs(specs_root(experiment))
    if name in specs.styles:
        return specs.styles[name]
    return specs.styles.get(specs.default_style, BUILTIN_STYLE)


def specs_for(experiment) -> dict[str, PlotSpec]:
    """The Specs to offer for an experiment: the container's, plus defaults
    for every plot in its Experiment Type's Plot Set that has none yet."""
    specs = adopt_legacy_member_specs(experiment)
    return fill_default_specs(specs.plots, experiment)


def fill_default_specs(saved: dict[str, PlotSpec], experiment) -> dict[str, PlotSpec]:
    """*saved*, plus a default Spec for every renderable plot in the type's
    Plot Set that has none."""
    time_label = experiment.type.resolve_time_label(experiment.config)
    factors = list((experiment.config.get("factors") or {}))
    out = dict(saved)
    for plot_id in (experiment.type.plot_ids() or ("km_curves",)):
        plot_id = _SPEC_ALIASES.get(plot_id, plot_id)
        if plot_id not in PLOT_TYPES or plot_id in out:
            continue
        spec = default_spec(plot_id, time_label)
        if PLOT_KINDS[plot_id].faceted:
            spec.facet_by = factors[0] if factors else ""
            if len(factors) > 1:
                spec.series_label = factors[1]
        out[plot_id] = spec
    return out


# ---------------------------------------------------------------------------
# What each plot is made of
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlotKind:
    """How one plot id is drawn: where its data comes from, what is on the y
    axis, and which of the Style's features mean anything for it.

    ``supports`` is what makes the editor honest. A censor tick on a hazard
    curve or an at-risk band under a forest plot is not a setting anybody
    wants greyed-in-but-ignored, so the controls that do not apply are
    disabled rather than silently doing nothing.
    """

    source: str                 # lifetables | individual | hazard_ratios
    geom: str                   # step | line | forest | distribution | interaction
    y: str = ""                 # lifetable column, for the series geoms
    y_label: str = ""
    #: x column. ``log_time`` for the log-log diagnostic, which is the one
    #: plot whose x axis is a transform rather than the time itself.
    x: str = "time"
    #: (lower, upper) lifetable columns for the confidence band, when the
    #: estimator publishes one.
    ci: tuple[str, str] | None = None
    #: (x, y) knot prepended to every series, or None when the plot has no
    #: natural origin — survivorship starts at 1, cumulative hazard at 0, but
    #: an interval rate has no value before the first interval.
    origin: tuple[float, float] | None = None
    faceted: bool = False
    supports: frozenset = frozenset()


#: Everything the Style can offer, per feature, so a kind names what it uses.
_CI = "ci"; _CENSOR = "censor"; _RISK = "risk"; _POINTS = "points"
_SERIES_FEATURES = frozenset({_POINTS})
_KM_FEATURES = frozenset({_CI, _CENSOR, _RISK, _POINTS})

PLOT_KINDS: dict[str, PlotKind] = {
    "km_curves": PlotKind("lifetables", "step", "km_lx", "Survival probability",
                          origin=(0.0, 1.0), ci=("km_ci_lo", "km_ci_hi"),
                          supports=_KM_FEATURES),
    "km_faceted": PlotKind("lifetables", "step", "km_lx", "Survival probability",
                           origin=(0.0, 1.0), ci=("km_ci_lo", "km_ci_hi"),
                           faceted=True, supports=_KM_FEATURES),
    "nelson_aalen": PlotKind("lifetables", "step", "na_H",
                             "Cumulative hazard", origin=(0.0, 0.0),
                             ci=("na_ci_lo", "na_ci_hi"),
                             supports=_SERIES_FEATURES | {_CI}),
    "number_at_risk": PlotKind("lifetables", "step", "n_at_risk",
                               "Individuals at risk",
                               supports=_SERIES_FEATURES),
    "cumulative_events": PlotKind("lifetables", "step", "cum_deaths",
                                  "Cumulative deaths", origin=(0.0, 0.0),
                                  supports=_SERIES_FEATURES),
    "mortality": PlotKind("lifetables", "line", "qx",
                          "Mortality (qx)", supports=_SERIES_FEATURES),
    "hazard": PlotKind("lifetables", "line", "hx", "Hazard rate",
                       supports=_SERIES_FEATURES),
    "smoothed_hazard": PlotKind("lifetables", "line", "hx_smooth",
                                "Smoothed hazard", supports=_SERIES_FEATURES),
    "log_log": PlotKind("lifetables", "step", "log_neg_log",
                        "log(−log S(t))", x="log_time",
                        supports=_SERIES_FEATURES),
    "survival_distribution": PlotKind("individual", "distribution",
                                      y_label="Density"),
    "hazard_ratio_forest": PlotKind("hazard_ratios", "forest",
                                    y_label="Comparison"),
    "interaction_lifespan": PlotKind("individual", "interaction",
                                     y_label="Median lifespan"),
}

#: Plot ids the publication renderer can draw — the whole Plot Set of every
#: Experiment Type, so anything the Plots panel offers can also be curated.
PLOT_TYPES: tuple[str, ...] = tuple(PLOT_KINDS)

#: Saved Specs whose id no longer exists, and what they become.
#:
#: ``km_risk_table`` was a second name for ``km_curves``. On the matplotlib
#: side it is a real second figure (``plot_km_with_risk_table`` against
#: ``plot_km_curves``), but here the At-Risk Band is a **Style** toggle, so
#: the two rendered byte-identical output and differed in nothing but a name.
#: The Spec's content decisions are still wanted; only its id was a duplicate.
_SPEC_ALIASES = {"km_risk_table": "km_curves"}


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def kind_for(spec_or_id) -> PlotKind:
    """The :class:`PlotKind` for a Spec or a plot id, defaulting to the KM
    curve so an unknown id renders as something rather than raising."""
    plot_id = getattr(spec_or_id, "plot_id", spec_or_id)
    return PLOT_KINDS.get(str(plot_id), PLOT_KINDS["km_curves"])


def treatments_selectable(spec_or_id) -> bool:
    """Whether ``spec.treatments`` actually narrows this kind's data.

    True for every series-shaped and distribution plot (:func:`series_data`,
    :func:`distribution_data`); false for the forest, which draws every saved
    comparison, and the interaction plot, which draws every factorial cell —
    neither reads the field.
    """
    kind = kind_for(spec_or_id)
    return kind.geom != "interaction" and kind.source != "hazard_ratios"


def _derived(grp: pd.DataFrame, kind: PlotKind, smoothing: float = 3.0) -> pd.DataFrame:
    """Add whatever column *kind* wants that the lifetable does not carry."""
    grp = grp.sort_values("time").copy()
    if kind.y == "cum_deaths":
        grp["cum_deaths"] = grp["n_deaths"].cumsum()
    elif kind.y == "hx_smooth":
        ## The same Gaussian kernel and bandwidth the analyst figure uses
        ## (``plotting.plot_smoothed_hazard``), so the publication figure is
        ## the same estimate in a different coat — not a second one.
        from scipy.ndimage import gaussian_filter1d

        values = grp["hx"].to_numpy(dtype=float)
        grp["hx_smooth"] = (gaussian_filter1d(values, sigma=smoothing)
                            if len(values) >= 5 else values)
    elif kind.y == "log_neg_log":
        ## Defined only where survival is strictly between 0 and 1 and time is
        ## positive: log(0) and log(-log(1)) are both infinite, and a curve
        ## running off to infinity is not a diagnostic.
        grp = grp[(grp["km_lx"] > 0) & (grp["km_lx"] < 1) & (grp["time"] > 0)]
        grp = grp.copy()
        grp["log_neg_log"] = np.log(-np.log(grp["km_lx"].to_numpy(dtype=float)))
        grp["log_time"] = np.log(grp["time"].to_numpy(dtype=float))
    return grp


def _facet_split(spec: PlotSpec, factors: tuple[str, ...]) -> tuple[int, int]:
    """Which half of a composite ``a/b`` treatment label is the facet.

    ``facet_by`` names a FACTOR, and the composite label is factor 1's level
    ``/`` factor 2's level — so naming factor 2 puts part 1 in the panels and
    part 0 on the curves. The name used to be ignored entirely (any non-empty
    string faceted by factor 1), which made the editor's field a decoy.
    An unknown name keeps the factor-1 default rather than failing a render.
    """
    if len(factors) > 1 and spec.facet_by == str(factors[1]):
        return 1, 0
    return 0, 1


def _apply_facet(data: pd.DataFrame, spec: PlotSpec,
                 factors: tuple[str, ...]) -> pd.DataFrame:
    """Split composite treatment labels into panel and series columns."""
    parts = data["treatment"].str.split("/", n=1, expand=True)
    if parts.shape[1] == 2:
        facet_part, series_part = _facet_split(spec, factors)
        data["_facet"] = parts[facet_part]
        data["_series"] = parts[series_part]
        data["label"] = data["_series"].map(
            lambda s: spec.display_names.get(s, s))
    return data


def series_data(lifetables: pd.DataFrame, spec: PlotSpec,
                kind: PlotKind | None = None,
                factors: tuple[str, ...] = ()) -> pd.DataFrame:
    """Per-treatment ``(x, value)`` knots for one series-shaped plot.

    One preparation for nine plots: they differ in which lifetable column is
    on the y axis, whether there is a value before the first event, and
    whether the estimator publishes a confidence band — not in how the series
    are selected, ordered, renamed or facetted.
    """
    kind = kind or kind_for(spec)
    lt = lifetables.copy()
    lt["treatment"] = lt["treatment"].astype(str)
    wanted = [t for t in (spec.treatments or [])
              if t in set(lt["treatment"])] or sorted(set(lt["treatment"]))

    frames: list[pd.DataFrame] = []
    for treatment in wanted:
        grp = _derived(lt[lt["treatment"] == treatment], kind)
        if grp.empty:
            continue
        x = grp[kind.x].to_numpy(dtype=float)
        y = grp[kind.y].to_numpy(dtype=float)
        lo, hi = ((grp[kind.ci[0]].to_numpy(dtype=float),
                   grp[kind.ci[1]].to_numpy(dtype=float)) if kind.ci
                  else (y, y))
        censored = grp["n_censored"].to_numpy()
        risk = grp["n_at_risk"].to_numpy()

        if kind.origin is not None:
            ## plotnine's geom_step needs the origin point explicitly; without
            ## it the first segment starts at the first event and the figure
            ## silently lies about what happened before it.
            ox, oy = kind.origin
            x = np.concatenate([[ox], x])
            y = np.concatenate([[oy], y])
            lo = np.concatenate([[oy], lo])
            hi = np.concatenate([[oy], hi])
            censored = np.concatenate([[0], censored])
            risk = np.concatenate([[risk[0] if len(risk) else 0], risk])

        block = pd.DataFrame({
            "time": x, "value": y, "ci_lo": lo, "ci_hi": hi,
            "n_censored": censored, "n_risk": risk,
        })
        block["treatment"] = treatment
        block["label"] = spec.display_names.get(treatment, treatment)
        frames.append(block)

    if not frames:
        return pd.DataFrame(columns=["time", "value", "treatment", "label"])
    data = pd.concat(frames, ignore_index=True)
    if spec.facet_by:
        data = _apply_facet(data, spec, factors)
    return data


def curve_data(lifetables: pd.DataFrame, spec: PlotSpec) -> pd.DataFrame:
    """Kaplan-Meier step coordinates — :func:`series_data` for a KM Spec.

    Kept as its own name because it is what every KM caller asks for, and
    because a Spec whose id is not a series plot at all must still get curve
    coordinates when something asks for curves.
    """
    kind = kind_for(spec)
    if kind.source != "lifetables":
        kind = PLOT_KINDS["km_curves"]
    return series_data(lifetables, spec, kind)


def step_expand(data: pd.DataFrame, group_cols: tuple[str, ...] = ("treatment",),
                value_cols: tuple[str, ...] = ("ci_lo", "ci_hi"),
                time_col: str = "time") -> pd.DataFrame:
    """Duplicate rows so a ribbon drawn over *data* is a staircase.

    ``geom_step`` draws the curve; ``geom_ribbon`` has no step of its own
    (plotnine's ribbon takes ``outline_type`` and nothing else), so the band
    has to arrive already stepped or it is drawn as straight lines between
    knots — an interval nobody computed, and visibly detached from the curve
    it is supposed to bound.

    Matches ``geom_step``'s default ``direction="hv"``: each value is held
    from its own time until the next one, so for consecutive knots
    ``(t0, y0), (t1, y1)`` the band emits ``(t0, y0), (t1, y0), (t1, y1)``.
    """
    if data.empty:
        return data
    groups = [c for c in group_cols if c in data.columns]
    values = [c for c in value_cols if c in data.columns]
    if not values:
        return data

    out: list[pd.DataFrame] = []
    for _key, grp in (data.groupby(list(groups), sort=False) if groups
                      else [(None, data)]):
        grp = grp.sort_values(time_col)
        ## The horizontal run of each segment: this row's value carried
        ## forward to the next row's time. The last row has no "next", so it
        ## contributes only its own knot.
        held = grp.iloc[:-1].copy()
        held[time_col] = grp[time_col].to_numpy()[1:]
        ## Held rows FIRST, then the knots, then a stable sort: at a time that
        ## now appears twice the carried-forward value has to come before the
        ## new one, or the ribbon's vertical edge is drawn on the wrong side
        ## of the step and the band leans away from its curve.
        out.append(pd.concat([held, grp], ignore_index=True)
                   .sort_values([time_col], kind="stable"))
    return pd.concat(out, ignore_index=True)


#: Marker shapes offered in the editor. The filled ones come first because
#: only they can show an outline — an unfilled shape has no interior for
#: ``point_fill`` to colour, so a stroke on one is just a thicker mark.
POINT_SHAPES = ("o", "s", "^", "v", "D", "d", "p", "h", "*", "+", "x", "|")
FILLED_SHAPES = ("o", "s", "^", "v", "D", "d", "p", "h", "*")

#: Which knots of a curve carry a marker.
POINT_AT = ("events", "censored", "all")

#: How a series' knots are joined. ``auto`` = the plot kind's own geometry.
LINE_STYLES = ("auto", "step", "line")


def effective_geom(style: PlotStyle, kind: PlotKind) -> str:
    """``"step"`` or ``"line"`` — the Style's choice, else the kind's own.

    One resolver, used by the curve layer AND the confidence band: a band
    stepped one way under a curve drawn the other would bound nothing.
    """
    if style.line_style in ("step", "line"):
        return style.line_style
    return kind.geom


def point_data(data: pd.DataFrame, style: PlotStyle,
               group_cols: tuple[str, ...] = ("treatment",)) -> pd.DataFrame:
    """The knots that get a marker, per :attr:`PlotStyle.point_at`.

    ``events`` is the useful default and the only one that needs deriving: a
    knot where the value actually **changed**, which excludes both the origin
    and the censoring-only knots — marking those would put a dot where
    nothing happened. On a survival curve that is exactly "where survival
    fell", because survival never rises.
    """
    if data.empty:
        return data
    mode = style.point_at if style.point_at in POINT_AT else "events"
    if mode == "all":
        return data[data["time"] > 0]
    if mode == "censored":
        return data[(data["time"] > 0) & (data["n_censored"] > 0)]

    groups = [c for c in group_cols if c in data.columns]
    out: list[pd.DataFrame] = []
    for _key, grp in (data.groupby(list(groups), sort=False) if groups
                      else [(None, data)]):
        grp = grp.sort_values("time")
        changed = grp["value"].diff().fillna(0) != 0
        out.append(grp[changed])
    return (pd.concat(out, ignore_index=True) if out
            else data.iloc[0:0])


def risk_band_data(data: pd.DataFrame, style: PlotStyle,
                   spec: PlotSpec) -> pd.DataFrame:
    """The At-Risk Band's text layer: one row per (curve, time point).

    Counts are read off the step data rather than recomputed, so the band can
    never disagree with the curve above it.
    """
    if data.empty:
        return pd.DataFrame(columns=["time", "y", "count", "label"])

    times = list(style.risk_table_times)
    if not times:
        t_max = float(data["time"].max())
        times = [round(t_max * f, 2) for f in (0.0, 0.25, 0.5, 0.75, 1.0)]

    series_col = "_series" if "_series" in data.columns else "label"
    facet_values = data["_facet"].unique() if "_facet" in data.columns else [None]
    labels = list(dict.fromkeys(data[series_col]))

    rows: list[dict] = []
    for facet in facet_values:
        scope = data if facet is None else data[data["_facet"] == facet]
        for i, label in enumerate(labels):
            curve = scope[scope[series_col] == label].sort_values("time")
            if curve.empty:
                continue
            y = -style.risk_row_height * (i + 1)
            for t in times:
                at_or_before = curve[curve["time"] <= t]
                # The count *entering* the next interval is what an at-risk
                # table reports, so read the last row at or before t.
                row_source = at_or_before if len(at_or_before) else curve
                count = int(row_source["n_risk"].iloc[-1 if len(at_or_before) else 0])
                row = {"time": t, "y": y, "count": count, "label": label,
                       series_col: label}
                if facet is not None:
                    row["_facet"] = facet
                rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def build_ggplot(data: pd.DataFrame, spec: PlotSpec, style: PlotStyle):
    """The plotnine figure for one Spec+Style, dispatched on the plot's kind.

    Four shapes cover the whole Plot Set: a series over time (nine plots), a
    forest of ratios, a distribution of lifespans, and an interaction of
    medians. They share the Style — the type, the palette, the panel
    treatment — and diverge only in the layers.
    """
    if data is None or data.empty:
        raise ValueError(f"No data for plot {spec.plot_id!r}.")
    kind = kind_for(spec)
    if kind.geom in ("step", "line"):
        return _build_series(data, spec, style, kind)
    if kind.geom == "forest":
        return _build_forest(data, spec, style, kind)
    if kind.geom == "distribution":
        return _build_distribution(data, spec, style, kind)
    return _build_interaction(data, spec, style, kind)


def _series_column(data: pd.DataFrame) -> str:
    return "_series" if "_series" in data.columns else "label"


def _build_series(data: pd.DataFrame, spec: PlotSpec, style: PlotStyle,
                  kind: PlotKind):
    """Nine of the twelve plots: a step or a line per treatment over time."""
    import plotnine as p9

    series_col = _series_column(data)
    labels = list(dict.fromkeys(data[series_col]))
    colours = style.colour_for(labels)

    geom = effective_geom(style, kind)
    line = p9.geom_step if geom == "step" else p9.geom_line
    g = (p9.ggplot(data, p9.aes(x="time", y="value", color=series_col))
         + line(size=style.line_width))
    ## Both the band and filled points map `fill`, and plotnine warns and
    ## replaces when a scale is added twice — so the flag is set here and the
    ## single scale is added at the end.
    needs_fill_scale = False

    if style.ci_band and _CI in kind.supports:
        ## Stepped by expanding the data, not by a geom parameter: plotnine's
        ## geom_ribbon has no `step`/`direction`, and passing one is a hard
        ## error ("Parameters {'step'} are not understood by either the geom,
        ## stat or layer"), which is what this used to raise the moment anyone
        ## ticked the box.
        band = (step_expand(data, group_cols=(series_col, "_facet"))
                if geom == "step" else data)
        g = g + p9.geom_ribbon(
            data=band,
            mapping=p9.aes(x="time", ymin="ci_lo", ymax="ci_hi",
                           fill=series_col),
            ## No `color=`: geom_ribbon already defaults to "none", and
            ## passing None instead crashed on any faceted plot — plotnine
            ## repeats each default across panels, and None is not iterable.
            alpha=style.ci_alpha, show_legend=False, inherit_aes=False,
        )
        needs_fill_scale = True

    if style.show_points and _POINTS in kind.supports:
        points = point_data(data, style, group_cols=(series_col, "_facet"))
        if len(points):
            layer, mapped_fill = _point_layer(points, style, series_col)
            g = g + layer
            needs_fill_scale = needs_fill_scale or mapped_fill

    if style.censor_ticks and _CENSOR in kind.supports:
        censored = data[(data["time"] > 0) & (data["n_censored"] > 0)]
        if len(censored):
            mapping = {"x": "time", "y": "value"}
            kwargs: dict[str, Any] = {}
            if style.censor_color:
                kwargs["color"] = style.censor_color
            else:
                mapping["color"] = series_col
            g = g + p9.geom_point(
                data=censored, mapping=p9.aes(**mapping),
                shape=style.censor_shape or "|", size=style.censor_size,
                show_legend=False, inherit_aes=False, **kwargs,
            )

    if spec.reference_line is not None:
        g = g + p9.geom_hline(yintercept=float(spec.reference_line),
                              linetype="dashed", color="#888888", size=0.4)

    y_lo = None
    if style.risk_table and _RISK in kind.supports:
        band = risk_band_data(data, style, spec)
        if len(band):
            g = g + p9.geom_text(
                data=band,
                mapping=p9.aes(x="time", y="y", label="count", color=series_col),
                size=style.risk_font_size, show_legend=False, inherit_aes=False,
            )
            y_lo = float(band["y"].min()) - style.risk_row_height * 0.6

    if spec.facet_by and "_facet" in data.columns:
        order = [f for f in spec.facet_order if f in set(data["_facet"])] \
            or list(dict.fromkeys(data["_facet"]))
        data["_facet"] = pd.Categorical(data["_facet"], categories=order,
                                        ordered=True)
        g = g + p9.facet_wrap("_facet", nrow=1)

    if needs_fill_scale:
        g = g + p9.scale_fill_manual(values=colours, guide=None)
    g = g + p9.scale_color_manual(values=colours,
                                  name=spec.series_label or "Treatment")

    ## A probability gets fixed 0–1 breaks and, with an At-Risk Band, room
    ## below zero for it. Everything else is free: a hazard rate and a count
    ## of survivors have neither an upper bound nor a meaningful 0.25.
    if kind.y == "km_lx":
        g = g + p9.scale_y_continuous(breaks=[0, 0.25, 0.5, 0.75, 1.0])
    coord_args: dict[str, Any] = {}
    if spec.y_limits:
        coord_args["ylim"] = tuple(spec.y_limits)
    elif y_lo is not None:
        coord_args["ylim"] = (y_lo, 1.02)
    if spec.x_limits:
        coord_args["xlim"] = tuple(spec.x_limits)
    if coord_args:
        g = g + p9.coord_cartesian(**coord_args)

    return (g
            # Centred at-risk labels at t=0 and t=max need room, or they clip.
            + p9.scale_x_continuous(expand=(0.07, 0))
            + p9.labs(title=spec.title or None, x=spec.x_label,
                      y=spec.y_label or kind.y_label)
            + _theme_for(style))


def _build_forest(data: pd.DataFrame, spec: PlotSpec, style: PlotStyle,
                  kind: PlotKind):
    """Pairwise hazard ratios with their intervals, on a log ratio axis.

    Log scale because a ratio is symmetric there: 0.5 and 2 sit the same
    distance from the line of no effect, which is the whole point of reading
    a forest plot by eye.
    """
    import plotnine as p9

    labels = list(dict.fromkeys(data["label"]))
    colours = style.colour_for(labels)
    data = data.copy()
    data["label"] = pd.Categorical(data["label"], categories=labels[::-1],
                                   ordered=True)

    g = (p9.ggplot(data, p9.aes(x="ratio", y="label", color="label"))
         + p9.geom_vline(xintercept=1.0, linetype="dashed", color="#888888",
                         size=0.4)
         + p9.geom_errorbarh(p9.aes(xmin="ci_lo", xmax="ci_hi"),
                             height=0.0, size=style.line_width,
                             show_legend=False))
    layer, _fill = _point_layer_xy(data, style, "label", x="ratio", y="label")
    g = (g + layer
         + p9.scale_color_manual(values=colours, guide=None)
         + p9.scale_x_log10())
    ## Only x is pinnable: the ratio axis is numeric, the other is the list
    ## of comparisons. A limit must stay positive — log10(0) has no where.
    if spec.x_limits and all(v > 0 for v in spec.x_limits):
        g = g + p9.coord_cartesian(xlim=tuple(spec.x_limits))
    return (g
            + p9.labs(title=spec.title or None,
                      x=spec.x_label or "Hazard ratio (log scale)",
                      y=spec.y_label or kind.y_label)
            + _theme_for(style))


def _build_distribution(data: pd.DataFrame, spec: PlotSpec, style: PlotStyle,
                        kind: PlotKind):
    """The distribution of individual lifespans, one density per treatment."""
    import plotnine as p9

    series_col = _series_column(data)
    labels = list(dict.fromkeys(data[series_col]))
    colours = style.colour_for(labels)

    g = (p9.ggplot(data, p9.aes(x="value", color=series_col, fill=series_col))
         + p9.geom_density(alpha=style.ci_alpha, size=style.line_width))
    if spec.facet_by and "_facet" in data.columns:
        g = g + p9.facet_wrap("_facet", nrow=1)
    coord_args = {}
    if spec.x_limits:
        coord_args["xlim"] = tuple(spec.x_limits)
    if spec.y_limits:
        coord_args["ylim"] = tuple(spec.y_limits)
    if coord_args:
        ## coord_cartesian, never scale limits: a scale limit DROPS the data
        ## outside it before the density is estimated, so zooming would
        ## silently re-shape the curves.
        g = g + p9.coord_cartesian(**coord_args)
    return (g
            + p9.scale_color_manual(values=colours,
                                    name=spec.series_label or "Treatment")
            + p9.scale_fill_manual(values=colours, guide=None)
            + p9.labs(title=spec.title or None, x=spec.x_label,
                      y=spec.y_label or kind.y_label)
            + _theme_for(style))


def _build_interaction(data: pd.DataFrame, spec: PlotSpec, style: PlotStyle,
                       kind: PlotKind):
    """Median lifespan by factor level, one line per level of the other.

    Non-parallel lines are the interaction — which is why the lines are drawn
    at all rather than leaving four disconnected points.
    """
    import plotnine as p9

    labels = list(dict.fromkeys(data["label"]))
    colours = style.colour_for(labels)

    g = (p9.ggplot(data, p9.aes(x="x", y="value", color="label", group="label"))
         + p9.geom_line(size=style.line_width)
         + p9.geom_errorbar(p9.aes(ymin="ci_lo", ymax="ci_hi"), width=0.06,
                            size=style.line_width * 0.8, show_legend=False))
    layer, _fill = _point_layer_xy(data, style, "label", x="x", y="value")
    g = g + layer
    ## Only y is pinnable: the other axis is the factor's levels.
    if spec.y_limits:
        g = g + p9.coord_cartesian(ylim=tuple(spec.y_limits))
    return (g
            + p9.scale_color_manual(values=colours,
                                    name=spec.series_label or "Treatment")
            + p9.labs(title=spec.title or None, x=spec.x_label,
                      y=spec.y_label or kind.y_label)
            + _theme_for(style))


_INSTALLED_FAMILIES: set[str] | None = None


def resolve_font_family(preferred: str) -> list[str]:
    """*preferred* filtered to what is installed, with sane sans fallbacks.

    Two reasons, both about the file that comes out: matplotlib stops
    emitting findfont warnings for a family nobody has, and the exported SVG
    names a font the machine really rendered with rather than one it
    silently substituted.
    """
    global _INSTALLED_FAMILIES
    if _INSTALLED_FAMILIES is None:
        from matplotlib import font_manager

        _INSTALLED_FAMILIES = {f.name for f in font_manager.fontManager.ttflist}
    candidates = [preferred, "Helvetica", "Arial", "Liberation Sans",
                  "DejaVu Sans"]
    available = [c for c in dict.fromkeys(candidates)
                 if c and c in _INSTALLED_FAMILIES]
    return available or ["DejaVu Sans"]


def _point_layer_xy(points: pd.DataFrame, style: PlotStyle, series_col: str,
                    x: str = "time", y: str = "value"):
    """:func:`_point_layer` over an arbitrary pair of columns — the forest and
    interaction plots put their markers on a category, not on a time."""
    return _point_layer(points, style, series_col, x=x, y=y, always=True)


def _point_layer(points: pd.DataFrame, style: PlotStyle, series_col: str,
                 x: str = "time", y: str = "value", always: bool = False):
    """``(layer, maps_fill)`` for the markers drawn on the curve.

    Outline and interior are two aesthetics, not one: matplotlib draws a
    filled marker's edge from ``color`` and its interior from ``fill``, with
    ``stroke`` as the edge weight. So an outlined point needs the curve colour
    in ``fill`` and the outline colour in ``color`` — the reverse of an
    un-outlined one, which is simply drawn in the curve colour.
    """
    import plotnine as p9

    shape = style.point_shape if style.point_shape in POINT_SHAPES else "o"
    stroke = max(0.0, float(style.point_stroke))
    mapping: dict[str, str] = {"x": x, "y": y}
    kwargs: dict[str, Any] = {
        "shape": shape,
        ## On a forest or interaction plot the marker IS the estimate, so it
        ## is never optional and never vanishingly small — the "draw points"
        ## toggle governs decoration on a curve, not the data itself.
        "size": max(style.point_size, 2.0) if always else style.point_size,
        "alpha": 1.0 if always else style.point_alpha,
    }
    maps_fill = False

    if stroke > 0 and shape in FILLED_SHAPES:
        kwargs["stroke"] = stroke
        ## The edge.
        if style.point_stroke_color:
            kwargs["color"] = style.point_stroke_color
        else:
            mapping["color"] = series_col
        ## The interior.
        if style.point_fill == "none":
            kwargs["fill"] = "none"
        elif style.point_fill:
            kwargs["fill"] = style.point_fill
        else:
            mapping["fill"] = series_col
            maps_fill = True
    else:
        ## No outline: one colour, and an explicit fill still wins so a hollow
        ## marker is reachable without turning the outline on.
        if style.point_fill and style.point_fill != "none":
            kwargs["color"] = style.point_fill
        else:
            mapping["color"] = series_col

    return p9.geom_point(data=points, mapping=p9.aes(**mapping),
                         show_legend=False, inherit_aes=False, **kwargs), maps_fill


def _theme_for(style: PlotStyle):
    import plotnine as p9

    base = getattr(p9, style.theme, p9.theme_classic)
    families = resolve_font_family(style.font_family)
    ink = style.text_color or "#000000"
    lw = max(0.0, float(style.line_pt))

    overrides: dict[str, Any] = {
        ## Pin every element to the same resolved face. Without it some
        ## elements take the theme's default and others the requested family,
        ## which reads as one font mysteriously condensing at certain sizes.
        "text": p9.element_text(family=families, color=ink),
        "figure_size": (style.width_mm / 25.4, style.height_mm / 25.4),
        "legend_position": style.legend_position,
        "legend_key": p9.element_blank(),
        "plot_title": p9.element_text(size=style.size_of("title"), color=ink),
        "axis_title": p9.element_text(size=style.size_of("axis_title"),
                                      color=ink),
        "axis_text": p9.element_text(size=style.size_of("tick"), color=ink),
        "legend_text": p9.element_text(size=style.size_of("legend"), color=ink),
        "legend_title": p9.element_text(size=style.size_of("legend"), color=ink),
        "strip_text": p9.element_text(size=style.size_of("strip"), color=ink),
        "axis_line": p9.element_line(size=lw),
        "axis_ticks": p9.element_line(size=lw),
        "panel_grid_minor": p9.element_blank(),
    }

    ## Gridlines are off by default here: a survivorship curve is read against
    ## its own steps, and horizontal rules at 0.25/0.5/0.75 compete with them.
    if style.grid == "none":
        overrides["panel_grid_major"] = p9.element_blank()
    elif style.grid == "y":
        overrides["panel_grid_major_x"] = p9.element_blank()

    if style.strip_style == "boxed":
        overrides["strip_background"] = p9.element_rect(
            fill=style.strip_bg or "#d9d9d9", color=ink, size=lw)
        ## A boxed strip reads as detached unless the panel is bordered too.
        overrides["panel_border"] = p9.element_rect(color=ink, size=lw,
                                                   fill="none")
    else:
        overrides["strip_background"] = p9.element_blank()
    if style.panel_border and "panel_border" not in overrides:
        overrides["panel_border"] = p9.element_rect(color=ink, size=lw,
                                                   fill="none")
    if style.panel_bg:
        overrides["panel_background"] = p9.element_rect(fill=style.panel_bg)

    ## theme_matplotlib is the one plotnine theme built from an rc dict
    ## rather than (base_size, base_family) — passing those was a TypeError
    ## the moment the theme was picked. The overrides above set every text
    ## element's size and family explicitly, so nothing is lost by not
    ## having base arguments to give it.
    if base is p9.theme_matplotlib:
        themed = base()
    else:
        themed = base(base_size=style.base_size, base_family=families[0])
    return themed + p9.theme(**overrides)


def forest_data(hazard_ratios: pd.DataFrame, spec: PlotSpec) -> pd.DataFrame:
    """One row per pairwise comparison: the ratio and its interval."""
    if hazard_ratios is None or not len(hazard_ratios):
        return pd.DataFrame(columns=["label", "ratio", "ci_lo", "ci_hi"])
    hr = hazard_ratios.copy()
    out = pd.DataFrame({
        "label": hr["group1"].astype(str) + " vs " + hr["group2"].astype(str),
        "ratio": hr["hazard_ratio"].astype(float),
        "ci_lo": hr["hr_ci_lo"].astype(float),
        "ci_hi": hr["hr_ci_hi"].astype(float),
    })
    ## A ratio whose interval touches zero cannot be drawn on a log axis;
    ## the matplotlib forest clips these the same way.
    return out[(out["ratio"] > 0) & (out["ci_lo"] > 0)]


def distribution_data(individual_data: pd.DataFrame, spec: PlotSpec,
                      factors: tuple[str, ...] = ()) -> pd.DataFrame:
    """One row per individual death: the lifespan and its treatment.

    Censored individuals are excluded — their lifespan is unknown, not the
    time they were last seen, and a density over last-seen times would be a
    different (and misleading) figure.
    """
    df = individual_data
    if df is None or not len(df):
        return pd.DataFrame(columns=["value", "treatment", "label"])
    df = df[df["event"] == 1] if "event" in df.columns else df
    treatments = df["treatment"].astype(str)
    wanted = [t for t in (spec.treatments or [])
              if t in set(treatments)] or sorted(set(treatments))
    df = df[treatments.isin(wanted)]
    out = pd.DataFrame({
        "value": df["time"].astype(float),
        "treatment": df["treatment"].astype(str),
    })
    out["label"] = out["treatment"].map(
        lambda t: spec.display_names.get(t, t))
    if spec.facet_by:
        out = _apply_facet(out, spec, factors)
    return out


def interaction_data(individual_data: pd.DataFrame,
                     spec: PlotSpec) -> pd.DataFrame:
    """Median lifespan (±SEM of the median via a normal approximation) per
    factorial cell, shaped for the interaction plot: factor 1 on x, one line
    per level of factor 2."""
    df = individual_data
    if df is None or not len(df) or "treatment" not in df.columns:
        return pd.DataFrame(columns=["x", "value", "label"])
    parts = df["treatment"].astype(str).str.split("/", n=1, expand=True)
    if parts.shape[1] != 2:
        ## Not factorial: nothing to cross.
        return pd.DataFrame(columns=["x", "value", "label"])
    work = pd.DataFrame({
        "x": parts[0], "series": parts[1],
        "time": df["time"].astype(float),
        "event": (df["event"] if "event" in df.columns else 1),
    })
    work = work[work["event"] == 1]
    rows = []
    for (level, series), grp in work.groupby(["x", "series"], sort=True):
        times = grp["time"].to_numpy(dtype=float)
        if not len(times):
            continue
        median = float(np.median(times))
        ## 1.2533·σ/√n — the standard error of a median under normality.
        se = 1.2533 * float(np.std(times, ddof=1)) / max(len(times), 1) ** 0.5 \
            if len(times) > 1 else 0.0
        rows.append({"x": str(level), "value": median,
                     "ci_lo": median - se, "ci_hi": median + se,
                     "series": str(series)})
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["x", "value", "label"])
    out["label"] = out["series"].map(lambda s: spec.display_names.get(s, s))
    return out


def data_for(experiment, spec: PlotSpec,
             lifetables: pd.DataFrame | None = None) -> pd.DataFrame:
    """The prepared frame for one Spec, whatever its kind needs.

    The three sources match the report's own builders (``plot_registry``):
    lifetables for the series plots, the individual data for distributions
    and interactions, the saved hazard ratios for the forest.
    """
    kind = kind_for(spec)
    factors = tuple(experiment.config.get("factors") or {})
    if kind.source == "lifetables":
        lt = lifetables if lifetables is not None else _load_lifetables(experiment)
        return series_data(lt, spec, kind, factors=factors)
    if kind.source == "hazard_ratios":
        return forest_data(_load_hazard_ratios(experiment), spec)
    individual = _load_individual_data(experiment)
    if kind.geom == "interaction":
        return interaction_data(individual, spec)
    return distribution_data(individual, spec, factors=factors)


def _load_individual_data(experiment) -> pd.DataFrame:
    """The saved individual-level frame; fall back to loading the input."""
    path = experiment.analysis_dir / "data_output" / "individual_data.csv"
    if path.is_file():
        return pd.read_csv(path)
    data, _ = experiment.load()
    return data


def available_treatments(experiment, spec: PlotSpec,
                         lifetables: pd.DataFrame | None = None) -> list[str]:
    """Every treatment id this Spec's kind could draw, for a checklist.

    Unlike :func:`series_data`/:func:`distribution_data`, this ignores
    ``spec.treatments`` — it is the full candidate set that field narrows,
    not narrowed by it. Empty for a kind :func:`treatments_selectable` says
    doesn't consult the field at all.
    """
    if not treatments_selectable(spec):
        return []
    kind = kind_for(spec)
    if kind.source == "lifetables":
        df = lifetables if lifetables is not None else _load_lifetables(experiment)
    else:
        df = _load_individual_data(experiment)
    if df is None or not len(df) or "treatment" not in df.columns:
        return []
    return sorted(set(df["treatment"].astype(str)))


def _load_hazard_ratios(experiment) -> pd.DataFrame:
    """The saved pairwise hazard ratios. Never recomputed here — a Cox fit is
    analysis, and the Plot Editor must not silently run one."""
    path = experiment.analysis_dir / "statistics" / "hazard_ratios.csv"
    if path.is_file():
        return pd.read_csv(path)
    return pd.DataFrame()


def figure_for(experiment, plot_id: str, spec: PlotSpec | None = None,
               style: PlotStyle | None = None, lifetables: pd.DataFrame | None = None):
    """Build the ggplot for one of an experiment's Publication Figures."""
    spec = spec or specs_for(experiment).get(plot_id) or default_spec(plot_id)
    style = style or resolve_style(spec.style, experiment)
    return build_ggplot(data_for(experiment, spec, lifetables), spec, style)


def _load_lifetables(experiment) -> pd.DataFrame:
    """Read the saved lifetables; fall back to computing them."""
    path = experiment.analysis_dir / "data_output" / "lifetables.csv"
    if path.is_file():
        return pd.read_csv(path)
    from . import lifetable

    data, _ = experiment.load()
    return lifetable.compute_lifetables(data)


def save_figure(g, path: str | Path, style: PlotStyle, dpi: int = 300) -> Path:
    """Write a vector figure with editable text (SVG/PDF) or a raster PNG."""
    import matplotlib as mpl

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fmt = target.suffix.lstrip(".").lower() or "svg"
    # Editable text is the whole point of a publication figure: without this
    # SVG text is exported as paths and no illustrator can retype a label.
    with mpl.rc_context({"svg.fonttype": "none", "pdf.fonttype": 42}):
        g.save(str(target), width=style.width_mm, height=style.height_mm,
               units="mm", dpi=dpi, verbose=False)
    return target


def render_png_bytes(g, style: PlotStyle, dpi: int = 110) -> bytes:
    """Rasterise for the Plot Editor's live preview."""
    import io

    import matplotlib as mpl

    buf = io.BytesIO()
    with mpl.rc_context({"svg.fonttype": "none"}):
        g.save(buf, format="png", width=style.width_mm, height=style.height_mm,
               units="mm", dpi=dpi, verbose=False)
    return buf.getvalue()


def render_all(experiment, fmt: str = "svg", log=None) -> list[Path]:
    """Render every Publication Figure for one Experiment Directory.

    Figures land in ``<experiment>/figures/`` — per member, because a Project
    never pools and so has no pooled figure to render.
    """
    emit = log or (lambda _m: None)
    written: list[Path] = []
    ## Only the plots the container's plot_specs.yaml actually defines — the
    ## sister app's rule. specs_for() fills defaults for the whole Plot Set
    ## so the EDITOR can offer every figure; rendering those defaults headless
    ## would produce a dozen figures nobody curated, and "render" would stop
    ## meaning "render my figures".
    specs = adopt_legacy_member_specs(experiment).plots
    if not specs:
        emit(f"{experiment.name}: nothing curated in plot_specs.yaml — "
             f"no figures rendered. Curate them in the Plot Editor first.")
        return written

    lifetables = None
    for plot_id, spec in specs.items():
        if plot_id not in PLOT_TYPES:
            continue
        try:
            if kind_for(spec).source == "lifetables" and lifetables is None:
                lifetables = _load_lifetables(experiment)
            style = resolve_style(spec.style, experiment)
            data = data_for(experiment, spec, lifetables)
            if data.empty:
                ## A forest with no saved Cox fit, an interaction with no
                ## factorial cells: named and skipped, not an error — the
                ## other figures still render.
                emit(f"  {plot_id}: no data for this experiment — skipped.")
                continue
            g = build_ggplot(data, spec, style)
            target = experiment.figures_dir / f"{plot_id}.{fmt}"
            save_figure(g, target, style)
            written.append(target)
            emit(f"  wrote {target.name}")
        except Exception as exc:  # noqa: BLE001 - one bad spec, not one dead run
            emit(f"  {plot_id}: skipped ({exc})")
    return written
