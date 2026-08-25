"""The Batch — a directory of Projects, run unattended (ADR-0009).

Purely a processing convenience: a Batch holds no analysis of its own, never
combines results, and is not itself a Project. Being one is structural — a
``batch.yaml`` appears only once batch-level scripting is authored, because
unlike a Project a Batch has no authority to declare.

**Discovery is recursive and prunes at each Project** (ADR-0009 amendment):
the walk descends until it finds a Project — ``project.yaml`` plus at least
one Member Experiment — and never looks inside one, because a Project's
subdirectories are its members by definition. Experimenters do not keep their
Projects in one flat folder; they keep ``Sept2026/ProjA`` and
``Archive/2025/ProjC``, and splitting a tree into flat batch folders to
satisfy the tool is the wrong direction of accommodation. Grouping folders are
therefore transparent, and a Project is identified by its **key** — its POSIX
path relative to the Batch root (``Sept2026/ProjA``; a top-level Project is
still just ``ProjA``, so every existing ``batch.yaml`` keeps working).

Note the level: a *Batch* holds Projects, and a *Project* holds Member
Experiments. "Member" is reserved for the lower level throughout this app, so
what a Batch Run targets is called a **Batch Project**.

A **Batch Run** executes one designated Project Script in every Project,
continue-on-error with per-Project log prefixes, and its only product is a
per-Project run summary.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfgmod
from . import layout
from .project import Project, is_project_dir

#: A runaway walk is a mis-clicked home directory, not a Batch. The cap is far
#: above any real batch and exists so pointing the Hub at ``/`` cannot hang it.
MAX_WALKED_DIRECTORIES = 20000

#: Never descended into. Everything else is decided structurally — a denylist
#: of output-directory names would misfire on a grouping folder that happens
#: to be called ``figures``.
_SKIP_DIRNAMES = {"__pycache__"}


@dataclass(frozen=True)
class BatchProject:
    """One Project a Batch Run can target, with its layout already read.

    *key* is the identity (POSIX path relative to the Batch root);
    *members* holds every experiment-shaped subdirectory, healthy or Blocked.
    Blocked is a property of the Member Experiment, never of the Project: a
    Project with four healthy members and one blocked member runs the four.
    """

    key: str
    directory: Path
    members: tuple = ()
    has_report: bool = False

    @property
    def usable(self) -> tuple:
        return tuple(m for m in self.members if m.usable)

    @property
    def blocked(self) -> tuple:
        return tuple(m for m in self.members if m.blocked)

    @property
    def runnable(self) -> bool:
        """False when nothing in it can be analysed — the run would only
        produce a failure, so such a Project starts unchecked."""
        return bool(self.usable)

    def summary(self) -> str:
        text = f"{len(self.usable)}/{len(self.members)} members"
        if self.blocked:
            text += f", {len(self.blocked)} blocked"
        return text


def project_kind(directory: Path | str) -> tuple[str, tuple]:
    """Classify *directory* as a Batch Project candidate.

    Returns ``(kind, members)`` where kind is:

    ``"project"``
        ``project.yaml`` and at least one member the run could use — certainly
        a Project. The walk prunes here.
    ``"unconfirmed"``
        ``project.yaml`` and experiment-shaped children, but not one the run
        could use. Probably a Project needing repair — but a grouping folder
        holding one junk subdirectory looks identical, so the walk descends
        first and only calls it a Project if nothing real turns up below.
    ``"marker"``
        ``project.yaml`` and nothing experiment-shaped at all: a grouping
        folder someone dropped a marker into. Walk through it.
    ``""``
        not a Project.

    One predicate for the library and the UI alike. An earlier short-circuit
    that asked :func:`is_project_dir` disagreed with this walk at the root, so
    a batch folder carrying a stray or legacy ``project.yaml`` enumerated its
    Projects perfectly and then showed an empty, dead Batch panel.
    """
    if not is_project_dir(directory):
        return "", ()
    members = tuple(layout.members_in(directory))
    if any(m.usable for m in members):
        return "project", members
    if members:
        ## Configured-but-unusable is not strong enough to prune on: a
        ## grouping folder with one ``template/survival_config.yaml`` looks
        ## exactly like a Project whose members are all blocked, and pruning
        ## there hides every real Project beneath it.
        return "unconfirmed", members
    return "marker", ()


def _has_report(project_dir: Path) -> bool:
    try:
        return any(name.lower().endswith("_report.pdf")
                   for name in os.listdir(project_dir))
    except OSError:
        return False


class _Walk:
    """One recursive discovery pass, with its budget and cycle guard.

    Depth-first and *decide-after-descending* for the ambiguous cases, so a
    stray ``project.yaml`` (or ``survival_config.yaml``) at a grouping level
    can never hide the Projects beneath it — the exact mistake recursion
    exists to tolerate.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.projects: list[BatchProject] = []
        self.skipped: list[tuple[str, str]] = []
        self.truncated = False
        self._seen: set[str] = set()
        self._budget = MAX_WALKED_DIRECTORIES

    def key(self, path: Path) -> str:
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def note(self, path: Path, why: str) -> None:
        self.skipped.append((self.key(path), why))

    def found(self, path: Path, members) -> None:
        self.projects.append(BatchProject(
            key=self.key(path), directory=Path(path), members=tuple(members),
            has_report=_has_report(Path(path))))

    def run(self) -> dict:
        kind, _members = project_kind(self.root)
        if kind == "project":
            ## A Project is never also a Batch: its subdirectories are its
            ## Member Experiments, not Projects.
            return self.result()
        self.descend(self.root)
        return self.result()

    def result(self) -> dict:
        self.projects.sort(key=lambda p: p.key)
        return {"projects": self.projects, "skipped": sorted(self.skipped),
                "truncated": self.truncated}

    def descend(self, directory: Path) -> int:
        """Walk *directory*'s children; returns how many Projects were found.

        A caller deciding "no Projects below, so this IS the Project" must
        check :attr:`truncated` first — a budget-exhausted descent found
        nothing because it never looked.
        """
        if self._budget <= 0:
            self.truncated = True
            return 0
        self._budget -= 1
        try:
            real = os.path.realpath(directory)
        except OSError:
            return 0
        if real in self._seen:
            return 0
        self._seen.add(real)

        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError as err:
            ## A directory nobody can read may hold a whole Project. Silently
            ## pruning it would report the Batch as smaller than it is.
            self.note(Path(directory), f"cannot be listed ({err.strerror or err})")
            return 0

        count = 0
        for entry in entries:
            if entry.name.startswith(".") or entry.name in _SKIP_DIRNAMES:
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    if entry.is_symlink() and entry.is_dir():
                        ## A link into an archive share would run its members
                        ## twice, and a link to an ancestor is a cycle.
                        self.note(Path(entry.path),
                                  "symlinked directory — not followed")
                    continue
            except OSError:
                self.note(Path(entry.path), "cannot be read")
                continue
            count += self.visit(Path(entry.path))
        return count

    def visit(self, path: Path) -> int:
        kind, members = project_kind(path)
        if kind == "project":
            self.found(path, members)
            return 1                              # prune: a Project is a leaf
        if kind == "unconfirmed":
            below = self.descend(path)
            if below or self.truncated:
                self.note(path, f"has {cfgmod.PROJECT_FILENAME} and "
                                f"{len(members)} folder(s) nothing can run; "
                                "treated as a folder of projects")
                return below
            self.found(path, members)
            return 1
        if kind == "marker":
            below = self.descend(path)
            ## Always reported: "I marked that folder as a Project — why isn't
            ## it in the list?" is the question this rule creates, and it
            ## deserves an answer in the log.
            self.note(path, f"has {cfgmod.PROJECT_FILENAME} but no member "
                            "experiment" + (f"; {below} project(s) found "
                                            "inside it instead" if below else ""))
            return below
        if layout.has_config(path):
            ## An Experiment Directory: its children are data/, analysis/,
            ## qc/ — never Projects. But a stray survival_config.yaml at a
            ## grouping level looks identical, so descend first and stop only
            ## if nothing turns up.
            below = self.descend(path)
            if below:
                self.note(path, f"has {cfgmod.CONFIG_FILENAME} and "
                                f"{below} project(s) inside it")
            return below
        return self.descend(path)


