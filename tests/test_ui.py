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

    ## Project-level only: rendering walks every member, so its button lives
    ## on the Project panel and NOWHERE on the experiment tiles. The script
    ## action still exists for Experiment Scripts.
    assert "Render publication figures" not in plots
    assert "Render publication figures" not in analyze

    ## Core, and ANALYZE: it stays put.
    assert "Run analysis" in analyze
    assert "Run analysis" not in plots

    ## Nothing the type contributes as a plot is left behind on Analyze.
    from pysurvanalysis.script_editor import actions as action_mod
    from pysurvanalysis.ui import Category

    registry = action_mod.registry_for(hub._experiment.type)
    plot_titles = {a.title for a in registry.values()
                   if a.category is Category.PLOTS
                   and a.key != "render_publication_figures"}
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


def test_plot_editor_saves_both_halves_to_the_project(qapp, analysed_project):
    """Specs AND Styles land in the container's one plot_specs.yaml — the
    sister app's model: what is saved here is the project default every
    member renders with."""
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

    payload = cfgmod.read_yaml(project.specs_path)
    assert payload["plots"]["km_faceted"]["title"] == "A curated title"
    assert payload["styles"]["default"]["width_mm"] == 160.0
    ## And nothing was written into the member.
    assert not (member.directory / cfgmod.SPECS_FILENAME).exists() \
        or "plots" not in cfgmod.read_yaml(
            member.directory / cfgmod.SPECS_FILENAME)
    ## The other member sees the same curation.
    assert pf.specs_for(project.member("rep_b"))["km_faceted"].title \
        == "A curated title"


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


