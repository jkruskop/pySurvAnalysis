"""Publication figures: style resolution up the chain, and the At-Risk Band."""

from __future__ import annotations

import pandas as pd
import pytest

from pysurvanalysis import lifetable, pubfigures as pf
from pysurvanalysis.domain import config as cfgmod


@pytest.fixture
def lifetables(project):
    member = project.member("rep_a")
    data, _factors = member.load()
    return lifetable.compute_lifetables(data)


def test_styles_resolve_member_then_project_then_builtin(project):
    member = project.member("rep_a")
    assert pf.resolve_style("default", member).width_mm == pf.BUILTIN_STYLE.width_mm

    pf.save_styles(project.directory,
                   {"default": pf.PlotStyle(name="default", width_mm=180)},
                   "default")
    project_style = pf.resolve_style("default", project.member("rep_a"))
    assert project_style.width_mm == 180

    pf.save_styles(member.directory,
                   {"local": pf.PlotStyle(name="local", width_mm=60)}, "local")
    assert pf.resolve_style("local", member).width_mm == 60
    # The project's shared look still wins for the shared name.
    assert pf.resolve_style("default", member).width_mm == 180


def test_specs_live_with_the_experiment(project):
    member = project.member("rep_a")
    specs = pf.specs_for(member)
    specs["km_faceted"].title = "Headline"
    path = pf.save_specs(member.directory, specs)
    assert path.parent == member.directory

    reloaded = pf.load_specs(member.directory)
    assert reloaded["km_faceted"].title == "Headline"
    # Nothing was written to the Project.
    assert "plots" not in cfgmod.read_yaml(project.specs_path)


def test_faceted_spec_is_seeded_from_the_declared_factors(project):
    spec = pf.specs_for(project.member("rep_a"))["km_faceted"]
    assert spec.facet_by == "Genotype"
    assert spec.series_label == "Treatment"


def test_curve_data_anchors_every_curve_at_one(lifetables):
    spec = pf.default_spec("km_curves")
    data = pf.curve_data(lifetables, spec)
    for _label, group in data.groupby("treatment", observed=True):
        first = group.sort_values("time").iloc[0]
        assert first["time"] == 0.0
        assert first["surv"] == 1.0


def test_at_risk_band_counts_match_the_lifetable(lifetables):
    spec = pf.default_spec("km_risk_table")
    style = pf.PlotStyle(risk_table=True)
    data = pf.curve_data(lifetables, spec)
    band = pf.risk_band_data(data, style, spec)

    assert len(band) > 0
    at_zero = band[band["time"] == 0.0]
    for _i, row in at_zero.iterrows():
        expected = lifetables[
            lifetables["treatment"].astype(str) == row["label"]
        ].sort_values("time")["n_at_risk"].iloc[0]
        assert row["count"] == expected


def test_at_risk_band_rows_stack_below_zero(lifetables):
    spec = pf.default_spec("km_risk_table")
    style = pf.PlotStyle(risk_table=True, risk_row_height=0.1)
    band = pf.risk_band_data(pf.curve_data(lifetables, spec), style, spec)
    assert band["y"].max() < 0
    assert round(band["y"].min(), 6) == round(-0.1 * band["label"].nunique(), 6)


def test_build_ggplot_produces_a_plot(lifetables):
    spec = pf.default_spec("km_curves")
    g = pf.build_ggplot(pf.curve_data(lifetables, spec), spec, pf.PlotStyle())
    assert g is not None


def test_render_all_writes_vector_files_with_live_text(project, tmp_path):
    member = project.member("rep_a")
    member.run_analysis()
    written = pf.render_all(member, fmt="svg")
    assert written
    for path in written:
        assert path.parent == member.figures_dir
        text = path.read_text(encoding="utf-8")
        # Editable text, not outlined paths — the point of a publication figure.
        assert "<text" in text


def test_empty_data_is_a_clear_error():
    spec = pf.default_spec("km_curves")
    with pytest.raises(ValueError, match="No curve data"):
        pf.build_ggplot(pd.DataFrame(columns=["time", "surv"]), spec, pf.PlotStyle())


# ── the confidence band ────────────────────────────────────────────────────

def test_step_expand_holds_each_value_until_the_next_time(lifetables):
    """The band has to be stepped in the DATA.

    plotnine's ``geom_ribbon`` has no ``step``/``direction`` of its own — it
    takes ``outline_type`` and nothing else — so a ribbon over unexpanded
    knots is drawn as straight lines between them: an interval nobody
    computed, visibly detached from the curve it bounds.
    """
    knots = pd.DataFrame({
        "time": [0.0, 1.0, 2.0],
        "ci_lo": [1.0, 0.8, 0.6],
        "ci_hi": [1.0, 0.9, 0.75],
        "treatment": ["a", "a", "a"],
    })
    out = pf.step_expand(knots)
    ## geom_step's default direction is "hv": hold, then step. At a time that
    ## now appears twice the carried-forward value must come first, or the
    ## ribbon's vertical edge lands on the wrong side of the step.
    assert list(zip(out["time"], out["ci_lo"])) == [
        (0.0, 1.0), (1.0, 1.0), (1.0, 0.8), (2.0, 0.8), (2.0, 0.6)]