def discover(root: Path | str) -> dict:
    """Everything one walk of *root* found.

    ``{"projects": [...], "skipped": [(key, why)], "truncated": bool}`` — the
    Projects in run order, every directory the walk dropped and why, and
    whether the walk hit its budget. The single source of truth for what a
    Batch contains: the table, the preflight and the run all read it, so what
    the user was shown is what runs. Cheap by construction — directory
    listings and at most one small YAML per member, never a Project load.
    """
    return _Walk(root).run()


def is_batch_dir(path: Path | str) -> bool:
    """A Batch is structural: at least one Project lies somewhere beneath.

    Deliberately the SAME walk the table and the run use — see
    :func:`project_kind` for why a short-circuit here was wrong. The Hub keeps
    one cached walk per selection, which is what makes this affordable.
    """
    return bool(discover(path)["projects"])


def project_directory(root: Path | str, key: str) -> Path:
    """Absolute directory of the Batch Project *key* under *root*.

    A key comes from the walk today, but this is the public key→directory
    resolver and keys also arrive from ``batch.yaml``, so one that escapes the
    Batch is refused rather than resolved.
    """
    parts = [part for part in str(key).split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts) or os.path.isabs(str(key)):
        raise ValueError(f"{key!r} is not a project in this batch")
    return Path(root).resolve().joinpath(*parts)


