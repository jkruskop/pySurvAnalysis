"""The Batch Run preflight.

Recursive discovery means the folder you picked no longer tells you what will
run: Projects can sit at any depth, and a Batch Run rewrites analysis in every
one of them. This dialog is the one surface that states the target list, and
the last point at which it can be changed.

It shows, per Project, its relative-path key, how many Member Experiments the
run can actually use, and every **Blocked Member** with its reason and the
action that clears it — scaffolding a missing ``survival_config.yaml``, or
naming which of several data files is the experiment.

Nothing here is a gate. A Project with blocked members still runs its healthy
ones, and the run is never refused — a stale folder must not stop ten Projects
at 2am. It is shown even when nothing is wrong, because with recursive
discovery the target list is the one thing no other surface states.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..domain import Project, ProjectError, config as cfgmod, layout as layout_mod
from ..domain.batch import discover
from ..ui import Category, icon

#: Roles on a tree row: which Project key, and which member directory.
_KEY_ROLE = Qt.ItemDataRole.UserRole
_DIR_ROLE = Qt.ItemDataRole.UserRole + 1

# Keys are relative paths in a recursive Batch. Keep the first column bounded
# so a deeply-nested Project cannot force the Batch surfaces wider than their
# panels; Qt paints the hidden tail with an ellipsis.
PROJECT_COLUMN_MAX_WIDTH = 280


def blocked_color() -> QColor:
    """Red that stays legible on both themes — the light theme's red is
    unreadable on the dark surface and vice versa."""
    from ..ui.theme import resolved_mode

    return QColor("#f87171") if resolved_mode() == "dark" else QColor("#b91c1c")


class BatchPreflightDialog(QDialog):
    """Confirm (and repair) what a Batch Run is about to do.

    ``exec()`` returning ``Accepted`` means run; :attr:`selected_keys` then
    carries the confirmed target list.
    """

    def __init__(self, parent, root, *, checked=None, log=None) -> None:
        super().__init__(parent)
        self._root = Path(root)
        self._log = log or (lambda _text: None)
        self._preferred = None if checked is None else {str(k) for k in checked}
        self._projects: list = []
        self._skipped: list = []
        self._truncated = False
        self._loading = False
        #: Keys the USER unchecked. A Project with nothing usable starts
        #: unchecked on its own, so "do not touch what I unchecked" has to
        #: mean the user's own act — otherwise repairing a Project here would
        #: not put it back in the run.
        self._user_unchecked: set[str] = set()
        #: Keys the user checked by hand — a Project nothing can run in still
        #: joins the run if they insist.
        self._user_checked: set[str] = set()
        self._seeded = False

        self.setWindowTitle("Batch Run — review")
        self.setMinimumSize(760, 520)

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        self._heading = QLabel("")
        self._heading.setWordWrap(True)
        self._heading.setStyleSheet("font-weight: 600;")
        outer.addWidget(self._heading)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Project", "Members", "Status"])
        self._tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        header = self._tree.header()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._tree.setColumnWidth(0, PROJECT_COLUMN_MAX_WIDTH)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._tree.itemSelectionChanged.connect(self._sync_fix_button)
        self._tree.itemChanged.connect(self._on_item_changed)
        outer.addWidget(self._tree, 1)

        actions = QHBoxLayout()
        self._btn_fix = QPushButton("Fix selected…")
        self._btn_fix.setIcon(icon("config", category=Category.TOOLS))
        self._btn_fix.setToolTip(
            "Repair the selected member: scaffold its config from the "
            "Project's defaults, or name which data file is the experiment.")
        self._btn_fix.clicked.connect(self._fix_selected)
        self._btn_fix.setEnabled(False)
        actions.addWidget(self._btn_fix)
        self._btn_fix_all = QPushButton("Scaffold every missing config")
        self._btn_fix_all.setToolTip(
            "Write a minimal survival_config.yaml, from each Project's own "
            "defaults, into every member that holds data but has no config. "
            "Ambiguous members are left alone and reported.")
        self._btn_fix_all.clicked.connect(self._fix_all)
        actions.addWidget(self._btn_fix_all)
        btn_rescan = QPushButton("Rescan")
        btn_rescan.setToolTip("Walk the batch folder again — for changes made "
                              "outside the app.")
        btn_rescan.clicked.connect(self.reload)
        actions.addWidget(btn_rescan)
        actions.addStretch(1)
        outer.addLayout(actions)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet("color: palette(mid); font-style: italic;")
        outer.addWidget(self._note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel)
        self._run_btn = buttons.addButton("Run batch",
                                          QDialogButtonBox.ButtonRole.AcceptRole)
        self._run_btn.setIcon(icon("play", category=Category.ANALYZE))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.reload()

    # ── state the caller reads ─────────────────────────────────────────────

    @property
    def selected_keys(self) -> list[str]:
        """The confirmed target list, in run order."""
        keys = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                keys.append(str(item.data(0, _KEY_ROLE)))
        return keys

    # ── building ───────────────────────────────────────────────────────────

    def reload(self) -> None:
        """Walk the batch folder and rebuild the tree.

        Check state is re-derived from what the user actually said plus what
        each Project can do *now* — never from the previous check column.
        Scaffolding a config is what MAKES a Project runnable, so re-deriving
        "unchecked" from the pre-repair state would exclude the very Project
        the user had just fixed.
        """
        found = discover(self._root)
        self._projects = found["projects"]
        self._skipped = found["skipped"]
        self._truncated = bool(found["truncated"])

        self._loading = True
        self._tree.clear()
        for entry in self._projects:
            item = QTreeWidgetItem([entry.key, f"{len(entry.usable)}/"
                                               f"{len(entry.members)}",
                                    f"{len(entry.blocked)} blocked"
                                    if entry.blocked else "ok"])
            item.setData(0, _KEY_ROLE, entry.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked
                               if self._wanted(entry) else Qt.CheckState.Unchecked)
            item.setToolTip(0, str(entry.directory))
            if entry.blocked:
                brush = QBrush(blocked_color())
                for column in range(3):
                    item.setForeground(column, brush)
            for member in entry.blocked:
                child = QTreeWidgetItem([member.name, "", member.status])
                child.setData(0, _KEY_ROLE, entry.key)
                child.setData(0, _DIR_ROLE, str(member.directory))
                child.setToolTip(0, member.detail or member.status)
                child.setToolTip(2, member.detail or member.status)
                child.setForeground(2, QBrush(blocked_color()))
                item.addChild(child)
            self._tree.addTopLevelItem(item)
            if entry.blocked:
                item.setExpanded(True)
        self._loading = False
        self._seeded = True
        self._refresh_heading()
        self._sync_fix_button()

    def _wanted(self, entry) -> bool:
        """Whether *entry* starts checked.

        A Project with nothing the run can use starts unchecked — it can only
        produce a failure. Everything else starts checked, unless the caller
        passed the Batch table's own column (first open) or the user has since
        said otherwise.
        """
        if entry.key in self._user_unchecked:
            return False
        if entry.key in self._user_checked:
            return True
        if not self._seeded and self._preferred is not None:
            return entry.key in self._preferred and entry.runnable
        return entry.runnable

    def _on_item_changed(self, item, column) -> None:
        if self._loading or column != 0 or item.parent() is not None:
            return
        key = str(item.data(0, _KEY_ROLE))
        if item.checkState(0) == Qt.CheckState.Checked:
            self._user_checked.add(key)
            self._user_unchecked.discard(key)
        else:
            self._user_unchecked.add(key)
            self._user_checked.discard(key)
        self._refresh_heading()

    def _refresh_heading(self) -> None:
        chosen = len(self.selected_keys)
        blocked = sum(len(p.blocked) for p in self._projects)
        self._heading.setText(
            f"{self._root} — {len(self._projects)} project(s) found, "
            f"{chosen} checked to run"
            + (f", {blocked} blocked member(s)" if blocked else ""))
        notes = []
        if self._skipped:
            notes.append(f"{len(self._skipped)} directory(ies) skipped — see "
                         "the Output log after the run.")
        if self._truncated:
            notes.append("The scan stopped early: this folder is larger than "
                         "a batch should be. Choose one closer to the projects.")
        if not self._projects:
            notes.append("Nothing to run. A Project is a folder with a "
                         "project.yaml and at least one member experiment.")
        self._note.setText(" ".join(notes))
        self._run_btn.setEnabled(bool(chosen))

    # ── repairs ────────────────────────────────────────────────────────────

    def _selected_member(self):
        """``(project_key, MemberLayout)`` for the selected child row."""
        items = self._tree.selectedItems()
        if not items:
            return None, None
        item = items[0]
        directory = item.data(0, _DIR_ROLE)
        if not directory:
            return None, None
        return str(item.data(0, _KEY_ROLE)), layout_mod.classify(directory)

    def _sync_fix_button(self) -> None:
        _key, member = self._selected_member()
        self._btn_fix.setEnabled(member is not None and member.fix is not None)
        if member is not None and member.fix is None and member.blocked:
            self._btn_fix.setToolTip(
                f"{member.name}: {member.detail or member.status} — no "
                "one-click fix for this one.")

    def _fix_selected(self) -> None:
        key, member = self._selected_member()
        if member is None or member.fix is None:
            return
        if member.fix == "config":
            self._scaffold_config(key, member)
        elif member.fix == "data_file":
            self._name_data_file(member)
        self.reload()

    def _fix_all(self) -> None:
        """Scaffold every missing config across the whole Batch.

        Only the unambiguous repair is offered in bulk: naming which of
        several data files is the experiment is a question only the
        experimenter can answer, one member at a time.
        """
        done = 0
        for entry in self._projects:
            for member in entry.blocked:
                if member.fix == "config" and self._scaffold_config(entry.key, member):
                    done += 1
        if not done:
            QMessageBox.information(
                self, "Nothing to scaffold",
                "No member is blocked on a missing config. Ambiguous members "
                "are left alone — name their data file one at a time.")
        self.reload()

    def _scaffold_config(self, key: str, member) -> bool:
        """Write a minimal config into *member* from its Project's defaults.

        The Project's own scaffolding path, not a second one: a config written
        any other way would not inherit the Project Defaults, and a member
        that restates a default freezes it.
        """
        try:
            project = Project(self._root / key if key else self._root)
            project.add_member(member.name)
        except (ProjectError, OSError) as exc:
            self._log(f"[preflight] {key}/{member.name}: {exc}")
            QMessageBox.warning(self, "Could not scaffold a config", str(exc))
            return False
        self._log(f"[preflight] scaffolded {cfgmod.CONFIG_FILENAME} in "
                  f"{key}/{member.name} from the project defaults.")
        return True

    def _name_data_file(self, member) -> None:
        """Write ``data_file:`` into an ambiguous member's config.

        The loader refuses to guess between several candidates, so this is the
        answer written down where the next run will read it — not a pick made
        silently on the user's behalf.
        """
        if not member.candidates:
            return
        choice, ok = QInputDialog.getItem(
            self, f"Which file is {member.name}?",
            "The experiment's data file:", list(member.candidates), 0, False)
        if not ok or not choice:
            return
        config = cfgmod.load_config(member.directory)
        config["data_file"] = choice
        cfgmod.save_config(member.directory, config)
        self._log(f"[preflight] {member.name}: data_file: {choice}")

    def focus_member(self, key: str) -> None:
        """Select and reveal the Project *key* — the entry point used by the
        Batch table's 'Fix blocked members…'."""
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if str(item.data(0, _KEY_ROLE)) == key:
                item.setExpanded(True)
                child = item.child(0) if item.childCount() else item
                self._tree.setCurrentItem(child)
                self._tree.scrollToItem(child)
                return
