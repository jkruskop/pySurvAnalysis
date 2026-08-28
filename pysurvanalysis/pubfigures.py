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
    """A sensible starting Spec for a survivorship figure."""
    return PlotSpec(plot_id=plot_id, x_label=time_label,
                    title="", reference_line=0.5)


# ---------------------------------------------------------------------------
# Reading and writing the two files
# ---------------------------------------------------------------------------

def load_styles(project_dir: str | Path | None) -> tuple[dict[str, PlotStyle], str]:
    """A Project's Style library and the name of its default."""
    if project_dir is None:
        return {"default": BUILTIN_STYLE}, "default"
    data = cfgmod.read_yaml(Path(project_dir) / cfgmod.SPECS_FILENAME)
    raw = data.get("styles") or {}
    styles = {name: PlotStyle.from_dict(name, body) for name, body in raw.items()
              if isinstance(body, dict)}
    styles.setdefault("default", BUILTIN_STYLE)
    default_name = str(data.get("default_style") or "default")
    if default_name not in styles:
        default_name = "default"
    return styles, default_name


def save_styles(project_dir: str | Path, styles: dict[str, PlotStyle],
                default_style: str = "default") -> Path:
    path = Path(project_dir) / cfgmod.SPECS_FILENAME
    data = cfgmod.read_yaml(path)
    data["styles"] = {name: style.to_dict() for name, style in styles.items()}
    data["default_style"] = default_style
    return cfgmod.write_yaml(path, data)


def load_specs(experiment_dir: str | Path) -> dict[str, PlotSpec]:
    """An Experiment Directory's Specs, keyed by plot id."""
    data = cfgmod.read_yaml(Path(experiment_dir) / cfgmod.SPECS_FILENAME)
    raw = data.get("plots") or {}
    return {pid: PlotSpec.from_dict(pid, body) for pid, body in raw.items()
            if isinstance(body, dict)}


def save_specs(experiment_dir: str | Path, specs: dict[str, PlotSpec]) -> Path:
    path = Path(experiment_dir) / cfgmod.SPECS_FILENAME
    data = cfgmod.read_yaml(path)
    data["plots"] = {pid: spec.to_dict() for pid, spec in specs.items()}
    return cfgmod.write_yaml(path, data)


def resolve_style(name: str, experiment) -> PlotStyle:
    """Resolve a style name upward: member file → Project file → built-in."""
    own, _ = load_styles(experiment.directory)
    if name in own and name != "default":
        return own[name]
    project = getattr(experiment, "project", None)
    if project is not None:
        shared, default_name = load_styles(project.directory)
        if name in shared:
            return shared[name]
        if name == "default":
            return shared.get(default_name, BUILTIN_STYLE)
    return own.get(name, BUILTIN_STYLE)


def specs_for(experiment) -> dict[str, PlotSpec]:
    """The Specs to offer for an experiment: saved ones, plus its Plot Set."""
    saved = load_specs(experiment.directory)
    time_label = experiment.type.resolve_time_label(experiment.config)
    for plot_id in (experiment.type.plot_ids() or ("km_curves",)):
        if plot_id in _CURVE_PLOTS and plot_id not in saved:
            spec = default_spec(plot_id, time_label)
            if plot_id == "km_faceted":
                factors = list((experiment.config.get("factors") or {}))
                spec.facet_by = factors[0] if factors else ""
                if len(factors) > 1:
                    spec.series_label = factors[1]
            saved[plot_id] = spec
    return saved


#: Plot ids the publication renderer can draw. Diagnostics (log-log, forest)
#: stay matplotlib-only: they are for the analyst, not the journal.
_CURVE_PLOTS = ("km_curves", "km_risk_table", "km_faceted")


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def curve_data(lifetables: pd.DataFrame, spec: PlotSpec) -> pd.DataFrame:
    """Step-function coordinates for every curve, t=0 anchored at S=1.

    plotnine's ``geom_step`` needs the origin point explicitly; without it the
    first curve segment starts at the first death and the figure silently lies
    about early survival.
    """
    lt = lifetables.copy()
    lt["treatment"] = lt["treatment"].astype(str)
    wanted = [t for t in (spec.treatments or [])
              if t in set(lt["treatment"])] or sorted(set(lt["treatment"]))

    frames: list[pd.DataFrame] = []
    for treatment in wanted:
        grp = lt[lt["treatment"] == treatment].sort_values("time")
        if grp.empty:
            continue
        block = pd.DataFrame({
            "time": np.concatenate([[0.0], grp["time"].to_numpy()]),
            "surv": np.concatenate([[1.0], grp["km_lx"].to_numpy()]),
            "ci_lo": np.concatenate([[1.0], grp["km_ci_lo"].to_numpy()]),
            "ci_hi": np.concatenate([[1.0], grp["km_ci_hi"].to_numpy()]),
            "n_censored": np.concatenate([[0], grp["n_censored"].to_numpy()]),
            "n_risk": np.concatenate(
                [[grp["n_at_risk"].iloc[0]], grp["n_at_risk"].to_numpy()]),
        })
        block["treatment"] = treatment
        block["label"] = spec.display_names.get(treatment, treatment)
        frames.append(block)

    if not frames:
        return pd.DataFrame(columns=["time", "surv", "treatment", "label"])
    data = pd.concat(frames, ignore_index=True)
    if spec.facet_by:
        parts = data["treatment"].str.split("/", n=1, expand=True)
        if parts.shape[1] == 2:
            data["_facet"], data["_series"] = parts[0], parts[1]
            data["label"] = data["_series"]
    return data


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