def nested_batch_files(root: Path | str) -> list[str]:
    """``batch.yaml`` files below *root* that this run ignores.

    Recursive discovery means a grouping folder can be a Batch in its own
    right and carry its own designation. Only the selected Batch's file
    governs — the script resolution is already three steps, and a fourth that
    depended on where the user clicked would be unmemorable — so these are
    named in the log rather than silently overridden.
    """
    root = Path(root).resolve()
    found: list[str] = []
    for project in discover(root)["projects"]:
        directory = project.directory.parent
        while len(str(directory)) > len(str(root)):
            candidate = directory / cfgmod.BATCH_FILENAME
            relative = os.path.relpath(candidate, root).replace(os.sep, "/")
            if candidate.is_file() and relative not in found:
                found.append(relative)
            directory = directory.parent
    return sorted(found)


@dataclass
class ProjectOutcome:
    """What one Project's leg of a Batch Run produced.

    *name* is the Project's key — its path relative to the Batch root, so two
    ``ProjA`` folders under different parents stay distinguishable.
    """

    name: str
    ok: bool
    message: str = ""
    #: Members the run could use, and members found — the ratio that stops
    #: "succeeded" being read as "analysed everything".
    usable: int = 0
    total: int = 0

    @property
    def partial(self) -> bool:
        return self.ok and self.total > 0 and self.usable < self.total


@dataclass
class BatchResult:
    outcomes: list[ProjectOutcome] = field(default_factory=list)

    @property
    def failures(self) -> list[ProjectOutcome]:
        return [o for o in self.outcomes if not o.ok]

    def summary(self) -> str:
        total, bad = len(self.outcomes), len(self.failures)
        if not total:
            return "Batch run: no Projects found."
        ## Blocked members are named in the same breath as the success count:
        ## a run that completed every Project while skipping half their
        ## members is not the run the user thinks they got.
        partial = [o for o in self.outcomes if o.partial]
        tail = ""
        if partial:
            tail = ("; incomplete: "
                    + ", ".join(f"{o.name} ({o.usable}/{o.total} members)"
                                for o in partial))
        if not bad:
            return f"Batch run: {total} Project(s) completed{tail}."
        names = ", ".join(o.name for o in self.failures)
        return (f"Batch run: {total - bad}/{total} Projects completed; "
                f"failed: {names}{tail}.")


