"""Reusable themed widgets shared across the pySurvAnalysis Qt apps.

Vendored from PyTrackingAnalysis with ``Ptrack*`` objectNames renamed to
``Psurv*`` so the vendored QSS rules are namespaced.

* :class:`SidebarNav`  — vertical navigation rail with category-tinted items
* :class:`TopBar`      — app title + arbitrary right-aligned controls
* :class:`Card`        — rounded panel with title, optional subtitle, and a body layout
* :class:`ActionButton`— QPushButton with category-coloured left border + icon
* :class:`PlotDock`    — tabbed interactive plot dock (matplotlib + nav toolbar)
* :class:`OutputLog`   — monospaced log panel that grows scrollback
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFontDatabase,
    QIcon,
    QPalette,
    QPixmap,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import icon
from .theme import Category, category_color, resolved_mode


# ---------------------------------------------------------------------------
# Sidebar navigation rail
# ---------------------------------------------------------------------------

class SidebarNav(QWidget):
    """Vertical navigation rail.

    Items emit :pyattr:`itemSelected` with the item's *key*. Use
    :meth:`add_item` to register entries; the first added item is selected
    by default.
    """

    itemSelected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, *, width: int = 180) -> None:
        super().__init__(parent)
        self.setObjectName("PsurvSidebar")
        self.setFixedWidth(width)
        self.setAutoFillBackground(True)
        pal = self.palette()
        bg = pal.color(QPalette.ColorRole.Window).darker(105) \
            if resolved_mode() == "light" \
            else pal.color(QPalette.ColorRole.Window).lighter(110)
        pal.setColor(QPalette.ColorRole.Window, bg)
        self.setPalette(pal)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(8, 12, 8, 12)
        self._lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

    def add_item(
        self,
        key: str,
        label: str,
        icon_name: str,
        *,
        category: Category | None = None,
        tooltip: str | None = None,
    ) -> QPushButton:
        btn = QPushButton(label, self)
        btn.setObjectName("PsurvSidebarItem")
        btn.setCheckable(True)
        btn.setIcon(icon(icon_name, category=category))
        btn.setIconSize(QSize(16, 16))
        if tooltip:
            btn.setToolTip(tooltip)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.clicked.connect(lambda _checked, k=key: self.itemSelected.emit(k))
        self._lay.addWidget(btn)
        self._group.addButton(btn)
        self._buttons[key] = btn
        if len(self._buttons) == 1:
            btn.setChecked(True)
        return btn

    def add_separator(self) -> None:
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self._lay.addWidget(line)

    def add_stretch(self) -> None:
        self._lay.addStretch(1)

    def select(self, key: str) -> None:
        btn = self._buttons.get(key)
        if btn is not None:
            btn.setChecked(True)
            self.itemSelected.emit(key)


# ---------------------------------------------------------------------------
# Top bar
# ---------------------------------------------------------------------------

class TopBar(QFrame):
    """Slim top bar with an app title on the left and slots on the right."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PsurvTopBar")
        self.setFixedHeight(56)
        self.setFrameShape(QFrame.Shape.NoFrame)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 12, 6)
        lay.setSpacing(10)

        self._title = QLabel(title, self)
        self._title.setObjectName("PsurvAppTitle")
        lay.addWidget(self._title)

        lay.addStretch(1)

        self._right_lay = QHBoxLayout()
        self._right_lay.setContentsMargins(0, 0, 0, 0)
        self._right_lay.setSpacing(8)
        right_host = QWidget(self)
        right_host.setLayout(self._right_lay)
        lay.addWidget(right_host)

    def add_right(self, widget: QWidget) -> None:
        self._right_lay.addWidget(widget)

    def set_title(self, title: str) -> None:
        self._title.setText(title)


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

