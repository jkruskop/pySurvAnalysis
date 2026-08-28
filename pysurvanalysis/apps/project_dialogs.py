"""The two dialogs behind the Hub's Create/Load and Experiments cards.

* :class:`ProjectInfoDialog` — the ``project.yaml`` editor. Three of the four
  ways into a Project share it (create the directory outright, initialize one
  already on disk, edit the one that is open), because the *design* half is
  identical and only the directory and the name differ.
* :class:`MemberConfigsDialog` — the bulk view: every subdirectory of a
  Project with its config and data status, so the missing configs can be made
  and the ambiguous ones settled without hunting through a file manager.

**What is edited here is a seed, not an authority** (ADR-0001). Project
Defaults are inherited by a member that says nothing; a member that states its
own value keeps it. Exactly one thing is enforced across members — the
Experiment Type — which is why that is the only field this dialog checks a
copied config against.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..domain import (
    Project,
    ProjectError,
    config as cfgmod,
    is_experiment_dir,
    is_project_dir,
    layout as layout_mod,
)
from ..experiment_types import available_types, get_type
from ..ui import ActionButton, Category, icon

#: ``defaults:`` keys this dialog owns. Anything else in the section rides
#: through an edit untouched — the same promise ``config.py`` makes about
#: unknown keys, and the reason a hand-written project.yaml is safe to open.
_MANAGED_DEFAULT_KEYS = ("experiment_type", "global", "factors")


def _levels_text(levels) -> str:
    if isinstance(levels, (list, tuple)):
        return ", ".join(str(x) for x in levels)
    return "" if levels is None else str(levels)


def _split_levels(text: str) -> list[str]:
    return [part.strip() for part in str(text).split(",") if part.strip()]


class ProjectInfoDialog(QDialog):
    """Create, initialize or edit a Project's ``project.yaml``.

    ``saved_dir`` is the Project directory on success, ``None`` on cancel.

    Two of the three ways in share this dialog through the
    *initialize_existing* flag rather than a subclass: creating the directory
    outright and promoting one that already exists differ only in where the
    directory comes from and whether the name is the user's to choose.
    Pointing it at a directory that already is a Project turns it into the
    editor for that Project, which is what the Hub's **Edit config…** does.
    """

    def __init__(self, parent=None, start_dir: str | None = None, *,
                 initialize_existing: bool = False) -> None:
        super().__init__(parent)
        self._initialize = bool(initialize_existing)
        self.setWindowTitle("Initialize existing directory"
                            if self._initialize else "Create / edit project")
        self.setMinimumWidth(560)
        self.saved_dir: str | None = None
        #: Everything in ``defaults:`` this form does not own, kept verbatim.
        self._carried_defaults: dict = {}
        #: ``global:`` values read off disk, so a key the chosen type does not
        #: define is still shown rather than silently dropped on the next save.
        self._global_values: dict = {}
        self._global_widgets: dict[str, QWidget] = {}
        self._type_touched = False

        outer = QVBoxLayout(self)
        intro = QLabel(
            "Turn a directory you already have into a Project: it keeps its "
            "own name, its subdirectories become the Member Experiments, and "
            "the type below is inferred from the first one that has a config. "
            "This writes project.yaml into it."
            if self._initialize else
            "A Project is a directory whose subdirectories are independent "
            "Member Experiments of one question. This writes its "
            "project.yaml — choosing a directory that already is a Project "
            "edits it instead."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(start_dir or "")
        self.dir_edit.editingFinished.connect(self._on_dir_changed)
        browse = QPushButton(icon("browse"), " Browse…")
        browse.clicked.connect(self._browse)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)
        holder = QWidget()
        holder.setLayout(dir_row)
        form.addRow("Directory:", holder)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("defaults to the directory name")
        if self._initialize:
            ## The directory IS the Project, so it names it. Shown rather than
            ## hidden, so the user can see what it will be called.
            self.name_edit.setReadOnly(True)
            self.name_edit.setToolTip(
                "The chosen directory's own name — initializing in place does "
                "not rename it.")
        form.addRow("Project name:", self.name_edit)

        self.question_edit = QLineEdit()
        self.question_edit.setPlaceholderText(
            "The one question these experiments address — the report cover "
            "and the AI narrative both read it.")
        form.addRow("Question:", self.question_edit)
        outer.addLayout(form)

        # ---- Project Defaults (a seed, not an authority) -------------------
        box = QGroupBox("Project Defaults — seeded into every new member")
        dform = QFormLayout(box)
        dform.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.type_combo = QComboBox()
        for exp_type in available_types():
            self.type_combo.addItem(exp_type.label, exp_type.key)
        self.type_combo.setToolTip(
            "The one thing enforced across members: every Member Experiment "
            "must share it, because the type selects the analyses, the Plot "
            "Set and the report sections.")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        dform.addRow("Experiment type:", self.type_combo)

        self.factors_table = QTableWidget(0, 2)
        self.factors_table.setHorizontalHeaderLabels(
            ["Factor", "Levels (comma-separated, reference first)"])
        self.factors_table.horizontalHeader().setStretchLastSection(True)
        self.factors_table.verticalHeader().setVisible(False)
        self.factors_table.setMaximumHeight(110)
        dform.addRow("Factors:", self.factors_table)
        frow = QHBoxLayout()
        add_f = QPushButton("Add factor")
        add_f.clicked.connect(
            lambda: self.factors_table.insertRow(self.factors_table.rowCount()))
        rm_f = QPushButton("Remove selected")
        rm_f.clicked.connect(self._remove_factor_row)
        frow.addWidget(add_f)
        frow.addWidget(rm_f)
        frow.addStretch(1)
        fholder = QWidget()
        fholder.setLayout(frow)
        dform.addRow("", fholder)

        ## Built from the selected type's own `default_global`, so a type that
        ## grows a setting grows a field here without this dialog knowing its
        ## name. Keys already in the file survive a type change for the same
        ## reason.
        self._global_form = QFormLayout()
        self._global_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        global_holder = QWidget()
        global_holder.setLayout(self._global_form)
        dform.addRow("Global:", global_holder)
        outer.addWidget(box)

        note = QLabel(
            "Defaults are a seed and a template: a member that states its own "
            "value keeps it, and a member that says nothing follows an edit "
            "made here. Only the Experiment Type is enforced across members.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid); font-style: italic;")
        outer.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._rebuild_global_form()
        if start_dir:
            self._on_dir_changed()

    # ── the directory ──────────────────────────────────────────────────────

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Choose the directory to initialize" if self._initialize
            else "Choose where the Project goes",
            self.dir_edit.text() or str(Path.home()))
        if chosen:
            self.dir_edit.setText(chosen)
            self._on_dir_changed()

    def _on_dir_changed(self) -> None:
        """Re-read whatever the chosen directory already says about itself."""
        text = self.dir_edit.text().strip()
        if not text:
            return
        target = Path(text).expanduser()
        if self._initialize or is_project_dir(target):
            self.name_edit.setText(target.name)
        if is_project_dir(target):
            self._load_existing(target)
        elif self._initialize:
            ## Nothing to load, but its subdirectories may already agree on a
            ## type — a study started before Projects existed.
            self._infer_type_from_members(target)

    def _load_existing(self, directory: Path) -> None:
        """Fill the form from a ``project.yaml`` that is already there."""
        try:
            config = cfgmod.read_yaml(directory / cfgmod.PROJECT_FILENAME)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.windowTitle(),
                                f"{directory.name}'s project.yaml could not be "
                                f"read:\n{exc}")
            return
        self.name_edit.setText(str(config.get("name") or directory.name))
        self.question_edit.setText(str(config.get("question") or ""))
        defaults = config.get("defaults")
        defaults = dict(defaults) if isinstance(defaults, dict) else {}
        self._carried_defaults = {k: v for k, v in defaults.items()
                                  if k not in _MANAGED_DEFAULT_KEYS}
        self._set_type(defaults.get("experiment_type"))
        section = defaults.get("global")
        self._global_values = dict(section) if isinstance(section, dict) else {}
        self._rebuild_global_form()
        self._set_factors(defaults.get("factors"))

    def _infer_type_from_members(self, directory: Path) -> None:
        """Adopt the type of the first subdirectory that already has a config.

        A directory being initialized usually holds experiments already, and
        their type is the answer — offering the alphabetically-first type
        instead would silently propose one the Project's own contents refute.
        """
        if self._type_touched:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for path in entries:
            if not path.is_dir() or not is_experiment_dir(path):
                continue
            try:
                config = cfgmod.load_config(path)
            except (OSError, ValueError):
                continue
            self._set_type(config.get("experiment_type"))
            self._set_factors(config.get("factors"))
            return

    # ── the type, its globals, its factors ─────────────────────────────────

    def _set_type(self, key) -> None:
        try:
            resolved = get_type(key)
        except ValueError:
            ## A config naming a type this build does not have: leave the
            ## combo alone rather than silently retyping the Project.
            return
        index = self.type_combo.findData(resolved.key)
        if index >= 0:
            blocked = self.type_combo.blockSignals(True)
            self.type_combo.setCurrentIndex(index)
            self.type_combo.blockSignals(blocked)

    def _current_type(self):
        return get_type(self.type_combo.currentData())

    def _on_type_changed(self) -> None:
        self._type_touched = True
        self._global_values = self._read_global_form()
        self._rebuild_global_form()

    def _rebuild_global_form(self) -> None:
        while self._global_form.rowCount():
            self._global_form.removeRow(0)
        self._global_widgets = {}
        seed = dict(self._current_type().default_global)
        ## The type's keys first, then anything the file carries that the type
        ## does not define — dropping those on a save would edit a config the
        ## user never touched.
        keys = list(seed) + [k for k in self._global_values if k not in seed]
        for key in keys:
            value = self._global_values.get(key, seed.get(key))
            if isinstance(value, bool):
                widget: QWidget = QCheckBox()
                widget.setChecked(bool(value))
            else:
                widget = QLineEdit("" if value is None else str(value))
                widget.setPlaceholderText(
                    "" if key not in seed else f"default: {seed[key]}")
            self._global_widgets[key] = widget
            self._global_form.addRow(f"{key}:", widget)

    def _read_global_form(self) -> dict:
        seed = dict(self._current_type().default_global)
        out: dict = {}
        for key, widget in self._global_widgets.items():
            if isinstance(widget, QCheckBox):
                out[key] = widget.isChecked()
                continue
            text = widget.text().strip()
            if not text:
                ## Empty means "inherit the type's default"; writing "" would
                ## freeze an empty string into the Project instead.
                continue
            out[key] = _coerce(text, seed.get(key, self._global_values.get(key)))
        return out

    def _set_factors(self, factors) -> None:
        self.factors_table.setRowCount(0)
        if not isinstance(factors, dict):
            return
        for name, levels in factors.items():
            row = self.factors_table.rowCount()
            self.factors_table.insertRow(row)
            self.factors_table.setItem(row, 0, QTableWidgetItem(str(name)))
            self.factors_table.setItem(row, 1,
                                       QTableWidgetItem(_levels_text(levels)))

    def _read_factors(self) -> dict:
        out: dict = {}
        for row in range(self.factors_table.rowCount()):
            name_item = self.factors_table.item(row, 0)
            name = (name_item.text().strip() if name_item else "")
            if not name:
                continue
            level_item = self.factors_table.item(row, 1)
            out[name] = _split_levels(level_item.text() if level_item else "")
        return out

    def _remove_factor_row(self) -> None:
        rows = sorted({i.row() for i in self.factors_table.selectedIndexes()},
                      reverse=True)
        for row in rows:
            self.factors_table.removeRow(row)

    # ── saving ─────────────────────────────────────────────────────────────

    def _resolved_target(self) -> Path | None:
        text = self.dir_edit.text().strip()
        if not text:
            QMessageBox.warning(self, self.windowTitle(),
                                "Choose a directory first.")
            return None
        target = Path(text).expanduser().resolve()

        if self._initialize:
            if not target.is_dir():
                QMessageBox.warning(
                    self, self.windowTitle(),
                    f"{target} does not exist.\n\nUse 'Create project…' to "
                    f"make a Project whose directory does not exist yet.")
                return None
            if is_project_dir(target):
                QMessageBox.warning(
                    self, self.windowTitle(),
                    f"{target.name} is already a Project.\n\nOpen it, then use "
                    f"'Edit config…' to change its project.yaml.")
                return None

        ## A project.yaml written beside a survival_config.yaml makes a Project
        ## whose only experiment is its own root — zero members and nothing to
        ## bind. The Project belongs on the parent.
        if is_experiment_dir(target) and not is_project_dir(target):
            resp = QMessageBox.question(
                self, self.windowTitle(),
                f"'{target.name}' is an Experiment Directory, not a Project.\n\n"
                f"Create the Project on '{target.parent.name}' instead, so "
                f"'{target.name}' becomes one of its members?")
            if resp != QMessageBox.StandardButton.Yes:
                return None
            target = target.parent
            self.dir_edit.setText(str(target))
            if self._initialize:
                self.name_edit.setText(target.name)
        return target

    def accept(self) -> None:  # noqa: D102 - Qt override
        target = self._resolved_target()
        if target is None:
            return

        exp_type = self._current_type()
        defaults = dict(self._carried_defaults)
        globals_ = self._read_global_form()
        if globals_:
            defaults["global"] = globals_
        factors = self._read_factors()
        if factors:
            defaults["factors"] = factors
        elif "factors" in defaults:
            defaults.pop("factors")
        name = self.name_edit.text().strip() or target.name
        question = self.question_edit.text().strip()

        try:
            if is_project_dir(target):
                ## Edit in place: read, mutate, write. Anything this form does
                ## not own — scripts, experiment_scripts, a key from a future
                ## version — is carried through untouched.
                project = Project(target)
                project.config["name"] = name
                project.config["question"] = question
                seed = dict(defaults)
                if not exp_type.is_custom:
                    seed = {"experiment_type": exp_type.key, **seed}
                project.config["defaults"] = seed
                project.save()
            else:
                target.mkdir(parents=True, exist_ok=True)
                project = Project.create(
                    target, name=name, question=question,
                    type_key=None if exp_type.is_custom else exp_type.key,
                    defaults=defaults)
        except (ProjectError, OSError, ValueError) as exc:
            QMessageBox.warning(self, self.windowTitle(),
                                f"Could not write project.yaml:\n{exc}")
            return

        self.saved_dir = str(project.directory)
        super().accept()


def _coerce(text: str, like):
    """Read *text* back as the kind of value *like* is.

    Types declare their defaults as real YAML scalars (``min_n_per_chamber``
    is an int, ``time_label`` a string), and writing every field back as a
    string would turn a validated integer setting into one that fails
    validation the next time the config is read.
    """
    if isinstance(like, bool):
        return text.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(like, int):
        try:
            return int(text)
        except ValueError:
            return text
    if isinstance(like, float):
        try:
            return float(text)
        except ValueError:
            return text
    return text


class MemberConfigsDialog(QDialog):
    """Create and settle the per-member ``survival_config.yaml`` files.

    ``project.yaml`` holds the shared defaults; the member configs live one
    level down, one per experiment directory — so a Project directory itself
    has no member config to select. This is where those files are made: every
    immediate subdirectory is listed with its config and data status, missing
    ones are scaffolded from the Project Defaults, and an ambiguous one gets
    the ``data_file:`` the loader refuses to guess.
    """

    def __init__(self, parent, project: Project, *, log=None,
                 on_change=None) -> None:
        super().__init__(parent)
        self._project = project
        self._log = log or (lambda _msg: None)
        self._on_change = on_change
        self._rows: list = []
        self.changed = False
        self.setWindowTitle("pySurvAnalysis — Experiment configs")
        self.setMinimumWidth(600)

        outer = QVBoxLayout(self)
        intro = QLabel(
            f"Each experiment directory in <b>{project.name}</b> carries its "
            f"own {cfgmod.CONFIG_FILENAME}. Missing ones are scaffolded from "
            f"the Project Defaults ({project.type.label}) and stay minimal, so "
            f"later edits to the Project keep reaching them.")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(intro)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Directory", "Config", "Data files", "Status"])
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._sync_buttons)
        self._table.itemDoubleClicked.connect(self._on_double_click)
        outer.addWidget(self._table)

        grid = QGridLayout()
        self._btn_create = ActionButton("Create config", Category.TOOLS,
                                        icon_name="new")
        self._btn_create.setToolTip(
            "Scaffold this directory's survival_config.yaml from the Project "
            "Defaults.")
        self._btn_create.clicked.connect(self._create_selected)
        self._btn_create_all = ActionButton("Create all missing",
                                            Category.TOOLS, icon_name="batch")
        self._btn_create_all.clicked.connect(self._create_all_missing)
        self._btn_data_file = ActionButton("Set data file…", Category.TOOLS,
                                           icon_name="excel")
        self._btn_data_file.setToolTip(
            "Name which of several candidate files is this member's data. The "
            "loader refuses to guess, so the answer is written into the "
            "config where the next run reads it.")
        self._btn_data_file.clicked.connect(self._name_data_file)
        self._btn_edit = ActionButton("Edit config…", Category.TOOLS,
                                      icon_name="config")
        self._btn_edit.setToolTip(
            f"Open this member's {cfgmod.CONFIG_FILENAME} in your desktop's "
            f"editor for YAML files.")
        self._btn_edit.clicked.connect(self._edit_selected)
        for i, btn in enumerate((self._btn_create, self._btn_create_all,
                                 self._btn_data_file, self._btn_edit)):
            grid.addWidget(btn, i // 2, i % 2)
        for col in range(2):
            grid.setColumnStretch(col, 1)
        outer.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.reload()

    # ── the table ──────────────────────────────────────────────────────────

    def reload(self) -> None:
        root = self._project.directory
        ## Both walks, deduplicated by name: members_in answers "what is
        ## experiment-shaped" and drops an empty folder, initializable_dirs
        ## answers "what has no config yet" and drops a healthy member. The
        ## union is every directory this dialog can act on.
        items = {}
        for item in layout_mod.members_in(root):
            items[item.name] = item
        for item in layout_mod.initializable_dirs(root):
            items.setdefault(item.name, item)
        self._rows = [items[name] for name in sorted(items, key=str.lower)]

        self._table.setRowCount(0)
        for item in self._rows:
            row = self._table.rowCount()
            self._table.insertRow(row)
            files = ", ".join(item.candidates) if item.candidates else "none"
            status = item.status or "empty"
            for col, value in enumerate((item.name,
                                         "yes" if item.configured else "missing",
                                         files, status)):
                cell = QTableWidgetItem(value)
                if item.detail:
                    cell.setToolTip(item.detail)
                self._table.setItem(row, col, cell)
        if self._rows:
            self._table.selectRow(0)
        self._sync_buttons()

    def _selected(self):
        rows = {i.row() for i in self._table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = rows.pop()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _sync_buttons(self) -> None:
        item = self._selected()
        self._btn_create.setEnabled(item is not None and not item.configured)
        self._btn_edit.setEnabled(item is not None and item.configured)
        self._btn_data_file.setEnabled(
            item is not None and item.fix == "data_file")
        self._btn_create_all.setEnabled(
            any(not row.configured for row in self._rows))

    # ── actions ────────────────────────────────────────────────────────────

    def _on_double_click(self, _item) -> None:
        item = self._selected()
        if item is None:
            return
        if item.configured:
            self._edit_selected()
        else:
            self._create_selected()

    def _scaffold(self, name: str) -> bool:
        """The Project's own scaffolding path, not a second one: a config
        written any other way would not inherit the Project Defaults, and a
        member that restates a default freezes it."""
        try:
            self._project.add_member(name)
        except (ProjectError, OSError) as exc:
            QMessageBox.warning(self, self.windowTitle(),
                                f"Could not create the config for "
                                f"'{name}':\n{exc}")
            return False
        self._log(f"Scaffolded {cfgmod.CONFIG_FILENAME} in {name} from the "
                  f"Project Defaults.")
        self.changed = True
        return True

    def _create_selected(self) -> None:
        item = self._selected()
        if item is None or item.configured:
            return
        if self._scaffold(item.name):
            self._finish()

    def _create_all_missing(self) -> None:
        missing = [row.name for row in self._rows if not row.configured]
        if not missing:
            return
        resp = QMessageBox.question(
            self, self.windowTitle(),
            f"Scaffold a {cfgmod.CONFIG_FILENAME} in {len(missing)} "
            f"directory(ies)?\n\n" + ", ".join(missing))
        if resp != QMessageBox.StandardButton.Yes:
            return
        for name in missing:
            self._scaffold(name)
        self._finish()

    def _name_data_file(self) -> None:
        item = self._selected()
        if item is None or not item.candidates:
            return
        choice, ok = QInputDialog.getItem(
            self, f"Which file is {item.name}?", "The experiment's data file:",
            list(item.candidates), 0, False)
        if not ok or not choice:
            return
        config = cfgmod.load_config(item.directory)
        config["data_file"] = choice
        cfgmod.save_config(item.directory, config)
        self._log(f"{item.name}: data_file: {choice}")
        self.changed = True
        self._finish()

    def _edit_selected(self) -> None:
        item = self._selected()
        if item is None or not item.configured:
            return
        path = cfgmod.config_path(item.directory)
        ## No Config Editor in this app: the member config is a small YAML
        ## file, and handing it to the desktop's own editor beats a half-built
        ## form that would silently drop the keys it does not know.
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.information(
                self, self.windowTitle(),
                f"No editor is registered for YAML files here.\n\nThe config "
                f"is at:\n{path}")

    def _finish(self) -> None:
        self._project.members(reload=True)
        self.reload()
        if self._on_change is not None:
            self._on_change()
