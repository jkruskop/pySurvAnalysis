"""The Analysis Hub — pySurvAnalysis's main window.

A horizontal tile strip (Batch · Project · Analyze · QC · Plots · Scripts · AI ·
Tools) over a full-width output area. Each tile shows only live status; all of
its controls live in an anchored panel, one open at a time.

Two things differ from the sister app by design:

* the **selection** may be a Batch, a Project, *or* a standalone Experiment
  Directory — a Project is not required to load anything (ADR-0003); and
* the **Analyze** panel's buttons are contributed by the loaded experiment's
  Experiment Type, so a button and its script action are one declaration
  (ADR-0002).

Batch discovery is recursive (ADR-0009), so the selection may name a folder
several levels above the Projects. The walk is expensive next to the single
``iterdir`` it replaced and every tile refresh reads it, so it is done once per
selection and cached on the ``Batch``; **Rescan** re-runs it. A Batch Run is
always confirmed in the preflight, because with recursion the folder the user
picked no longer says what will run.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..gui_env import sanitize_input_method_environment

## Before Qt is imported, not after: the overrides are read when the
## platform plugin initialises.
sanitize_input_method_environment()

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QBrush
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..domain import (
    Batch,
    Project,
    ProjectError,
    SurvivalExperiment,
    config as cfgmod,
    is_experiment_dir,
    is_project_dir,
    layout as layout_mod,
    upgrade as upgrade_mod,
)
from ..experiment_types import available_types
from ..script_editor.project_actions import DEFAULT_PROJECT_SCRIPT_NAME
from ..ui import (
    ActionButton,
    Card,
    Category,
    OutputLog,
    PlotDock,
    TopBar,
    apply_theme,
    current_mode,
    icon,
)
from ..ui import settings as ui_settings
from ._hub_tiles import ClickAwayFilter, StatusPanel, StatusTile, TilePanel
from .batch_preflight import BatchPreflightDialog, blocked_color
from .common import TaskWorker

PANEL_WIDTH = 540

#: key, title, icon, category — the strip, left to right.
TILES = (
    ("batch", "Batch", "batch", Category.NEUTRAL),
    ("project", "Project", "project", Category.NEUTRAL),
    ("qc", "QC", "qc", Category.QC),
    ("analyze", "Analyze", "analyze", Category.ANALYZE),
    ("plots", "Plots", "plots", Category.PLOTS),
    ("scripts", "Scripts", "scripts", Category.SCRIPTS),
    ("ai", "AI", "ai", Category.AI),
    ("tools", "Tools", "tools", Category.TOOLS),
)


#: The Batch picker's leading entry — designates nothing (see ADR: no
#: designation means each Project runs its own default script).
BATCH_OWN_SCRIPT_ITEM = f"Each project's own {DEFAULT_PROJECT_SCRIPT_NAME!r} script (default)"


class HubWindow(QMainWindow):
    """The Hub. One selection, at most one loaded experiment, one open panel."""

    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("pySurvAnalysis — Analysis Hub")
        self.resize(1360, 900)

        self._selection: Path | None = None
        self._batch: Batch | None = None
        self._project: Project | None = None
        self._experiment: SurvivalExperiment | None = None
        self._worker: TaskWorker | None = None
        self._tiles: dict[str, StatusTile] = {}
        self._panels: dict[str, TilePanel] = {}
        self._open_panel: str | None = None

        self._build_ui()
        self._click_away = ClickAwayFilter(self)
        app = QApplication.instance()
        app.installEventFilter(self._click_away)
        ## Belt to closeEvent's braces: catch quit paths that never close
        ## the window (see _detach_click_away).
        app.aboutToQuit.connect(self._detach_click_away)

        ## Nothing is selected on launch unless a path was named on the
        ## command line: the Hub opens on no subject, and the user picks one
        ## (Open project…, or Recent). Restoring the last project silently
        ## re-opened work the user may have finished with.
        if initial_path:
            self._set_selection(initial_path)
        self._refresh_all()

    # ── construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(8)

        self._topbar = TopBar("pySurvAnalysis")
        ## Opening lives in the Project card, where the work starts; the top
        ## bar keeps only Recent and the theme toggle.
        recent_btn = QPushButton(icon("menu"), " Recent")
        recent_btn.clicked.connect(self._show_recent_menu)
        theme_btn = QPushButton(icon("theme_dark"), "")
        theme_btn.setToolTip("Toggle light/dark theme")
        theme_btn.clicked.connect(self._toggle_theme)
        for btn in (recent_btn, theme_btn):
            self._topbar.add_right(btn)
        outer.addWidget(self._topbar)

        strip = QWidget()
        strip_lay = QHBoxLayout(strip)
        strip_lay.setContentsMargins(0, 0, 0, 0)
        strip_lay.setSpacing(1)
        for i, (key, title, icon_name, category) in enumerate(TILES):
            tile = StatusTile(key, title, icon_name, category)
            tile.set_rounding(8 if i == 0 else 0, 0)
            tile.clicked.connect(self._toggle_panel)
            self._tiles[key] = tile
            strip_lay.addWidget(tile)
        self._status_panel = StatusPanel()
        strip_lay.addWidget(self._status_panel, 1)
        outer.addWidget(strip)
        self._strip = strip

        # The log is the dock's first tab; figures open beside it.
        self._log = OutputLog()
        self._plots = PlotDock(self._log)
        outer.addWidget(self._plots, 1)

        self._central = central
        for key, *_ in TILES:
            panel = TilePanel(key, PANEL_WIDTH, central)
            self._panels[key] = panel
        self._build_panels()

    def _build_panels(self) -> None:
        self._build_batch_panel()
        self._build_project_panel()
        self._build_qc_panel()
        self._build_analyze_panel()
        self._build_plots_panel()
        self._build_scripts_panel()
        self._build_ai_panel()
        self._build_tools_panel()
        for panel in self._panels.values():
            panel.finish()

    # ── panels ─────────────────────────────────────────────────────────────

    def _build_batch_panel(self) -> None:
        card = Card("Batch run", Category.NEUTRAL, icon_name="batch",
                    subtitle="Run one Project Script in every Project inside "
                             "this folder, continue-on-error. Projects are "
                             "found recursively, so they can sit at any depth.")
        row = QHBoxLayout()
        open_btn = QPushButton(icon("open"), " Choose batch folder…")
        open_btn.setToolTip(
            "Pick the folder that holds your Projects. They are found "
            "recursively, so grouping folders (Sept2026/, Archive/2025/) are "
            "transparent — every Project found is listed below for the run.")
        open_btn.clicked.connect(self._pick_directory)
        rescan = QPushButton(icon("refresh"), " Rescan")
        rescan.setToolTip(
            "Walk the batch folder again. The project list is read once when "
            "the folder is selected; rescan after adding or fixing projects "
            "outside the app.")
        rescan.clicked.connect(self._action_rescan_batch)
        self._btn_batch_rescan = rescan
        row.addWidget(open_btn)
        row.addWidget(rescan)
        card.add_body(row)

        self._batch_empty = QLabel(
            "Choose a folder with Projects anywhere inside it, and every one "
            "found is listed here for the run. A Project is a folder with a "
            "project.yaml and at least one member experiment.")
        self._batch_empty.setStyleSheet("color: palette(mid); font-style: italic;")
        self._batch_empty.setWordWrap(True)
        card.add_body(self._batch_empty)

        self._batch_table = self._make_table(
            ["Project", "Type", "Members", "Report", "Status"])
        self._batch_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._batch_table.setToolTip(
            "Checked Projects join the next Batch Run. A row's name is its "
            "path inside the batch folder. Double-click to open that Project; "
            "right-click for its blocked members.")
        self._batch_table.doubleClicked.connect(self._on_batch_double_clicked)
        ## Right-click, not double-click: double-click already means "open
        ## this Project", so the repair menu takes the gesture that is free.
        self._batch_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._batch_table.customContextMenuRequested.connect(self._batch_menu)
        card.add_body(self._batch_table)
        hint = QLabel("Double-click a project to open its Project panel. "
                      "Right-click to fix its blocked members.")
        hint.setStyleSheet("color: palette(mid); font-style: italic;")
        hint.setWordWrap(True)
        card.add_body(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("Script:"))
        self._batch_script = QComboBox()
        self._batch_script.setSizePolicy(QSizePolicy.Policy.Ignored,
                                         QSizePolicy.Policy.Fixed)
        row.addWidget(self._batch_script, 1)
        card.add_body(row)

        run = ActionButton("Run batch", Category.NEUTRAL, icon_name="play")
        run.setToolTip(
            "Review the target list, then run the designated Project Script "
            "in every checked Project — continue-on-error, per-Project "
            "summary at the end.")
        ## Through a lambda: clicked() would otherwise pass its bool into the
        ## focus argument.
        run.clicked.connect(lambda: self._action_run_batch())
        card.add_body(run)

        ## A Batch Run touches every member of every Project, so the figure
        ## tabs it would open run into the hundreds and bury the Output tab
        ## the user is actually reading. Checked, new tabs stop being created;
        ## the Output tab keeps streaming and every artefact is still written
        ## to disk. On by default, and deliberately NOT gated on a Batch being
        ## selected — it applies to every run.
        self._chk_suppress_tabs = QCheckBox("Suppress new plot tabs")
        self._chk_suppress_tabs.setToolTip(
            "Stop opening a tab for every figure. The Output tab keeps "
            "updating and every figure is still written to disk — only the "
            "tabs are skipped. Applies to all runs while it is checked, not "
            "just Batch Runs.")
        self._chk_suppress_tabs.setChecked(True)
        card.add_body(self._chk_suppress_tabs)

        ## Everything that acts on a Batch is off until one is selected. The
        ## suppress-tabs box is deliberately NOT in this list: it applies to
        ## every run, so it stays usable with no Batch in hand.
        self._batch_widgets = (self._batch_table, self._batch_script, run,
                               rescan)
        for widget in self._batch_widgets:
            widget.setEnabled(False)
        self._batch_card = card
        self._panels["batch"].add_card(card)

    def _build_project_panel(self) -> None:
        card = Card("Project", Category.NEUTRAL, icon_name="project",
                    subtitle="Double-click a member to load it.")
        ## Open and Create lead the card: opening or making a Project is the
        ## first thing anyone does here, so they sit above the members grid.
        row = QHBoxLayout()
        open_btn = QPushButton(icon("open"), " Open project…")
        open_btn.clicked.connect(self._pick_directory)
        create = QPushButton(icon("new"), " Create project…")
        create.clicked.connect(self._action_create_project)
        row.addWidget(open_btn)
        row.addWidget(create)
        card.add_body(row)

        self._members_table = self._make_table(
            ["Member", "Type", "N", "Analysed", "Exclusions"])
        self._members_table.doubleClicked.connect(self._on_member_double_clicked)
        card.add_body(self._members_table)

        ## Three ways in, because members arrive three ways: an existing
        ## experiment folder, an empty one to fill, or a bare workbook.
        row = QHBoxLayout()
        adopt_dir = QPushButton(icon("open"), " Add directory…")
        adopt_dir.setToolTip("Take an existing experiment directory (with a "
                             "data/ folder) into this Project.")
        adopt_dir.clicked.connect(self._action_add_directory)
        create_dir = QPushButton(icon("add"), " Create directory…")
        create_dir.setToolTip("Scaffold an empty member: a data/ folder and a "
                              "default config from the Project's type.")
        create_dir.clicked.connect(self._action_add_member)
        adopt_file = QPushButton(icon("excel"), " Add experiment…")
        adopt_file.setToolTip("Build a member around one DLife workbook.")
        adopt_file.clicked.connect(self._action_add_experiment)
        for btn in (adopt_dir, create_dir, adopt_file):
            row.addWidget(btn)
        card.add_body(row)
        self._panels["project"].add_card(card)

        actions_card = Card("Actions", Category.NEUTRAL, icon_name="report")
        self._project_actions_card = actions_card
        ## Every button here is NEUTRAL. They are all project actions, and
        ## colouring each by the category of the work it happens to do made
        ## one card read as a rainbow of unrelated things — the panel's
        ## identity already comes from the tile above it. Category colour is
        ## reserved for the panels where it distinguishes something: the
        ## type-contributed Analyze and Plots buttons, and Tools.
        ## Two rows of two: these are peers, and a stack of full-width
        ## buttons made small actions look like the main event.
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        report_btn = ActionButton("Project report", Category.NEUTRAL,
                                  icon_name="report")
        report_btn.setToolTip(
            "Bind one section per Member Experiment from each member's SAVED "
            "outputs, behind the Member Inventory and the Divergence Note. A "
            "member that has not been analysed yields a 'not analysed' "
            "section rather than being silently analysed.")
        report_btn.clicked.connect(self._action_project_report)
        view_btn = ActionButton("View reports", Category.NEUTRAL,
                                icon_name="pdf")
        view_btn.clicked.connect(self._action_view_reports)
        self._btn_view_reports = view_btn
        validate_btn = ActionButton("Validate YAMLs", Category.NEUTRAL,
                                    icon_name="validate")
        validate_btn.setToolTip(
            "Check the Project's project.yaml and every member's "
            "survival_config.yaml — parse errors and semantic problems alike. "
            "Validating only the loaded member left the rest of a Project "
            "unchecked, which is exactly where a type mismatch hides.")
        validate_btn.clicked.connect(self._action_validate_project)
        plots_btn = ActionButton("Plot editor…", Category.NEUTRAL,
                                 icon_name="plot")
        plots_btn.clicked.connect(self._action_open_plot_editor)
        for i, btn in enumerate((report_btn, view_btn, validate_btn, plots_btn)):
            grid.addWidget(btn, i // 2, i % 2)
        for col in range(2):
            grid.setColumnStretch(col, 1)
        actions_card.add_body(grid)
        self._panels["project"].add_card(actions_card)

        scripts_card = Card("Scripts", Category.SCRIPTS, icon_name="scripts",
                            subtitle="The Project's own scripts first, then "
                                     "the built-ins.")
        self._project_scripts_card = scripts_card
        row = QHBoxLayout()
        self._project_script = QComboBox()
        self._project_script.setSizePolicy(QSizePolicy.Policy.Ignored,
                                           QSizePolicy.Policy.Fixed)
        row.addWidget(self._project_script, 1)
        run_btn = ActionButton("Run script", Category.NEUTRAL, icon_name="play")
        run_btn.clicked.connect(self._action_run_project_script)
        row.addWidget(run_btn)
        scripts_card.add_body(row)
        edit_btn = ActionButton("Edit scripts…", Category.NEUTRAL,
                                icon_name="config")
        edit_btn.setToolTip(
            "Open the Script Editor on project.yaml — Project Scripts plus "
            "the central experiment_scripts: one recipe serving every member.")
        edit_btn.clicked.connect(self._action_open_script_editor)
        scripts_card.add_body(edit_btn)
        self._panels["project"].add_card(scripts_card)

    def _build_analyze_panel(self) -> None:
        self._analyze_card = Card(
            "Analyze", Category.ANALYZE, icon_name="analyze",
            subtitle="Buttons here are contributed by the loaded experiment's "
                     "Experiment Type.")
        self._panels["analyze"].add_card(self._analyze_card)

    def _build_qc_panel(self) -> None:
        card = Card("Quality control", Category.QC, icon_name="qc",
                    subtitle="Exclusion groups are configuration: the active "
                             "group is written to survival_config.yaml and "
                             "stamped on every output.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Active group:"))
        self._group_combo = QComboBox()
        self._group_combo.setEditable(True)
        row.addWidget(self._group_combo, 1)
        card.add_body(row)

        apply_btn = ActionButton("Set active group", Category.QC, icon_name="check")
        apply_btn.clicked.connect(self._action_set_exclusion_group)
        card.add_body(apply_btn)

        viewer = ActionButton("Chamber QC viewer…", Category.QC, icon_name="chamber")
        viewer.clicked.connect(self._action_open_qc_viewer)
        card.add_body(viewer)
        self._panels["qc"].add_card(card)

    def _build_plots_panel(self) -> None:
        ## Plot-producing actions live here, not under Analyze: an Action
        ## already declares its category, and a plot is a plot wherever the
        ## Experiment Type contributed it from.
        self._plot_actions_card = Card(
            "Plots", Category.PLOTS, icon_name="plot",
            subtitle="Buttons here are contributed by the loaded experiment's "
                     "Experiment Type.")
        self._panels["plots"].add_card(self._plot_actions_card)

        card = Card("Publication figures", Category.PLOTS, icon_name="figures",
                    subtitle="Vector figures from plot_specs.yaml — styles come "
                             "from the Project, specs from the experiment.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Format:"))
        self._fig_format = QComboBox()
        self._fig_format.addItems(["svg", "pdf", "png"])
        row.addWidget(self._fig_format, 1)
        card.add_body(row)

        render = ActionButton("Render figures", Category.PLOTS, icon_name="figures")
        render.clicked.connect(self._action_render_figures)
        card.add_body(render)
        editor = ActionButton("Plot editor…", Category.PLOTS, icon_name="plot")
        editor.clicked.connect(self._action_open_plot_editor)
        card.add_body(editor)
        self._panels["plots"].add_card(card)

    def _build_scripts_panel(self) -> None:
        card = Card("Experiment scripts", Category.SCRIPTS, icon_name="scripts",
                    subtitle="The loaded experiment's own scripts, plus the "
                             "Project's central set.")
        self._scripts_combo = QComboBox()
        card.add_body(self._scripts_combo)
        run = ActionButton("Run script", Category.SCRIPTS, icon_name="play")
        run.clicked.connect(self._action_run_experiment_script)
        card.add_body(run)
        edit = ActionButton("Edit scripts…", Category.SCRIPTS, icon_name="config")
        edit.clicked.connect(self._action_open_script_editor)
        card.add_body(edit)
        self._panels["scripts"].add_card(card)

    def _build_ai_panel(self) -> None:
        card = Card("AI narrative", Category.AI, icon_name="ai",
                    subtitle="A paragraph per member plus a labelled "
                             "across-members paragraph. Summarizes the saved "
                             "numbers; never computes its own.")
        self._ai_status = QLabel("")
        self._ai_status.setWordWrap(True)
        card.add_body(self._ai_status)

        row = QHBoxLayout()
        row.addWidget(QLabel("Provider:"))
        self._ai_provider = QComboBox()
        row.addWidget(self._ai_provider, 1)
        card.add_body(row)

        run = ActionButton("Write narrative", Category.AI, icon_name="ai")
        run.clicked.connect(self._action_ai_narrative)
        card.add_body(run)
        with_report = ActionButton("Project report with narrative",
                                   Category.AI, icon_name="report")
        with_report.clicked.connect(
            lambda: self._action_project_report(with_narrative=True))
        card.add_body(with_report)
        self._panels["ai"].add_card(card)

    def _build_tools_panel(self) -> None:
        card = Card("Tools", Category.TOOLS, icon_name="tools")
        for label, icon_name, handler in (
            ("Upgrade directory…", "upgrade", self._action_upgrade),
            ("Wrap in a project…", "project", self._action_wrap_in_project),
            ("Validate config", "validate", self._action_validate_config),
            ("Open analysis folder", "open", self._action_open_analysis),
            ("Clear log", "clear", self._log.clear),
        ):
            btn = ActionButton(label, Category.TOOLS, icon_name=icon_name)
            btn.clicked.connect(handler)
            card.add_body(btn)
        self._panels["tools"].add_card(card)

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(headers)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        table.setMinimumHeight(150)
        return table

    # ── panel open/close ───────────────────────────────────────────────────

    def _toggle_panel(self, key: str) -> None:
        if self._open_panel == key:
            self.close_panel()
            return
        self._open_panel_for(key)

    def _open_panel_for(self, key: str) -> None:
        """Open *key*'s panel, whatever is open now.

        Separate from :meth:`_toggle_panel` because some flows *move* the user
        to a panel — double-clicking a Batch row lands them on Project, and a
        finished load lands them on Analyze — and a toggle would close it
        again whenever they were already there.
        """
        self.close_panel()
        tile = self._tiles[key]
        panel = self._panels[key]
        top_left = tile.mapTo(self._central, tile.rect().bottomLeft())
        ## rect().bottom* coordinates are inclusive; +1 starts the panel just
        ## below the strip while preserving the caller-owned bottom margin.
        panel.open_at(top_left.x(), top_left.y() + 1, self._central.height() - 8)
        tile.set_active(True)
        self._open_panel = key

    def close_panel(self) -> None:
        if self._open_panel is None:
            return
        self._panels[self._open_panel].hide()
        self._tiles[self._open_panel].set_active(False)
        self._open_panel = None

    def _handle_click_away(self, event) -> None:
        """Close the open panel when a press lands outside it.

        Called by :class:`ClickAwayFilter` on GUI-thread mouse presses only.
        The click itself is never swallowed. Presses on the tile strip are
        ignored so a tile's own toggle still sees the panel as open (and
        therefore closes it) rather than re-opening it.
        """
        if self._open_panel is None:
            return
        panel = self._panels.get(self._open_panel)
        if panel is None or not panel.isVisible():
            return
        widget = QApplication.widgetAt(event.globalPosition().toPoint())
        ## A press in another window (a dialog, the QC viewer, the Script
        ## Editor) is not a click away from this panel — closing it there left
        ## the user's place lost behind a dialog they were about to dismiss.
        if widget is not None and widget.window() is not self:
            return
        probe = widget
        while probe is not None:
            if probe is panel or probe is self._strip:
                return
            probe = probe.parentWidget()
        self.close_panel()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        ## Keep an open panel anchored under its tile when the window resizes.
        ## getattr: a resize can arrive before __init__ finishes building.
        key = getattr(self, "_open_panel", None)
        if key is not None:
            self._open_panel = None
            self._toggle_panel(key)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()
        super().keyPressEvent(event)

    def _detach_click_away(self) -> None:
        """Uninstall the app-level filter.

        Left installed it outlives the widgets it forwards to, and Qt still
        routes shutdown events through it once a panel has been shown —
        observed as a segfault on quit.
        """
        app = QApplication.instance()
        if app is not None and self._click_away is not None:
            app.removeEventFilter(self._click_away)
        self._click_away = None

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.close_panel()
        self._detach_click_away()
        super().closeEvent(event)

    # ── selection ──────────────────────────────────────────────────────────

    def _pick_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Open a Batch, Project or Experiment directory",
            str(self._selection or Path.home()))
        if path:
            self._set_selection(path)
            self._refresh_all()

    def _show_recent_menu(self) -> None:
        menu = QMenu(self)
        recent = ui_settings.get("recent_projects", []) or []
        if not recent:
            menu.addAction("(nothing recent)").setEnabled(False)
        for path in recent:
            act = QAction(path, self)
            act.triggered.connect(
                lambda _checked, p=path: (self._set_selection(p), self._refresh_all()))
            menu.addAction(act)
        menu.exec(self.cursor().pos())

    def _set_selection(self, path: str | Path) -> None:
        """Classify a directory as Batch, Project, standalone Experiment, or bare.

        The selection names the working container; loading a Member Experiment
        is a separate act (a double-click in the members table), so the two
        contexts can never disagree about the current subject.
        """
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            self._warn(f"{p} is not a directory.")
            return

        self._selection = p
        self._batch = None
        self._project = None
        self._experiment = None

        if is_project_dir(p):
            try:
                self._project = Project(p)
            except ProjectError as exc:
                self._warn(str(exc))
        elif is_experiment_dir(p):
            # A standalone Experiment Directory loads itself: with no pooling,
            # a Project buys it nothing (ADR-0003).
            parent_project = Project(p.parent) if is_project_dir(p.parent) else None
            self._project = parent_project
            defaults = parent_project.defaults if parent_project else {}
            self._experiment = SurvivalExperiment(p, defaults=defaults,
                                                  project=parent_project)
            self._log.append_line(f"Loaded standalone experiment {p.name} "
                             f"({self._experiment.type.label}).")
        else:
            ## Recursive: Projects need not be immediate children, so a
            ## grouping folder full of dated subfolders is a Batch too. The
            ## walk is done once here and cached on the Batch.
            candidate = Batch(p)
            if candidate.batch_projects():
                self._batch = candidate

        ui_settings.add_recent_project(str(p))
        kind = ("Batch" if self._batch is not None else
                "Project" if self._project is not None else
                "Experiment" if self._experiment is not None else "Directory")
        self._log.append_line(f"{kind}: {p}")
        if self._batch is not None:
            for key, why in self._batch.skipped():
                self._log.append_line(f"[batch] {key} skipped — {why}")
            if self._batch.truncated:
                self._log.append_line(
                    f"[batch] the scan of {p} stopped early — this folder is "
                    "larger than a batch should be, and projects deeper in it "
                    "were not found. Choose one closer to the projects.")

    def _on_member_double_clicked(self, index) -> None:
        if self._project is None:
            return
        row = index.row()
        item = self._members_table.item(row, 0)
        if item is None:
            return
        name = item.text()
        try:
            self._experiment = self._project.member(name)
        except ProjectError as exc:
            self._warn(str(exc))
            return
        self._log.append_line(f"Loaded {name} ({self._experiment.type.label}).")
        self._refresh_all()
        ## Loading is a means, not an end: the next thing anyone does with a
        ## member is analyse it, so the double-click lands them there rather
        ## than leaving the Project panel open over a now-live Analyze tile.
        self._open_panel_for("analyze")

    # ── refresh ────────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        ## Re-read the members from disk first. Project.members() caches, and
        ## every surface below reads through it — so after a config write (an
        ## exclusion group set here, a script run, an edit in another window)
        ## the table went on showing the state the Project was loaded with,
        ## and a member that had just gone stale never said so. Cheap: one
        ## small YAML per member, which is what the status contract assumes.
        if self._project is not None:
            self._project.members(reload=True)
        self._refresh_tables()
        self._refresh_action_panels()
        self._refresh_scripts()
        self._refresh_exclusion_groups()
        self._refresh_ai()
        self._refresh_tiles()

    def _refresh_tiles(self) -> None:
        ## Batch and Project are never dimmed, whatever is selected: they are
        ## the two ways INTO the Hub — their panels hold the pickers that
        ## create the state everything else waits on, so they must not read as
        ## unavailable when nothing is loaded yet.
        self._tiles["batch"].set_dimmed(False)
        if self._batch is not None:
            blocked = self._batch.blocked_count()
            headline = f"{len(self._batch.batch_projects())} project(s)"
            if blocked:
                headline += f" · {blocked} blocked"
            self._tiles["batch"].set_summary([headline, self._batch.name])
        elif self._project is not None:
            self._tiles["batch"].set_summary(
                ["selection is a project", "open its parent to batch"])
        else:
            self._tiles["batch"].set_summary(
                ["no batch selected", "click here ▸ Choose batch folder…"])

        self._tiles["project"].set_dimmed(False)
        if self._project is not None:
            members = self._project.members()
            analysed = sum(1 for m in members if m.status().analyzed)
            loaded = (f"loaded: {self._experiment.name}" if self._experiment
                      else "double-click a member to load")
            self._tiles["project"].set_summary(
                [f"{len(members)} member(s) · {analysed} analysed", loaded])
        elif self._experiment is not None:
            self._tiles["project"].set_summary(
                ["standalone experiment", self._experiment.name])
        elif self._batch is not None:
            ## A Batch is selected but no Project inside it: the fix is
            ## double-clicking a row in the Batch panel's table.
            self._tiles["project"].set_summary(
                [self._batch.name, "double-click a project"])
        elif self._selection is None:
            ## Nothing is selected on launch, so the tile has to say where the
            ## way in is now that the top bar has no Open button.
            self._tiles["project"].set_summary(
                ["nothing selected", "click here ▸ Open project…"])
        else:
            self._tiles["project"].set_summary(
                ["not a project yet", "Tools ▸ Upgrade or Create project"])

        has_exp = self._experiment is not None
        for key in ("analyze", "qc", "plots", "scripts"):
            self._tiles[key].set_dimmed(not has_exp)
        if has_exp:
            status = self._experiment.status()
            self._tiles["analyze"].set_summary(
                [self._experiment.type.label,
                 f"{status.n_total or '—'} individuals"
                 if status.analyzed else "not analysed yet"])
            self._tiles["qc"].set_summary(
                [f"group: {self._experiment.exclusion_group or 'none'}",
                 f"{status.n_excluded} chamber(s) excluded"])
            self._tiles["plots"].set_summary(
                [f"{len(self._experiment.type.plot_ids())} figure(s) in the set",
                 f"headline: {self._experiment.type.headline_plot_id or '—'}"])
            self._tiles["scripts"].set_summary(
                [f"{len(self._experiment.scripts())} experiment script(s)",
                 f"{len(self._project.scripts()) if self._project else 0} "
                 f"project script(s)"])
        else:
            for key, hint in (("analyze", "load an experiment to analyse"),
                              ("qc", "load an experiment"),
                              ("plots", "load an experiment"),
                              ("scripts", "load one to run scripts")):
                self._tiles[key].set_summary([hint, ""])

        ## The AI tile is about the SUBJECT as much as the provider key: with
        ## a key but no Project loaded it used to sit lit next to a dimmed AI
        ## card.
        providers = self._ai_provider.count()
        if not providers:
            self._tiles["ai"].set_dimmed(True)
            self._tiles["ai"].set_summary(["no API key", "add one to .env"])
        else:
            ready = self._project is not None
            self._tiles["ai"].set_dimmed(not ready)
            self._tiles["ai"].set_summary(
                [f"{providers} provider(s)",
                 "per-member + across-members" if ready
                 else "select a project first"])
        self._tiles["tools"].set_summary(["directory tools", ""])
        self._refresh_card_dimming()
        self._refresh_report_button()

        rows = [("Selection", str(self._selection or "none"))]
        if self._project is not None:
            rows.append(("Project", f"{self._project.name} · "
                                    f"{self._project.type.label}"))
            if self._project.question:
                rows.append(("Question", self._project.question))
        if self._experiment is not None:
            rows.append(("Experiment", f"{self._experiment.name} · "
                                       f"{self._experiment.type.label}"))
        else:
            rows.append(("Experiment", "none loaded"))
        self._status_panel.set_rows(rows)

    def _refresh_report_button(self) -> None:
        """View reports needs something to view.

        Enabled on the Project report OR any member report: unlike the sister
        app there is nothing pooled to lay beside the members, so one half on
        its own is still a useful thing to open.
        """
        button = getattr(self, "_btn_view_reports", None)
        if button is None:
            return
        if self._project is None:
            button.setEnabled(False)
            button.setToolTip("Select a Project first.")
            return
        members = self._member_report_paths(self._project)
        project_report = self._project.report_path.is_file()
        button.setEnabled(project_report or bool(members))
        if project_report and members:
            button.setToolTip(f"Open the Project report and {len(members)} "
                              "member report(s), each in your PDF viewer.")
        elif project_report:
            button.setToolTip("Open the Project report. No member reports yet.")
        elif members:
            button.setToolTip(f"Open {len(members)} member report(s). No "
                              "Project report yet — run Project report first.")
        else:
            button.setToolTip("No reports yet — run Project report first.")

    def _refresh_card_dimming(self) -> None:
        """Grey the cards whose actions have no subject yet.

        Same gating as the buttons inside them (and the tiles above them):
        everything experiment-level waits on a loaded Member Experiment, and
        the AI narrative waits on a Project. The cards stay live — dimming
        says "nothing to act on", not "do not touch" — which is why the Batch
        and Project panels are absent from this list: they hold the pickers
        that create the state everything else waits on.
        """
        loaded = self._experiment is not None
        for key, ready in (("qc", loaded), ("analyze", loaded),
                           ("plots", loaded), ("scripts", loaded),
                           ("ai", self._project is not None
                            and self._ai_provider.count() > 0)):
            for card in self._panels[key].cards():
                card.set_dimmed(not ready)
        ## The Project panel is mixed: its first card carries Open and Create,
        ## which must stay bright with nothing selected, while the two below
        ## it act on a Project that may not exist yet.
        for card in (self._project_actions_card, self._project_scripts_card):
            card.set_dimmed(self._project is None)

    def _restyle_cards(self) -> None:
        """Repaint every card for the current theme — card surfaces are theme
        colours too, dimmed ones especially."""
        for panel in self._panels.values():
            for card in panel.cards():
                card.restyle()

    def _refresh_tables(self) -> None:
        ## Rebuilding must not silently re-check a Project the user unchecked;
        ## a new row defaults to checked unless nothing in it can run, which
        ## can only produce a failure.
        previous = {}
        for row in range(self._batch_table.rowCount()):
            item = self._batch_table.item(row, 0)
            if item is not None:
                previous[item.text()] = item.checkState()
        self._batch_table.setRowCount(0)
        live = self._batch is not None
        self._batch_empty.setVisible(not live)
        for widget in self._batch_widgets:
            widget.setEnabled(live)
        if not live:
            ## Clear the picker too. Leaving the previous Batch's central
            ## project_scripts: listed made a designation from a folder the
            ## user had navigated away from look like it was still in force.
            self._batch_script.clear()
        if self._batch is not None:
            for entry in self._batch.batch_projects():
                try:
                    project = Project(entry.directory)
                    type_label = project.type.label
                    report = "yes" if project.report_path.is_file() else "no"
                except Exception as exc:  # noqa: BLE001 - a bad Project still lists
                    type_label, report = f"error: {exc}", "—"
                blocked = entry.blocked
                self._append_row(self._batch_table, [
                    entry.key, type_label,
                    f"{len(entry.usable)}/{len(entry.members)}", report,
                    f"{len(blocked)} blocked" if blocked else "ok",
                ])
                row = self._batch_table.rowCount() - 1
                item = self._batch_table.item(row, 0)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(previous.get(
                    entry.key, Qt.CheckState.Checked if entry.runnable
                    else Qt.CheckState.Unchecked))
                item.setToolTip(str(entry.directory))
                if blocked:
                    ## Red, with the reasons in the tooltip: the panel has no
                    ## room for them and the preflight is one click away.
                    brush = QBrush(blocked_color())
                    detail = "\n".join(m.describe() for m in blocked)
                    for column in range(self._batch_table.columnCount()):
                        cell = self._batch_table.item(row, column)
                        if cell is not None:
                            cell.setForeground(brush)
                            cell.setToolTip(
                                f"{entry.key}\n\n{detail}" if column == 0
                                else detail)
            self._batch_script.clear()
            from ..script_editor import project_actions

            ## The leading entry designates nothing: each Project runs its own
            ## 'batch' script. It stays first so a Batch needs no batch.yaml
            ## until someone deliberately designates one script for all.
            self._batch_script.addItem(BATCH_OWN_SCRIPT_ITEM)
            names = [s["name"] for s in self._batch.project_scripts()]
            names += [n for n in project_actions.builtin_names() if n not in names]
            self._batch_script.addItems(names)
            if self._batch.designated_script:
                idx = self._batch_script.findText(self._batch.designated_script)
                if idx >= 0:
                    self._batch_script.setCurrentIndex(idx)

        self._members_table.setRowCount(0)
        if self._project is not None:
            for member in self._project.members():
                st = member.status()
                ## "re-run needed" beats a bare date: the saved results are
                ## real, they are just of a different analysis population
                ## than the config now asks for.
                analysed = "no"
                if st.analyzed:
                    analysed = "re-run needed" if st.stale else (st.analyzed_at or "yes")
                self._append_row(self._members_table, [
                    member.name,
                    member.type.label,
                    str(st.n_total or "—"),
                    analysed,
                    st.exclusion_group or "none",
                ])
                if st.stale:
                    row = self._members_table.rowCount() - 1
                    brush = QBrush(blocked_color())
                    detail = (f"Analysed under exclusion group "
                              f"{st.analysed_group or 'none'!r}, but the "
                              f"config now asks for "
                              f"{st.exclusion_group or 'none'!r}. Re-run the "
                              f"analysis so the saved results match.")
                    for column in range(self._members_table.columnCount()):
                        cell = self._members_table.item(row, column)
                        if cell is not None:
                            cell.setForeground(brush)
                            cell.setToolTip(detail)
            self._project_script.clear()
            from ..script_editor import project_actions

            names = [s["name"] for s in self._project.scripts()]
            names += [n for n in project_actions.builtin_names() if n not in names]
            self._project_script.addItems(names)

    @staticmethod
    def _append_row(table: QTableWidget, values: list[str]) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for col, value in enumerate(values):
            table.setItem(row, col, QTableWidgetItem(str(value)))

    def _refresh_action_panels(self) -> None:
        """Rebuild the contributed buttons from ``core ∪ type`` (ADR-0002).

        One registry, split by the category each Action already declares:
        plot-producing actions go to the Plots card, beside Render figures;
        everything else stays on Analyze.
        """
        analyze = self._analyze_card.body_layout()
        plots = self._plot_actions_card.body_layout()
        for layout in (analyze, plots):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)

        if self._experiment is None:
            analyze.addWidget(QLabel("Load an experiment to see its actions."))
            plots.addWidget(QLabel("Load an experiment to see its plots."))
            return

        from ..script_editor import actions as action_mod

        registry = action_mod.registry_for(self._experiment.type)
        order = [k for k in action_mod.CORE_KEYS if k in registry]
        order += [k for k in sorted(registry) if k not in order]
        for key in order:
            action = registry[key]
            btn = ActionButton(action.title, action.category,
                               icon_name=action.icon_name)
            btn.setToolTip(action.description)
            btn.clicked.connect(lambda _c, k=key: self._run_action(k))
            target = plots if action.category is Category.PLOTS else analyze
            target.addWidget(btn)

    def _refresh_scripts(self) -> None:
        self._scripts_combo.clear()
        if self._experiment is None:
            return
        from ..script_editor import project_actions

        names = [s["name"] for s in self._experiment.scripts()]
        names += [n for n in project_actions.BUILTIN_EXPERIMENT_SCRIPTS
                  if n not in names]
        self._scripts_combo.addItems(names)

    def _refresh_exclusion_groups(self) -> None:
        self._group_combo.clear()
        if self._experiment is None:
            return
        from .. import exclusions

        groups = exclusions.list_groups(self._experiment.directory)
        self._group_combo.addItems(groups)
        active = self._experiment.exclusion_group
        if active:
            idx = self._group_combo.findText(active)
            if idx >= 0:
                self._group_combo.setCurrentIndex(idx)
            else:
                self._group_combo.setEditText(active)

    def _refresh_ai(self) -> None:
        from ..ai import narrative

        self._ai_provider.clear()
        try:
            providers = narrative.available_providers()
        except Exception:  # noqa: BLE001 - a missing optional package is not fatal
            providers = []
        self._ai_provider.addItems([p.name for p in providers])
        self._ai_status.setText(
            "No provider configured — set ANTHROPIC_API_KEY or OPENAI_API_KEY "
            "in your environment or a .env file." if not providers else
            f"Ready: {', '.join(p.name for p in providers)}."
        )

    # ── running work ───────────────────────────────────────────────────────

    def _spawn(self, name: str, fn) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._warn("A task is already running.")
            return
        self._log.append_line(f"▶ {name}")
        worker = TaskWorker(name, fn)
        ## append_STREAM: log_text carries raw stdout chunks, and `print`
        ## writes its text and its terminator separately. Treating each chunk
        ## as a finished line put a blank row after every printed line and
        ## broke wide pandas tables apart.
        worker.log_text.connect(self._log.append_stream)
        worker.figure_ready.connect(self._on_figure)
        worker.finished_ok.connect(lambda msg: self._log.append_line(f"✔ {msg}"))
        worker.failed.connect(lambda msg: self._log.append_line(f"✘ {msg}"))
        worker.finished.connect(self._refresh_all)
        self._worker = worker
        worker.start()

    def _on_figure(self, title: str, figure) -> None:
        if self._tabs_suppressed():
            ## Closed, not merely skipped: a figure that never becomes a tab
            ## has no widget to own it, and pyplot would hold it for the life
            ## of the process — over a Batch Run that is exactly the leak the
            ## switch exists to avoid. The file is on disk either way.
            try:
                import matplotlib.pyplot as plt

                plt.close(figure)
            except Exception:  # noqa: BLE001
                pass
            self._log.append_line(
                f"[plot] {title} not shown — 'Suppress new plot tabs' is on "
                "(Batch panel).")
            return
        self._plots.add_figure(title, figure)

    def _tabs_suppressed(self) -> bool:
        """The Batch panel's 'Suppress new plot tabs' switch.

        Read through ``getattr`` because the log starts flowing before the
        panels are built, and a task can outlive the panel that owns the box.
        """
        box = getattr(self, "_chk_suppress_tabs", None)
        return box is not None and box.isChecked()

    def _run_action(self, key: str) -> None:
        """Execute one Analyze button — the same action a script step names."""
        from ..script_editor import actions as action_mod
        from ..script_editor.spec import RunContext

        experiment = self._experiment
        if experiment is None:
            return
        action = action_mod.registry_for(experiment.type)[key]
        figures: list = []

        def _job():
            ctx = RunContext(
                project_dir=experiment.directory,
                experiment=experiment,
                log=print,
                figure=lambda title, fig: figures.append((title, fig)),
                assume_censored=experiment.type.resolve_assume_censored(
                    experiment.config),
                exclusion_group=experiment.exclusion_group,
            )
            if key not in {"load_data", "run_analysis"}:
                # Every other action needs data; loading it here keeps a
                # single button click self-contained.
                action_mod.POOL["load_data"].execute({}, ctx)
            action.execute({}, ctx)
            return figures or f"{action.title} complete."

        self._spawn(action.title, _job)

    # ── actions ────────────────────────────────────────────────────────────

    def _action_run_batch(self, focus: str | None = None) -> None:
        """Review, then run.

        The preflight is always shown — with recursive discovery the folder
        the user picked no longer says what will run, and that target list is
        the one thing no other surface states.
        """
        if self._batch is None:
            self._warn("Select a directory that holds Projects first.")
            return
        dialog = BatchPreflightDialog(
            self, self._batch.directory,
            checked=self._batch_checked_keys(), log=self._log.append_line)
        if focus is not None:
            dialog.focus_member(focus)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        ## Scaffolding inside the dialog changes the tree either way, so the
        ## cached walk is stale whether or not the run goes ahead.
        self._batch.rescan()
        self._refresh_all()
        if not accepted:
            return
        keys = dialog.selected_keys
        if not keys:
            self._warn("No Projects checked — check at least one row.")
            return

        batch, name = self._batch, self._batch_script.currentText()
        if name == BATCH_OWN_SCRIPT_ITEM:
            name = None                       # no designation: each its own
        label = name or f"each project's own {DEFAULT_PROJECT_SCRIPT_NAME!r} script"
        self._spawn(f"Batch run: {label}",
                    lambda: batch.run(name, log=print,
                                      project_names=keys).summary())

    def _batch_checked_keys(self) -> list[str]:
        """The Projects checked in the Batch table, by key."""
        keys = []
        for row in range(self._batch_table.rowCount()):
            item = self._batch_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                keys.append(item.text())
        return keys

    def _action_rescan_batch(self) -> None:
        if self._batch is None:
            self._warn("Select a directory that holds Projects first.")
            return
        found = self._batch.rescan()
        blocked = self._batch.blocked_count()
        self._log.append_line(
            f"[batch] rescanned {self._batch.directory}: "
            f"{len(found['projects'])} project(s)"
            + (f", {blocked} blocked member(s)" if blocked else ""))
        for key, why in found["skipped"]:
            self._log.append_line(f"[batch] {key} skipped — {why}")
        self._refresh_all()

    def _batch_entry_at(self, row: int):
        """The scanned Project on table *row*, or None if it has gone."""
        item = self._batch_table.item(row, 0)
        if item is None or self._batch is None:
            return None
        for entry in self._batch.batch_projects():
            if entry.key == item.text():
                return entry
        return None

    def _batch_menu(self, point) -> None:
        """Right-click on a project row: repair its blocked members."""
        item = self._batch_table.itemAt(point)
        if item is None:
            return
        entry = self._batch_entry_at(item.row())
        if entry is None:
            return
        menu = QMenu(self)
        fix = menu.addAction(f"Fix blocked members in {entry.key}…")
        fix.setEnabled(bool(entry.blocked))
        if entry.blocked:
            fix.setToolTip("\n".join(m.describe() for m in entry.blocked))
        open_it = menu.addAction(f"Open {entry.key}")
        chosen = menu.exec(self._batch_table.viewport().mapToGlobal(point))
        if chosen is fix:
            ## The same review window, so its Run button means the same thing
            ## it does everywhere else.
            self._action_run_batch(focus=entry.key)
        elif chosen is open_it:
            self._open_batch_project(entry)

    def _on_batch_double_clicked(self, index) -> None:
        entry = self._batch_entry_at(index.row())
        if entry is not None:
            self._open_batch_project(entry)

    def _open_batch_project(self, entry) -> None:
        """Enter a Batch Project and switch the visible panel to it.

        The selection still names exactly one working container, so this is an
        ordinary selection change down to that Project — there is no drill-in
        state and no "up to batch" button; reaching the Batch again is picking
        its folder.
        """
        self._set_selection(entry.directory)
        self._refresh_all()
        self._open_panel_for("project")

    def _action_run_project_script(self) -> None:
        if self._project is None:
            self._warn("No Project selected.")
            return
        from ..domain.batch import resolve_designated_script
        from ..script_editor import project_actions

        project, name = self._project, self._project_script.currentText()
        ## Same resolver a Batch Run uses — no central scripts here, so it
        ## reads the Project's own first, then the built-ins, and reports a
        ## conditionally dropped step the same way.
        steps, _source, note = resolve_designated_script(name, [], project)
        if steps is None:
            self._warn(f"No Project Script named {name!r}.")
            return
        if note:
            self._log.append_line(f"! {note}")

        def _job():
            project_actions.run_script(project, steps, log=print)
            return f"Project script {name!r} complete."

        self._spawn(f"Project script: {name}", _job)

    def _action_project_report(self, with_narrative: bool = False) -> None:
        if self._project is None:
            self._warn("No Project selected.")
            return
        from .. import project_report
        from ..ai import narrative as ai_narrative

        project = self._project

        def _job():
            text = None
            if with_narrative:
                text = ai_narrative.generate(project, log=print)
            written = project_report.write_project_report(
                project, narrative=text, log=print)
            return f"Project report: {written.get('pdf') or written.get('md')}"

        self._spawn("Project report", _job)

    def _action_validate_project(self) -> None:
        """Check the Project's YAML and every member's, not just the loaded one.

        A Project is exactly where a problem hides from a per-member check:
        the one hard cross-member rule is the shared Experiment Type, and a
        member whose config was never scaffolded is invisible to the members
        table until a Batch Run fails on it.
        """
        if self._project is None:
            self._warn("No Project selected.")
            return
        checked = 1 + len(self._project.member_dirs())
        problems = self._project.validate()
        if problems:
            self._log.append_line("Project validation problems:")
            for problem in problems:
                self._log.append_line(f"  - {problem}")
        else:
            self._log.append_line("Project validation passed.")
        for divergence in self._project.divergences():
            self._log.append_line(f"  divergence — {divergence}")

        ## Blocked members are a validation result too — a directory holding
        ## data with no config is not a member yet, so nothing above sees it.
        blocked = [m for m in layout_mod.members_in(self._project.directory)
                   if m.blocked]
        for member in blocked:
            self._log.append_line(f"  blocked — {member.describe()}")
        self._log.append_line(
            f"[validate] {checked} file(s) checked, {len(problems)} "
            f"problem(s), {len(blocked)} blocked member(s).")

    def _member_report_paths(self, project) -> list[Path]:
        """Every per-member report that exists on disk, in table order.

        A member's report is named for its DIRECTORY, not the data file inside
        it, which is the same rule the pipeline writes it under.
        """
        found = []
        for directory in project.member_dirs():
            candidate = directory / "analysis" / f"{directory.name}_report.pdf"
            if candidate.is_file():
                found.append(candidate)
        return found

    def _action_view_reports(self) -> None:
        """Open the Project report and every member report at once."""
        if self._project is None:
            self._warn("No Project selected.")
            return
        targets = []
        if self._project.report_path.is_file():
            targets.append(self._project.report_path)
        targets += self._member_report_paths(self._project)
        if not targets:
            self._warn("No reports yet — run Project report first.")
            return
        opened = sum(1 for path in targets if self._open_pdf(path))
        if opened:
            self._log.append_line(
                f"[reports] opened {opened} report(s) in your PDF viewer.")

    def _open_pdf(self, path: Path) -> bool:
        """Hand *path* to the desktop's PDF viewer; the viewer decides window
        vs tab.

        ``QDesktopServices`` covers all three desktops (ShellExecute, Launch
        Services, xdg-open). It can still fail on a Linux box with no
        xdg-utils and no registered handler, so each platform's own opener is
        tried before giving up.
        """
        import os
        import subprocess

        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            return True
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # noqa: S606 — the OS picks the app
            elif sys.platform == "darwin":
                ## -n: a new instance, so several files cannot collapse into
                ## one reused window.
                subprocess.Popen(["open", "-n", str(path)], close_fds=True)
            else:
                subprocess.Popen(["xdg-open", str(path)], close_fds=True)
        except Exception as err:  # noqa: BLE001
            self._log.append_line(f"[reports] could not open {path.name}: {err}")
            return False
        return True

    def _action_add_member(self) -> None:
        if self._project is None:
            self._warn("Create or select a Project first.")
            return
        name = self._prompt_text("Add member", "Directory name for the new "
                                               "Member Experiment:")
        if not name:
            return
        member = self._project.add_member(name)
        self._log.append_line(f"Scaffolded {member.directory} from the Project defaults. "
                         f"Put its data file in {member.data_dir}.")
        self._refresh_all()

    def _action_add_directory(self) -> None:
        if self._project is None:
            self._warn("Create or select a Project first.")
            return
        path = QFileDialog.getExistingDirectory(
            self, "Add an existing experiment directory", str(self._project.directory))
        if not path:
            return
        try:
            member = self._project.adopt_directory(path)
        except (ProjectError, OSError) as exc:
            self._warn(str(exc))
            return
        moved = "" if Path(path).resolve() == member.directory else \
            f" (copied from {Path(path).resolve()})"
        self._log.append_line(f"Added member {member.name}{moved}.")
        self._refresh_all()

    def _action_add_experiment(self) -> None:
        if self._project is None:
            self._warn("Create or select a Project first.")
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Add a DLife survival workbook", str(self._project.directory),
            "DLife workbook (*.xlsx)")
        if not path:
            return
        source = Path(path).resolve()
        inside = self._project.directory in source.parents
        try:
            member = self._project.adopt_data_file(source)
        except (ProjectError, OSError) as exc:
            self._warn(str(exc))
            return
        verb = "moved" if inside else "copied"
        self._log.append_line(
            f"Added member {member.name}: {verb} {source.name} into "
            f"{member.data_dir}.")
        self._refresh_all()

    def _action_create_project(self) -> None:
        if self._selection is None:
            self._warn("Open a directory first.")
            return
        target = self._selection
        if is_experiment_dir(target):
            # Writing project.yaml here would make a Project with zero members.
            target = target.parent
        if is_project_dir(target):
            self._warn(f"{target} is already a Project.")
            return
        types = available_types()
        labels = [t.label for t in types]
        choice = self._prompt_choice("Create project", "Experiment type:", labels)
        if choice is None:
            return
        exp_type = types[labels.index(choice)]
        question = self._prompt_text("Create project",
                                     "What question do these experiments address?")
        project = Project.create(target, question=question or "",
                                 type_key=None if exp_type.is_custom else exp_type.key)
        self._log.append_line(f"Created {project.config_path}")
        self._set_selection(target)
        self._refresh_all()

    def _action_set_exclusion_group(self) -> None:
        if self._experiment is None:
            self._warn("Load an experiment first.")
            return
        group = self._group_combo.currentText().strip()
        config = dict(self._experiment.raw_config)
        if group:
            config["exclusions"] = {"group": group}
        else:
            config.pop("exclusions", None)
        cfgmod.save_config(self._experiment.directory, config)
        self._experiment = SurvivalExperiment(
            self._experiment.directory,
            defaults=self._project.defaults if self._project else {},
            project=self._project)
        self._log.append_line(
            f"Active exclusion group for {self._experiment.name}: "
            f"{group or 'none'} — written to {cfgmod.CONFIG_FILENAME} and "
            f"stamped on every future run.")
        self._refresh_all()

    def _action_open_qc_viewer(self) -> None:
        if self._experiment is None:
            self._warn("Load an experiment first.")
            return
        from .qc_viewer import QcViewerWindow

        viewer = QcViewerWindow(str(self._experiment.directory))
        viewer.show()
        self._qc_window = viewer

    def _action_render_figures(self) -> None:
        if self._experiment is None:
            self._warn("Load an experiment first.")
            return
        from .. import pubfigures

        experiment, fmt = self._experiment, self._fig_format.currentText()

        def _job():
            written = pubfigures.render_all(experiment, fmt=fmt, log=print)
            return f"{len(written)} figure(s) in {experiment.figures_dir}"

        self._spawn("Render publication figures", _job)

    def _action_open_plot_editor(self) -> None:
        if self._experiment is None:
            self._warn("Load an experiment first — the Plot Editor is "
                       "experiment-level here, because figures are per member.")
            return
        from .plot_editor import PlotEditorWindow

        editor = PlotEditorWindow(self._experiment)
        editor.show()
        self._plot_editor = editor

    def _action_run_experiment_script(self) -> None:
        if self._experiment is None:
            self._warn("Load an experiment first.")
            return
        from ..script_editor import project_actions

        experiment = self._experiment
        name = self._scripts_combo.currentText()
        steps = None
        for script in experiment.scripts():
            if script.get("name") == name:
                steps = list(script.get("steps") or [])
        if steps is None:
            steps = project_actions.BUILTIN_EXPERIMENT_SCRIPTS.get(name)
        if steps is None:
            self._warn(f"No Experiment Script named {name!r}.")
            return

        figures: list = []

        def _job():
            project_actions.run_experiment_script(
                experiment, steps, log=print,
                figure=lambda t, f: figures.append((t, f)))
            return figures or f"Script {name!r} complete."

        self._spawn(f"Experiment script: {name}", _job)

    def _action_open_script_editor(self) -> None:
        from ..script_editor.window import ScriptEditorWindow

        target = self._experiment.directory if self._experiment else self._selection
        if target is None:
            self._warn("Open a directory first.")
            return
        editor = ScriptEditorWindow(str(target))
        editor.show()
        self._script_editor = editor

    def _action_ai_narrative(self) -> None:
        if self._project is None:
            self._warn("The narrative is written per Project.")
            return
        from ..ai import narrative as ai_narrative

        project = self._project
        provider = self._ai_provider.currentText() or None

        def _job():
            text = ai_narrative.generate(project, provider=provider, log=print)
            for name, paragraph in text.items():
                print(f"\n[{name}]\n{paragraph}")
            return f"{len(text)} narrative section(s)."

        self._spawn("AI narrative", _job)

    def _action_upgrade(self) -> None:
        if self._selection is None:
            self._warn("Open a directory first.")
            return
        plan = upgrade_mod.plan(self._selection)
        if plan.is_noop:
            self._log.append_line("Nothing to upgrade: " + "; ".join(plan.warnings))
            return
        message = ("This will:\n  - " + "\n  - ".join(plan.actions)
                   + ("\n\nNotes:\n  - " + "\n  - ".join(plan.warnings)
                      if plan.warnings else "")
                   + "\n\nNothing is deleted or moved.")
        if QMessageBox.question(self, "Upgrade directory", message) \
                != QMessageBox.StandardButton.Yes:
            return
        upgrade_mod.apply(plan)
        self._log.append_line(f"Upgraded {plan.directory}.")
        self._set_selection(plan.directory)
        self._refresh_all()

    def _action_wrap_in_project(self) -> None:
        if self._experiment is None:
            self._warn("Load a standalone experiment first.")
            return
        parent = self._experiment.directory.parent
        if is_project_dir(parent):
            self._warn(f"{parent} is already a Project.")
            return
        project = Project.create(
            parent,
            type_key=None if self._experiment.type.is_custom
            else self._experiment.type.key)
        self._log.append_line(f"Wrapped {self._experiment.name} in {project.config_path}")
        self._set_selection(parent)
        self._refresh_all()

    def _action_validate_config(self) -> None:
        if self._experiment is None:
            self._warn("Load an experiment first.")
            return
        problems = self._experiment.validate()
        if problems:
            self._log.append_line(f"{self._experiment.name} config problems:")
            for p in problems:
                self._log.append_line(f"  - {p}")
        else:
            self._log.append_line(f"{self._experiment.name}: config is valid.")

    def _action_open_analysis(self) -> None:
        import subprocess

        target = (self._experiment.analysis_dir if self._experiment
                  else self._selection)
        if target is None:
            return
        target.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(target)])

    # ── small dialogs ──────────────────────────────────────────────────────

    def _warn(self, message: str) -> None:
        self._log.append_line(f"! {message}")
        QMessageBox.warning(self, "pySurvAnalysis", message)

    def _prompt_text(self, title: str, label: str) -> str | None:
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal)
        return text.strip() if ok else None

    def _prompt_choice(self, title: str, label: str,
                       options: list[str]) -> str | None:
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getItem(self, title, label, options, 0, False)
        return text if ok else None

    def _toggle_theme(self) -> None:
        mode = "light" if current_mode() == "dark" else "dark"
        apply_theme(QApplication.instance(), mode)
        ui_settings.set_value("theme", mode)
        for tile in self._tiles.values():
            tile.restyle()
        self._status_panel.restyle()
        for panel in self._panels.values():
            panel.restyle()
        self._restyle_cards()


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app, ui_settings.get("theme", "auto"))
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    window = HubWindow(initial)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