def point_data(data: pd.DataFrame, style: PlotStyle,
               group_cols: tuple[str, ...] = ("treatment",)) -> pd.DataFrame:
    """The knots that get a marker, per :attr:`PlotStyle.point_at`.

    ``events`` is the useful default and the only one that needs deriving: a
    knot is an event where survival actually fell, which excludes both the
    t=0 anchor and the censoring-only knots — marking those would put a dot
    where nobody died.
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
        fell = grp["surv"].diff() < 0
        out.append(grp[fell])
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
    """Assemble the plotnine figure for one Spec+Style."""
    import plotnine as p9

    if data.empty:
        raise ValueError(f"No curve data for plot {spec.plot_id!r}.")

    series_col = "_series" if "_series" in data.columns else "label"
    labels = list(dict.fromkeys(data[series_col]))
    colours = style.colour_for(labels)

    g = (p9.ggplot(data, p9.aes(x="time", y="surv", color=series_col))
         + p9.geom_step(size=style.line_width))
    ## Both the band and filled points map `fill`, and plotnine warns and
    ## replaces when a scale is added twice — so the flag is set here and the
    ## single scale is added at the end.
    needs_fill_scale = False

    if style.ci_band:
        ## Stepped by expanding the data, not by a geom parameter: plotnine's
        ## geom_ribbon has no `step`/`direction`, and passing one is a hard
        ## error ("Parameters {'step'} are not understood by either the geom,
        ## stat or layer"), which is what this used to raise the moment anyone
        ## ticked the box.
        band = step_expand(data, group_cols=(series_col, "_facet"))
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

    if style.show_points:
        points = point_data(data, style, group_cols=(series_col, "_facet"))
        if len(points):
            layer, mapped_fill = _point_layer(points, style, series_col)
            g = g + layer
            needs_fill_scale = needs_fill_scale or mapped_fill

    if style.censor_ticks:
        censored = data[(data["time"] > 0) & (data["n_censored"] > 0)]
        if len(censored):
            mapping = {"x": "time", "y": "surv"}
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

    y_lo = 0.0
    if style.risk_table:
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
        data["_facet"] = pd.Categorical(data["_facet"], categories=order, ordered=True)
        g = g + p9.facet_wrap("_facet", nrow=1)

    y_limits = spec.y_limits or [y_lo, 1.02]
    coord_args: dict[str, Any] = {"ylim": tuple(y_limits)}
    if spec.x_limits:
        coord_args["xlim"] = tuple(spec.x_limits)
    if needs_fill_scale:
        g = g + p9.scale_fill_manual(values=colours, guide=None)
    g = (g
         + p9.scale_color_manual(values=colours, name=spec.series_label or "Treatment")
         + p9.scale_y_continuous(breaks=[0, 0.25, 0.5, 0.75, 1.0])
         # Centred at-risk labels at t=0 and t=max need room, or they clip.
         # Only an explicit x-limit overrides this expansion.
         + p9.scale_x_continuous(expand=(0.07, 0))
         + p9.coord_cartesian(**coord_args)
         + p9.labs(title=spec.title or None, x=spec.x_label, y=spec.y_label)
         + _theme_for(style))
    return g


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


def _point_layer(points: pd.DataFrame, style: PlotStyle, series_col: str):
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
    mapping: dict[str, str] = {"x": "time", "y": "surv"}
    kwargs: dict[str, Any] = {
        "shape": shape,
        "size": style.point_size,
        "alpha": style.point_alpha,
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

    return base(base_size=style.base_size,
                base_family=families[0]) + p9.theme(**overrides)


def figure_for(experiment, plot_id: str, spec: PlotSpec | None = None,
               style: PlotStyle | None = None, lifetables: pd.DataFrame | None = None):
    """Build the ggplot for one of an experiment's Publication Figures."""
    spec = spec or specs_for(experiment).get(plot_id) or default_spec(plot_id)
    style = style or resolve_style(spec.style, experiment)
    lt = lifetables if lifetables is not None else _load_lifetables(experiment)
    return build_ggplot(curve_data(lt, spec), spec, style)


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
    specs = specs_for(experiment)
    if not specs:
        emit(f"{experiment.name}: no publication figures defined.")
        return written

    lifetables = None
    for plot_id, spec in specs.items():
        if plot_id not in _CURVE_PLOTS:
            continue
        try:
            if lifetables is None:
                lifetables = _load_lifetables(experiment)
            style = resolve_style(spec.style, experiment)
            g = build_ggplot(curve_data(lifetables, spec), spec, style)
            target = experiment.figures_dir / f"{plot_id}.{fmt}"
            save_figure(g, target, style)
            written.append(target)
            emit(f"  wrote {target.name}")
        except Exception as exc:  # noqa: BLE001 - one bad spec, not one dead run
            emit(f"  {plot_id}: skipped ({exc})")
    return written
