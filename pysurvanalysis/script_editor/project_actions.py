"""Project-level action registry — the second script level.

Same step shape and the same visual editor as an Experiment Script, but a
separate registry dispatching over a
:class:`~pysurvanalysis.script_editor.spec.ProjectRunContext` that holds a
Project, never an experiment. The levels cannot mix by construction.

The only bridge downward is ``run_in_experiments``, which runs a named
Experiment Script in every Member Experiment — or, with ``only:``, in just
those named — continue-on-error, because one broken member must not cost you
the other nine.
"""

from __future__ import annotations

from typing import Any

from ..ui import Category
from .spec import Action, ParamSpec, ProjectRunContext, RunContext


def _parse_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _exec_validate_project(_params: dict, ctx: ProjectRunContext) -> None:
    problems = ctx.project.validate()
    if problems:
        raise RuntimeError(
            "Project validation failed:\n  - " + "\n  - ".join(problems)
        )
    ctx.log(f"{len(ctx.project.members())} member(s) validated.")
    for divergence in ctx.project.divergences():
        ctx.log(f"  divergence — {divergence}")


def _exec_run_in_experiments(params: dict, ctx: ProjectRunContext) -> None:
    from . import actions as experiment_actions

    name = str(params.get("script") or "").strip()
    if not name:
        raise RuntimeError("run_in_experiments: no script named.")
    only = set(_parse_list(params.get("only")))

    members = [m for m in ctx.project.members() if not only or m.name in only]
    unknown = only - {m.name for m in ctx.project.members()}
    for missing in sorted(unknown):
        ctx.log(f"  {missing}: not a member of this Project — skipped.")
        ctx.failures.append(missing)
    if not members:
        ctx.log("run_in_experiments: no members to run.")
        return

    for member in members:
        prefix = f"  [{member.name}] "
        steps = _member_script(member, ctx.project, name)
        if steps is None:
            ctx.log(f"{prefix}no Experiment Script named {name!r} — skipped.")
            ctx.failures.append(member.name)
            continue
        problems = experiment_actions.validate_steps(steps, member.type)
        if problems:
            # ADR-0002: a hard error, and the Project's run stops here rather
            # than producing a report that looks complete.
            raise RuntimeError(
                f"{member.name}: script {name!r} cannot run as a "
                f"{member.type.label}:\n  - " + "\n  - ".join(problems)
            )
        try:
            run_experiment_script(member, steps,
                                  log=lambda m, p=prefix: ctx.log(f"{p}{m}"))
        except Exception as exc:  # noqa: BLE001 - continue-on-error across members
            ctx.log(f"{prefix}FAILED: {exc}")
            ctx.failures.append(member.name)

    done = len(members) - len([f for f in ctx.failures if f in
                               {m.name for m in members}])
    ctx.log(f"run_in_experiments({name}): {done}/{len(members)} member(s) completed.")


def _exec_render_publication_figures(params: dict, ctx: ProjectRunContext) -> None:
    """Render the Project's curated Publication Figures for every member.

    The curation lives in the **Project's** ``plot_specs.yaml`` — one set of
    Specs and Styles every member renders with. A Project that has curated
    nothing renders nothing: this runs unattended inside a Batch Run, and
    nobody asked for default-spec figures. (A Spec a member still carries
    from the old per-member layout is honoured via the same adoption rule
    the Plot Editor uses.)
    """
    from .. import pubfigures

    fmt = str(params.get("format") or "svg")
    total = 0
    rendered = 0
    members = ctx.project.members()
    for member in members:
        if not pubfigures.adopt_legacy_member_specs(member).plots:
            ctx.log(f"  [{member.name}] nothing curated — skipped.")
            continue
        ctx.log(f"  [{member.name}] publication figures…")
        rendered += 1
        total += len(pubfigures.render_all(
            member, fmt=fmt, log=lambda m, p=member.name: ctx.log(f"  [{p}] {m}")))
    if not rendered:
        ctx.log("render_publication_figures: this Project has no curated "
                "figure specs — nothing rendered. Curate figures in the "
                "Plot Editor first.")
        return
    ctx.log(f"{total} publication figure(s) across {rendered}/{len(members)} member(s).")


def _exec_project_report(params: dict, ctx: ProjectRunContext) -> None:
    from .. import project_report

    formats = tuple(_parse_list(params.get("formats")) or ("pdf", "md"))
    narrative = None
    if params.get("with_narrative"):
        from ..ai import narrative as ai_narrative

        narrative = ai_narrative.generate(ctx.project, log=ctx.log)
    written = project_report.write_project_report(
        ctx.project, formats=formats, narrative=narrative, log=ctx.log)
    if not written:
        raise RuntimeError("project_report: nothing was written.")


