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
    assert hub._batch is None


def test_the_two_ways_in_are_never_dimmed(hub):
    """Batch and Project stay lit whatever is selected.

    Their panels hold the pickers that create the state every other tile
    waits on, so a dimmed Batch tile would say "unavailable" about the one
    control that makes it available. They say what to do next in words
    instead.
    """
    assert not hub._tiles["batch"].is_dimmed()
    assert not hub._tiles["project"].is_dimmed()
    assert "project" in hub._tiles["batch"].summary_text()


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
        ## Not dimmed — the Project tile is a way in, and its panel is where
        ## "Create project…" lives. It says the state in words instead.
        assert not window._tiles["project"].is_dimmed()
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


# ---------------------------------------------------------------------------
# The recursive Batch panel, and the polish that came with it
# ---------------------------------------------------------------------------

@pytest.fixture
def nested_batch(tmp_path):
    """A Batch whose Projects sit at two different depths, one of them with a
    member that nothing can run."""
    from pysurvanalysis.domain import Project
    from tests.conftest import make_experiment_dir, write_cohort

    for group, name in (("Sept2026", "ProjA"), ("Archive/2025", "ProjB")):
        directory = tmp_path / group / name
        Project.create(directory, type_key="standard_lifespan")
        make_experiment_dir(directory / "m1", type_key="standard_lifespan",
                            minimal=True, seed=1)
    write_cohort(tmp_path / "Sept2026" / "ProjA" / "m2" / "data" / "c.csv")
    return tmp_path


@pytest.fixture
def batch_hub(qapp, nested_batch):
    from pysurvanalysis.apps.hub import HubWindow

    window = HubWindow(str(nested_batch))
    yield window
    window.close()


def _batch_rows(hub):
    return [[hub._batch_table.item(row, col).text()
             for col in range(hub._batch_table.columnCount())]
            for row in range(hub._batch_table.rowCount())]


def test_the_batch_panel_lists_projects_at_any_depth(batch_hub):
    assert batch_hub._batch is not None
    names = [row[0] for row in _batch_rows(batch_hub)]
    assert names == ["Archive/2025/ProjB", "Sept2026/ProjA"]


def test_a_row_states_its_usable_members_and_its_block_count(batch_hub):
    rows = {row[0]: row for row in _batch_rows(batch_hub)}
    assert rows["Sept2026/ProjA"][2] == "1/2"
    assert rows["Sept2026/ProjA"][4] == "1 blocked"
    assert rows["Archive/2025/ProjB"][4] == "ok"


def test_rebuilding_the_table_keeps_what_the_user_unchecked(batch_hub):
    from PyQt6.QtCore import Qt as _Qt

    batch_hub._batch_table.item(1, 0).setCheckState(_Qt.CheckState.Unchecked)
    batch_hub._refresh_all()
    assert batch_hub._batch_checked_keys() == ["Archive/2025/ProjB"]


def test_double_clicking_a_row_selects_that_project_and_shows_its_panel(batch_hub):
    index = batch_hub._batch_table.model().index(1, 0)
    batch_hub._on_batch_double_clicked(index)
    assert batch_hub._project is not None
    assert batch_hub._project.directory.name == "ProjA"
    assert batch_hub._open_panel == "project"


def test_the_preflight_states_the_target_list(qapp, nested_batch):
    from pysurvanalysis.apps.batch_preflight import BatchPreflightDialog

    dialog = BatchPreflightDialog(None, nested_batch)
    try:
        assert "2 project(s) found" in dialog._heading.text()
        assert "1 blocked member(s)" in dialog._heading.text()
        assert dialog.selected_keys == ["Archive/2025/ProjB", "Sept2026/ProjA"]
    finally:
        dialog.close()


def test_a_project_with_nothing_runnable_starts_unchecked(qapp, tmp_path):
    """It could only produce a failure — but repairing it in the preflight
    must put it back in the run, or the fix silently excludes the very Project
    the user just fixed."""
    from pysurvanalysis.apps.batch_preflight import BatchPreflightDialog
    from pysurvanalysis.domain import Project
    from tests.conftest import write_cohort

    Project.create(tmp_path / "Broken", type_key="standard_lifespan")
    write_cohort(tmp_path / "Broken" / "m" / "data" / "c.csv")
    dialog = BatchPreflightDialog(None, tmp_path)
    try:
        assert dialog.selected_keys == []
        dialog._fix_all()
        assert dialog.selected_keys == ["Broken"]
    finally:
        dialog.close()


def test_the_preflight_scaffolds_from_the_projects_own_defaults(qapp, nested_batch):
    from pysurvanalysis.apps.batch_preflight import BatchPreflightDialog
    from pysurvanalysis.domain import config as cfgmod

    dialog = BatchPreflightDialog(None, nested_batch)
    try:
        dialog._fix_all()
    finally:
        dialog.close()
    member = nested_batch / "Sept2026" / "ProjA" / "m2"
    assert cfgmod.is_experiment_dir(member)
    ## Minimal on purpose: a member that restates a default freezes it.
    assert "global" not in cfgmod.load_config(member)


