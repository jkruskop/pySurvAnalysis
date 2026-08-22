"""Report block assembly, the Project Report binder, and output stamping."""

from __future__ import annotations

import json

import pytest

from pysurvanalysis import project_report, report_builder as rb
from pysurvanalysis.report_pkg import model as m


@pytest.fixture
def analysed(analysed_project):
    project, _results = analysed_project
    return project


@pytest.fixture
def result_a(analysed_project):
    _project, results = analysed_project
    return results["rep_a"]


def _blocks_of(report, kind):
    return [b for b in report.blocks if isinstance(b, kind)]


def test_experiment_report_leads_with_the_headline_figure(result_a):
    report = rb.build_experiment_report(result_a)

    figures = _blocks_of(report, m.Figure)
    assert figures and "headline figure" in (figures[0].title or "")


def test_report_sections_follow_the_type(result_a):
    report = rb.build_experiment_report(result_a)
    titles = [b.title for b in _blocks_of(report, m.SectionDivider)]
    assert "Factorial analysis" in titles          # interaction-only section
    assert titles.index("Experiment summary") < titles.index("Factorial analysis")


def test_cover_stamps_the_exclusion_group(project):
    member = project.member("rep_a")
    config = dict(member.raw_config)
    config["exclusions"] = {"group": "review_v2"}
    from pysurvanalysis.domain import config as cfgmod

    cfgmod.save_config(member.directory, config)

    from pysurvanalysis.domain import Project

    member = Project(project.directory).member("rep_a")
    result = member.run_analysis()
    cover = _blocks_of(rb.build_experiment_report(result), m.Cover)[0]
    stamped = dict(cover.metadata)
    assert "review_v2" in stamped["Exclusion group"]

    payload = json.loads(
        (member.analysis_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert payload["exclusion_group"] == "review_v2"


def test_significant_rows_are_tinted_semantically(result_a):
    tables = _blocks_of(rb.build_experiment_report(result_a), m.Table)
    tinted = [t for t in tables if t.row_levels]
    assert tinted, "no table carried semantic row levels"
    assert all(isinstance(lv, m.Level) for t in tinted for lv in t.row_levels)


def test_both_backends_write_from_the_same_blocks(result_a, tmp_path):
    written = rb.write_experiment_report(result_a, tmp_path)
    assert written["pdf"].is_file() and written["md"].is_file()
    assert written["pdf"].stat().st_size > 1000
    text = written["md"].read_text(encoding="utf-8")
    assert "# rep_a" in text
    assert "![" in text                      # figures linked, not inlined


def test_project_report_binds_one_section_per_member(analysed):
    report = project_report.build_project_report(analysed)
    dividers = [b.title for b in _blocks_of(report, m.SectionDivider)]
    for member in analysed.members():
        assert member.name in dividers


def test_project_report_carries_inventory_and_divergence(analysed):
    report = project_report.build_project_report(analysed)
    titles = [t.title for t in _blocks_of(report, m.Table)]
    assert "Member inventory" in titles
    assert "Divergence note" in titles


def test_an_unanalysed_member_says_so_and_is_not_analysed(project):
    project.member("rep_a").run_analysis()
    report = project_report.build_project_report(project)
    paragraphs = " ".join(p.text for p in _blocks_of(report, m.Paragraph))
    assert "rep_b has not been analysed" in paragraphs
    assert not (project.member("rep_b").analysis_dir / "run_summary.json").is_file()


def test_saved_analysis_rebuilds_sections_without_recomputing(analysed):
    member = analysed.member("rep_a")
    saved = project_report.SavedAnalysis(member)
    assert saved.exists
    assert len(saved.summary) > 0
    assert saved.omnibus_lr.get("p_value") is not None
    assert len(saved.cox_analyses) == 2          # Cox + RMST companions
    assert saved.figure_paths                      # figures found on disk


def test_project_report_writes_both_formats(analysed):
    written = project_report.write_project_report(analysed)
    assert written["pdf"].is_file() and written["md"].is_file()
    assert written["pdf"].parent == analysed.directory
