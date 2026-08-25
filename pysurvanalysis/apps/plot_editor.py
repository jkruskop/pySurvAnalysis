"""The Plot Editor — curate Publication Figures for one Experiment Directory.

Experiment-level, not project-level: with no pooling there is no pooled figure,
so figures belong to a member and the editor opens one (ADR-0005). Specs are
saved into the experiment's ``plot_specs.yaml``; Styles are saved up into the
Project's, where every member's figures share them.

Presentation only — it never touches ``survival_config.yaml``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..gui_env import sanitize_input_method_environment

## Before Qt is imported, not after: the overrides are read when the
## platform plugin initialises.
sanitize_input_method_environment()

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import pubfigures as pf
from ..domain import Project, SurvivalExperiment, is_project_dir
from ..ui import ActionButton, Card, Category, OutputLog, TopBar, apply_theme, icon
from ..ui import settings as ui_settings


class PlotEditorWindow(QMainWindow):
    """Live preview of one Spec+Style, and the two Save buttons behind it."""

    def __init__(self, experiment: SurvivalExperiment) -> None:
        super().__init__()
        self.experiment = experiment
        self.setWindowTitle(f"Plot Editor — {experiment.name}")
        self.resize(1200, 820)

        self._specs = pf.specs_for(experiment)
        self._styles, self._default_style = pf.load_styles(
            experiment.project.directory if experiment.project else None)
        self._lifetables = None
        self._current_id = (experiment.type.headline_plot_id
                            if experiment.type.headline_plot_id in self._specs
                            else next(iter(self._specs), None))

        self._build_ui()
        self._load_spec_into_form()
        self._refresh_preview()

    # ── construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(8)

        bar = TopBar(f"Plot Editor — {self.experiment.name}")
        save_spec = QPushButton(icon("save"), " Save spec")
        save_spec.clicked.connect(self._save_spec)
        save_style = QPushButton(icon("save_as"), " Save style to project")
        save_style.clicked.connect(self._save_style)
        export = QPushButton(icon("figures"), " Export…")
        export.clicked.connect(self._export)
        for btn in (save_spec, save_style, export):
            bar.add_right(btn)
        outer.addWidget(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        side = QWidget()
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 0, 0)
        side_lay.setSpacing(10)
        side_lay.addWidget(self._build_spec_card())
        side_lay.addWidget(self._build_style_card())
        side_lay.addStretch(1)
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setWidget(side)
        side_scroll.setMinimumWidth(380)
        splitter.addWidget(side_scroll)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        self._preview = QLabel("No preview yet.")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumSize(600, 420)
        right_lay.addWidget(self._preview, 1)
        self._log = OutputLog()
        self._log.setMaximumHeight(150)
        right_lay.addWidget(self._log)
        splitter.addWidget(right)
        splitter.setSizes([400, 800])
        outer.addWidget(splitter, 1)

    def _build_spec_card(self) -> Card:
        card = Card("Figure", Category.PLOTS, icon_name="plot",
                    subtitle="Content decisions — saved to this experiment's "
                             "plot_specs.yaml.")
        form = QFormLayout()

        self._plot_combo = QComboBox()
        self._plot_combo.addItems(list(self._specs))
        if self._current_id:
            self._plot_combo.setCurrentText(self._current_id)
        self._plot_combo.currentTextChanged.connect(self._on_plot_changed)
        form.addRow("Figure:", self._plot_combo)

        self._title_edit = QLineEdit()
        self._x_label = QLineEdit()
        self._y_label = QLineEdit()
        self._series_label = QLineEdit()
        self._facet_by = QLineEdit()
        for label, widget in (("Title:", self._title_edit),
                              ("X label:", self._x_label),
                              ("Y label:", self._y_label),
                              ("Legend title:", self._series_label),
                              ("Facet by:", self._facet_by)):
            widget.editingFinished.connect(self._refresh_preview)
            form.addRow(label, widget)

        self._reference_line = QDoubleSpinBox()
        self._reference_line.setRange(-1.0, 1.0)
        self._reference_line.setSingleStep(0.05)
        self._reference_line.setSpecialValueText("none")
        self._reference_line.setValue(-1.0)
        self._reference_line.valueChanged.connect(self._refresh_preview)
        form.addRow("Reference line:", self._reference_line)

        self._style_combo = QComboBox()
        self._style_combo.addItems(list(self._styles))
        self._style_combo.currentTextChanged.connect(self._on_style_changed)
        form.addRow("Style:", self._style_combo)

        card.add_body(form)
        return card

    def _build_style_card(self) -> Card:
        card = Card("Style", Category.PLOTS, icon_name="config",
                    subtitle="The shared look — saved up to the Project so "
                             "every member's figures match.")
        form = QFormLayout()

        self._width = QDoubleSpinBox(); self._width.setRange(40, 400)
        self._height = QDoubleSpinBox(); self._height.setRange(30, 400)
        for widget, label in ((self._width, "Width (mm):"),
                              (self._height, "Height (mm):")):
            widget.valueChanged.connect(self._refresh_preview)
            form.addRow(label, widget)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(list(pf.THEMES))
        self._theme_combo.currentTextChanged.connect(self._refresh_preview)
        form.addRow("Theme:", self._theme_combo)

        self._base_size = QDoubleSpinBox(); self._base_size.setRange(5, 24)
        self._base_size.valueChanged.connect(self._refresh_preview)
        form.addRow("Base font size:", self._base_size)

        self._line_width = QDoubleSpinBox(); self._line_width.setRange(0.2, 5.0)
        self._line_width.setSingleStep(0.1)
        self._line_width.valueChanged.connect(self._refresh_preview)
        form.addRow("Line width:", self._line_width)

        self._censor_ticks = QCheckBox("Censor ticks")
        self._ci_band = QCheckBox("95% CI bands")
        self._risk_table = QCheckBox("At-risk band below the curves")
        for box in (self._censor_ticks, self._ci_band, self._risk_table):
            box.stateChanged.connect(self._refresh_preview)
            form.addRow("", box)

        self._legend_pos = QComboBox()
        self._legend_pos.addItems(["right", "left", "top", "bottom", "none"])
        self._legend_pos.currentTextChanged.connect(self._refresh_preview)
        form.addRow("Legend:", self._legend_pos)

        card.add_body(form)

        row = QHBoxLayout()
        refresh = ActionButton("Refresh preview", Category.PLOTS, icon_name="refresh")
        refresh.clicked.connect(self._refresh_preview)
        row.addWidget(refresh)
        card.add_body(row)
        return card

    # ── state <-> form ─────────────────────────────────────────────────────

    @property
    def spec(self) -> pf.PlotSpec | None:
        return self._specs.get(self._current_id) if self._current_id else None

    @property
    def style(self) -> pf.PlotStyle:
        return self._styles.get(self._style_combo.currentText(), pf.BUILTIN_STYLE)

    def _load_spec_into_form(self) -> None:
        spec = self.spec
        if spec is None:
            return
        for widget, value in ((self._title_edit, spec.title),
                              (self._x_label, spec.x_label),
                              (self._y_label, spec.y_label),
                              (self._series_label, spec.series_label),
                              (self._facet_by, spec.facet_by)):
            widget.blockSignals(True)
            widget.setText(value)
            widget.blockSignals(False)
        self._reference_line.blockSignals(True)
        self._reference_line.setValue(
            spec.reference_line if spec.reference_line is not None else -1.0)
        self._reference_line.blockSignals(False)
        self._style_combo.blockSignals(True)
        self._style_combo.setCurrentText(
            spec.style if spec.style in self._styles else self._default_style)
        self._style_combo.blockSignals(False)
        self._load_style_into_form()

    def _load_style_into_form(self) -> None:
        style = self.style
        for widget, value in ((self._width, style.width_mm),
                              (self._height, style.height_mm),
                              (self._base_size, style.base_size),
                              (self._line_width, style.line_width)):
            widget.blockSignals(True)
            widget.setValue(float(value))
            widget.blockSignals(False)
        for widget, value in ((self._censor_ticks, style.censor_ticks),
                              (self._ci_band, style.ci_band),
                              (self._risk_table, style.risk_table)):
            widget.blockSignals(True)
            widget.setChecked(bool(value))
            widget.blockSignals(False)
        for combo, value in ((self._theme_combo, style.theme),
                             (self._legend_pos, style.legend_position)):
            combo.blockSignals(True)
            combo.setCurrentText(value)
            combo.blockSignals(False)

    def _harvest(self) -> tuple[pf.PlotSpec, pf.PlotStyle]:
        """Read the form back into the live Spec and Style objects."""
        spec = self.spec
        style = self.style
        if spec is not None:
            spec.title = self._title_edit.text()
            spec.x_label = self._x_label.text()
            spec.y_label = self._y_label.text()
            spec.series_label = self._series_label.text()
            spec.facet_by = self._facet_by.text()
            ref = self._reference_line.value()
            spec.reference_line = None if ref <= -0.999 else ref
            spec.style = self._style_combo.currentText()
        style.width_mm = self._width.value()
        style.height_mm = self._height.value()
        style.theme = self._theme_combo.currentText()
        style.base_size = self._base_size.value()
        style.line_width = self._line_width.value()
        style.censor_ticks = self._censor_ticks.isChecked()
        style.ci_band = self._ci_band.isChecked()
        style.risk_table = self._risk_table.isChecked()
        style.legend_position = self._legend_pos.currentText()
        return spec, style

    # ── preview ────────────────────────────────────────────────────────────

    def _on_plot_changed(self, plot_id: str) -> None:
        self._current_id = plot_id
        self._load_spec_into_form()
        self._refresh_preview()

    def _on_style_changed(self, _name: str) -> None:
        self._load_style_into_form()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        spec, style = self._harvest()
        if spec is None:
            self._preview.setText("This experiment has no publication figures.")
            return
        try:
            if self._lifetables is None:
                self._lifetables = pf._load_lifetables(self.experiment)
            g = pf.build_ggplot(pf.curve_data(self._lifetables, spec), spec, style)
            data = pf.render_png_bytes(g, style)
        except Exception as exc:  # noqa: BLE001 - a bad spec shows, never crashes
            self._preview.setText(f"Preview failed:\n{exc}")
            self._log.append_line(f"Preview failed: {exc}")
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self._preview.setPixmap(pixmap.scaled(
            self._preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    # ── saving ─────────────────────────────────────────────────────────────

    def _save_spec(self) -> None:
        self._harvest()
        path = pf.save_specs(self.experiment.directory, self._specs)
        self._log.append_line(f"Saved specs to {path}")

    def _save_style(self) -> None:
        self._harvest()
        project = self.experiment.project
        if project is None:
            if is_project_dir(self.experiment.directory.parent):
                project = Project(self.experiment.directory.parent)
            else:
                QMessageBox.information(
                    self, "Plot Editor",
                    "Styles are shared by a Project, and this is a standalone "
                    "experiment. Saving the style to the experiment's own "
                    "plot_specs.yaml instead.")
                pf.save_styles(self.experiment.directory, self._styles,
                               self._style_combo.currentText())
                return
        path = pf.save_styles(project.directory, self._styles,
                              self._style_combo.currentText())
        self._log.append_line(f"Saved styles to {path} — every member's figures "
                              f"use them.")

    def _export(self) -> None:
        spec, style = self._harvest()
        if spec is None:
            return
        default = self.experiment.figures_dir / f"{spec.plot_id}.svg"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export figure", str(default),
            "Vector (*.svg *.pdf);;Raster (*.png)")
        if not path:
            return
        try:
            g = pf.build_ggplot(pf.curve_data(self._lifetables, spec), spec, style)
            written = pf.save_figure(g, path, style)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Plot Editor", f"Export failed: {exc}")
            return
        self._log.append_line(f"Exported {written}")


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app, ui_settings.get("theme", "auto"))
    if len(sys.argv) < 2:
        print("usage: pysurv-plots <experiment-directory>")
        sys.exit(2)
    directory = Path(sys.argv[1]).resolve()
    project = Project(directory.parent) if is_project_dir(directory.parent) else None
    experiment = SurvivalExperiment(
        directory, defaults=project.defaults if project else {}, project=project)
    window = PlotEditorWindow(experiment)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
