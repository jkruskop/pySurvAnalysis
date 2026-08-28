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

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
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


#: Bounds on the preview's render resolution. The floor keeps a figure legible
#: in a small window; the ceiling stops a maximised window on a 4K screen from
#: rasterising a 3000px image nobody can see the extra detail in.
_PREVIEW_MIN_DPI = 96
_PREVIEW_MAX_DPI = 400


class ColorButton(QPushButton):
    """A small swatch; clicking opens a colour dialog.

    The dialog exposes the alpha channel because two of the values here are
    legitimately not colours: full transparency stores ``"none"``
    (matplotlib's transparent, which is how a hollow point is asked for), and
    partial alpha stores an ``#rrggbbaa`` hex. Both render.
    """

    changed = pyqtSignal()

    def __init__(self, color: str = "#4C72B0", parent=None,
                 auto_text: str = "auto") -> None:
        super().__init__(parent)
        self.setFixedSize(44, 22)
        self._auto_text = auto_text
        self._color = ""
        self.set_color(color)
        self.clicked.connect(self._pick)

    def color(self) -> str:
        return self._color

    def _qcolor(self) -> QColor:
        value = self._color
        if value in ("", "none"):
            return QColor(0, 0, 0, 0)
        if len(value) == 9:                      # matplotlib #rrggbbaa
            return QColor(int(value[1:3], 16), int(value[3:5], 16),
                          int(value[5:7], 16), int(value[7:9], 16))
        return QColor(value)

    def set_color(self, color: str) -> None:
        self._color = str(color or "")
        if self._color in ("", "none"):
            self.setText(self._auto_text if self._color == "" else "none")
            self.setStyleSheet(
                "QPushButton { background: palette(base); color: palette(mid);"
                " border: 1px dashed palette(mid); border-radius: 3px;"
                " font-size: 7pt; }")
            return
        self.setText("")
        c = self._qcolor()
        self.setStyleSheet(
            f"QPushButton {{ background: rgba({c.red()},{c.green()},"
            f"{c.blue()},{c.alpha()}); border: 1px solid palette(mid); "
            f"border-radius: 3px; }}")

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(
            self._qcolor(), self, "Pick colour (alpha 0 = transparent)",
            QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not chosen.isValid():
            return
        alpha = chosen.alpha()
        if alpha == 0:
            self.set_color("none")
        elif alpha < 255:
            self.set_color(f"#{chosen.red():02x}{chosen.green():02x}"
                           f"{chosen.blue():02x}{alpha:02x}")
        else:
            self.set_color(chosen.name())
        self.changed.emit()


## Wheel-transparent controls. Ignoring the wheel makes Qt bubble the event up
## to the scroll area, so scrolling this long options panel never silently
## edits whichever spinbox the cursor happened to be over.
class _NoWheelSpin(QDoubleSpinBox):
    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        event.ignore()


class _NoWheelCombo(QComboBox):
    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        event.ignore()


class _NoWheelFontCombo(QFontComboBox):
    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        event.ignore()


def _spin(lo: float, hi: float, step: float = 0.1, decimals: int = 1,
          special: str | None = None) -> _NoWheelSpin:
    box = _NoWheelSpin()
    box.setRange(lo, hi)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setMaximumWidth(90)
    if special is not None:
        box.setSpecialValueText(special)
    return box


def _combo(items) -> _NoWheelCombo:
    box = _NoWheelCombo()
    box.addItems(list(items))
    return box


def _fmt_number(value) -> str:
    """Render a float without a trailing ``.0`` — the times a user typed come
    back looking like the times a user typed."""
    number = float(value)
    return str(int(number)) if number == int(number) else str(number)


def _parse_numbers(text: str) -> list[float]:
    """Comma- or space-separated numbers; anything unparseable is dropped
    rather than raising, because this is read on every keystroke-ending edit
    and a half-typed list is not an error."""
    out: list[float] = []
    for part in str(text or "").replace(",", " ").split():
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def _row(*widgets) -> QWidget:
    """Pack widgets onto one form row, so a value and its modifier stay
    together instead of each taking a label of its own."""
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for w in widgets:
        lay.addWidget(w)
    lay.addStretch(1)
    return holder


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

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._refresh_preview)

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
        side_lay.addWidget(self._build_canvas_card())
        side_lay.addWidget(self._build_curves_card())
        side_lay.addWidget(self._build_panels_card())
        side_lay.addWidget(self._build_colours_card())
        side_lay.addStretch(1)
        self._connect_style_controls()
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

    def _build_canvas_card(self) -> Card:
        card = Card("Canvas & type", Category.PLOTS, icon_name="config",
                    subtitle="The shared look — saved up to the Project so "
                             "every member's figures match.")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._width = _spin(40, 400, 5, 0)
        self._height = _spin(30, 400, 5, 0)
        form.addRow("Size (mm):", _row(self._width, QLabel("×"), self._height))

        self._theme_combo = _combo(pf.THEMES)
        form.addRow("Theme:", self._theme_combo)

        self._font_combo = _NoWheelFontCombo()
        self._font_combo.setMaximumWidth(200)
        form.addRow("Font:", self._font_combo)

        self._base_size = _spin(4, 32, 0.5)
        self._text_color = ColorButton("#000000", auto_text="black")
        form.addRow("Base size (pt):", _row(self._base_size,
                                            QLabel("  text:"),
                                            self._text_color))

        ## Every one of these is 0 = "follow the base size", so a style that
        ## only sets the base still scales as one thing. The overrides are for
        ## the single element that has to differ.
        self._title_pt = _spin(0, 40, 0.5, 1, special="auto")
        self._axis_title_pt = _spin(0, 40, 0.5, 1, special="auto")
        self._tick_pt = _spin(0, 40, 0.5, 1, special="auto")
        self._legend_pt = _spin(0, 40, 0.5, 1, special="auto")
        self._strip_pt = _spin(0, 40, 0.5, 1, special="auto")
        for label, widget in (("Title (pt):", self._title_pt),
                              ("Axis titles (pt):", self._axis_title_pt),
                              ("Tick labels (pt):", self._tick_pt),
                              ("Legend (pt):", self._legend_pt),
                              ("Facet strips (pt):", self._strip_pt)):
            widget.setToolTip("0 = follow the base size.")
            form.addRow(label, widget)

        card.add_body(form)
        return card

    def _build_curves_card(self) -> Card:
        card = Card("Curves & points", Category.PLOTS, icon_name="km",
                    subtitle="The step curve itself, its markers, its censor "
                             "ticks and its confidence band.")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._line_width = _spin(0.1, 6.0, 0.1)
        self._line_pt = _spin(0.0, 4.0, 0.1)
        self._line_pt.setToolTip(
            "Axis lines, ticks and panel borders — the figure's furniture, "
            "which is a different decision from the curve's own weight.")
        form.addRow("Curve width:", _row(self._line_width,
                                         QLabel("  axes:"), self._line_pt))

        # ---- points ------------------------------------------------------
        self._show_points = QCheckBox("Draw points on the curve")
        self._show_points.setToolTip(
            "Off by default: a lifespan cohort has an event on nearly every "
            "day, and a marker per event buries the curve.")
        form.addRow("", self._show_points)

        self._point_at = _combo(pf.POINT_AT)
        self._point_at.setToolTip(
            "events = knots where survival actually fell (not the t=0 anchor, "
            "not censoring-only knots); censored = knots with a censoring; "
            "all = every observed time.")
        form.addRow("Points at:", self._point_at)

        self._point_shape = _combo(pf.POINT_SHAPES)
        self._point_size = _spin(0.2, 12.0, 0.2)
        form.addRow("Shape / size:", _row(self._point_shape, self._point_size))

        self._point_alpha = _spin(0.0, 1.0, 0.05, 2)
        self._point_fill = ColorButton("", auto_text="curve")
        self._point_fill.setToolTip(
            "The marker's interior. 'curve' follows the series colour; a fully "
            "transparent pick gives a hollow marker.")
        form.addRow("Opacity / fill:", _row(self._point_alpha,
                                            self._point_fill))

        self._point_stroke = _spin(0.0, 3.0, 0.1)
        self._point_stroke.setToolTip(
            "Outline weight around each point. 0 = no outline — the marker is "
            "drawn solid in the curve colour. Only the filled shapes can show "
            "one; a stroke on '+' or 'x' is just a thicker mark.")
        self._point_stroke_color = ColorButton("#000000", auto_text="curve")
        form.addRow("Outline:", _row(self._point_stroke,
                                     self._point_stroke_color))

        # ---- censor ticks -------------------------------------------------
        self._censor_ticks = QCheckBox("Censor ticks")
        form.addRow("", self._censor_ticks)
        self._censor_shape = _combo(pf.POINT_SHAPES)
        self._censor_size = _spin(0.2, 12.0, 0.2)
        self._censor_color = ColorButton("", auto_text="curve")
        form.addRow("Tick shape/size:", _row(self._censor_shape,
                                             self._censor_size,
                                             self._censor_color))

        # ---- confidence band ---------------------------------------------
        self._ci_band = QCheckBox("95% CI bands")
        form.addRow("", self._ci_band)
        self._ci_alpha = _spin(0.0, 1.0, 0.05, 2)
        form.addRow("Band opacity:", self._ci_alpha)

        card.add_body(form)
        return card

    def _build_panels_card(self) -> Card:
        card = Card("Panels & legend", Category.PLOTS, icon_name="plots",
                    subtitle="Backgrounds, borders, facet strips, gridlines "
                             "and the at-risk band.")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._panel_bg = ColorButton("", auto_text="theme")
        self._panel_border = QCheckBox("Border")
        form.addRow("Panel:", _row(self._panel_bg, self._panel_border))

        self._grid = _combo(("none", "y", "both"))
        self._grid.setToolTip(
            "Off by default: a survivorship curve is read against its own "
            "steps, and rules at 0.25/0.5/0.75 compete with them.")
        form.addRow("Gridlines:", self._grid)

        self._strip_style = _combo(("plain", "boxed"))
        self._strip_bg = ColorButton("#d9d9d9")
        form.addRow("Facet strips:", _row(self._strip_style, self._strip_bg))

        self._legend_pos = _combo(("right", "left", "top", "bottom", "none"))
        form.addRow("Legend:", self._legend_pos)

        self._risk_table = QCheckBox("At-risk band below the curves")
        form.addRow("", self._risk_table)
        self._risk_font_size = _spin(3, 20, 0.5)
        self._risk_row_height = _spin(0.02, 0.4, 0.005, 3)
        form.addRow("Band size:", _row(self._risk_font_size,
                                       QLabel("  row:"),
                                       self._risk_row_height))
        self._risk_times = QLineEdit()
        self._risk_times.setPlaceholderText("auto — e.g. 0, 20, 40, 60")
        self._risk_times.setToolTip(
            "The times the counts are printed at. Empty spreads them evenly "
            "across the observed range; a list pins them, which is what a "
            "figure beside another one needs.")
        self._risk_times.editingFinished.connect(self._refresh_preview)
        form.addRow("Band times:", self._risk_times)

        card.add_body(form)
        return card

    def _build_colours_card(self) -> Card:
        """One swatch per curve in the current figure, plus the fallback cycle.

        Rebuilt whenever the figure changes, because the curves are a property
        of the data and the Spec's treatment list — not of the Style, which is
        shared and may be used by a member with different treatments.
        """
        card = Card("Colours", Category.PLOTS, icon_name="figures",
                    subtitle="Per-curve assignments, then the cycle anything "
                             "unassigned falls back to.")
        self._series_form = QFormLayout()
        self._series_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._series_swatches: dict[str, ColorButton] = {}
        card.add_body(self._series_form)

        self._cycle_row = QHBoxLayout()
        self._cycle_row.setSpacing(4)
        self._cycle_swatches: list[ColorButton] = []
        holder = QWidget()
        holder.setLayout(self._cycle_row)
        holder.setToolTip(
            "The cycle a curve with no explicit colour takes, in order — so a "
            "style can carry a journal's palette without naming every "
            "treatment in advance.")
        card.add_body(QLabel("Fallback cycle:"))
        card.add_body(holder)

        reset = QPushButton("Reset curve colours to the cycle")
        reset.setToolTip("Clear every per-curve assignment. The cycle itself "
                         "is left alone.")
        reset.clicked.connect(self._reset_series_colours)
        card.add_body(reset)

        row = QHBoxLayout()
        refresh = ActionButton("Refresh preview", Category.PLOTS,
                               icon_name="refresh")
        refresh.clicked.connect(self._refresh_preview)
        row.addWidget(refresh)
        card.add_body(row)
        return card

    # ── colours ────────────────────────────────────────────────────────────

    def _series_labels(self) -> list[str]:
        """The curve labels the current figure will draw, in plot order."""
        spec = self.spec
        if spec is None or self._lifetables is None:
            return []
        try:
            data = pf.curve_data(self._lifetables, spec)
        except Exception:  # noqa: BLE001 - the preview reports it; not here
            return []
        if data.empty:
            return []
        col = "_series" if "_series" in data.columns else "label"
        return list(dict.fromkeys(data[col]))

    def _rebuild_colour_controls(self) -> None:
        while self._series_form.rowCount():
            self._series_form.removeRow(0)
        self._series_swatches = {}
        style = self.style
        labels = self._series_labels()
        cycle = list(style.palette_cycle or pf.DEFAULT_PALETTE)
        for i, label in enumerate(labels):
            ## What this curve would be WITHOUT an explicit assignment. Kept
            ## on the swatch so harvest can tell "the user picked this" from
            ## "the cycle happened to give this" — without it, opening the
            ## editor and touching anything would pin every curve's colour
            ## into the shared Style and the cycle would stop meaning
            ## anything.
            auto = cycle[i % len(cycle)] if cycle else pf.DEFAULT_PALETTE[0]
            swatch = ColorButton(style.palette.get(label) or auto)
            swatch.setProperty("auto_colour", auto)
            swatch.changed.connect(self._refresh_preview)
            self._series_swatches[label] = swatch
            self._series_form.addRow(f"{label}:", swatch)
        if not labels:
            self._series_form.addRow(
                "", QLabel("No curves yet — check the figure's settings."))

        while self._cycle_row.count():
            item = self._cycle_row.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        self._cycle_swatches = []
        cycle = list(style.palette_cycle or pf.DEFAULT_PALETTE)
        for colour in cycle:
            swatch = ColorButton(colour)
            swatch.setFixedSize(24, 20)
            swatch.changed.connect(self._refresh_preview)
            self._cycle_swatches.append(swatch)
            self._cycle_row.addWidget(swatch)
        self._cycle_row.addStretch(1)

    def _reset_series_colours(self) -> None:
        self.style.palette = {}
        self._rebuild_colour_controls()
        self._refresh_preview()

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

    #: form attribute -> style field, for the three kinds of control that
    #: round-trip mechanically. Written once so load and harvest cannot
    #: disagree about which widget owns which field — the failure mode when
    #: a style has thirty of them is a control that silently does nothing.
    _NUMBERS = (
        ("_width", "width_mm"), ("_height", "height_mm"),
        ("_base_size", "base_size"), ("_title_pt", "title_pt"),
        ("_axis_title_pt", "axis_title_pt"), ("_tick_pt", "tick_pt"),
        ("_legend_pt", "legend_pt"), ("_strip_pt", "strip_pt"),
        ("_line_width", "line_width"), ("_line_pt", "line_pt"),
        ("_point_size", "point_size"), ("_point_alpha", "point_alpha"),
        ("_point_stroke", "point_stroke"), ("_censor_size", "censor_size"),
        ("_ci_alpha", "ci_alpha"), ("_risk_font_size", "risk_font_size"),
        ("_risk_row_height", "risk_row_height"),
    )
    _FLAGS = (
        ("_show_points", "show_points"), ("_censor_ticks", "censor_ticks"),
        ("_ci_band", "ci_band"), ("_risk_table", "risk_table"),
        ("_panel_border", "panel_border"),
    )
    _CHOICES = (
        ("_theme_combo", "theme"), ("_legend_pos", "legend_position"),
        ("_point_at", "point_at"), ("_point_shape", "point_shape"),
        ("_censor_shape", "censor_shape"), ("_grid", "grid"),
        ("_strip_style", "strip_style"),
    )
    _COLOURS = (
        ("_text_color", "text_color"), ("_point_fill", "point_fill"),
        ("_point_stroke_color", "point_stroke_color"),
        ("_censor_color", "censor_color"), ("_panel_bg", "panel_bg"),
        ("_strip_bg", "strip_bg"),
    )

    def _connect_style_controls(self) -> None:
        """Every style control re-renders. One place, so a control added to a
        card is never left inert."""
        for attr, _field in self._NUMBERS:
            getattr(self, attr).valueChanged.connect(self._refresh_preview)
        for attr, _field in self._FLAGS:
            getattr(self, attr).stateChanged.connect(self._refresh_preview)
        for attr, _field in self._CHOICES:
            getattr(self, attr).currentTextChanged.connect(self._refresh_preview)
        for attr, _field in self._COLOURS:
            getattr(self, attr).changed.connect(self._refresh_preview)
        self._font_combo.currentFontChanged.connect(self._refresh_preview)

    def _load_style_into_form(self) -> None:
        style = self.style
        for attr, field_name in self._NUMBERS:
            widget = getattr(self, attr)
            widget.blockSignals(True)
            widget.setValue(float(getattr(style, field_name)))
            widget.blockSignals(False)
        for attr, field_name in self._FLAGS:
            widget = getattr(self, attr)
            widget.blockSignals(True)
            widget.setChecked(bool(getattr(style, field_name)))
            widget.blockSignals(False)
        for attr, field_name in self._CHOICES:
            widget = getattr(self, attr)
            widget.blockSignals(True)
            widget.setCurrentText(str(getattr(style, field_name)))
            widget.blockSignals(False)
        for attr, field_name in self._COLOURS:
            widget = getattr(self, attr)
            widget.blockSignals(True)
            widget.set_color(str(getattr(style, field_name)))
            widget.blockSignals(False)
        self._font_combo.blockSignals(True)
        self._font_combo.setCurrentFont(QFont(style.font_family))
        self._font_combo.blockSignals(False)
        self._risk_times.blockSignals(True)
        self._risk_times.setText(", ".join(
            _fmt_number(t) for t in (style.risk_table_times or [])))
        self._risk_times.blockSignals(False)
        self._rebuild_colour_controls()

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
        for attr, field_name in self._NUMBERS:
            setattr(style, field_name, getattr(self, attr).value())
        for attr, field_name in self._FLAGS:
            setattr(style, field_name, getattr(self, attr).isChecked())
        for attr, field_name in self._CHOICES:
            setattr(style, field_name, getattr(self, attr).currentText())
        for attr, field_name in self._COLOURS:
            setattr(style, field_name, getattr(self, attr).color())
        style.font_family = self._font_combo.currentFont().family()
        style.risk_table_times = _parse_numbers(self._risk_times.text())
        ## Only the curves actually on screen are written back, so opening a
        ## member with fewer treatments never drops another member's colours
        ## from a shared Style. And only the ones that deviate: `palette` means
        ## "explicitly assigned", so a swatch still showing its cycle colour is
        ## removed rather than pinned.
        for label, swatch in self._series_swatches.items():
            colour = swatch.color()
            if colour and colour != swatch.property("auto_colour"):
                style.palette[label] = colour
            else:
                style.palette.pop(label, None)
        if self._cycle_swatches:
            style.palette_cycle = [s.color() for s in self._cycle_swatches]
        return spec, style

    # ── preview ────────────────────────────────────────────────────────────

    def _on_plot_changed(self, plot_id: str) -> None:
        self._current_id = plot_id
        self._load_spec_into_form()
        self._refresh_preview()

    def _on_style_changed(self, _name: str) -> None:
        self._load_style_into_form()
        self._refresh_preview()

    def _preview_dpi(self, style) -> int:
        """The DPI that fills the preview widget exactly, in **device** pixels.

        A Publication Figure is sized in millimetres, so its pixel size is a
        function of DPI alone. Rendering at a fixed 110 gave a 519x389 raster
        for the default 120x90mm style — smaller than the preview widget has
        ever been — and Qt then upscaled it, which is what made every preview
        soft. Rasterising is not what costs the time here (the plotnine build
        is ~110ms whatever the DPI), so there is nothing to buy by rendering
        small.

        The device pixel ratio is part of the sum: on a HiDPI screen the
        widget's logical size is half of what actually gets painted, so a
        raster matched to the logical size is upscaled twice over.
        """
        ratio = self._preview.devicePixelRatioF()
        width_in = max(float(style.width_mm), 1.0) / 25.4
        height_in = max(float(style.height_mm), 1.0) / 25.4
        size = self._preview.size()
        ## KeepAspectRatio fits whichever axis is more constrained, so that is
        ## the axis that decides the resolution.
        dpi = min(size.width() * ratio / width_in,
                  size.height() * ratio / height_in)
        return int(max(_PREVIEW_MIN_DPI, min(_PREVIEW_MAX_DPI, dpi)))

    def _refresh_preview(self) -> None:
        spec, style = self._harvest()
        if spec is None:
            self._preview.setText("This experiment has no publication figures.")
            return
        try:
            if self._lifetables is None:
                self._lifetables = pf._load_lifetables(self.experiment)
            ## The curves are a property of the DATA and the Spec, so they are
            ## not known until the lifetables are read — which happens here,
            ## after the form was first built. Rebuild when the set changes
            ## (first render, and any Spec edit that adds or drops a curve).
            if set(self._series_swatches) != set(self._series_labels()):
                self._rebuild_colour_controls()
                spec, style = self._harvest()
            g = pf.build_ggplot(pf.curve_data(self._lifetables, spec), spec, style)
            data = pf.render_png_bytes(g, style, dpi=self._preview_dpi(style))
        except Exception as exc:  # noqa: BLE001 - a bad spec shows, never crashes
            self._preview.setText(f"Preview failed:\n{exc}")
            self._log.append_line(f"Preview failed: {exc}")
            return
        ratio = self._preview.devicePixelRatioF()
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        ## The raster is in device pixels, so say so. Without this Qt reads it
        ## as logical pixels and paints it at ratio x, undoing the resolution
        ## it was just given.
        pixmap.setDevicePixelRatio(ratio)
        ## Downscale only. Scaling up is the thing being fixed: when the DPI
        ## ceiling bites (a very large window), a figure shown a little under
        ## the widget's size is better than a blurred one filling it.
        target = self._preview.size() * ratio
        if (pixmap.width() > target.width()
                or pixmap.height() > target.height()):
            pixmap = pixmap.scaled(
                target, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
        self._preview.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Re-render, do not rescale: the preview's resolution is chosen from
        the widget's size, so a resize changes what "sharp" means.

        Debounced, because a window drag emits one resize per frame and each
        one would otherwise rebuild the figure.
        """
        super().resizeEvent(event)
        self._resize_timer.start(150)

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
