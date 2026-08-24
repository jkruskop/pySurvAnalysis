"""The Batch — a directory of Projects, run unattended.

Purely a processing convenience: a Batch holds no analysis of its own, never
combines results, and is not itself a Project. Being one is structural — a
``batch.yaml`` appears only once batch-level scripting is authored, because
unlike a Project a Batch has no authority to declare.

A **Batch Run** executes one designated Project Script in every Project,
continue-on-error with per-Project log prefixes, and its only product is a
per-Project run summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfgmod
from .project import Project, is_project_dir


@dataclass
class ProjectOutcome:
    """What one Project's leg of a Batch Run produced."""

    name: str
    ok: bool
    message: str = ""


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
        if not bad:
            return f"Batch run: {total} Project(s) completed."
        names = ", ".join(o.name for o in self.failures)
        return f"Batch run: {total - bad}/{total} Projects completed; failed: {names}."


class Batch:
    """A directory whose immediate subdirectories holding ``project.yaml`` are
    its Projects."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        self.config = cfgmod.read_yaml(self.directory / cfgmod.BATCH_FILENAME)

    @property
    def name(self) -> str:
        return self.directory.name

    @property
    def config_path(self) -> Path:
        return self.directory / cfgmod.BATCH_FILENAME

    def project_dirs(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(d for d in self.directory.iterdir()
                      if d.is_dir() and is_project_dir(d))

    def projects(self) -> list[Project]:
        return [Project(d) for d in self.project_dirs()]

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

    def run(self, script_name: str | None = None, log=None) -> BatchResult:
        """Run one Project Script in every Project, continue-on-error.

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

        dirs = self.project_dirs()
        if not dirs:
            emit(f"No Projects under {self.directory} — nothing to run.")
            return result

        for d in dirs:
            prefix = f"[{d.name}] "
            try:
                project = Project(d)
            except Exception as exc:  # noqa: BLE001 - one bad Project must not stop the Batch
                emit(f"{prefix}skipped: {exc}")
                result.outcomes.append(ProjectOutcome(d.name, False, str(exc)))
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
                result.outcomes.append(ProjectOutcome(d.name, False, msg))
                continue

            if note:
                emit(f"{prefix}{note}")
            try:
                project_actions.run_script(
                    project, steps, log=lambda m, p=prefix: emit(f"{p}{m}")
                )
            except Exception as exc:  # noqa: BLE001 - continue-on-error is the point
                emit(f"{prefix}FAILED: {exc}")
                result.outcomes.append(ProjectOutcome(d.name, False, str(exc)))
            else:
                result.outcomes.append(ProjectOutcome(d.name, True))

        emit(result.summary())
        return result


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