def test_the_batch_tile_counts_projects_and_blocks(batch_hub):
    text = batch_hub._tiles["batch"].summary_text()
    assert "2 project(s)" in text and "1 blocked" in text


def test_cards_dim_until_they_have_a_subject(hub):
    for key in ("qc", "analyze", "plots", "scripts"):
        assert all(card.is_dimmed() for card in hub._panels[key].cards()), key
    ## ...but the two ways IN never dim: their panels hold the pickers.
    assert not any(card.is_dimmed() for card in hub._panels["batch"].cards())
    _load_first_member(hub)
    for key in ("qc", "analyze", "plots", "scripts"):
        assert not any(card.is_dimmed() for card in hub._panels[key].cards()), key


def test_loading_a_member_lands_on_the_analyze_panel(hub):
    _load_first_member(hub)
    assert hub._open_panel == "analyze"


def test_suppressing_tabs_closes_the_figure_instead_of_showing_it(hub):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hub._chk_suppress_tabs.setChecked(True)
    figure = plt.figure()
    before = hub._plots.count()
    hub._on_figure("a curve", figure)
    assert hub._plots.count() == before
    ## Closed, not merely skipped: with no tab to own it pyplot would hold the
    ## figure for the life of the process.
    assert not plt.fignum_exists(figure.number)


def test_unsuppressed_figures_still_become_tabs(hub):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hub._chk_suppress_tabs.setChecked(False)
    before = hub._plots.count()
    hub._on_figure("a curve", plt.figure())
    assert hub._plots.count() == before + 1


def test_the_output_log_reassembles_a_streamed_line(qapp):
    """`print` writes its text and its terminator separately, so a chunk is
    not a line. Treating each chunk as one put a blank row after every printed
    line and broke wide tables apart."""
    from pysurvanalysis.ui import OutputLog

    log = OutputLog()
    log.append_stream("one")
    log.append_stream("\n")
    log.append_stream("two\nthree")
    log.append_stream("\n")
    assert log.toPlainText().splitlines() == ["one", "two", "three"]


def test_a_finished_message_never_glues_onto_a_partial_line(qapp):
    from pysurvanalysis.ui import OutputLog

    log = OutputLog()
    log.append_stream("half a line")
    log.append_line("a complete message")
    assert log.toPlainText().splitlines() == ["half a line", "a complete message"]


def test_clearing_the_output_leaves_the_tab_in_place(hub):
    hub._log.append_line("something")
    hub._plots.clear_output()
    assert hub._log.toPlainText() == ""
    assert hub._plots.count() >= 1
    assert hub._plots.widget(0) is hub._log


def test_a_member_analysed_under_another_exclusion_group_reads_stale(analysed_project):
    """An Exclusion Group is configuration, stamped on every output so the
    same input and config always give the same result — so a changed group
    makes the saved numbers describe a population nobody asked for."""
    from pysurvanalysis.domain import config as cfgmod

    project, _results = analysed_project
    member = project.member("rep_a")
    assert not member.status().stale
    config = cfgmod.load_config(member.directory)
    config["exclusions"] = {"group": "review_v2"}
    cfgmod.save_config(member.directory, config)
    ## reload=True: members() caches, which is why _refresh_all re-reads.
    project.members(reload=True)
    assert project.member("rep_a").status().stale


def test_the_members_table_notices_a_config_written_under_it(hub):
    """The table is where member state is read, so it must reflect disk — not
    the state the Project happened to be loaded with."""
    from pysurvanalysis.domain import config as cfgmod

    _load_first_member(hub)
    hub._group_combo.setEditText("review_v2")
    hub._action_set_exclusion_group()
    row = [hub._members_table.item(0, col).text()
           for col in range(hub._members_table.columnCount())]
    assert row[0] == "rep_a"
    assert row[3] == "re-run needed"
    assert row[4] == "review_v2"


def test_the_batch_controls_are_off_until_a_batch_is_selected(hub):
    """The Project fixture selects a Project, which is never also a Batch."""
    assert hub._batch is None
    assert hub._batch_empty.isVisible() or not hub._panels["batch"].isVisible()
    for widget in hub._batch_widgets:
        assert not widget.isEnabled()


def test_navigating_away_from_a_batch_clears_its_script_picker(batch_hub, tmp_path):
    """A designation from a folder the user has left must not look like it is
    still in force."""
    from pysurvanalysis.domain import Project
    from tests.conftest import make_experiment_dir

    assert batch_hub._batch_script.count() > 0
    elsewhere = tmp_path / "Solo"
    Project.create(elsewhere, type_key="standard_lifespan")
    make_experiment_dir(elsewhere / "m1", type_key="standard_lifespan",
                        minimal=True)
    batch_hub._set_selection(elsewhere)
    batch_hub._refresh_all()
    assert batch_hub._batch is None
    assert batch_hub._batch_script.count() == 0
    assert batch_hub._batch_table.rowCount() == 0