class Batch:
    """A directory with at least one Project anywhere beneath it.

    The walk is done once, at construction, and reused: recursive discovery is
    far more expensive than the single ``iterdir`` it replaced, and the Hub
    refreshes its tiles on every checkbox click. :meth:`rescan` re-runs it for
    changes made outside the app.
    """

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.config = cfgmod.read_yaml(self.directory / cfgmod.BATCH_FILENAME)
        self._found: dict | None = None

    @property
    def name(self) -> str:
        return self.directory.name

    @property
    def config_path(self) -> Path:
        return self.directory / cfgmod.BATCH_FILENAME

    # ── discovery ──────────────────────────────────────────────────────────

    def found(self) -> dict:
        """The cached walk — see :func:`discover` for its shape."""
        if self._found is None:
            self._found = discover(self.directory)
        return self._found

    def rescan(self) -> dict:
        self._found = None
        return self.found()

    def batch_projects(self) -> list[BatchProject]:
        """Every Project under this Batch, in run order (by key)."""
        return list(self.found()["projects"])

    def skipped(self) -> list[tuple[str, str]]:
        """``(key, why)`` for every directory the walk dropped."""
        return list(self.found()["skipped"])

    @property
    def truncated(self) -> bool:
        """The walk hit its budget — Projects deeper in were never seen."""
        return bool(self.found()["truncated"])

    def project_keys(self) -> list[str]:
        return [p.key for p in self.batch_projects()]

    def project_dirs(self) -> list[Path]:
        return [p.directory for p in self.batch_projects()]

    def projects(self) -> list[Project]:
        return [Project(d) for d in self.project_dirs()]

    def blocked_count(self) -> int:
        return sum(len(p.blocked) for p in self.batch_projects())

    @property
    def designated_script(self) -> str | None:
        """The Project Script name a Batch Run executes in every Project."""
        name = self.config.get("script")
        return str(name) if name else None

    def project_scripts(self) -> list[dict]:
        """Central Project Scripts — one recipe serving every Project."""
        return cfgmod.scripts_of(self.config, "project_scripts")

    def save(self) -> Path:
        return cfgmod.write_yaml(self.config_path, self.config)

    # ── running ────────────────────────────────────────────────────────────

    def run(self, script_name: str | None = None, log=None,
            project_names: list[str] | None = None) -> BatchResult:
        """Run one Project Script in every Project, continue-on-error.

        *project_names* limits the run to those Project keys — the confirmed
        target list from the preflight. ``None`` means every Project the walk
        found. Unchecking a Project means "do not touch this one", and
        recursive discovery surfaces Projects the user may not have known
        were there, so scoping is not optional decoration.

        *script_name* (or, failing that, the Batch's designation) names one
        script to run everywhere. **No designation means "each Project's own
        ``batch`` script"** — there is no implicit built-in fallback, because
        every ``project.yaml`` is created with one and a silent substitution
        would hide that a Project's script had been deleted.

        A Project whose script refuses to start (ADR-0002: a step naming an
        action its Experiment Type does not provide is a hard error) is logged,
        counted as a failure, and the Batch moves to the next Project.
        """
        from ..script_editor import project_actions

        emit = log or (lambda _m: None)
        wanted = script_name or self.designated_script
        result = BatchResult()

        targets = self._targets(project_names)
        if not targets:
            emit(f"No Projects under {self.directory} — nothing to run.")
            return result

        for key, why in self.skipped():
            emit(f"[batch] {key} skipped — {why}")
        if self.truncated:
            emit(f"[batch] the scan of {self.directory} stopped early — this "
                 "folder is larger than a batch should be, and projects "
                 "deeper in it were never found.")
        for nested in nested_batch_files(self.directory):
            emit(f"[batch] {nested} is ignored — only the selected batch's "
                 f"{cfgmod.BATCH_FILENAME} governs this run.")

        for entry in targets:
            prefix = f"[{entry.key}] "
            if entry.blocked:
                ## Reported, never a refusal: a stale folder must not stop ten
                ## Projects at 2am. The denominator matters too — "succeeded"
                ## must not read as "analysed everything".
                emit(f"{prefix}{len(entry.blocked)} blocked member(s) will not "
                     f"be analysed: "
                     + "; ".join(m.describe() for m in entry.blocked))
            try:
                project = Project(entry.directory)
            except Exception as exc:  # noqa: BLE001 - one bad Project must not stop the Batch
                emit(f"{prefix}skipped: {exc}")
                result.outcomes.append(ProjectOutcome(entry.key, False, str(exc)))
                continue

            steps, _source, note = resolve_designated_script(
                wanted, self.project_scripts(), project)
            if steps is None:
                msg = (f"no Project Script named {wanted!r} in this Project, in "
                       f"{cfgmod.BATCH_FILENAME}, or among the built-ins"
                       if wanted else
                       "no Project Script to run — author one in the Script "
                       "Editor (the default is named "
                       f"{project_actions.DEFAULT_PROJECT_SCRIPT_NAME!r})")
                emit(f"{prefix}skipped: {msg}")
                result.outcomes.append(ProjectOutcome(entry.key, False, msg))
                continue

            if note:
                emit(f"{prefix}{note}")
            try:
                project_actions.run_script(
                    project, steps, log=lambda m, p=prefix: emit(f"{p}{m}")
                )
            except Exception as exc:  # noqa: BLE001 - continue-on-error is the point
                emit(f"{prefix}FAILED: {exc}")
                result.outcomes.append(ProjectOutcome(entry.key, False, str(exc)))
            else:
                result.outcomes.append(ProjectOutcome(
                    entry.key, True, usable=len(entry.usable),
                    total=len(entry.members)))

        emit(result.summary())
        return result

    def _targets(self, project_names) -> list[BatchProject]:
        """The Projects this run visits.

        *project_names* is the confirmed target list from the preflight, given
        as keys. Matching normalizes both sides, so a caller that still passes
        bare folder names for a flat Batch keeps working.
        """
        found = self.batch_projects()
        if project_names is None:
            return found
        wanted = {str(n).replace(os.sep, "/").strip("/") for n in project_names}
        return [p for p in found if p.key in wanted]


