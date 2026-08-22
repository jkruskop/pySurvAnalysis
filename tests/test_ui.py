"""Hub, Plot Editor and Script Editor: state, not pixels.

Every test runs against the offscreen Qt platform; nothing here opens a window
a human has to close, and no test triggers a modal (``_warn`` would hang).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from pysurvanalysis.ui import apply_theme  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    apply_theme(app, "light")
    return app


@pytest.fixture
def hub(qapp, analysed_project):
    from pysurvanalysis.apps.hub import HubWindow

    project, _results = analysed_project
    window = HubWindow(str(project.directory))
    yield window
    window.close()


def _load_first_member(hub):
    index = hub._members_table.model().index(0, 0)
    hub._on_member_double_clicked(index)


def test_the_strip_has_all_eight_tiles(hub):
    assert list(hub._tiles) == ["batch", "project", "analyze", "qc", "plots",
                                "scripts", "ai", "tools"]


def test_a_project_selection_lights_the_project_tile(hub):
    assert hub._project is not None
    assert not hub._tiles["project"].is_dimmed()
    assert hub._batch is None and hub._tiles["batch"].is_dimmed()


def test_experiment_tiles_dim_until_something_is_loaded(hub):
    for key in ("analyze", "qc", "plots", "scripts"):
        assert hub._tiles[key].is_dimmed(), key
    _load_first_member(hub)
    for key in ("analyze", "qc", "plots", "scripts"):
        assert not hub._tiles[key].is_dimmed(), key


def test_the_members_table_is_the_way_to_load(hub):
    assert hub._experiment is None
    assert hub._members_table.rowCount() == 2
    _load_first_member(hub)
    assert hub._experiment.name == "rep_a"
    # The selection did not move down into the member.
    assert hub._selection == hub._project.directory


def test_analyze_buttons_come_from_the_type(hub):
    _load_first_member(hub)
    labels = _button_labels(hub._analyze_card)
    assert "Cox factorial model" in labels        # contributed by Interaction
    assert "Run analysis" in labels               # core
    assert "Parametric AFT models" not in labels  # not in this type's registry


def _button_labels(card) -> list[str]:
    layout = card.body_layout()
    return [layout.itemAt(i).widget().text()
            for i in range(layout.count())
            if hasattr(layout.itemAt(i).widget(), "text")]


def test_only_one_panel_is_open_at_a_time(hub):
    hub._toggle_panel("project")
    assert hub._open_panel == "project"
    hub._toggle_panel("tools")
    assert hub._open_panel == "tools"
    assert not hub._panels["project"].isVisible()
    hub._toggle_panel("tools")
    assert hub._open_panel is None


def test_the_status_readout_names_project_and_experiment(hub):
    assert "none loaded" in hub._status_panel.status_text()
    _load_first_member(hub)
    text = hub._status_panel.status_text()
    assert "rep_a" in text and "Interaction Experiment" in text


def test_a_standalone_experiment_selects_and_loads_itself(qapp, tmp_path):
    from pysurvanalysis.apps.hub import HubWindow
    from tests.conftest import make_experiment_dir

    directory = make_experiment_dir(tmp_path / "lone", type_key="standard_lifespan")
    window = HubWindow(str(directory))
    try:
        assert window._experiment is not None
        assert window._project is None
        assert window._tiles["project"].is_dimmed()
        assert "standalone" in window._tiles["project"].summary_text()
    finally:
        window.close()


def test_setting_the_exclusion_group_writes_the_config(hub):
    from pysurvanalysis.domain import config as cfgmod

    _load_first_member(hub)
    hub._group_combo.setEditText("review_v2")
    hub._action_set_exclusion_group()
    saved = cfgmod.load_config(hub._experiment.directory)
    assert saved["exclusions"]["group"] == "review_v2"
    assert hub._experiment.exclusion_group == "review_v2"


def test_plot_editor_opens_on_the_headline_figure(qapp, analysed_project):
    from pysurvanalysis.apps.plot_editor import PlotEditorWindow

    project, _results = analysed_project
    editor = PlotEditorWindow(project.member("rep_a"))
    try:
        assert editor._current_id == "km_faceted"
        assert editor.spec.facet_by == "Genotype"
        editor._refresh_preview()
        assert editor._preview.pixmap() is not None
    finally:
        editor.close()


def test_plot_editor_saves_specs_down_and_styles_up(qapp, analysed_project):
    from pysurvanalysis import pubfigures as pf
    from pysurvanalysis.apps.plot_editor import PlotEditorWindow
    from pysurvanalysis.domain import config as cfgmod

    project, _results = analysed_project
    member = project.member("rep_a")
    editor = PlotEditorWindow(member)
    try:
        editor._title_edit.setText("A curated title")
        editor._width.setValue(160.0)
        editor._save_spec()
        editor._save_style()
    finally:
        editor.close()

    assert pf.load_specs(member.directory)["km_faceted"].title == "A curated title"
    styles = cfgmod.read_yaml(project.specs_path)["styles"]
    assert styles["default"]["width_mm"] == 160.0
    assert "plots" not in cfgmod.read_yaml(project.specs_path)


def test_script_editor_switches_level_and_registry(qapp, analysed_project):
    from pysurvanalysis.script_editor.window import ScriptEditorWindow

    project, _results = analysed_project
    window = ScriptEditorWindow(str(project.member("rep_a").directory))
    try:
        assert window._level == "experiment"
        assert "cox_interaction" in window._registry()
        window._level_combo.setCurrentText("Project scripts")
        assert window._level == "project"
        assert "run_in_experiments" in window._registry()
        assert "cox_interaction" not in window._registry()
        assert window._target_path().name == "project.yaml"
    finally:
        window.close()
