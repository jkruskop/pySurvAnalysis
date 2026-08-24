"""Hub, Plot Editor and Script Editor: state, not pixels.

Every test runs against the offscreen Qt platform; nothing here opens a window
a human has to close, and no test triggers a modal (``_warn`` would hang).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
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
    ## QC precedes Analyze: you decide what to exclude before you analyse it.
    assert list(hub._tiles) == ["batch", "project", "qc", "analyze", "plots",
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


def test_plot_actions_land_on_the_plots_card_not_analyze(hub):
    """An Action's category decides its card: PLOTS ones leave Analyze."""
    _load_first_member(hub)
    analyze = _button_labels(hub._analyze_card)
    plots = _button_labels(hub._plot_actions_card)

    ## Core, and PLOTS: it renders figures, so it belongs beside them.
    assert "Render publication figures" in plots
    assert "Render publication figures" not in analyze

    ## Core, and ANALYZE: it stays put.
    assert "Run analysis" in analyze
    assert "Run analysis" not in plots

    ## Nothing the type contributes as a plot is left behind on Analyze.
    from pysurvanalysis.script_editor import actions as action_mod
    from pysurvanalysis.ui import Category

    registry = action_mod.registry_for(hub._experiment.type)
    plot_titles = {a.title for a in registry.values()
                   if a.category is Category.PLOTS}
    assert plot_titles, "expected this type to contribute at least one plot"
    assert plot_titles.isdisjoint(analyze)
    assert plot_titles <= set(plots)


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


def _shown(hub):
    """Show the window at the origin so global press points are resolvable."""
    hub.show()
    hub.move(0, 0)
    QApplication.instance().processEvents()
    return hub


def _press(global_pos):
    """Deliver a left-press at *global_pos*, the way the app-level filter sees
    one: through QApplication.notify, to whatever widget is under the point."""
    app = QApplication.instance()
    target = QApplication.widgetAt(global_pos)
    ## The offscreen screen is 800x800 and the strip forces a wider window, so
    ## a point past its right edge resolves to nothing at all.
    assert target is not None, f"no widget at {global_pos} — point off-screen"
    event = QMouseEvent(QEvent.Type.MouseButtonPress,
                        QPointF(target.mapFromGlobal(global_pos)),
                        QPointF(global_pos),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    app.sendEvent(target, event)
    app.processEvents()


def _blank_topbar_point(hub):
    """A spot on the top bar: above every panel, never the strip, no button."""
    return hub._topbar.mapToGlobal(QPoint(200, hub._topbar.height() // 2))


def test_a_press_outside_an_open_panel_closes_it(hub):
    ## Regression: the filter forwards to HubWindow._handle_click_away, and a
    ## missing handler raised inside a Qt event filter, which PyQt escalates
    ## to an abort — the Hub died on the first click after launch.
    _shown(hub)
    for key in hub._tiles:
        hub._toggle_panel(key)
        assert hub._open_panel == key and hub._panels[key].isVisible(), key
        _press(_blank_topbar_point(hub))
        assert hub._open_panel is None, key
        assert not hub._panels[key].isVisible(), key


def test_a_press_inside_an_open_panel_keeps_it_open(hub):
    _shown(hub)
    hub._toggle_panel("batch")
    _press(hub._panels["batch"].mapToGlobal(QPoint(8, 8)))
    assert hub._open_panel == "batch"


def test_a_press_on_the_strip_is_left_to_the_tile(hub):
    ## The filter must ignore the strip: closing there would let the tile's
    ## own toggle re-open the panel it was meant to close.
    _shown(hub)
    hub._toggle_panel("batch")
    _press(hub._tiles["batch"].mapToGlobal(QPoint(6, 6)))
    assert hub._open_panel is None
    hub._toggle_panel("batch")
    _press(hub._tiles["project"].mapToGlobal(QPoint(6, 6)))
    assert hub._open_panel == "project"


def test_a_resize_keeps_the_open_panel_anchored(hub):
    _shown(hub)
    hub._toggle_panel("project")
    hub.resize(hub.width() + 80, hub.height() - 40)
    QApplication.instance().processEvents()
    assert hub._open_panel == "project"
    panel, tile = hub._panels["project"], hub._tiles["project"]
    assert panel.isVisible()
    ## Still under its tile, clamped inside the window, after the tiles moved.
    tile_x = tile.mapTo(hub._central, tile.rect().bottomLeft()).x()
    assert panel.x() == max(8, min(tile_x, hub._central.width() - panel.width() - 8))


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
