"""Visual Script Editor: palette / canvas / inspector / preview, level-aware.

One canvas and one YAML splicer serve three script sets:

* **Experiment scripts** — an Experiment Directory's ``survival_config.yaml``
  ``scripts:``, whose palette is ``core ∪ type`` for that experiment's type;
* **Project scripts** — ``project.yaml`` ``scripts:``, over the separate
  project-action registry; and
* **Central experiment scripts** — ``project.yaml`` ``experiment_scripts:``,
  one recipe serving every member.

The levels cannot mix: switching the level switches the registry, and a step
naming an action outside the active registry is a hard error (ADR-0002).
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from ..gui_env import sanitize_input_method_environment

## Before Qt is imported, not after: the overrides are read when the
## platform plugin initialises.
sanitize_input_method_environment()

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import yaml

from ..domain import config as cfgmod
from ..domain import is_experiment_dir, is_project_dir
from ..ui import ActionButton, Category, TopBar, icon, resolved_mode
from ..ui import settings as ui_settings
from . import project_actions
from .actions import POOL, registry_for, validate_steps
from .canvas import Canvas
from .inspector import Inspector
from .palette import Palette


#: level key → (label, target file, yaml section)
LEVELS = {
    "experiment": ("Experiment scripts", cfgmod.CONFIG_FILENAME, "scripts"),
    "project": ("Project scripts", cfgmod.PROJECT_FILENAME, "scripts"),
    "central": ("Central experiment scripts", cfgmod.PROJECT_FILENAME,
                "experiment_scripts"),
}


class ScriptEditorWindow(QMainWindow):
    """Edit the saved scripts of an Experiment Directory or a Project."""

    scriptsSaved = pyqtSignal(str)  # absolute YAML path

    def __init__(
        self,
        project_dir: str | Path,
        factors: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("pySurvAnalysis — Script Editor")
        self.resize(1280, 780)

        self._directory = Path(project_dir)
        self._project_dir = self._directory  # kept: callers pass either level
        self._factors = list(factors or [])
        self._dirty = False
        self._experiment = None
        self._project = None
        self._resolve_context()

        self._level = ("experiment" if self._experiment is not None else "project")
        self._scripts: list[dict] = self._read_scripts(self._level)
        self._active_idx = 0 if self._scripts else -1

        self._build_ui()
        self._load_active_script()

    # ------------------------------------------------------------- context

    def _resolve_context(self) -> None:
        """Work out which of an Experiment Directory / Project we are editing."""
        from ..domain import Project, SurvivalExperiment

        d = self._directory
        if is_project_dir(d):
            self._project = Project(d)
        elif is_experiment_dir(d):
            parent = Project(d.parent) if is_project_dir(d.parent) else None
            self._project = parent
            self._experiment = SurvivalExperiment(
                d, defaults=parent.defaults if parent else {}, project=parent)
            if not self._factors:
                self._factors = list(
                    (self._experiment.config.get("factors") or {}))

    def _available_levels(self) -> list[str]:
        levels = []
        if self._experiment is not None:
            levels.append("experiment")
        if self._project is not None:
            levels.extend(["project", "central"])
        return levels or ["experiment"]

    def _registry(self) -> dict:
        if self._level == "project":
            return project_actions.PROJECT_ACTIONS
        exp_type = self._experiment.type if self._experiment is not None else None
        if self._level == "central" and exp_type is None and self._project is not None:
            exp_type = self._project.type
        return registry_for(exp_type)

    def _target_path(self, level: str | None = None) -> Path:
        level = level or self._level
        _label, filename, _section = LEVELS[level]
        if level == "experiment" and self._experiment is not None:
            base = self._experiment.directory
        elif self._project is not None:
            base = self._project.directory
        else:
            base = self._directory
        return base / filename

    def _read_scripts(self, level: str) -> list[dict]:
        _label, _filename, section = LEVELS[level]
        data = cfgmod.read_yaml(self._target_path(level))
        return [deepcopy(s) for s in cfgmod.scripts_of(data, section)]

    # --------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._top_bar = TopBar(f"Script Editor — {self._project_dir.name}")
        save_btn = ActionButton("Save", Category.LOAD, icon_name="save", primary=True)
        save_btn.clicked.connect(self._save)
        new_btn = ActionButton("+ New script", Category.SCRIPTS, icon_name="add")
        new_btn.clicked.connect(self._new_script)
        del_btn = ActionButton("− Delete script", Category.QC, icon_name="delete")
        del_btn.clicked.connect(self._delete_script)
        self._top_bar.add_right(new_btn)
        self._top_bar.add_right(del_btn)
        self._top_bar.add_right(save_btn)
        outer.addWidget(self._top_bar)

        # Level switcher + scripts dropdown + name editor
        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(12, 8, 12, 8)
        ctrl_row.addWidget(QLabel("Level:"))
        self._level_combo = QComboBox()
        for key in self._available_levels():
            self._level_combo.addItem(LEVELS[key][0], key)
        self._level_combo.setCurrentText(LEVELS[self._level][0])
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        ctrl_row.addWidget(self._level_combo)
        ctrl_row.addSpacing(16)
        ctrl_row.addWidget(QLabel("Active script:"))
        self._scripts_combo = QComboBox()
        self._scripts_combo.setMinimumWidth(240)
        self._scripts_combo.currentIndexChanged.connect(self._on_script_selected)
        ctrl_row.addWidget(self._scripts_combo)
        rename = ActionButton("Rename…", Category.TOOLS, icon_name="config")
        rename.clicked.connect(self._rename_active)
        ctrl_row.addWidget(rename)
        check = ActionButton("Validate", Category.TOOLS, icon_name="validate")
        check.clicked.connect(self._validate_active)
        ctrl_row.addWidget(check)
        ctrl_row.addStretch(1)
        self._context_lbl = QLabel("")
        ctrl_row.addWidget(self._context_lbl)
        outer.addLayout(ctrl_row)

        # Three-pane horizontal splitter, with preview underneath
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.setChildrenCollapsible(False)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.setChildrenCollapsible(False)

        self._palette = Palette(self._registry())
        self._palette.actionRequested.connect(self._on_action_added)
        h_splitter.addWidget(self._palette)

        self._canvas = Canvas()
        self._canvas.stepsChanged.connect(self._on_steps_changed)
        self._canvas.stepSelected.connect(self._on_step_selected)
        h_splitter.addWidget(self._canvas)

        self._inspector = Inspector(self._factors)
        self._inspector.stepEdited.connect(self._on_step_edited)
        h_splitter.addWidget(self._inspector)

        h_splitter.setSizes([240, 540, 360])
        v_splitter.addWidget(h_splitter)

        # YAML preview at bottom
        preview_host = QWidget()
        preview_lay = QVBoxLayout(preview_host)
        preview_lay.setContentsMargins(8, 4, 8, 4)
        preview_lay.addWidget(QLabel("Live YAML preview"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(220)
        self._preview.setStyleSheet(
            'QPlainTextEdit { font-family: "JetBrains Mono", "Menlo", "Consolas", monospace; '
            'font-size: 10pt; }'
        )
        preview_lay.addWidget(self._preview)
        v_splitter.addWidget(preview_host)
        v_splitter.setSizes([540, 220])

        outer.addWidget(v_splitter, 1)
        self._refresh_scripts_combo()
        self._refresh_context_label()

    # -------------------------------------------------------- script ops

    def _refresh_scripts_combo(self) -> None:
        self._scripts_combo.blockSignals(True)
        self._scripts_combo.clear()
        for s in self._scripts:
            self._scripts_combo.addItem(s.get("name", "(unnamed)"))
        if self._active_idx >= 0:
            self._scripts_combo.setCurrentIndex(self._active_idx)
        self._scripts_combo.blockSignals(False)

    def _on_script_selected(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._scripts):
            return
        self._active_idx = idx
        self._load_active_script()

    def _load_active_script(self) -> None:
        if self._active_idx < 0 or self._active_idx >= len(self._scripts):
            self._canvas.set_steps([])
            self._update_preview()
            return
        script = self._scripts[self._active_idx]
        self._canvas.set_steps(list(script.get("steps") or []))
        self._update_preview()

    def _new_script(self) -> None:
        name, ok = QInputDialog.getText(self, "New script", "Name:")
        if not ok or not name.strip():
            return
        self._scripts.append({"name": name.strip(), "steps": []})
        self._active_idx = len(self._scripts) - 1
        self._dirty = True
        self._refresh_scripts_combo()
        self._load_active_script()

    def _delete_script(self) -> None:
        if self._active_idx < 0:
            return
        ans = QMessageBox.question(
            self, "Delete script",
            f"Delete '{self._scripts[self._active_idx].get('name')}'?",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        del self._scripts[self._active_idx]
        self._active_idx = min(self._active_idx, len(self._scripts) - 1)
        self._dirty = True
        self._refresh_scripts_combo()
        self._load_active_script()

    def _rename_active(self) -> None:
        if self._active_idx < 0:
            return
        cur = self._scripts[self._active_idx].get("name", "")
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=cur)
        if not ok or not name.strip():
            return
        self._scripts[self._active_idx]["name"] = name.strip()
        self._dirty = True
        self._refresh_scripts_combo()
        self._update_preview()

    # -------------------------------------------------------- canvas/inspector

    def _on_action_added(self, action_key: str) -> None:
        if self._active_idx < 0:
            QMessageBox.information(self, "No script", "Create a script first (+ New script).")
            return
        action = self._registry().get(action_key)
        if action is None:
            return
        # Build a step with default param values
        step: dict = {"action": action_key}
        for spec in action.params:
            if spec.default is not None:
                step[spec.name] = spec.default
        self._canvas.append_step(step)
        self._dirty = True

    def _on_steps_changed(self, steps: list[dict]) -> None:
        if self._active_idx < 0:
            return
        self._scripts[self._active_idx]["steps"] = list(steps)
        self._dirty = True
        self._update_preview()

    def _on_step_selected(self, idx: int, step: dict) -> None:
        action = self._registry().get(step.get("action", "")) if step else None
        self._inspector.show_step(idx, action, step or {})

    def _on_step_edited(self, idx: int, step: dict) -> None:
        if self._active_idx < 0:
            return
        steps = list(self._scripts[self._active_idx].get("steps") or [])
        if 0 <= idx < len(steps):
            steps[idx] = step
            self._scripts[self._active_idx]["steps"] = steps
            self._canvas.set_steps(steps, keep_selection=idx)
            self._dirty = True
            self._update_preview()

    def _on_level_changed(self, _idx: int) -> None:
        if self._dirty and not self._confirm_discard():
            self._level_combo.blockSignals(True)
            self._level_combo.setCurrentText(LEVELS[self._level][0])
            self._level_combo.blockSignals(False)
            return
        self._level = self._level_combo.currentData()
        self._scripts = self._read_scripts(self._level)
        self._active_idx = 0 if self._scripts else -1
        self._dirty = False
        self._palette.set_actions(self._registry())
        self._refresh_scripts_combo()
        self._refresh_context_label()
        self._load_active_script()

    def _confirm_discard(self) -> bool:
        return QMessageBox.question(
            self, "Unsaved changes",
            "Switching level discards unsaved edits. Continue?"
        ) == QMessageBox.StandardButton.Yes

    def _refresh_context_label(self) -> None:
        target = self._target_path()
        if self._level == "project":
            detail = "project action registry"
        else:
            exp_type = (self._experiment.type if self._experiment is not None
                        else (self._project.type if self._project else None))
            detail = f"core ∪ {getattr(exp_type, 'label', 'Custom Experiment')}"
        self._context_lbl.setText(f"{target.name} · {detail}")

    def _validate_active(self) -> None:
        steps = self._canvas.steps()
        if self._level == "project":
            problems = project_actions.validate_project_steps(steps)
        else:
            exp_type = (self._experiment.type if self._experiment is not None
                        else (self._project.type if self._project else None))
            problems = validate_steps(steps, exp_type)
        if problems:
            QMessageBox.warning(
                self, "Script will not run",
                "A step names an action this level does not provide, so the "
                "script would refuse to start:\n\n  - " + "\n  - ".join(problems))
        else:
            QMessageBox.information(self, "Validate",
                                    "Every step resolves — this script will run.")

    def _update_preview(self) -> None:
        _label, _filename, section = LEVELS[self._level]
        scripts_view = {section: self._scripts}
        try:
            text = yaml.safe_dump(scripts_view, sort_keys=False, indent=2, default_flow_style=False)
        except Exception as err:  # noqa: BLE001
            text = f"# could not serialize: {err}"
        self._preview.setPlainText(text)

    # ------------------------------------------------------------- IO

    def _save(self) -> None:
        """Splice this level's section into its file, other keys untouched."""
        _label, _filename, section = LEVELS[self._level]
        path = self._target_path()
        data = cfgmod.read_yaml(path)
        data[section] = deepcopy(self._scripts)
        cfgmod.write_yaml(path, data)
        self._dirty = False
        self.scriptsSaved.emit(str(path))
        QMessageBox.information(
            self, "Saved",
            f"Wrote {len(self._scripts)} script(s) to {path} under `{section}:`.")
