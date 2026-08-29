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

from ..gui_env import sanitize_input_method_environment, use_agg_matplotlib

## Before Qt is imported, not after: the overrides are read when the
## platform plugin initialises.
sanitize_input_method_environment()
use_agg_matplotlib()

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
        ## the user is actually reading. Checked, a BATCH RUN stops creating
        ## tabs; the Output tab keeps streaming and every artefact is still
        ## written to disk. Batch Runs only: a plot button clicked on one
        ## experiment is a request to SEE that figure, and suppressing it
        ## made the button do nothing visible.
        self._chk_suppress_tabs = QCheckBox("Suppress plot tabs during batch runs")
        self._chk_suppress_tabs.setToolTip(
            "Stop a Batch Run opening a tab for every figure of every member. "
            "The Output tab keeps updating and every figure is still written "
            "to disk — only the tabs are skipped. Plots requested directly on "
            "an experiment always open.")
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
        """Three cards: the ways into a Project, the members themselves, and
        what you do with a Project once its members exist.

        Both action sets are laid out the same way and for the same reason:
        a folder is in one of three states before it is a Project (or a
        member), and each state has its own button. Mirrors the sister app's
        Create/Load and Experiments cards one concept at a time; where a
        button here has no counterpart there, it is one of ADR-0008's ways a
        member arrives from outside the Project.
        """
        card = Card("Create/Load", Category.NEUTRAL, icon_name="project",
                    subtitle="Open a Project directory and edit its project.yaml.")
        self._project_create_card = card

        ## Two columns, four buttons, no ragged row: the three states a folder
        ## can be in — it is a Project, it does not exist at all, or its
        ## directory exists but its project.yaml does not — then the editor
        ## for the one that is open.
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        open_btn = ActionButton("Open project…", Category.NEUTRAL,
                                icon_name="open")
        open_btn.setToolTip(
            "Open a directory that already holds a project.yaml. Picking the "
            "one already open re-reads it from disk, so members added or "
            "analysed outside the Hub show up — the picker is the reload. It "
            "also takes a Batch folder or a standalone Experiment Directory, "
            "which a Project is never required for (ADR-0003).")
        open_btn.clicked.connect(self._pick_directory)
        create_btn = ActionButton("Create project…", Category.NEUTRAL,
                                  icon_name="new")
        create_btn.setToolTip(
            "Make a Project that does not exist yet: choose where it goes, "
            "name it, and fill in its question and defaults. The directory is "
            "created for you.")
        create_btn.clicked.connect(self._action_create_project)
        init_btn = ActionButton("Initialize existing directory…",
                                Category.NEUTRAL, icon_name="project")
        init_btn.setToolTip(
            "Turn a directory you already have into a Project: it keeps its "
            "own name, any experiment subdirectories already in it become the "
            "members, and project.yaml is written there. The path for a study "
            "that started before there were Projects.")
        init_btn.clicked.connect(self._action_initialize_project)
        self._btn_edit_project_cfg = ActionButton(
            "Edit config…", Category.NEUTRAL, icon_name="config")
        self._btn_edit_project_cfg.setToolTip(
            "Open the Project editor on the open Project's project.yaml — its "
            "name, question, Experiment Type and Project Defaults. Giving a "
            "directory its first project.yaml is 'Initialize existing "
            "directory…', not this.")
        self._btn_edit_project_cfg.setEnabled(False)
        self._btn_edit_project_cfg.clicked.connect(
            self._action_edit_project_config)
        for i, btn in enumerate((open_btn, create_btn, init_btn,
                                 self._btn_edit_project_cfg)):
            grid.addWidget(btn, i // 2, i % 2)
        ## Full width on its own row: not a fifth way in, but the check you
        ## run over the Project that is open.
        validate_btn = ActionButton("Validate YAMLs", Category.NEUTRAL,
                                    icon_name="validate")
        validate_btn.setToolTip(
            "Check the Project's project.yaml and every member's "
            "survival_config.yaml — parse errors and semantic problems alike. "
            "Validating only the loaded member left the rest of a Project "
            "unchecked, which is exactly where a type mismatch hides.")
        validate_btn.clicked.connect(self._action_validate_project)
        grid.addWidget(validate_btn, 2, 0, 1, 2)
        for col in range(2):
            grid.setColumnStretch(col, 1)
        card.add_body(grid)

        ## What is loaded, described: name, type, member count, divergences and
        ## any load problems. Project information, so it sits with the Project
        ## it describes rather than over the members table.
        self._project_summary = QLabel("")
        self._project_summary.setWordWrap(True)
        card.add_body(self._project_summary)
        self._panels["project"].add_card(card)

        # ---- the members themselves ----------------------------------------
        members_card = Card("Experiments", Category.NEUTRAL,
                            icon_name="experiment",
                            subtitle="Double-click a member to load it.")
        self._project_members_card = members_card
        self._members_table = self._make_table(
            ["Member", "Config", "Type", "N", "Analysed", "Exclusions"])
        self._members_table.doubleClicked.connect(self._on_member_double_clicked)
        members_card.add_body(self._members_table)
        hint = QLabel("A row marked Config: missing is a folder with no "
                      "survival_config.yaml — double-click it to scaffold one.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid); font-style: italic;")
        members_card.add_body(hint)

        ## The same three states as the card above, one level down: the member
        ## exists (the table), it does not exist at all (Create), or its
        ## directory exists but its config does not (Initialize).
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        create_exp = ActionButton("Create experiment…", Category.NEUTRAL,
                                  icon_name="add")
        create_exp.setToolTip(
            "Create a member directory and scaffold its survival_config.yaml "
            "from the Project Defaults. The scaffold stays minimal, so later "
            "edits to the Project keep reaching it.")
        create_exp.clicked.connect(self._action_create_experiment)
        init_exp = ActionButton("Initialize existing directory…",
                                Category.NEUTRAL, icon_name="project")
        init_exp.setToolTip(
            "Adopt a directory that is already in the Project but has no "
            "survival_config.yaml: the config is scaffolded from the Project "
            "Defaults, and a directory holding several candidate data files "
            "is asked which one is the experiment.")
        init_exp.clicked.connect(self._action_initialize_experiment)
        configs_btn = ActionButton("Experiment configs…", Category.NEUTRAL,
                                   icon_name="config")
        configs_btn.setToolTip(
            "The bulk view: every subdirectory with its config and data "
            "status, so the missing configs can be made and the ambiguous "
            "ones settled without hunting through a file manager.")
        configs_btn.clicked.connect(self._action_member_configs)
        ## Two columns, like the card above and for the same reason: three of
        ## these labels across a 540px panel do not fit, and the panel does
        ## not scroll sideways — it clips. The two ways IN sit side by side,
        ## and the bulk editor takes its own full-width row below them, where
        ## Validate YAMLs sits on the Create/Load card.
        for i, btn in enumerate((create_exp, init_exp)):
            grid.addWidget(btn, 0, i)
        grid.addWidget(configs_btn, 1, 0, 1, 2)
        for col in range(2):
            grid.setColumnStretch(col, 1)
        members_card.add_body(grid)

        ## ADR-0008's other two ways a member arrives, and the reason this card
        ## has five buttons where the sister app's has three: there, replicates
        ## are always made in place; here one can walk in from a collaborator's
        ## drive or be a single loose workbook. Separated rather than mixed in,
        ## because these two reach OUTSIDE the Project and the three above do
        ## not.
        members_card.add_section_label("Bring one in from outside")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        adopt_dir = ActionButton("Add directory…", Category.NEUTRAL,
                                 icon_name="open")
        adopt_dir.setToolTip("Copy an experiment directory from OUTSIDE the "
                             "Project in (it needs a data/ folder with a "
                             "DLife workbook) — the Project owns its members' "
                             "data. A folder already inside the Project is "
                             "'Initialize existing directory…'s job instead.")
        adopt_dir.clicked.connect(self._action_add_directory)
        adopt_file = ActionButton("Add experiment…", Category.NEUTRAL,
                                  icon_name="excel")
        adopt_file.setToolTip("Build a member around one DLife workbook: it is "
                              "named after the file, the file lands in its "
                              "data/, and a minimal config is written.")
        adopt_file.clicked.connect(self._action_add_experiment)
        for i, btn in enumerate((adopt_dir, adopt_file)):
            grid.addWidget(btn, 0, i)
        for col in range(2):
            grid.setColumnStretch(col, 1)
        members_card.add_body(grid)

        ## Nothing here has anything to inherit from until a Project is open.
        self._member_action_buttons = [create_exp, init_exp, configs_btn,
                                       adopt_dir, adopt_file]
        self._set_member_actions_enabled(False)
        self._panels["project"].add_card(members_card)

        actions_card = Card("Actions", Category.NEUTRAL, icon_name="report")
        self._project_actions_card = actions_card
        ## Every button here is NEUTRAL. They are all project actions, and
        ## colouring each by the category of the work it happens to do made
        ## one card read as a rainbow of unrelated things — the panel's
        ## identity already comes from the tile above it. Category colour is
        ## reserved for the panels where it distinguishes something: the
        ## type-contributed Analyze and Plots buttons, and Tools.
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
        plots_btn = ActionButton("Plot editor…", Category.NEUTRAL,
                                 icon_name="plot")
        plots_btn.setToolTip(
            "Author Publication Figures: a member's Specs, and the Project's "
            "shared Styles. Opens on the member selected in the table above "
            "(or the loaded one); with several to choose from and none "
            "picked, it asks which.")
        plots_btn.clicked.connect(self._action_open_plot_editor)
        for i, btn in enumerate((report_btn, view_btn, plots_btn)):
            grid.addWidget(btn, 0, i)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        actions_card.add_body(grid)

        ## Rendering is project-level: it walks every member. Paired with its
        ## format on one row, the way the Scripts card pairs Run with the
        ## script it runs.
        row = QHBoxLayout()
        self._fig_format = QComboBox()
        self._fig_format.addItems(["svg", "pdf", "png"])
        self._fig_format.setToolTip(
            "svg and pdf keep text editable — the point of a publication "
            "figure. png is for a slide.")
        self._fig_format.setSizePolicy(QSizePolicy.Policy.Ignored,
                                       QSizePolicy.Policy.Fixed)
        render_btn = ActionButton("Render publication figures",
                                  Category.NEUTRAL, icon_name="figures")
        render_btn.setToolTip(
            "Render the Project's curated Publication Figures into each "
            "member's figures/ folder. The curation is the Project's "
            "plot_specs.yaml (ADR-0005 as amended): one set of Specs and "
            "Styles, rendered per member. A Project with nothing curated "
            "renders nothing.")
        render_btn.clicked.connect(self._action_render_figures)
        ## Action first, its modifier second: the button is what you came for,
        ## and the format is a detail of how it writes.
        row.addWidget(render_btn, 2)
        row.addWidget(self._fig_format, 1)
        actions_card.add_body(row)
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

    def _set_member_actions_enabled(self, enabled: bool) -> None:
        for btn in getattr(self, "_member_action_buttons", []):
            btn.setEnabled(enabled)

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
        self._group_combo.setToolTip(
            "The Exclusion Groups found in this experiment's "
            "qc/remove_chambers.csv. Groups are created in the Chamber QC "
            "viewer (flag chambers, then Save Exclusions… under a name) — "
            "setting a name no group carries excludes nothing.")
        row.addWidget(self._group_combo, 1)
        card.add_body(row)
        ## The empty state, said where it appears: an empty picker otherwise
        ## reads as broken, when it just means nobody has saved a group yet.
        self._group_hint = QLabel("")
        self._group_hint.setWordWrap(True)
        self._group_hint.setStyleSheet("color: palette(mid); font-style: italic;")
        card.add_body(self._group_hint)

        apply_btn = ActionButton("Set active group", Category.QC, icon_name="check")
        apply_btn.setToolTip(
            "Write `exclusions: {group: …}` into survival_config.yaml. Every "
            "future run drops that group's chambers and stamps the group on "
            "its outputs; a blank name clears the key.")
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
        ## No Publication-figure card here. Authoring a figure is Plot Editor
        ## work — the Spec and its Style are what a figure IS (ADR-0005) — and
        ## rendering is a Project action, because it runs over every member.
        ## Two buttons on this tile meant a third and fourth place to think
        ## about figures, each acting on a different subject.

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
        config_cell = self._members_table.item(row, 1)
        if config_cell is not None and config_cell.text() == "missing":
            ## Not a member yet, so there is nothing to load — but the row is
            ## exactly one scaffolded config away from being one, and asking
            ## is cheaper than sending the user to a button they have not
            ## found yet.
            resp = QMessageBox.question(
                self, "Create config",
                f"'{name}' has no {cfgmod.CONFIG_FILENAME}.\n\nScaffold one "
                f"from the Project Defaults and make it a member?")
            if resp == QMessageBox.StandardButton.Yes:
                self._create_member_config(name)
                self._refresh_all()
            return
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
        self._refresh_project_card()
        self._refresh_tiles()

    def _refresh_project_card(self) -> None:
        """The Create/Load card's own state: what the fourth button will do,
        whether the member actions have anything to inherit from, and the
        summary line describing what is loaded."""
        self._set_member_actions_enabled(self._project is not None)

        ## Edit only, never "Create config…": writing a project.yaml into a
        ## directory that has none IS 'Initialize existing directory…', and
        ## two buttons doing one thing made the card look like it had four
        ## ways in when it has three.
        self._btn_edit_project_cfg.setEnabled(self._project is not None)

        if self._project is None:
            self._project_summary.setText(
                "No Project loaded. Open one, create one, or initialize a "
                "directory you already have — a standalone Experiment "
                "Directory loads without any of them (ADR-0003).")
            self._project_summary.setToolTip("")
            return

        project = self._project
        members = project.members()
        pending = project.unconfigured_dirs()
        parts = [f"<b>{project.name}</b> · {project.type.label} · "
                 f"{len(members)} member(s)"]
        if pending:
            parts.append(f"{len(pending)} directory(ies) with no config: "
                         f"{', '.join(pending[:4])}"
                         + (" …" if len(pending) > 4 else ""))
        if project.question:
            parts.append(f"Question: {project.question}")
        divergences = project.divergences()
        if divergences:
            ## Declared, never fatal: members address one question in
            ## different ways, and the Project Report says so on its own page.
            parts.append("Divergence: "
                         + "; ".join(d.aspect for d in divergences))
        problems = project.validate()
        if problems:
            parts.append(f"{len(problems)} problem(s) — run Validate YAMLs.")
        self._project_summary.setText("<br>".join(parts))
        self._project_summary.setToolTip(str(project.directory))

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
        for card in (self._project_members_card, self._project_actions_card,
                     self._project_scripts_card):
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
                    "yes",
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
            ## The third state, listed rather than left invisible: a folder in
            ## the Project with no survival_config.yaml is not a member, so
            ## nothing else in the Hub can see it — and a table that shows
            ## only the members says a half-set-up Project is a complete one.
            for item in layout_mod.initializable_dirs(self._project.directory):
                self._append_row(self._members_table, [
                    item.name, "missing", "—", "—", "—", "—",
                ])
                row = self._members_table.rowCount() - 1
                brush = QBrush(blocked_color())
                detail = (item.detail or "No survival_config.yaml — "
                          "double-click to scaffold one from the Project "
                          "Defaults.")
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
        plot-producing actions go to the Plots card, everything else to
        Analyze. Those contributed buttons are now all the Plots panel holds
        — authoring a Publication Figure is Plot Editor work and rendering
        one is a Project action.
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
        ## The render action stays in the registry — an Experiment Script may
        ## legitimately render this member's figures — but its BUTTON is
        ## project-level only: rendering walks every member, so it lives on
        ## the Project panel and nowhere else.
        registry = {k: a for k, a in registry.items()
                    if k != "render_publication_figures"}
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
        hint = getattr(self, "_group_hint", None)
        if self._experiment is None:
            if hint is not None:
                hint.setText("")
            return
        from .. import exclusions

        groups = exclusions.list_groups(self._experiment.directory)
        self._group_combo.addItems(groups)
        if hint is not None:
            if groups:
                hint.setText("")
            else:
                hint.setText(
                    "No groups yet — open the Chamber QC viewer, flag "
                    "chambers, and Save Exclusions… under a name; it will be "
                    "listed here. (Long-format data has no chambers, and "
                    "then there is nothing to exclude.)")
        active = self._experiment.exclusion_group
        if active:
            idx = self._group_combo.findText(active)
            if idx >= 0:
                self._group_combo.setCurrentIndex(idx)
            else:
                self._group_combo.setEditText(active)
        ## A name typed here that no saved group carries excludes NOTHING —
        ## warn beside the picker rather than let it look like a policy.
        if active and groups and active not in groups and hint is not None:
            hint.setText(
                f"The active group {active!r} is not in "
                f"qc/remove_chambers.csv — it currently excludes no chambers.")

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

    def _spawn(self, name: str, fn, *, batch: bool = False) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._warn("A task is already running.")
            return
        ## Whether THIS task's figures may be suppressed. Only a Batch Run
        ## qualifies (see the checkbox); per-spawn state rather than a global,
        ## so the answer cannot leak from one task to the next.
        self._worker_is_batch = batch
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
                f"[plot] {title} not shown — 'Suppress plot tabs during "
                "batch runs' is on (Batch panel).")
            return
        self._plots.add_figure(title, figure)

    def _tabs_suppressed(self) -> bool:
        """True only while a Batch Run is up AND the switch is on.

        The switch never touches a figure the user asked for by clicking a
        plot button on one experiment — that click is a request to SEE the
        figure, and honouring the box there made the button do nothing
        visible. Read through ``getattr`` because the log starts flowing
        before the panels are built, and a task can outlive the panel that
        owns the box.
        """
        if not getattr(self, "_worker_is_batch", False):
            return False
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
                                      project_names=keys).summary(),
                    batch=True)

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

    # ── the three states a member directory can be in ──────────────────────

    def _create_member_config(self, name: str):
        """Scaffold *name*'s ``survival_config.yaml`` from the Project Defaults.

        Returns the member, or None when it failed (reported to the user).
        Shared by Create experiment, Initialize existing directory, the
        Experiment configs dialog and the members table's double-click, so
        every one of them inherits the defaults the same way.
        """
        if self._project is None:
            return None
        try:
            member = self._project.add_member(name)
        except (ProjectError, OSError) as exc:
            self._warn(f"Could not create the config for '{name}': {exc}")
            return None
        self._log.append_line(
            f"Scaffolded {cfgmod.config_path(member.directory)} from the "
            f"Project Defaults. Put its data file in {member.data_dir}.")
        return member

    def _action_create_experiment(self) -> None:
        """The member does not exist at all: make its directory and scaffold
        its config from the Project Defaults.

        Everything the config needs is already settled in project.yaml and
        inherited from it, so the only thing to ask for is the name.
        """
        if self._project is None:
            self._warn("Create or select a Project first — a member's "
                       "defaults are inherited from its project.yaml.")
            return
        name = self._prompt_text("Create experiment",
                                 "New member directory name:")
        if not name:
            return
        try:
            directory = self._project.member_dir(name)
        except ProjectError as exc:
            self._warn(str(exc))
            return
        if is_experiment_dir(directory):
            self._warn(f"'{name}' already exists and has a config.")
            return
        if directory.exists():
            ## The other state, and it has its own button: initializing looks
            ## at what is already in the directory instead of assuming it is
            ## empty.
            self._warn(
                f"'{name}' already exists.\n\nUse 'Initialize existing "
                "directory…' to give the directory you already have a config.")
            return
        if self._create_member_config(name) is None:
            return
        self._refresh_all()
        ## The scaffold is a starting point, not a finished member: it has no
        ## data file yet. Both ways of finishing it are one click away rather
        ## than left to be found.
        self._finish_new_member_config(name, directory)

    def _finish_new_member_config(self, name: str, directory: Path) -> None:
        """Offer the two ways to finish a just-created member.

        What a fresh member lacks here is its **workbook** — the config is
        conformant the moment it is written, because everything but the data
        is inherited. Copying a config from a member that already works is the
        second offer, for the run whose members share an input format and an
        exclusion group.
        """
        box = QMessageBox(self)
        box.setWindowTitle("Create experiment")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"'{name}' is ready, with a {cfgmod.CONFIG_FILENAME} "
                    f"scaffolded from the Project Defaults.")
        box.setInformativeText(
            "It has no data yet. Add its workbook now, or copy a config from "
            "a member that is already set up.")
        data_btn = box.addButton("Add data file…",
                                 QMessageBox.ButtonRole.AcceptRole)
        copy_btn = box.addButton("Copy config from…",
                                 QMessageBox.ButtonRole.ActionRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(data_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is data_btn:
            self._add_member_data_file(name, directory)
        elif clicked is copy_btn:
            self._copy_member_config(name, directory)
        self._refresh_all()

    def _add_member_data_file(self, name: str, directory: Path) -> None:
        """Copy a chosen data file into a new member's ``data/``."""
        import shutil

        chosen, _filter = QFileDialog.getOpenFileName(
            self, f"Choose the data file for '{name}'",
            str(self._project.directory if self._project else directory),
            "Survival data (*.xlsx *.csv *.tsv);;All files (*)")
        if not chosen:
            return
        source = Path(chosen).resolve()
        target = directory / "data" / source.name
        if target.exists() and target.resolve() == source:
            return
        if target.exists():
            self._warn(f"{target} already exists — nothing was copied.")
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except OSError as exc:
            self._warn(f"Could not copy '{source.name}':\n{exc}")
            return
        self._log.append_line(f"Copied {source} to {target}")

    def _copy_member_config(self, name: str, directory: Path) -> bool:
        """Replace *name*'s scaffolded config with one chosen from elsewhere.

        Checked **before** it is written, with the one rule every member is
        held to at load time (ADR-0001): a config of the wrong Experiment Type
        makes the whole Project refuse to load, and the user would otherwise
        have to find and undo the copy by hand. Differing factors and levels
        are Divergence, not error, so they are not grounds to refuse.
        """
        import shutil

        project = self._project
        if project is None:
            return False
        chosen, _filter = QFileDialog.getOpenFileName(
            self, f"Choose a {cfgmod.CONFIG_FILENAME} to copy into '{name}'",
            str(project.directory),
            f"Member config ({cfgmod.CONFIG_FILENAME});;"
            "YAML files (*.yaml *.yml);;All files (*)")
        if not chosen:
            return False
        source = Path(chosen).resolve()
        target = cfgmod.config_path(directory)
        if target.exists() and source == target.resolve():
            self._warn(f"That is '{name}'s own config — nothing was copied.")
            return False
        try:
            config = cfgmod.read_yaml(source)
        except (OSError, ValueError) as exc:
            self._warn(f"'{source.name}' could not be read:\n{exc}\n\n"
                       "The scaffolded config is still in place.")
            return False
        problems = project.type_problems_for(config, source.name)
        if problems:
            self._warn(
                f"'{source.name}' cannot be a member of {project.name}:\n  - "
                + "\n  - ".join(problems[:6])
                + ("\n  - …" if len(problems) > 6 else "")
                + "\n\nNothing was copied; the scaffolded config is still in "
                "place.")
            return False
        try:
            shutil.copyfile(source, target)
        except OSError as exc:
            self._warn(f"Could not copy '{source.name}':\n{exc}")
            return False
        self._log.append_line(f"Copied {source} to {target}")
        ## Conforming is not the same as usable. Report what is left rather
        ## than let the member fail at run time — the same split upstream
        ## makes between "would break the Project" (refused above) and "would
        ## break this member" (said here).
        remaining = cfgmod.validate_config(
            cfgmod.merge_defaults(config, project.defaults))
        if remaining:
            self._log.append_line(
                f"[config] {name}: {len(remaining)} thing(s) still to fix — "
                + "; ".join(remaining[:3]))
        ## A copied config restates what the scaffold inherited, which freezes
        ## today's Project Defaults into this member. `experiment_type` is
        ## exempt: every member states its own, minimal scaffolds included.
        restated = sorted(set(config) & set(project.defaults)
                          - {"experiment_type"})
        if restated:
            self._log.append_line(
                f"[config] {name}: {', '.join(restated)} now stated in the "
                f"member, so edits to the Project Defaults no longer reach "
                f"it.")
        return True

    def _action_initialize_experiment(self) -> None:
        """The member's directory exists but its config does not: scaffold one.

        Nothing is moved on the way — unlike the sister app, this loader reads
        ``data/`` *and* the directory root, so a workbook loose in the folder
        is already where it will be found (ADR-0009). What remains is the
        config, and the one question the loader refuses to answer for itself:
        which file is the experiment, when there is more than one.
        """
        project = self._project
        if project is None:
            self._warn("Create or select a Project first — a member's "
                       "defaults are inherited from its project.yaml.")
            return
        candidates = layout_mod.initializable_dirs(project.directory)
        if not candidates:
            self._warn(
                f"Every directory in '{project.name}' already has a "
                f"{cfgmod.CONFIG_FILENAME}.\n\nUse 'Create experiment…' to "
                f"make a new member.")
            return
        labels = [f"{item.name}  —  {item.status or 'empty'}"
                  for item in candidates]
        choice = self._prompt_choice(
            "Initialize existing directory",
            f"Directory to make a member of '{project.name}':", labels)
        if choice is None:
            return
        item = candidates[labels.index(choice)]

        ## Re-classify rather than trusting the listing: it was built before
        ## the user had a chance to change anything on disk.
        state = layout_mod.classify(item.directory)
        if state.status == layout_mod.UNREADABLE:
            self._warn(f"'{state.name}': {state.detail or state.status}\n\n"
                       "This one has to be sorted out by hand.")
            return
        member = self._create_member_config(item.name)
        if member is None:
            return
        ## Several candidate files and no `data_file:` is the one blocked
        ## state a scaffold does not clear, and the answer is the user's.
        after = layout_mod.classify(item.directory)
        if after.fix == "data_file" and after.candidates:
            self._name_member_data_file(after)
        self._refresh_all()

    def _name_member_data_file(self, item) -> None:
        """Write ``data_file:`` into an ambiguous member's config."""
        choice = self._prompt_choice(
            f"Which file is {item.name}?", "The experiment's data file:",
            list(item.candidates))
        if choice is None:
            return
        config = cfgmod.load_config(item.directory)
        config["data_file"] = choice
        cfgmod.save_config(item.directory, config)
        self._log.append_line(f"{item.name}: data_file: {choice}")

    def _action_member_configs(self) -> None:
        """The bulk view over every subdirectory's config."""
        if self._project is None:
            self._warn("Create or select a Project first.")
            return
        from .project_dialogs import MemberConfigsDialog

        dialog = MemberConfigsDialog(self, self._project,
                                     log=self._log.append_line)
        dialog.exec()
        self._refresh_all()

    # ── ADR-0008: the two ways a member arrives from outside ───────────────

    def _action_add_directory(self) -> None:
        if self._project is None:
            self._warn("Create or select a Project first.")
            return
        path = QFileDialog.getExistingDirectory(
            self, "Add an experiment directory from outside the Project",
            str(self._project.directory.parent))
        if not path:
            return
        chosen = Path(path).resolve()
        ## Strictly the way in from OUTSIDE (ADR-0010): a folder already in
        ## the Project is the other button's state, and letting this one take
        ## it too meant two buttons covering one case with different rules —
        ## this one refuses an empty folder or a bare CSV that Initialize
        ## handles fine.
        if chosen.parent == self._project.directory:
            self._warn(
                f"'{chosen.name}' is already in this Project.\n\nUse "
                "'Initialize existing directory…' to make a folder that is "
                "already here a member — Add directory is for copying one in "
                "from outside.")
            return
        try:
            member = self._project.adopt_directory(chosen)
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

    # ── the three states a Project directory can be in ─────────────────────

    def _action_create_project(self) -> None:
        """The Project does not exist yet: choose where it goes and name it."""
        from .project_dialogs import ProjectInfoDialog

        start = str(self._selection) if self._selection else ""
        dialog = ProjectInfoDialog(self, start_dir=start)
        if dialog.exec() and dialog.saved_dir:
            self._log.append_line(
                f"Wrote {Path(dialog.saved_dir) / cfgmod.PROJECT_FILENAME}")
            self._set_selection(dialog.saved_dir)
            self._refresh_all()

    def _action_initialize_project(self) -> None:
        """Promote a directory that already exists — usually with experiment
        subdirectories in it — into a Project, keeping its own name.

        The third way in: Open project wants a project.yaml already there,
        Create project makes the directory too.
        """
        from .project_dialogs import ProjectInfoDialog

        ## Prefilling a directory that is already a Project would only earn the
        ## dialog's refusal, so offer the selection only when it is the kind of
        ## directory this button takes.
        start = ""
        if self._selection is not None and not is_project_dir(self._selection):
            start = str(self._selection)
        dialog = ProjectInfoDialog(self, start_dir=start,
                                   initialize_existing=True)
        if dialog.exec() and dialog.saved_dir:
            self._log.append_line(
                f"Initialized {Path(dialog.saved_dir) / cfgmod.PROJECT_FILENAME}")
            self._set_selection(dialog.saved_dir)
            self._refresh_all()

    def _action_edit_project_config(self) -> None:
        """Edit the open Project's ``project.yaml``.

        Only ever an edit. Writing the file into a directory that has none is
        the third button's job — 'Initialize existing directory…' does exactly
        that, and having this one do it too meant two controls with one
        behaviour.
        """
        from .project_dialogs import ProjectInfoDialog

        if self._project is None:
            self._warn("Open a Project first. To give a directory its first "
                       "project.yaml, use 'Initialize existing directory…'.")
            return
        dialog = ProjectInfoDialog(self, start_dir=str(self._project.directory))
        if dialog.exec() and dialog.saved_dir:
            self._log.append_line(
                f"Saved {Path(dialog.saved_dir) / cfgmod.PROJECT_FILENAME}")
            self._set_selection(dialog.saved_dir)
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
        """Render every member's curated Publication Figures.

        Runs the registered ``render_publication_figures`` action rather than
        calling ``pubfigures.render_all`` directly, so this button and a
        Batch Run cannot drift apart about which members get figures — the
        skip-the-uncurated rule (ADR-0005) is stated once, in the action.
        """
        if self._project is None:
            self._warn("Select a Project first — rendering walks its members.")
            return
        from ..script_editor import project_actions

        project, fmt = self._project, self._fig_format.currentText()

        def _job():
            project_actions.run_script(
                project,
                [{"action": "render_publication_figures", "format": fmt}],
                log=print)
            return f"Publication figures rendered as {fmt}."

        self._spawn("Render publication figures", _job)

    def _selected_member(self):
        """The member the members table is pointing at, if it is one.

        A row for an unconfigured directory is not a member and answers None,
        the same as no selection at all.
        """
        if self._project is None:
            return None
        rows = {i.row() for i in self._members_table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = rows.pop()
        name_cell = self._members_table.item(row, 0)
        config_cell = self._members_table.item(row, 1)
        if name_cell is None or config_cell is None or config_cell.text() != "yes":
            return None
        try:
            return self._project.member(name_cell.text())
        except ProjectError:
            return None

    def _plot_editor_subject(self):
        """Which member the Plot Editor opens on, from the Project panel.

        Specs are per-experiment (ADR-0005), so the editor always has one
        member as its subject — but this is now the only way in, so it
        resolves one rather than refusing without a loaded experiment: the
        selected row, else the loaded member, else the only member there is,
        else ask.
        """
        member = self._selected_member()
        if member is not None:
            return member
        if self._experiment is not None:
            return self._experiment
        if self._project is None:
            return None
        members = self._project.members()
        if len(members) == 1:
            return members[0]
        if not members:
            self._warn("This Project has no Member Experiments yet — a Plot "
                       "Spec belongs to one, so there is nothing to author.")
            return None
        names = [m.name for m in members]
        choice = self._prompt_choice(
            "Plot editor", "Author which member's figures?", names)
        return members[names.index(choice)] if choice in names else None

    def _action_open_plot_editor(self) -> None:
        subject = self._plot_editor_subject()
        if subject is None:
            return
        from .plot_editor import PlotEditorWindow

        editor = PlotEditorWindow(subject)
        editor.show()
        self._plot_editor = editor
        self._log.append_line(f"Plot Editor: {subject.name}")

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
