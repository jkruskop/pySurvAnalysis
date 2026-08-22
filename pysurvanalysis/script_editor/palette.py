"""Action palette — list of available actions, double-click to add."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..ui import icon
from .actions import Action


class Palette(QWidget):
    """Library of actions; emits :pyattr:`actionRequested(key)` on double-click."""

    actionRequested = pyqtSignal(str)

    def __init__(self, actions: dict[str, Action], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        outer.addWidget(QLabel("<b>Actions</b>"))
        outer.addWidget(QLabel("Double-click to append to the script."))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_double_click)
        outer.addWidget(self._list, 1)
        self.set_actions(actions)

    def set_actions(self, actions: dict[str, Action]) -> None:
        """Rebuild the library — the registry changes with the script level and
        with the loaded experiment's Experiment Type (ADR-0002)."""
        self._list.clear()
        for category in ("LOAD", "ANALYZE", "PLOTS", "QC", "SCRIPTS", "AI", "TOOLS"):
            cat_actions = [
                a for a in actions.values() if a.category.name == category
            ]
            if not cat_actions:
                continue
            header = QListWidgetItem(f"── {category} ──")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(header)
            for action in sorted(cat_actions, key=lambda a: a.title):
                suffix = "  ·type" if getattr(action, "from_type", False) else ""
                item = QListWidgetItem(action.title + suffix)
                item.setIcon(icon(action.icon_name, category=action.category))
                item.setToolTip(action.description)
                item.setData(int(Qt.ItemDataRole.UserRole), action.key)
                self._list.addItem(item)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        key = item.data(int(Qt.ItemDataRole.UserRole))
        if isinstance(key, str) and key:
            self.actionRequested.emit(key)