def _exec_generate_ai_narrative(params: dict, ctx: ProjectRunContext) -> None:
    from ..ai import narrative as ai_narrative

    # Soft-fail by contract: a provider outage logs and the pipeline continues.
    try:
        result = ai_narrative.generate(ctx.project, log=ctx.log,
                                       provider=params.get("provider") or None)
    except Exception as exc:  # noqa: BLE001
        ctx.log(f"AI narrative skipped: {exc}")
        return
    if result:
        ctx.log(f"AI narrative written for {len(result)} section(s).")


PROJECT_ACTIONS: dict[str, Action] = {
    "validate_project": Action(
        key="validate_project",
        title="Validate project",
        description=(
            "Check that every member shares the Project's Experiment Type and "
            "is configured; report divergence without failing on it."
        ),
        category=Category.TOOLS,
        icon_name="validate",
        params=(),
        execute_fn=_exec_validate_project,
    ),
    "run_in_experiments": Action(
        key="run_in_experiments",
        title="Run in experiments",
        description=(
            "Run a named Experiment Script in every Member Experiment "
            "(or just those listed)."
        ),
        category=Category.SCRIPTS,
        icon_name="script",
        params=(
            ParamSpec("script", "string", "Experiment script name"),
            ParamSpec("only", "list", "Only these members (blank = all)"),
        ),
        execute_fn=_exec_run_in_experiments,
    ),
    "render_publication_figures": Action(
        key="render_publication_figures",
        title="Render publication figures",
        description="Write every member's vector Publication Figures.",
        category=Category.PLOTS,
        icon_name="figures",
        params=(
            ParamSpec("format", "choice", "Format", default="svg",
                      choices=("svg", "pdf", "png")),
        ),
        execute_fn=_exec_render_publication_figures,
    ),
    "project_report": Action(
        key="project_report",
        title="Project report",
        description=(
            "Bind one independent section per Member Experiment into "
            "<project>_report.pdf, with the inventory and divergence note."
        ),
        category=Category.ANALYZE,
        icon_name="report",
        params=(
            ParamSpec("formats", "list", "Formats", default="pdf,md"),
            ParamSpec("with_narrative", "bool", "Include AI narrative",
                      default=False),
        ),
        execute_fn=_exec_project_report,
    ),
    "generate_ai_narrative": Action(
        key="generate_ai_narrative",
        title="Generate AI narrative",
        description=(
            "Write a per-member summary plus a labelled across-members "
            "paragraph. Summarizes saved numbers; never computes its own."
        ),
        category=Category.AI,
        icon_name="ai",
        params=(
            ParamSpec("provider", "choice", "Provider", default="",
                      choices=("", "anthropic", "openai")),
        ),
        execute_fn=_exec_generate_ai_narrative,
    ),
}


# ---------------------------------------------------------------------------
# Built-in Project Scripts
# ---------------------------------------------------------------------------

BUILTIN_SCRIPTS: dict[str, list[dict]] = {
    "Standard pipeline": [
        {"action": "validate_project"},
        {"action": "run_in_experiments", "script": "Standard analysis"},
        {"action": "render_publication_figures"},
        {"action": "project_report"},
    ],
    # Preferred for an unattended run: it does not gate on validation, which
    # would fail a Project mid-migration.
    "Report pipeline": [
        {"action": "run_in_experiments", "script": "Standard analysis"},
        {"action": "render_publication_figures"},
        {"action": "project_report"},
    ],
}

#: The Experiment Script every member gets by default — named by the built-in
#: Project Scripts above, and resolved from here when nothing defines it.
BUILTIN_EXPERIMENT_SCRIPTS: dict[str, list[dict]] = {
    "Standard analysis": [
        {"action": "run_analysis"},
    ],
}


#: The Project Script every ``project.yaml`` is created with. It is named
#: after what it *is* — the script a Batch Run executes in this Project —
#: rather than after the built-in it was copied from, which hid that.
DEFAULT_PROJECT_SCRIPT_NAME = "batch"


