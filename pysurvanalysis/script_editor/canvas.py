"""Canvas — ordered list of step cards with move-up / move-down / delete."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..ui import Category, icon
from .actions import ACTIONS


class _StepCard(QFrame):
    """A single step card in the canvas."""

    def __init__(
        self,
        index: int,
        step: dict,
        on_select,
        on_move,
        on_delete,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._index = index
        self._step = step
        self._on_select = on_select

        action = ACTIONS.get(step.get("action", ""))
        cat: Category = action.category if action else Category.NEUTRAL
        ic_name = action.icon_name if action else "play"
        title = action.title if action else step.get("action", "(unknown)")

        self.setStyleSheet(
            f"QFrame {{ border: 1px solid palette(mid); border-radius: 6px;"
            f" border-left: 3px solid {_color(cat)}; padding: 4px; }}"
        )

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(6)

        num = QLabel(f"<b>{index + 1}.</b>")
        num.setMinimumWidth(20)
        outer.addWidget(num)

        ic_lbl = QLabel()
        ic_lbl.setPixmap(icon(ic_name, category=cat).pixmap(16, 16))
        outer.addWidget(ic_lbl)

        text = QLabel(title)
        outer.addWidget(text, 1)

        params_summary = ", ".join(
            f"{k}={v}" for k, v in step.items() if k != "action"
        )
        if params_summary:
            sub = QLabel(params_summary)
            sub.setStyleSheet("color: palette(mid); font-size: 9pt;")
            sub.setMaximumWidth(220)
            outer.addWidget(sub)

        up = QToolButton()
        up.setIcon(icon("up"))
        up.setAutoRaise(True)
        up.clicked.connect(lambda: on_move(index, -1))
        down = QToolButton()
        down.setIcon(icon("down"))
        down.setAutoRaise(True)
        down.clicked.connect(lambda: on_move(index, +1))
        delete = QToolButton()
        delete.setIcon(icon("delete"))
        delete.setAutoRaise(True)
        delete.clicked.connect(lambda: on_delete(index))
        outer.addWidget(up)
        outer.addWidget(down)
        outer.addWidget(delete)

    def mousePressEvent(self, event):  # noqa: N802 — Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_select(self._index, self._step)
        super().mousePressEvent(event)


def _color(cat: Category) -> str:
    from ..ui.theme import category_color

    return category_color(cat)


class Canvas(QWidget):
    """Vertical list of step cards.

    Emits :pyattr:`stepsChanged(list)` when steps are added/removed/reordered,
    and :pyattr:`stepSelected(idx, step)` when the user clicks one.
    """

    stepsChanged = pyqtSignal(list)
    stepSelected = pyqtSignal(int, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        outer.addWidget(QLabel("<b>Steps</b>"))

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(self._scroll.Shape.NoFrame)
        self._host = QWidget()
        self._host_lay = QVBoxLayout(self._host)
        self._host_lay.setContentsMargins(0, 0, 0, 0)
        self._host_lay.setSpacing(6)
        self._host_lay.addStretch(1)
        self._scroll.setWidget(self._host)
        outer.addWidget(self._scroll, 1)

        self._steps: list[dict] = []
        self._selected_idx = -1

    def set_steps(self, steps: list[dict], keep_selection: int | None = None) -> None:
        self._steps = list(steps)
        self._rebuild()
        if keep_selection is not None and 0 <= keep_selection < len(self._steps):
            self._selected_idx = keep_selection
            self.stepSelected.emit(keep_selection, self._steps[keep_selection])

    def steps(self) -> list[dict]:
        """The steps currently on the canvas."""
        return list(self._steps)

    def append_step(self, step: dict) -> None:
        self._steps.append(step)
        self._rebuild()
        self.stepsChanged.emit(self._steps)
        self.stepSelected.emit(len(self._steps) - 1, step)

    def _rebuild(self) -> None:
        # Clear (everything except the trailing stretch)
        while self._host_lay.count() > 1:
            item = self._host_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, step in enumerate(self._steps):
            card = _StepCard(
                i, step,
                on_select=self._select,
                on_move=self._move,
                on_delete=self._delete,
                parent=self._host,
            )
            self._host_lay.insertWidget(i, card)

    def _select(self, idx: int, step: dict) -> None:
        self._selected_idx = idx
        self.stepSelected.emit(idx, step)

    def _move(self, idx: int, delta: int) -> None:
        new_idx = idx + delta
        if not (0 <= new_idx < len(self._steps)):
            return
        self._steps[idx], self._steps[new_idx] = self._steps[new_idx], self._steps[idx]
        self._rebuild()
        self.stepsChanged.emit(self._steps)
        self.stepSelected.emit(new_idx, self._steps[new_idx])

    def _delete(self, idx: int) -> None:
        if not (0 <= idx < len(self._steps)):
            return
        del self._steps[idx]
        self._rebuild()
        self.stepsChanged.emit(self._steps)
        if self._steps:
            new_idx = min(idx, len(self._steps) - 1)
            self.stepSelected.emit(new_idx, self._steps[new_idx])
        else:
            self.stepSelected.emit(-1, {})
