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