def resolve_designated_script(name: str | None, central_scripts: list[dict],
                              project: Project) -> tuple[list[dict] | None, str, str | None]:
    """Resolve the designated Project Script *name* for *project*.

    Order: the Batch's central ``project_scripts:``, then the Project's own
    ``scripts:``, then the built-ins — central first, so one recipe in
    ``batch.yaml`` really does serve every Project.

    *name* of ``None`` means "no designation": the Project runs its OWN
    default script, the one named ``batch`` that every ``project.yaml`` is
    created with, else its first authored script. There is deliberately no
    built-in fallback here — a Project whose ``scripts:`` is empty does not
    run, and says so.

    Returns ``(steps, source, note)``; ``(None, "", None)`` when the name
    resolves nowhere. *note* explains a conditionally dropped step.
    """
    from ..script_editor import project_actions

    own = {str(s.get("name")): s for s in project.scripts()}
    if not name:
        script = own.get(project_actions.DEFAULT_PROJECT_SCRIPT_NAME)
        if script is None:
            scripts = project.scripts()
            script = scripts[0] if scripts else None
        if script is None:
            return None, "", None
        return list(script.get("steps") or []), "project.yaml scripts", None

    for script in central_scripts:
        if script.get("name") == name:
            return list(script.get("steps") or []), f"{cfgmod.BATCH_FILENAME} project_scripts", None
    if name in own:
        return list(own[name].get("steps") or []), "project.yaml scripts", None
    if name == "Report pipeline":
        steps, note = project_actions.report_pipeline_for(project)
        return steps, "built-in", note
    steps = project_actions.builtin_steps(name)
    if steps is None:
        return None, "", None
    return steps, "built-in", None