def default_project_script() -> dict:
    """A fresh copy of the default Project Script, for seeding a
    ``project.yaml``.

    A copy, not a shared constant: the caller writes it into a file the user
    then edits. Written out rather than left in code so a user reading their
    ``project.yaml`` can see what a Batch Run will do here, and change it.
    """
    return {
        "name": DEFAULT_PROJECT_SCRIPT_NAME,
        "notes": ("Created with the project, and what a Batch Run runs here "
                  "unless another script is designated. Analyses every member, "
                  "renders their curated publication figures, then builds the "
                  "project report. Edit or replace it in the Script Editor — a "
                  "project with no script here cannot be run from the Project "
                  "card or a Batch Run."),
        "steps": [dict(step) for step in BUILTIN_SCRIPTS["Report pipeline"]],
    }


def report_pipeline_for(project) -> tuple[list[dict], str | None]:
    """The Report pipeline as it will actually run on *project*.

    The figure step is dropped up front when no member has curated Specs, so
    an unattended run says so before it starts rather than logging a skip per
    member. Returns ``(steps, note)``; *note* explains a dropped step.
    """
    from .. import pubfigures

    steps = list(BUILTIN_SCRIPTS["Report pipeline"])
    ## The curation is the Project's now; a leftover per-member spec still
    ## counts, through the same adoption rule the renderer applies.
    if pubfigures.load_specs(project.directory) or any(
            pubfigures.adopt_legacy_member_specs(m).plots
            for m in project.members()):
        return [dict(s) for s in steps], None
    kept = [dict(s) for s in steps if s.get("action") != "render_publication_figures"]
    return kept, "no curated figure specs in this project — figure step skipped"


def builtin_steps(name: str) -> list[dict] | None:
    steps = BUILTIN_SCRIPTS.get(name)
    return list(steps) if steps else None


def builtin_names() -> list[str]:
    return list(BUILTIN_SCRIPTS)


def _member_script(member, project, name: str) -> list[dict] | None:
    """Resolve an Experiment Script name: Project's central set, then the
    member's own, then the shipped default."""
    for script in project.experiment_scripts():
        if script.get("name") == name:
            return list(script.get("steps") or [])
    from ..domain import config as cfgmod

    for script in cfgmod.scripts_of(member.raw_config, "scripts"):
        if script.get("name") == name:
            return list(script.get("steps") or [])
    steps = BUILTIN_EXPERIMENT_SCRIPTS.get(name)
    return list(steps) if steps else None


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def run_experiment_script(experiment, steps, log=None, figure=None) -> RunContext:
    """Execute an Experiment Script against one Experiment Directory."""
    from . import actions as experiment_actions

    emit = log or (lambda _m: None)
    problems = experiment_actions.validate_steps(steps, experiment.type)
    if problems:
        raise RuntimeError(
            f"{experiment.name}: this script cannot run as a "
            f"{experiment.type.label}:\n  - " + "\n  - ".join(problems)
        )

    registry = experiment_actions.registry_for(experiment.type)
    ctx = RunContext(
        project_dir=experiment.directory,
        experiment=experiment,
        log=emit,
        figure=figure or (lambda _t, _f: None),
        assume_censored=experiment.type.resolve_assume_censored(experiment.config),
        exclusion_group=experiment.exclusion_group,
    )
    for i, step in enumerate(steps or [], 1):
        key = step.get("action")
        action = registry[key]
        emit(f"[{i}/{len(steps)}] {action.title}")
        params = {k: v for k, v in step.items() if k != "action"}
        action.execute(params, ctx)
    return ctx


def run_script(project, steps, log=None, figure=None) -> ProjectRunContext:
    """Execute a Project Script against one Project."""
    emit = log or (lambda _m: None)
    problems = validate_project_steps(steps)
    if problems:
        raise RuntimeError(
            "This Project Script cannot run:\n  - " + "\n  - ".join(problems)
        )

    ctx = ProjectRunContext(project=project, log=emit,
                            figure=figure or (lambda _t, _f: None))
    for i, step in enumerate(steps or [], 1):
        action = PROJECT_ACTIONS[step["action"]]
        emit(f"[{i}/{len(steps)}] {action.title}")
        params = {k: v for k, v in step.items() if k != "action"}
        action.execute(params, ctx)
    if ctx.failures:
        emit(f"Completed with {len(ctx.failures)} member failure(s): "
             f"{', '.join(sorted(set(ctx.failures)))}")
    return ctx


def validate_project_steps(steps) -> list[str]:
    problems: list[str] = []
    for i, step in enumerate(steps or [], 1):
        key = (step or {}).get("action")
        if not key:
            problems.append(f"Step {i} has no action.")
        elif key not in PROJECT_ACTIONS:
            problems.append(
                f"Step {i} uses project action {key!r}, which does not exist. "
                f"Available: {', '.join(sorted(PROJECT_ACTIONS))}."
            )
    return problems
