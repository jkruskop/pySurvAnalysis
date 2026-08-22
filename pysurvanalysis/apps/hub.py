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
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
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
    upgrade as upgrade_mod,
)
from ..experiment_types import available_types
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
from .common import TaskWorker

PANEL_WIDTH = 540

#: key, title, icon, category — the strip, left to right.
TILES = (
    ("batch", "Batch", "batch", Category.NEUTRAL),
    ("project", "Project", "project", Category.NEUTRAL),
    ("analyze", "Analyze", "analyze", Category.ANALYZE),
    ("qc", "QC", "qc", Category.QC),
    ("plots", "Plots", "plots", Category.PLOTS),
    ("scripts", "Scripts", "scripts", Category.SCRIPTS),
    ("ai", "AI", "ai", Category.AI),
    ("tools", "Tools", "tools", Category.TOOLS),
)


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
        QApplication.instance().installEventFilter(self._click_away)

        if initial_path:
            self._set_selection(initial_path)
        else:
            recent = ui_settings.get("recent_projects", []) or []
            if recent:
                self._set_selection(recent[0])
        self._refresh_all()

    # ── construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(8)

        self._topbar = TopBar("pySurvAnalysis")
        open_btn = QPushButton(icon("open"), " Open…")
        open_btn.clicked.connect(self._pick_directory)
        recent_btn = QPushButton(icon("menu"), " Recent")
        recent_btn.clicked.connect(self._show_recent_menu)
        theme_btn = QPushButton(icon("theme_dark"), "")
        theme_btn.setToolTip("Toggle light/dark theme")
        theme_btn.clicked.connect(self._toggle_theme)
        for btn in (open_btn, recent_btn, theme_btn):
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
        self._build_analyze_panel()
        self._build_qc_panel()
        self._build_plots_panel()
        self._build_scripts_panel()
        self._build_ai_panel()
        self._build_tools_panel()
        for panel in self._panels.values():
            panel.finish()

    # ── panels ─────────────────────────────────────────────────────────────

    def _build_batch_panel(self) -> None:
        card = Card("Batch run", Category.NEUTRAL, icon_name="batch",
                    subtitle="Run one Project Script in every Project below "
                             "this directory, continue-on-error.")
        self._batch_table = self._make_table(["Project", "Type", "Members", "Report"])
        card.add_body(self._batch_table)

        row = QHBoxLayout()
        row.addWidget(QLabel("Script:"))
        self._batch_script = QComboBox()
        row.addWidget(self._batch_script, 1)
        card.add_body(row)

        run = ActionButton("Run batch", Category.NEUTRAL, icon_name="play")
        run.clicked.connect(self._action_run_batch)
        card.add_body(run)
        self._panels["batch"].add_card(card)

    def _build_project_panel(self) -> None:
        card = Card("Project", Category.NEUTRAL, icon_name="project",
                    subtitle="Double-click a member to load it.")
        self._members_table = self._make_table(
            ["Member", "Type", "N", "Analysed", "Exclusions"])
        self._members_table.doubleClicked.connect(self._on_member_double_clicked)
        card.add_body(self._members_table)

        row = QHBoxLayout()
        add = QPushButton(icon("add"), " Add member…")
        add.clicked.connect(self._action_add_member)
        create = QPushButton(icon("new"), " Create project…")
        create.clicked.connect(self._action_create_project)
        row.addWidget(add)
        row.addWidget(create)
        card.add_body(row)
        self._panels["project"].add_card(card)

        run_card = Card("Project actions", Category.ANALYZE, icon_name="report")
        row = QHBoxLayout()
        row.addWidget(QLabel("Script:"))
        self._project_script = QComboBox()
        row.addWidget(self._project_script, 1)
        run_card.add_body(row)
        run_btn = ActionButton("Run project script", Category.ANALYZE, icon_name="play")
        run_btn.clicked.connect(self._action_run_project_script)
        run_card.add_body(run_btn)
        report_btn = ActionButton("Project report", Category.ANALYZE, icon_name="report")
        report_btn.clicked.connect(self._action_project_report)
        run_card.add_body(report_btn)
        validate_btn = ActionButton("Validate project", Category.TOOLS,
                                    icon_name="validate")
        validate_btn.clicked.connect(self._action_validate_project)
        run_card.add_body(validate_btn)
        self._panels["project"].add_card(run_card)

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
        self.close_panel()
        tile = self._tiles[key]
        panel = self._panels[key]
        top_left = tile.mapTo(self._central, tile.rect().bottomLeft())
        panel.open_at(top_left.x(), top_left.y() + 4, self._central.height())
        tile.set_active(True)
        self._open_panel = key

    def close_panel(self) -> None:
        if self._open_panel is None:
            return
        self._panels[self._open_panel].hide()
        self._tiles[self._open_panel].set_active(False)
        self._open_panel = None

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape:
            self.close_panel()
        super().keyPressEvent(event)

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
        elif any(d.is_dir() and is_project_dir(d) for d in p.iterdir()):
            self._batch = Batch(p)

        ui_settings.add_recent_project(str(p))
        self._log.append_line(f"Selection: {p}")

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

    # ── refresh ────────────────────────────────────────────────────────────

    def _refresh_all(self) -> None:
        self._refresh_tables()
        self._refresh_analyze_panel()
        self._refresh_scripts()
        self._refresh_exclusion_groups()
        self._refresh_ai()
        self._refresh_tiles()

    def _refresh_tiles(self) -> None:
        batch_projects = len(self._batch.project_dirs()) if self._batch else 0
        self._tiles["batch"].set_dimmed(self._batch is None)
        self._tiles["batch"].set_summary(
            [f"{batch_projects} project(s)", self._batch.name] if self._batch
            else ["no batch selected", "select a folder of projects"])

        if self._project is not None:
            members = self._project.members()
            analysed = sum(1 for m in members if m.status().analyzed)
            loaded = (f"loaded: {self._experiment.name}" if self._experiment
                      else "double-click a member to load")
            self._tiles["project"].set_summary(
                [f"{len(members)} member(s) · {analysed} analysed", loaded])
            self._tiles["project"].set_dimmed(False)
        elif self._experiment is not None:
            self._tiles["project"].set_summary(
                ["standalone experiment", self._experiment.name])
            self._tiles["project"].set_dimmed(True)
        else:
            self._tiles["project"].set_summary(
                ["not a project yet", "Tools ▸ Upgrade or Create project"])
            self._tiles["project"].set_dimmed(True)

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

        providers = self._ai_provider.count()
        self._tiles["ai"].set_dimmed(providers == 0 or self._project is None)
        self._tiles["ai"].set_summary(
            [f"{providers} provider(s) configured",
             "per-member + across-members"])
        self._tiles["tools"].set_summary(["directory tools", ""])

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

    def _refresh_tables(self) -> None:
        self._batch_table.setRowCount(0)
        if self._batch is not None:
            for d in self._batch.project_dirs():
                try:
                    project = Project(d)
                    type_label = project.type.label
                    members = str(len(project.members()))
                    report = "yes" if project.report_path.is_file() else "no"
                except Exception as exc:  # noqa: BLE001 - a bad Project still lists
                    type_label, members, report = f"error: {exc}", "—", "—"
                self._append_row(self._batch_table,
                                 [d.name, type_label, members, report])
            self._batch_script.clear()
            from ..script_editor import project_actions

            names = project_actions.builtin_names()
            names += [s["name"] for s in self._batch.project_scripts()]
            self._batch_script.addItems(names)
            if self._batch.designated_script:
                idx = self._batch_script.findText(self._batch.designated_script)
                if idx >= 0:
                    self._batch_script.setCurrentIndex(idx)

        self._members_table.setRowCount(0)
        if self._project is not None:
            for member in self._project.members():
                st = member.status()
                self._append_row(self._members_table, [
                    member.name,
                    member.type.label,
                    str(st.n_total or "—"),
                    (st.analyzed_at or "yes") if st.analyzed else "no",
                    st.exclusion_group or "none",
                ])
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

    def _refresh_analyze_panel(self) -> None:
        """Rebuild the Analyze buttons from ``core ∪ type`` (ADR-0002)."""
        layout = self._analyze_card.body_layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        if self._experiment is None:
            layout.addWidget(QLabel("Load an experiment to see its actions."))
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
            layout.addWidget(btn)

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
        worker.log_text.connect(self._log.append_line)
        worker.figure_ready.connect(self._on_figure)
        worker.finished_ok.connect(lambda msg: self._log.append_line(f"✔ {msg}"))
        worker.failed.connect(lambda msg: self._log.append_line(f"✘ {msg}"))
        worker.finished.connect(self._refresh_all)
        self._worker = worker
        worker.start()

    def _on_figure(self, title: str, figure) -> None:
        self._plots.add_figure(title, figure)

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

    def _action_run_batch(self) -> None:
        if self._batch is None:
            self._warn("Select a directory that holds Projects first.")
            return
        batch, name = self._batch, self._batch_script.currentText()
        self._spawn(f"Batch run: {name}",
                    lambda: batch.run(name, log=print).summary())

    def _action_run_project_script(self) -> None:
        if self._project is None:
            self._warn("No Project selected.")
            return
        from ..script_editor import project_actions

        project, name = self._project, self._project_script.currentText()
        steps = None
        for script in project.scripts():
            if script.get("name") == name:
                steps = list(script.get("steps") or [])
        steps = steps if steps is not None else project_actions.builtin_steps(name)
        if steps is None:
            self._warn(f"No Project Script named {name!r}.")
            return

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
        if self._project is None:
            self._warn("No Project selected.")
            return
        problems = self._project.validate()
        if problems:
            self._log.append_line("Project validation problems:")
            for p in problems:
                self._log.append_line(f"  - {p}")
        else:
            self._log.append_line("Project validation passed.")
        for divergence in self._project.divergences():
            self._log.append_line(f"  divergence — {divergence}")

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


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app, ui_settings.get("theme", "auto"))
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    window = HubWindow(initial)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
