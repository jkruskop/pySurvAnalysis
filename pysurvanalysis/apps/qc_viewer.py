"""QC Viewer — chamber-overlay KM panels with hover identification.

For each treatment, draws all chambers' KM curves on one panel as
translucent lines. mplcursors hover annotations reveal the chamber id of
the line under the cursor; clicking a line toggles its excluded state.
"Save Exclusions…" persists the current state to ``remove_chambers.csv``
under a user-named group.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("QtAgg")  # noqa: E402

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import data_loader, exclusions, lifetable, plotting
from ..ui import ActionButton, Category, TopBar, apply_theme, icon, resolved_mode
from ..ui import settings as ui_settings


class _ChamberPanel(QWidget):
    """One tab in the QC viewer: KM overlay for a single treatment."""

    def __init__(
        self,
        per_chamber_lt,
        treatment: str,
        excluded: set,
        on_toggle,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._treatment = treatment
        self._excluded = set(excluded)
        self._on_toggle = on_toggle
        self._per_chamber_lt = per_chamber_lt

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._fig = plotting.plot_chamber_overlay_km(
            per_chamber_lt, treatment, excluded_chambers=self._excluded,
        )
        self._canvas = FigureCanvasQTAgg(self._fig)
        toolbar = NavigationToolbar2QT(self._canvas, self)
        outer.addWidget(toolbar)
        outer.addWidget(self._canvas, 1)

        self._wire_hover_and_click()

    def _wire_hover_and_click(self) -> None:
        try:
            import mplcursors

            cursor = mplcursors.cursor(self._fig, hover=True)

            @cursor.connect("add")
            def _on_add(sel):  # noqa: ANN001
                gid = sel.artist.get_gid() or ""
                label = sel.artist.get_label() or gid
                sel.annotation.set_text(label)
                sel.annotation.get_bbox_patch().set(alpha=0.85)

            self._mpl_cursor = cursor
        except Exception:  # noqa: BLE001
            pass

        self._canvas.mpl_connect("pick_event", self._on_pick)
        for ax in self._fig.axes:
            for line in ax.get_lines():
                line.set_picker(5)

    def _on_pick(self, event) -> None:  # noqa: ANN001
        gid = event.artist.get_gid() or ""
        if not gid.startswith("chamber-"):
            return
        chamber_str = gid.split("-", 1)[1]
        chamber: object
        try:
            chamber = int(chamber_str)
        except ValueError:
            chamber = chamber_str
        if chamber in self._excluded:
            self._excluded.discard(chamber)
        else:
            self._excluded.add(chamber)
        self._on_toggle(chamber, chamber in self._excluded)
        self._restyle()

    def update_excluded(self, excluded: set) -> None:
        self._excluded = set(excluded)
        self._restyle()

    def _restyle(self) -> None:
        for ax in self._fig.axes:
            for line in ax.get_lines():
                gid = line.get_gid() or ""
                if not gid.startswith("chamber-"):
                    continue
                chamber_str = gid.split("-", 1)[1]
                try:
                    cham_val = int(chamber_str)
                except ValueError:
                    cham_val = chamber_str
                if cham_val in self._excluded:
                    line.set_color("#dc2626")
                    line.set_linestyle("--")
                    line.set_alpha(0.7)
                else:
                    line.set_color("#1f77b4")
                    line.set_linestyle("-")
                    line.set_alpha(0.4)
        self._canvas.draw_idle()


class QcViewerWindow(QMainWindow):
    """QC Viewer main window."""

    def __init__(self, project_dir: str | Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("pySurvAnalysis — QC Viewer")
        self.resize(1300, 820)

        self._project_dir: Path | None = None
        self._data = None
        self._per_chamber_lt = None
        self._panels: dict[str, _ChamberPanel] = {}
        self._excluded: set = set()

        self._build_ui()

        if project_dir is not None:
            self._set_project(Path(project_dir))

    # --------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._top_bar = TopBar("pySurvAnalysis — QC Viewer")
        save_btn = ActionButton(
            "Save Exclusions…", Category.LOAD, icon_name="save", primary=True,
        )
        save_btn.clicked.connect(self._save_exclusions)
        self._top_bar.add_right(save_btn)

        self._btn_theme = QToolButton()
        self._btn_theme.setIcon(
            icon("theme_dark" if resolved_mode() == "light" else "theme_light")
        )
        self._btn_theme.setIconSize(QSize(18, 18))
        self._btn_theme.setAutoRaise(True)
        self._btn_theme.setToolTip("Toggle light / dark theme")
        self._btn_theme.clicked.connect(self._toggle_theme)
        self._top_bar.add_right(self._btn_theme)
        outer.addWidget(self._top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        side = QWidget()
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(12, 12, 12, 12)
        side_lay.setSpacing(8)
        side.setMinimumWidth(280)
        side.setMaximumWidth(380)

        side_lay.addWidget(QLabel("Project"))
        self._proj_label = QLabel("(no project)")
        self._proj_label.setStyleSheet("color: palette(mid); font-style: italic;")
        side_lay.addWidget(self._proj_label)

        pick_btn = QPushButton("Pick project…")
        pick_btn.clicked.connect(self._pick_project)
        side_lay.addWidget(pick_btn)

        side_lay.addWidget(QLabel("Active exclusion group"))
        self._group_combo = QComboBox()
        self._group_combo.setEditable(True)
        self._group_combo.currentTextChanged.connect(self._on_group_changed)
        side_lay.addWidget(self._group_combo)

        side_lay.addWidget(QLabel("Excluded chambers"))
        self._exc_list = QListWidget()
        self._exc_list.itemDoubleClicked.connect(self._on_exc_double_click)
        side_lay.addWidget(self._exc_list, 1)

        bar = QHBoxLayout()
        clear_btn = QPushButton("Clear all")
        clear_btn.clicked.connect(self._clear_all)
        side_lay.addWidget(clear_btn)
        side_lay.addLayout(bar)

        splitter.addWidget(side)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._placeholder = QLabel(
            "Pick a project, then load.\n\n"
            "Each tab shows one treatment with all chambers' KM curves overlaid. "
            "Hover a curve to see its chamber id; click a curve to toggle the "
            "chamber's exclusion."
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: palette(mid); font-style: italic;")
        self._tabs.addTab(self._placeholder, "QC")
        splitter.addWidget(self._tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 980])
        outer.addWidget(splitter, 1)

    # ------------------------------------------------------------ project

    def _pick_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pick project directory")
        if path:
            self._set_project(Path(path))

    def _set_project(self, path: Path) -> None:
        path = path.expanduser().resolve()
        if not path.is_dir():
            QMessageBox.warning(self, "Not a directory", f"{path} is not a directory.")
            return
        self._project_dir = path
        self._proj_label.setText(str(path))
        # Populate group combo
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        for g in exclusions.list_groups(path):
            self._group_combo.addItem(g)
        if self._group_combo.count() == 0:
            self._group_combo.addItem("default")
        self._group_combo.blockSignals(False)
        self._excluded = set(exclusions.chambers_for_group(path, self._group_combo.currentText().strip()))
        self._reload_data()

    def _on_group_changed(self, group: str) -> None:
        if self._project_dir is None:
            return
        self._excluded = set(
            exclusions.chambers_for_group(self._project_dir, group.strip())
        )
        self._refresh_excluded_list()
        for panel in self._panels.values():
            panel.update_excluded(self._excluded)

    def _reload_data(self) -> None:
        if self._project_dir is None:
            return
        # An Experiment Directory names its own data file (config first, then
        # data/, then the root); a bare folder still gets the old glob.
        path: Path | None = None
        try:
            from ..domain import SurvivalExperiment, is_experiment_dir

            if is_experiment_dir(self._project_dir):
                path = SurvivalExperiment(self._project_dir).data_file()
        except Exception:  # noqa: BLE001 - fall through to the glob
            path = None
        if path is None:
            for base in (self._project_dir / "data", self._project_dir):
                for pattern in ("*.xlsx", "*.csv", "*.tsv"):
                    files = sorted(base.glob(pattern)) if base.is_dir() else []
                    if files:
                        path = files[0]
                        break
                if path is not None:
                    break
        if path is None:
            QMessageBox.warning(
                self, "No data",
                "No .xlsx, .csv, or .tsv file found in this directory or its "
                "data/ subdirectory.",
            )
            return
        try:
            # QC needs to see *every* chamber so the user can choose which to
            # exclude — so we never pre-drop chambers here. The data file's
            # Design sheet (Excel) is the authoritative source for the
            # experimental factor names; CSV inputs auto-detect.
            self._data, _factors = data_loader.load_experiment(
                path, excluded_chambers=set(),
            )
        except Exception as err:  # noqa: BLE001
            QMessageBox.warning(self, "Load failed", str(err))
            return

        if "chamber" not in self._data.columns or self._data["chamber"].astype(str).eq("N/A").all():
            QMessageBox.information(
                self, "No chambers",
                "The loaded data does not have chamber-level information "
                "(e.g. CSV inputs). The QC viewer only applies to Excel files "
                "with a per-chamber Design sheet.",
            )
            return

        self._per_chamber_lt = lifetable.compute_lifetables_per_chamber(self._data)
        self._build_panels()
        self._refresh_excluded_list()

    def _build_panels(self) -> None:
        # Remove placeholder + any old panels
        while self._tabs.count():
            w = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if w is not None:
                w.deleteLater()
        self._panels.clear()
        if self._per_chamber_lt is None or len(self._per_chamber_lt) == 0:
            return
        treatments = sorted(self._per_chamber_lt["treatment"].unique())
        for treatment in treatments:
            panel = _ChamberPanel(
                self._per_chamber_lt, treatment,
                self._excluded, self._on_panel_toggle, parent=self._tabs,
            )
            self._panels[treatment] = panel
            self._tabs.addTab(panel, treatment)

    # ------------------------------------------------------------ actions

    def _on_panel_toggle(self, chamber, is_excluded: bool) -> None:
        if is_excluded:
            self._excluded.add(chamber)
        else:
            self._excluded.discard(chamber)
        # Sync siblings
        for panel in self._panels.values():
            panel.update_excluded(self._excluded)
        self._refresh_excluded_list()

    def _refresh_excluded_list(self) -> None:
        self._exc_list.clear()
        try:
            sorted_items = sorted(self._excluded, key=lambda x: (isinstance(x, str), x))
        except TypeError:
            sorted_items = sorted(self._excluded, key=str)
        for chamber in sorted_items:
            QListWidgetItem(f"Chamber {chamber}", self._exc_list)

    def _on_exc_double_click(self, item: QListWidgetItem) -> None:
        text = item.text()
        if not text.startswith("Chamber "):
            return
        chamber_str = text[len("Chamber "):]
        try:
            chamber = int(chamber_str)
        except ValueError:
            chamber = chamber_str
        self._excluded.discard(chamber)
        self._refresh_excluded_list()
        for panel in self._panels.values():
            panel.update_excluded(self._excluded)

    def _clear_all(self) -> None:
        self._excluded = set()
        self._refresh_excluded_list()
        for panel in self._panels.values():
            panel.update_excluded(self._excluded)

    def _save_exclusions(self) -> None:
        if self._project_dir is None:
            return
        group, ok = QInputDialog.getText(
            self, "Save Exclusions",
            "Save exclusions as group:",
            text=self._group_combo.currentText().strip() or "default",
        )
        if not ok or not group.strip():
            return
        path = exclusions.write_exclusions(self._project_dir, group.strip(), sorted(self._excluded, key=str))
        QMessageBox.information(
            self, "Saved",
            f"Saved {len(self._excluded)} chamber(s) to {path.name} (group '{group.strip()}').",
        )
        # Refresh group combo to include the new group
        cur = self._group_combo.currentText()
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        for g in exclusions.list_groups(self._project_dir):
            self._group_combo.addItem(g)
        idx = self._group_combo.findText(cur)
        if idx >= 0:
            self._group_combo.setCurrentIndex(idx)
        else:
            self._group_combo.setEditText(cur)
        self._group_combo.blockSignals(False)

    def _toggle_theme(self) -> None:
        new_mode = "light" if resolved_mode() == "dark" else "dark"
        ui_settings.set_value("theme", new_mode)
        QMessageBox.information(
            self, "Theme changed",
            "Theme preference saved. Restart the app to apply."
        )


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, ui_settings.get("theme", "auto"))
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    win = QcViewerWindow(initial)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