def test_suppressing_tabs_closes_the_figure_only_during_a_batch_run(hub):
    """The switch is batch-scoped: a plot button clicked on one experiment is
    a request to SEE that figure, and suppressing it made the button do
    nothing visible."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hub._chk_suppress_tabs.setChecked(True)

    ## Not a batch task: the figure is shown, box or no box.
    hub._worker_is_batch = False
    figure = plt.figure()
    before = hub._plots.count()
    hub._on_figure("a curve", figure)
    assert hub._plots.count() == before + 1

    ## A batch task: suppressed, and closed rather than merely skipped —
    ## with no tab to own it pyplot would hold the figure for the life of
    ## the process.
    hub._worker_is_batch = True
    figure = plt.figure()
    before = hub._plots.count()
    hub._on_figure("a curve", figure)
    assert hub._plots.count() == before
    assert not plt.fignum_exists(figure.number)

    ## Batch task, box off: shown.
    hub._chk_suppress_tabs.setChecked(False)
    figure = plt.figure()
    before = hub._plots.count()
    hub._on_figure("a curve", figure)
    assert hub._plots.count() == before + 1
    hub._worker_is_batch = False


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
    assert row[1] == "yes"
    assert row[4] == "re-run needed"
    assert row[5] == "review_v2"


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


# ── the three states a folder can be in, at both levels ────────────────────

@pytest.fixture
def fresh_hub(qapp, tmp_path):
    """A Hub over a throwaway Project.

    Not the session-scoped ``hub`` fixture: these tests write directories into
    the Project, and the shared one is read by every other test in this file.
    """
    from pysurvanalysis.apps.hub import HubWindow
    from pysurvanalysis.domain import Project
    from tests.conftest import make_experiment_dir

    root = tmp_path / "states"
    Project.create(root, name="States", type_key="interaction")
    make_experiment_dir(root / "rep_a", minimal=True)
    (root / "rep_b_bare").mkdir()
    window = HubWindow(str(root))
    ## Every action under test reports refusals through _warn, which is modal.
    window._warned = []
    window._warn = lambda message: window._warned.append(message)
    yield window
    window.close()


def _member_rows(hub):
    return [(hub._members_table.item(r, 0).text(),
             hub._members_table.item(r, 1).text())
            for r in range(hub._members_table.rowCount())]


def test_the_members_table_shows_the_unconfigured_third_state(fresh_hub):
    """A folder with no config is not a member, so nothing else in the Hub can
    see it — and a table showing only members calls a half-set-up Project
    complete."""
    assert _member_rows(fresh_hub) == [("rep_a", "yes"), ("rep_b_bare", "missing")]


def test_double_clicking_a_missing_row_offers_to_scaffold_it(fresh_hub, monkeypatch):
    """The row is one config away from being a member, and asking beats
    sending the user to a button they have not found yet."""
    from PyQt6.QtWidgets import QMessageBox

    from pysurvanalysis.apps import hub as hub_mod

    monkeypatch.setattr(hub_mod.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    index = fresh_hub._members_table.model().index(1, 0)
    fresh_hub._on_member_double_clicked(index)
    assert fresh_hub._experiment is None            # scaffolding is not loading
    assert _member_rows(fresh_hub) == [("rep_a", "yes"), ("rep_b_bare", "yes")]


def test_create_experiment_sends_an_existing_folder_to_initialize(fresh_hub):
    """The two buttons cover different states; Create must not quietly adopt
    whatever is already in the directory."""
    fresh_hub._prompt_text = lambda *a, **k: "rep_b_bare"
    fresh_hub._finish_new_member_config = lambda *a, **k: None
    fresh_hub._action_create_experiment()
    assert fresh_hub._warned and "Initialize existing directory" in fresh_hub._warned[-1]
    assert _member_rows(fresh_hub) == [("rep_a", "yes"), ("rep_b_bare", "missing")]


def test_create_experiment_scaffolds_a_minimal_member(fresh_hub):
    """Minimal on purpose: a member that restates a default freezes it."""
    from pysurvanalysis.domain import config as cfgmod

    fresh_hub._prompt_text = lambda *a, **k: "rep_c"
    fresh_hub._finish_new_member_config = lambda *a, **k: None
    fresh_hub._action_create_experiment()
    member = fresh_hub._project.member("rep_c")
    assert member.data_dir.is_dir()
    assert "global" not in cfgmod.load_config(member.directory)
    assert ("rep_c", "yes") in _member_rows(fresh_hub)


def test_initialize_existing_directory_makes_the_bare_folder_a_member(fresh_hub):
    fresh_hub._prompt_choice = lambda title, label, options: options[0]
    fresh_hub._action_initialize_experiment()
    assert [m.name for m in fresh_hub._project.members()] == ["rep_a", "rep_b_bare"]
    assert not fresh_hub._warned


def test_initialize_existing_directory_says_when_there_is_nothing_to_do(fresh_hub):
    fresh_hub._prompt_choice = lambda title, label, options: options[0]
    fresh_hub._action_initialize_experiment()
    fresh_hub._action_initialize_experiment()
    assert "already has a" in fresh_hub._warned[-1]


def test_the_member_actions_wait_for_a_project(fresh_hub, tmp_path):
    """A member with nothing to inherit from is not a member."""
    assert all(b.isEnabled() for b in fresh_hub._member_action_buttons)
    bare = tmp_path / "not_a_project"
    bare.mkdir()
    fresh_hub._set_selection(bare)
    fresh_hub._refresh_all()
    assert not any(b.isEnabled() for b in fresh_hub._member_action_buttons)


def test_the_fourth_project_button_only_ever_edits(fresh_hub, tmp_path):
    """It is the editor for the Project that is open, and nothing else.

    Writing a project.yaml into a directory that has none is what 'Initialize
    existing directory…' does; having this button do it too gave the card two
    controls with one behaviour.
    """
    assert fresh_hub._btn_edit_project_cfg.text() == "Edit config…"
    assert fresh_hub._btn_edit_project_cfg.isEnabled()

    bare = tmp_path / "not_a_project"
    bare.mkdir()
    fresh_hub._set_selection(bare)
    fresh_hub._refresh_all()
    assert fresh_hub._btn_edit_project_cfg.text() == "Edit config…"
    assert not fresh_hub._btn_edit_project_cfg.isEnabled()

    ## And it refuses rather than quietly creating one, naming the button
    ## that does create it.
    fresh_hub._action_edit_project_config()
    assert "Initialize existing directory" in fresh_hub._warned[-1]
    assert not (bare / "project.yaml").exists()


def test_the_summary_line_describes_what_is_loaded(fresh_hub):
    text = fresh_hub._project_summary.text()
    assert "States" in text and "Interaction Experiment" in text
    assert "1 member(s)" in text
    assert "rep_b_bare" in text                     # the unconfigured folder


# ── the project.yaml editor the three ways in share ────────────────────────

def test_project_info_dialog_creates_the_directory_it_is_given(qapp, tmp_path):
    from PyQt6.QtWidgets import QTableWidgetItem

    from pysurvanalysis.apps.project_dialogs import ProjectInfoDialog
    from pysurvanalysis.domain import Project

    target = tmp_path / "brand_new"
    dialog = ProjectInfoDialog(None, start_dir=str(target))
    dialog.name_edit.setText("Brand new")
    dialog.question_edit.setText("Does it help?")
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("interaction"))
    dialog.factors_table.insertRow(0)
    dialog.factors_table.setItem(0, 0, QTableWidgetItem("Genotype"))
    dialog.factors_table.setItem(0, 1, QTableWidgetItem("wt, mut"))
    dialog.accept()

    assert dialog.saved_dir == str(target.resolve())
    project = Project(target)
    assert project.name == "Brand new"
    assert project.question == "Does it help?"
    assert project.type_key == "interaction"
    assert project.defaults["factors"] == {"Genotype": ["wt", "mut"]}
    ## Every Project ships a batch script, however it was made.
    assert [s["name"] for s in project.scripts()] == ["batch"]


def test_editing_a_project_carries_through_what_the_form_does_not_own(qapp, project):
    """Scripts, styles, a key from a future version: an edit here must not be
    a truncation."""
    from pysurvanalysis.apps.project_dialogs import ProjectInfoDialog
    from pysurvanalysis.domain import Project

    project.config["defaults"]["something_new"] = {"kept": True}
    project.save()

    dialog = ProjectInfoDialog(None, start_dir=str(project.directory))
    assert dialog.name_edit.text() == "Test project"
    assert dialog.type_combo.currentData() == "interaction"
    dialog.question_edit.setText("A sharper question")
    dialog.accept()

    reloaded = Project(project.directory)
    assert reloaded.question == "A sharper question"
    assert reloaded.type_key == "interaction"
    assert reloaded.defaults["something_new"] == {"kept": True}
    assert [s["name"] for s in reloaded.scripts()] == ["batch"]


def test_initializing_infers_the_type_from_what_is_already_there(qapp, tmp_path):
    """A study started before there were Projects already knows its type;
    offering the alphabetically-first one would propose one its own contents
    refute."""
    from pysurvanalysis.apps.project_dialogs import ProjectInfoDialog
    from pysurvanalysis.domain import Project
    from tests.conftest import make_experiment_dir

    legacy = tmp_path / "legacy_study"
    make_experiment_dir(legacy / "run1", type_key="standard_lifespan")

    dialog = ProjectInfoDialog(None, start_dir=str(legacy),
                               initialize_existing=True)
    assert dialog.type_combo.currentData() == "standard_lifespan"
    assert dialog.name_edit.text() == "legacy_study"     # keeps its own name
    dialog.accept()

    project = Project(legacy)
    assert project.type_key == "standard_lifespan"
    assert [m.name for m in project.members()] == ["run1"]
    assert project.validate() == []


def test_initializing_refuses_a_directory_that_is_already_a_project(qapp, project,
                                                                    monkeypatch):
    from pysurvanalysis.apps import project_dialogs

    warned = []
    monkeypatch.setattr(project_dialogs.QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[-1]))
    dialog = project_dialogs.ProjectInfoDialog(
        None, start_dir=str(project.directory), initialize_existing=True)
    assert dialog._resolved_target() is None
    assert warned and "already a Project" in warned[-1]


def test_member_configs_dialog_lists_both_states_and_creates_the_missing(
        qapp, project, monkeypatch):
    from pysurvanalysis.apps.project_dialogs import MemberConfigsDialog
    from PyQt6.QtWidgets import QMessageBox
    from pysurvanalysis.apps import project_dialogs

    (project.directory / "rep_c").mkdir()
    dialog = MemberConfigsDialog(None, project)
    assert [(r.name, r.configured) for r in dialog._rows] == [
        ("rep_a", True), ("rep_b", True), ("rep_c", False)]
    assert dialog._btn_create_all.isEnabled()

    monkeypatch.setattr(project_dialogs.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog._create_all_missing()
    assert all(r.configured for r in dialog._rows)
    assert dialog.changed
    assert not dialog._btn_create_all.isEnabled()


def test_no_panel_asks_for_more_width_than_it_gets(hub, qapp):
    """A panel clips rather than scrolls sideways, so over-wide content just
    disappears — silently, and only for whoever has the narrowest labels.

    Measured against every panel, not just the one that broke: the failure is
    a button row whose labels do not fit, and any card can grow one.
    """
    from pysurvanalysis.apps.hub import PANEL_WIDTH

    for key, panel in hub._panels.items():
        hub._open_panel_for(key)
        qapp.processEvents()
        host = panel._scroll.widget()
        ## The panel's own frame margins and the host layout's, which the
        ## content does not get (see TilePanel.__init__).
        available = PANEL_WIDTH - 8 - 16
        assert host.minimumSizeHint().width() <= available, (
            f"the {key} panel needs {host.minimumSizeHint().width()}px of "
            f"content width but has {available}px")
    hub.close_panel()


# ── publication figures live in two places, not four ───────────────────────

def test_the_plots_panel_holds_only_contributed_actions(hub):
    """Authoring a figure is Plot Editor work and rendering one is a Project
    action, so neither belongs on this tile."""
    from PyQt6.QtWidgets import QAbstractButton

    cards = hub._panels["plots"].cards()
    assert cards == [hub._plot_actions_card]
    labels = [b.text() for c in cards for b in c.findChildren(QAbstractButton)]
    assert not [t for t in labels if "figure" in t.lower() or "editor" in t.lower()]


def test_rendering_figures_is_a_project_action_over_every_member(hub, tmp_path,
                                                                 monkeypatch):
    """One implementation, shared with a Batch Run: the rule about which
    members get figures (ADR-0005) is stated in the action, not twice."""
    from pysurvanalysis.script_editor import project_actions

    calls = []
    monkeypatch.setattr(project_actions, "run_script",
                        lambda project, steps, **kw: calls.append((project, steps)))
    monkeypatch.setattr(hub, "_spawn", lambda _name, fn: fn())

    hub._fig_format.setCurrentText("pdf")
    hub._action_render_figures()
    assert len(calls) == 1
    project, steps = calls[0]
    assert project is hub._project                  # the Project, not a member
    assert steps == [{"action": "render_publication_figures", "format": "pdf"}]


def test_rendering_figures_needs_a_project_not_an_experiment(fresh_hub, tmp_path):
    bare = tmp_path / "nothing"
    bare.mkdir()
    fresh_hub._set_selection(bare)
    fresh_hub._refresh_all()
    fresh_hub._action_render_figures()
    assert fresh_hub._warned and "Select a Project first" in fresh_hub._warned[-1]


def test_the_plot_editor_resolves_a_member_from_the_project_panel(fresh_hub,
                                                                  monkeypatch):
    """It is the only way into the editor now, so it resolves a subject rather
    than refusing without a loaded experiment.

    Specs are still per-experiment (ADR-0005) — the button just answers "which
    member" from the panel it lives on instead of making the user load one.
    """
    opened = []

    class _FakeEditor:
        def __init__(self, experiment):
            opened.append(experiment.name)

        def show(self):
            pass

    import pysurvanalysis.apps.plot_editor as pe
    monkeypatch.setattr(pe, "PlotEditorWindow", _FakeEditor)

    ## One member: no question to ask.
    fresh_hub._action_open_plot_editor()
    assert opened == ["rep_a"]

    ## Two members and a selected row: the selection decides.
    fresh_hub._prompt_choice = lambda *a, **k: pytest.fail(
        "should not ask when a row is selected")
    fresh_hub._prompt_text = lambda *a, **k: "rep_z"
    fresh_hub._finish_new_member_config = lambda *a, **k: None
    fresh_hub._action_create_experiment()
    row = next(r for r in range(fresh_hub._members_table.rowCount())
               if fresh_hub._members_table.item(r, 0).text() == "rep_z")
    fresh_hub._members_table.selectRow(row)
    fresh_hub._action_open_plot_editor()
    assert opened[-1] == "rep_z"


def test_the_plot_editor_asks_which_member_when_nothing_points_at_one(fresh_hub,
                                                                     monkeypatch):
    import pysurvanalysis.apps.plot_editor as pe

    opened = []

    class _FakeEditor:
        def __init__(self, experiment):
            opened.append(experiment.name)

        def show(self):
            pass

    monkeypatch.setattr(pe, "PlotEditorWindow", _FakeEditor)
    fresh_hub._prompt_text = lambda *a, **k: "rep_z"
    fresh_hub._finish_new_member_config = lambda *a, **k: None
    fresh_hub._action_create_experiment()
    fresh_hub._members_table.clearSelection()

    asked = []
    fresh_hub._prompt_choice = lambda title, label, options: (
        asked.append(options) or options[-1])
    fresh_hub._action_open_plot_editor()
    assert asked == [["rep_a", "rep_z"]]
    assert opened == ["rep_z"]


# ── the Plot Editor's expanded controls ────────────────────────────────────

@pytest.fixture
def editor(qapp, tmp_path):
    from pysurvanalysis.apps.plot_editor import PlotEditorWindow
    from pysurvanalysis.domain import SurvivalExperiment
    from tests.conftest import make_experiment_dir

    directory = make_experiment_dir(tmp_path / "curated", type_key="interaction")
    window = PlotEditorWindow(SurvivalExperiment(directory))
    window.resize(1300, 900)
    ## The curves are not known until the lifetables are read, which happens
    ## on the first render.
    window._refresh_preview()
    yield window
    window.close()


def test_every_style_field_is_reachable_from_the_form(editor):
    """A style with forty fields fails silently: a control is added, its field
    is never harvested, and the figure just ignores it.

    So the mapping tables are asserted to COVER the dataclass. ``name`` is the
    Style's identity — chosen by the Save dialog, not edited in the form.
    """
    from dataclasses import fields

    from pysurvanalysis import pubfigures as pf

    mapped = {f for _attr, f in (editor._NUMBERS + editor._FLAGS
                                 + editor._CHOICES + editor._COLOURS)}
    mapped |= {"font_family", "risk_table_times", "palette", "palette_cycle"}
    declared = {f.name for f in fields(pf.PlotStyle)} - {"name"}
    assert declared - mapped == set(), \
        f"style fields with no control: {sorted(declared - mapped)}"


def test_every_mapped_control_round_trips(editor):
    """Load → harvest must be lossless, or an edit made in one card is undone
    by switching to another figure and back."""
    style = editor.style
    style.show_points = True
    style.point_stroke = 0.7
    style.point_shape = "s"
    style.point_at = "all"
    style.point_fill = "none"
    style.title_pt = 13.0
    style.tick_pt = 6.5
    style.text_color = "#223344"
    style.grid = "y"
    style.strip_style = "boxed"
    style.panel_border = True
    style.panel_bg = "#fafafa"
    style.line_pt = 1.4
    style.risk_table_times = [0.0, 25.0, 50.0]

    editor._load_style_into_form()
    _spec, harvested = editor._harvest()

    assert harvested.show_points is True
    assert harvested.point_stroke == 0.7
    assert harvested.point_shape == "s"
    assert harvested.point_at == "all"
    assert harvested.point_fill == "none"
    assert harvested.title_pt == 13.0
    assert harvested.tick_pt == 6.5
    assert harvested.text_color == "#223344"
    assert harvested.grid == "y"
    assert harvested.strip_style == "boxed"
    assert harvested.panel_border is True
    assert harvested.panel_bg == "#fafafa"
    assert harvested.line_pt == 1.4
    assert harvested.risk_table_times == [0.0, 25.0, 50.0]


def test_a_swatch_left_on_its_cycle_colour_is_not_pinned(editor):
    """``palette`` means "explicitly assigned".

    Without this, merely opening the editor and touching anything would write
    every curve's colour into the shared Style, and the fallback cycle would
    stop meaning anything for every other member using that Style.
    """
    assert set(editor._series_swatches) == {"ctrl", "drug"}
    _spec, style = editor._harvest()
    assert style.palette == {}

    editor._series_swatches["drug"].set_color("#aa3355")
    _spec, style = editor._harvest()
    assert style.palette == {"drug": "#aa3355"}

    editor._reset_series_colours()
    _spec, style = editor._harvest()
    assert style.palette == {}


def test_the_at_risk_times_field_ignores_a_half_typed_list(editor):
    """It is read on every edit, so a list mid-typing is not an error."""
    editor._risk_times.setText("0, 20, , 40x, 60")
    _spec, style = editor._harvest()
    assert style.risk_table_times == [0.0, 20.0, 60.0]


def test_the_plot_editor_has_no_output_log(editor):
    """Nothing in this window streams.

    The log printed four things: a failure the preview already states in full,
    and three one-line save confirmations. A 150px terminal for those was
    space taken from the figure, so the confirmations moved to the status bar.
    """
    from pysurvanalysis.ui import OutputLog

    assert not editor.findChildren(OutputLog)
    assert not hasattr(editor, "_log")


def test_saving_confirms_on_the_status_bar(editor):
    editor._save_spec()
    message = editor._status.currentMessage()
    assert "Saved" in message and "plot_specs.yaml" in message


def test_save_writes_only_the_current_figure(editor):
    """The working set fills defaults for the whole Plot Set so every figure
    is editable — but only what the user saves over lands in the yaml, or a
    render would produce every possible plot instead of the curated ones."""
    from pysurvanalysis import pubfigures as pf
    from pysurvanalysis.domain import config as cfgmod

    editor._title_edit.setText("Only me")
    editor._save_spec()
    payload = cfgmod.read_yaml(editor._specs_root / cfgmod.SPECS_FILENAME)
    current = editor._current_id
    assert list(payload["plots"]) == [current]
    assert payload["plots"][current]["title"] == "Only me"
    ## And the style it references was saved with it: a spec against an
    ## unsaved style would render with the stale copy on disk.
    assert payload["plots"][current]["style"] in payload["styles"]


def test_a_failed_preview_still_says_so_in_the_preview(editor, monkeypatch):
    """It was said twice — in the label and in the log. Removing the log must
    not have removed the message."""
    from pysurvanalysis import pubfigures as pf

    def _boom(*_a, **_k):
        raise ValueError("boom")

    monkeypatch.setattr(pf, "build_ggplot", _boom)
    editor._refresh_preview()
    assert editor._preview.text() == "Preview failed:\nboom"


def test_the_reference_line_is_governed_by_its_checkbox(editor):
    """Unchecked = no line. "none" used to be spelled -1.0, which both hid a
    legal value (a log-log reference is negative) and made "no line" a thing
    you scroll to rather than a thing you say."""
    assert editor._ref_check.isChecked()          # KM seeds the 0.5 median line

    editor._ref_check.setChecked(False)
    spec, _style = editor._harvest()
    assert spec.reference_line is None
    assert not editor._reference_line.isEnabled()

    editor._ref_check.setChecked(True)
    editor._reference_line.setValue(-0.25)        # legal now: log-log space
    spec, _style = editor._harvest()
    assert spec.reference_line == -0.25

    editor._load_spec_into_form()                 # and it round-trips
    assert editor._ref_check.isChecked()
    assert editor._reference_line.value() == -0.25
