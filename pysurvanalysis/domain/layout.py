"""Experiment Directory layout: what a Batch Run can actually use.

A Project's Member Experiments are discovered by their
``survival_config.yaml`` — but a directory can carry that file and still be
unusable, and a directory holding a perfectly good workbook can be invisible
because nobody scaffolded a config for it. This module names those states so
they are reported *before* an unattended run rather than three hours into one:

* :func:`classify` — what a directory is, and why a run cannot use it.
* :func:`members_in` — every experiment-shaped subdirectory of a Project,
  healthy or **Blocked**, de-duplicated by real path.

"Usable" is decided with the loader's own rule — the same
``DATA_SUFFIXES``/``is_data_file`` filter and the same ``data/``-then-root
search order :class:`SurvivalExperiment.data_file` uses — never a lookalike. A
classifier that says "healthy" where the loader says "no .xlsx/.csv/.tsv
found" is worse than no classifier: it moves the failure from the preflight,
where someone is looking, into the middle of a Batch Run.

**Deliberate divergence from PyTrackingAnalysis.** Upstream's equivalent
module also *files* an "Unfiled Recording" — a DTrack export loose at the
experiment root — into ``data/``, because its loader reads ``data/`` alone.
There is no such state here: this loader searches ``data/`` and then the
directory root, so a workbook at either is already found. What is left of
upstream's blocked-set are the states this loader really does refuse — no
config, no data, and an ambiguous directory holding several candidate files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import config as cfgmod

#: Subdirectories of a Project that are never Member Experiments. Output
#: directories are the one thing reliably not a member, and without this a
#: Project root that also holds a stray workbook has its own ``data/`` listed
#: as a candidate member.
_NOT_MEMBERS = {"data", "analysis", "qc", "figures", "__pycache__"}

# Status values. The empty string is "not experiment-shaped at all", which is
# not a problem to report — most subdirectories of anything are not.
NOT_AN_EXPERIMENT = ""
OK = "ok"
NO_CONFIG = "no config"
NO_DATA = "no data"
AMBIGUOUS = "ambiguous"
UNREADABLE = "unreadable"

#: Which action clears each status. ``None`` means no button can fix it.
_FIX = {NO_CONFIG: "config", AMBIGUOUS: "data_file"}


@dataclass(frozen=True)
class MemberLayout:
    """What one directory is, from its layout alone — no data is read.

    The config *is* parsed (cheaply, and only to honour a ``data_file:`` key),
    because ignoring it would call an explicitly-named input ambiguous.
    """

    directory: Path
    name: str
    status: str
    detail: str = ""
    #: Candidate input files the loader would consider, by name.
    candidates: tuple[str, ...] = ()
    #: Whether ``survival_config.yaml`` is present — the Project's own
    #: membership test, which is not the same question as "can it run".
    configured: bool = False

    @property
    def blocked(self) -> bool:
        """A run cannot use this directory as it stands."""
        return self.status not in (OK, NOT_AN_EXPERIMENT)

    @property
    def usable(self) -> bool:
        return self.status == OK

    @property
    def fix(self) -> str | None:
        """``"config"``, ``"data_file"``, or None when nothing can repair it."""
        return _FIX.get(self.status)

    def describe(self) -> str:
        return f"{self.name}: {self.status}" + (f" — {self.detail}" if self.detail else "")


def _readable(directory: Path) -> bool:
    try:
        os.listdir(directory)
    except OSError:
        return False
    return True


def _candidates(base: Path) -> list[Path]:
    """Input files the loader would find directly in *base*, in its order."""
    from .experiment import is_data_file

    if not os.path.isdir(base):
        return []
    try:
        return sorted(p for p in base.iterdir() if is_data_file(p))
    except OSError:
        return []


def data_candidates(directory: Path) -> tuple[Path, list[Path]]:
    """``(base, files)`` — where the loader would look, and what it finds.

    Mirrors :meth:`SurvivalExperiment.data_file`'s search exactly: ``data/``
    first, then the directory root, stopping at the first base that holds
    anything. Stopping matters — a directory with one workbook in ``data/``
    and an old copy at the root is unambiguous to the loader, and calling it
    ambiguous here would block a run that would have succeeded.
    """
    directory = Path(directory)
    for base in (directory / "data", directory):
        found = _candidates(base)
        if found:
            return base, found
    return directory, []


def has_config(directory: Path | str) -> bool:
    """``survival_config.yaml`` at the root — the membership test.

    Deliberately :func:`config.is_experiment_dir` itself: a directory this
    says has no config is one the Project genuinely cannot see, which is what
    makes "scaffold a config" the right offer.
    """
    return cfgmod.is_experiment_dir(directory)


def classify(directory: Path | str) -> MemberLayout:
    """What *directory* is: usable member, Blocked Experiment, or neither.

    Layout plus the config's ``data_file:`` key — no data is read, so this
    stays cheap enough to run over every subdirectory of every Project in a
    Batch.
    """
    directory = Path(directory)
    name = directory.name

    def _blocked(status, detail, candidates=()):
        return MemberLayout(directory, name, status, detail,
                            tuple(candidates), configured)

    if not os.path.isdir(directory):
        return MemberLayout(directory, name, NOT_AN_EXPERIMENT)
    if not _readable(directory):
        ## Unknown is not the same as absent: a directory nobody can list may
        ## hold a member, and silently dropping it would overstate the
        ## Project's coverage in both the preflight and the run summary.
        return MemberLayout(directory, name, UNREADABLE,
                            "cannot be listed (permissions?)")

    configured = has_config(directory)

    ## An explicit `data_file:` settles the question before any search — it is
    ## exactly how the loader resolves an otherwise-ambiguous directory, and
    ## the fix this module offers for one.
    named = cfgmod.load_config(directory).get("data_file") if configured else None
    if named:
        candidate = Path(named)
        if not candidate.is_absolute():
            candidate = directory / candidate
        if os.path.isfile(candidate):
            return MemberLayout(directory, name, OK, candidates=(str(named),),
                                configured=True)
        return _blocked(NO_DATA,
                        f"`data_file: {named}` does not exist (looked at "
                        f"{candidate})")

    base, found = data_candidates(directory)
    names = tuple(p.name for p in found)
    where = "data/" if base != directory else "the directory root"

    if len(found) > 1:
        ## The loader raises here rather than picking one, so this is a real
        ## block — and unlike upstream's equivalent it has a real fix: name
        ## one with `data_file:`.
        detail = (f"{len(found)} data files in {where} "
                  f"({', '.join(names[:3])}) — which is the experiment?")
        if not configured:
            ## Nothing to write the answer into yet; the config comes first.
            return _blocked(NO_CONFIG,
                            f"holds {len(found)} data files but no "
                            f"{cfgmod.CONFIG_FILENAME}", names)
        return _blocked(AMBIGUOUS, detail, names)

    if found:
        if configured:
            return MemberLayout(directory, name, OK, candidates=names,
                                configured=True)
        return _blocked(NO_CONFIG,
                        f"holds {names[0]} but no {cfgmod.CONFIG_FILENAME}",
                        names)

    if configured:
        return _blocked(NO_DATA,
                        f"{cfgmod.CONFIG_FILENAME} but no "
                        f".xlsx/.csv/.tsv in data/ or the directory root")
    return MemberLayout(directory, name, NOT_AN_EXPERIMENT)


def members_in(project_dir: Path | str) -> list[MemberLayout]:
    """Classify every immediate subdirectory of *project_dir* that could be a
    Member Experiment, in name order.

    Symlinked directories are followed — :meth:`Project.member_dirs` counts
    them, so refusing to would make a Project of symlinked members look empty
    — but a symlinked *copy* of a member already seen is dropped: the same
    recording analysed twice under two names is the failure, not the symlink
    itself. Output directories are excluded by name, unless one carries a
    config of its own: a member somebody named ``data`` is a member, and
    discovery disagreeing with the Project about its own membership is worse
    than the odd name.
    """
    project_dir = Path(project_dir)
    found: list[MemberLayout] = []
    seen: set[str] = set()
    try:
        entries = sorted(project_dir.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for path in entries:
        if path.name.startswith("."):
            continue
        if not os.path.isdir(path):
            continue
        if path.name.lower() in _NOT_MEMBERS and not has_config(path):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        item = classify(path)
        if item.status != NOT_AN_EXPERIMENT:
            found.append(item)
    return found