def test_step_expand_keeps_curves_apart(lifetables):
    """Expansion is per curve: one long staircase across two treatments would
    close the ribbon across the gap between them."""
    knots = pd.DataFrame({
        "time": [0.0, 1.0, 0.0, 1.0],
        "ci_lo": [1.0, 0.8, 1.0, 0.5],
        "ci_hi": [1.0, 0.9, 1.0, 0.7],
        "treatment": ["a", "a", "b", "b"],
    })
    out = pf.step_expand(knots)
    assert out.groupby("treatment").size().to_dict() == {"a": 3, "b": 3}


@pytest.mark.parametrize("type_key", ["standard_lifespan", "interaction"])
def test_every_plot_in_the_set_renders_with_the_band_on(project, type_key):
    """Ticking CI bands used to raise "Parameters {'step'} are not understood
    by either the geom, stat or layer" — and once that was fixed, a
    ``color=None`` default crashed every *faceted* plot, which the
    single-panel plots never exercised.

    So: every plot the type can draw, both band states.
    """
    from pysurvanalysis.experiment_types import get_type

    member = project.member("rep_a")
    data, _factors = member.load()
    tables = lifetable.compute_lifetables(data)

    for plot_id in get_type(type_key).plot_ids():
        spec = pf.default_spec(plot_id)
        if plot_id == "km_faceted":
            spec.facet_by = "Genotype"
        curves = pf.curve_data(tables, spec)
        if curves.empty:
            continue
        for band in (False, True):
            style = pf.PlotStyle()
            style.ci_band = band
            g = pf.build_ggplot(curves, spec, style)
            ## Built AND drawn: the parameter errors this guards against only
            ## surface when plotnine assembles the layers.
            assert pf.render_png_bytes(g, style, dpi=72)


# ── the expanded style: points, type, panels, colour ───────────────────────

def test_size_of_follows_the_base_until_it_is_overridden():
    """Every per-element size defaults to 0 = "follow the base", so a style
    that sets only ``base_size`` still scales as one thing."""
    style = pf.PlotStyle(base_size=10.0)
    assert style.size_of("axis_title") == 10.0
    assert style.size_of("tick") == 10.0
    assert style.size_of("title") == 12.0        # titles lead by 2pt
    assert style.size_of("strip") == 11.0

    style.tick_pt = 6.5
    assert style.size_of("tick") == 6.5
    assert style.size_of("axis_title") == 10.0   # the override is local


def test_point_at_selects_the_knots_it_says_it_does(lifetables):
    """``events`` has to exclude both the t=0 anchor and censoring-only knots
    — a marker at either puts a dot where nobody died."""
    spec = pf.default_spec("km_curves")
    data = pf.curve_data(lifetables, spec)

    events = pf.point_data(data, pf.PlotStyle(point_at="events"))
    assert len(events)
    assert (events["time"] > 0).all()
    ## Every marked knot is one where survival actually fell.
    for treatment, grp in data.groupby("treatment"):
        marked = set(events[events["treatment"] == treatment]["time"])
        grp = grp.sort_values("time")
        fell = set(grp[grp["surv"].diff() < 0]["time"])
        assert marked == fell

    everything = pf.point_data(data, pf.PlotStyle(point_at="all"))
    assert len(everything) == len(data[data["time"] > 0])

    censored = pf.point_data(data, pf.PlotStyle(point_at="censored"))
    assert (censored["n_censored"] > 0).all()


def test_an_outlined_point_maps_fill_and_a_plain_one_does_not(lifetables):
    """matplotlib draws a filled marker's edge from ``color`` and its interior
    from ``fill``, so an outlined point needs the curve colour in ``fill`` —
    the reverse of an un-outlined one."""
    spec = pf.default_spec("km_curves")
    data = pf.curve_data(lifetables, spec)
    points = pf.point_data(data, pf.PlotStyle(point_at="events"))

    _layer, maps_fill = pf._point_layer(
        points, pf.PlotStyle(point_stroke=0.6, point_fill=""), "label")
    assert maps_fill

    _layer, maps_fill = pf._point_layer(
        points, pf.PlotStyle(point_stroke=0.0), "label")
    assert not maps_fill

    ## A stroke on an unfillable shape has no interior to colour, so it does
    ## not take the outlined path.
    _layer, maps_fill = pf._point_layer(
        points, pf.PlotStyle(point_stroke=0.6, point_shape="x"), "label")
    assert not maps_fill


def test_the_palette_cycle_is_the_fallback_and_explicit_colours_win():
    style = pf.PlotStyle(palette_cycle=["#111111", "#222222"],
                         palette={"b": "#ff0000"})
    assert style.colour_for(["a", "b", "c"]) == {
        "a": "#111111", "b": "#ff0000", "c": "#111111"}


def test_font_family_resolves_to_something_installed():
    """The exported SVG must name a font the machine really rendered with,
    not one matplotlib silently substituted."""
    resolved = pf.resolve_font_family("A Font Nobody Has")
    assert resolved and "A Font Nobody Has" not in resolved

    from matplotlib import font_manager
    installed = {f.name for f in font_manager.fontManager.ttflist}
    assert set(resolved) <= installed or resolved == ["DejaVu Sans"]