class Card(QFrame):
    """Rounded panel with a category-tinted left border + title row."""

    def __init__(
        self,
        title: str,
        category: Category = Category.NEUTRAL,
        subtitle: str | None = None,
        icon_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PsurvCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._category = category

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self._icon = icon(icon_name, category=category) if icon_name else None
        self._icon_lbl: QLabel | None = None
        if self._icon is not None:
            self._icon_lbl = QLabel(self)
            title_row.addWidget(self._icon_lbl)

        self._title_lbl = QLabel(title, self)
        self._title_lbl.setObjectName("PsurvCardTitle")
        title_row.addWidget(self._title_lbl, 1)
        self._title_row = title_row

        outer.addLayout(title_row)

        self._subtitle_lbl: QLabel | None = None
        if subtitle:
            sub = QLabel(subtitle, self)
            sub.setObjectName("PsurvCardSubtitle")
            sub.setWordWrap(True)
            outer.addWidget(sub)
            self._subtitle_lbl = sub

        self._body = QVBoxLayout()
        self._body.setSpacing(8)
        outer.addLayout(self._body)

        self._dimmed = False
        self.setAutoFillBackground(False)
        self.restyle()

    def set_dimmed(self, dimmed: bool) -> None:
        """Grey the card's surface to show its actions have no subject yet.

        Dimming is presentation only — the card stays live, so the control
        that fixes the missing state (a picker, a checkbox) keeps working; the
        actions themselves are gated with ``setEnabled`` as before.
        """
        if dimmed != self._dimmed:
            self._dimmed = dimmed
            self.restyle()

    def is_dimmed(self) -> bool:
        return self._dimmed

    def restyle(self) -> None:
        """Repaint the card for the CURRENT theme and dim state.

        The colours come from ``surface_colors`` rather than palette roles,
        which qdarktheme leaves at the platform's light values — deriving the
        card background from ``Base`` painted white cards on the dark UI.

        Every visible piece is repainted rather than fading the whole card
        with a ``QGraphicsOpacityEffect``: an effect composites the card over
        whatever is behind it, and behind it is a scroll viewport still
        painting the platform's LIGHT base, so on the dark theme the "dim"
        came out brighter than the live card.
        """
        from .theme import surface_colors

        chrome = surface_colors()
        base = QColor(chrome["base"])
        if self._dimmed:
            ## Away from the live surface in the direction the theme reads as
            ## recessed, and far enough to survive a glance: on the dark theme
            ## a few points of lightness is invisible.
            bg = base.darker(112) if resolved_mode() == "light" else base.darker(150)
            accent = text = chrome["muted"]
        else:
            bg, accent, text = base, category_color(self._category), chrome["text"]
        self.setStyleSheet(
            f"QFrame#PsurvCard {{ background: {bg.name()}; "
            f"border: 1px solid {chrome['border']}; border-radius: 10px; }}"
            f"QFrame#PsurvCard QLabel {{ color: {text}; "
            f"background: transparent; }}"
            f"QFrame#PsurvCard QLabel#PsurvCardSubtitle {{ "
            f"color: {chrome['muted']}; }}"
        )
        self._title_lbl.setStyleSheet(
            f"QLabel#PsurvCardTitle {{"
            f"  border-left: 4px solid {accent};"
            f"  padding-left: 8px;"
            f"  color: {text};"
            f"}}"
        )
        if self._subtitle_lbl is not None:
            self._subtitle_lbl.setStyleSheet(
                f"QLabel#PsurvCardSubtitle {{ color: {chrome['muted']}; }}")
        if self._icon_lbl is not None and self._icon is not None:
            ## Qt's own greyed rendering — the category tint at full strength
            ## was the loudest thing left on a dimmed card.
            mode = QIcon.Mode.Disabled if self._dimmed else QIcon.Mode.Normal
            self._icon_lbl.setPixmap(self._icon.pixmap(QSize(20, 20), mode))

    def body_layout(self) -> QVBoxLayout:
        return self._body

    def add_body(self, widget_or_layout: QWidget | Any) -> None:
        if isinstance(widget_or_layout, QWidget):
            self._body.addWidget(widget_or_layout)
        else:
            self._body.addLayout(widget_or_layout)

    def set_title(self, title: str) -> None:
        self._title_lbl.setText(title)

    def add_section_label(self, text: str) -> None:
        lbl = QLabel(text, self)
        lbl.setObjectName("PsurvSectionDivider")
        self._body.addWidget(lbl)


# ---------------------------------------------------------------------------
# Action button
# ---------------------------------------------------------------------------

class ActionButton(QPushButton):
    """QPushButton with a category-coloured left accent and themed icon."""

    def __init__(
        self,
        text: str,
        category: Category = Category.NEUTRAL,
        icon_name: str | None = None,
        *,
        primary: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._category = category
        if not self.toolTip():
            self.setToolTip(text)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if icon_name is not None:
            self.setIcon(icon(icon_name, category=category))
            self.setIconSize(QSize(16, 16))
        col = category_color(category)
        weight = "600" if primary else "500"
        bg = "palette(highlight)" if primary else "palette(button)"
        fg = "palette(highlighted-text)" if primary else "palette(button-text)"
        self.setStyleSheet(
            f"QPushButton {{"
            f"  border-left: 3px solid {col};"
            f"  border-radius: 6px;"
            f"  padding: 6px 12px;"
            f"  font-weight: {weight};"
            f"  background: {bg};"
            f"  color: {fg};"
            f"}}"
            f"QPushButton:hover {{ background: {col}; color: white; }}"
            f"QPushButton:disabled {{ color: palette(mid); border-left-color: palette(mid); }}"
        )


# ---------------------------------------------------------------------------
# Output log
# ---------------------------------------------------------------------------

class OutputLog(QPlainTextEdit):
    """Read-only log panel with a capped scrollback."""

    def __init__(self, parent: QWidget | None = None, *, max_lines: int = 5000) -> None:
        super().__init__(parent)
        self.setObjectName("PsurvLog")
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_lines)
        # Force a fixed-width font so tabular pandas output (.to_string) lines up.
        # QSS font-family doesn't always apply to QPlainTextEdit, and the named
        # fonts in theme.py may not be installed on every platform.
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setStyleHint(mono.StyleHint.Monospace)
        self.setFont(mono)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        #: Text written without a closing newline, waiting for the rest of its
        #: line. It is displayed immediately (as its own block) and that block
        #: is rewritten when the remainder arrives.
        self._pending = ""
        self._pending_shown = False

    def append_line(self, text: str) -> None:
        """Append *text* as one or more COMPLETE lines.

        For callers that hand over a finished message — most of the app. A
        trailing newline is optional and never treated as "more to come", so
        two consecutive messages cannot run together.
        """
        if not text:
            return
        self._flush_pending()
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()          # a trailing newline closes, it does not add
        for line in lines:
            self.appendPlainText(line.rstrip())
        self._after_append()

    def append_stream(self, chunk: str) -> None:
        """Append a raw chunk from a redirected ``stdout``.

        Unlike :meth:`append_line` a chunk has no line discipline: ``print``
        writes its text and its terminator separately, so one call can carry
        several lines, a bare newline, or the front half of a line. Passing
        those straight to ``appendPlainText`` put every fragment on its own
        row, which is what broke pandas tables across the log. The trailing
        fragment is shown immediately and rewritten in place when the rest of
        it arrives, so nothing appears twice.
        """
        if not chunk:
            return
        lines = (self._pending + chunk).split("\n")
        self._pending = lines.pop()
        if self._pending_shown:
            self._drop_last_block()
            self._pending_shown = False
        for line in lines:
            self.appendPlainText(line.rstrip())
        if self._pending:
            self.appendPlainText(self._pending)
            self._pending_shown = True
        self._after_append()

    def clear_log(self) -> None:
        """Erase the scrollback, including any partially-streamed line."""
        self.clear()
        self._flush_pending()

    def _flush_pending(self) -> None:
        """Close off a partial streamed line, so a complete message from
        somewhere else cannot be glued onto its end."""
        self._pending = ""
        self._pending_shown = False

    def _after_append(self) -> None:
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.ensureCursorVisible()

    def _drop_last_block(self) -> None:
        """Remove the block holding the partial line, so the completed line
        replaces it rather than appearing twice."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()


# ---------------------------------------------------------------------------
# Plot dock
# ---------------------------------------------------------------------------

class PlotDock(QTabWidget):
    """Tabbed dock for matplotlib figures.

    The first tab is always *Output* (the supplied :class:`OutputLog`);
    subsequent tabs are added by :meth:`add_figure` and are individually
    closable.
    """

    def __init__(self, output_log: OutputLog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self._on_close)

        self._output_log = output_log
        self.addTab(output_log, icon("info"), "Output")
        self.tabBar().setTabButton(0, self.tabBar().ButtonPosition.RightSide, None)
        self.setCornerWidget(self._build_clear_bar(), Qt.Corner.TopRightCorner)

    def _build_clear_bar(self) -> QWidget:
        """Row of clear buttons in the dock's top-right corner.

        One per thing that accumulates. A single "Clear plots" could not empty
        a log that had been streaming for an hour, and closing the Output tab
        is not an option — it is the one tab that never closes.
        """
        bar = QWidget(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(2)
        for text, tip, slot in (
            ("Clear plot tabs", "Close every figure tab and show the Output tab.",
             self.clear_figures),
            ("Clear output", "Erase the contents of the Output tab.",
             self.clear_output),
        ):
            btn = QToolButton(bar)
            btn.setText(text)
            btn.setIcon(icon("clear"))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setAutoRaise(True)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
        return bar

    def clear_figures(self) -> None:
        """Close every figure tab and return to the Output tab."""
        for idx in range(self.count() - 1, 0, -1):
            widget = self.widget(idx)
            self.removeTab(idx)
            if widget is not None:
                widget.deleteLater()
        self.setCurrentWidget(self._output_log)

    def clear_output(self) -> None:
        """Erase everything in the Output log."""
        self._output_log.clear_log()

    def _on_close(self, idx: int) -> None:
        if idx == 0:
            return
        w = self.widget(idx)
        self.removeTab(idx)
        if w is not None:
            w.deleteLater()

    def add_figure(self, title: str, figure: Any, *, interactive: bool = False) -> None:
        """Embed *figure* (a matplotlib ``Figure``) as a new tab."""
        if not hasattr(figure, "savefig") and hasattr(figure, "draw"):
            figure = figure.draw()

        if interactive:
            host = QWidget(self)
            lay = QVBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

            canvas = FigureCanvasQTAgg(figure)
            toolbar = NavigationToolbar2QT(canvas, host)
            lay.addWidget(toolbar)
            lay.addWidget(canvas, 1)
            try:
                import mplcursors

                cursor = mplcursors.cursor(figure, hover=True)
                host._mpl_cursor = cursor  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
            widget: QWidget = host
        else:
            import io as _io

            from .zoom import ZoomableImageView

            buf = _io.BytesIO()
            figure.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)
            pix = QPixmap()
            pix.loadFromData(buf.getvalue())
            try:
                import matplotlib.pyplot as _plt

                _plt.close(figure)
            except Exception:  # noqa: BLE001
                pass
            widget = ZoomableImageView(pix)

        idx = self.addTab(widget, icon("plots", category=Category.PLOTS), title)
        self.setCurrentIndex(idx)
