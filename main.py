"""Entry point for pySurvAnalysis.

Subcommands::

    pysurvanalysis hub [path]             # launch the Analysis Hub
    pysurvanalysis qc [experiment_dir]    # launch the QC Viewer
    pysurvanalysis plots <experiment_dir> # launch the Plot Editor
    pysurvanalysis run <path> [opts]      # analyse one experiment
    pysurvanalysis project <dir> [--script NAME]
    pysurvanalysis batch <dir> [--script NAME]
    pysurvanalysis upgrade <dir> [--type KEY] [--dry-run]

``run`` takes an Experiment Directory (config-driven, writes ``analysis/``) or
a bare data file (a Custom Experiment, writes ``<stem>_results/`` as before).

Without a subcommand, launches the Hub.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "input_path",
        metavar="INPUT",
        help="Experiment Directory, a directory holding one .xlsx, or a data file.",
    )
    p.add_argument("--output-dir", "-o", default=None,
                   help="Output dir (defaults to analysis/ for an Experiment "
                        "Directory, else <stem>_results/).")
    p.add_argument("--no-assume-censored", action="store_true",
                   help="Excel: don't assume unaccounted individuals are censored.")
    p.add_argument("--time-col", default="Age", help="CSV time column (default: Age).")
    p.add_argument("--event-col", default="Event", help="CSV event column (default: Event).")
    p.add_argument("--factor-cols", nargs="+", default=None, metavar="COL",
                   help="CSV long: factor column names.")
    p.add_argument("--format", dest="csv_format", choices=["auto", "long", "wide"],
                   default="auto", help="CSV format hint.")
    p.add_argument("--col-mapping", default=None, metavar="YAML",
                   help="CSV wide: YAML file with column-to-group mapping.")
    p.add_argument("--factor-names", nargs=2, default=None, metavar=("F1", "F2"),
                   help="CSV wide: two factor names.")
    p.add_argument("--exclusion-group", default=None,
                   help="Apply this exclusion group (overrides the config's).")
    p.add_argument("--figures", action="store_true",
                   help="Also render the Publication Figures.")


def _cmd_hub(args: argparse.Namespace) -> int:
    from pysurvanalysis.apps.hub import main as hub_main

    sys.argv = [sys.argv[0]] + ([str(args.path)] if args.path else [])
    hub_main()
    return 0


def _cmd_qc(args: argparse.Namespace) -> int:
    from pysurvanalysis.apps.qc_viewer import main as qc_main

    sys.argv = [sys.argv[0]] + ([str(args.path)] if args.path else [])
    qc_main()
    return 0


def _cmd_plots(args: argparse.Namespace) -> int:
    from pysurvanalysis.apps.plot_editor import main as plots_main

    sys.argv = [sys.argv[0], str(args.path)]
    plots_main()
    return 0


def _load_experiment(path: Path):
    """An Experiment Directory (with its Project's defaults), or ``None``."""
    from pysurvanalysis.domain import (
        Project, SurvivalExperiment, is_experiment_dir, is_project_dir,
    )

    if not path.is_dir() or not is_experiment_dir(path):
        return None
    project = Project(path.parent) if is_project_dir(path.parent) else None
    return SurvivalExperiment(path, defaults=project.defaults if project else {},
                              project=project)


def _cmd_run(args: argparse.Namespace) -> int:
    from pysurvanalysis.pipeline import run_analysis

    path = Path(args.input_path)
    experiment = _load_experiment(path)

    extra_excluded: set = set()
    if args.exclusion_group:
        from pysurvanalysis import exclusions

        base = path if path.is_dir() else path.parent
        extra_excluded = exclusions.chambers_for_group(base, args.exclusion_group)
        if extra_excluded:
            print(f"Excluding {len(extra_excluded)} chamber(s) from group "
                  f"'{args.exclusion_group}'.")

    if experiment is not None:
        print(f"{experiment.name}: {experiment.type.label}")
        problems = experiment.validate()
        if problems:
            print("Configuration problems:")
            for problem in problems:
                print(f"  - {problem}")
            return 2
        result = experiment.run_analysis(log=print, extra_excluded=extra_excluded)
        if args.figures:
            from pysurvanalysis import pubfigures

            pubfigures.render_all(experiment, log=print)
    else:
        col_mapping = None
        if args.col_mapping:
            import yaml

            with open(args.col_mapping, "r", encoding="utf-8") as fh:
                col_mapping = yaml.safe_load(fh)
        result = run_analysis(
            args.input_path,
            args.output_dir,
            assume_censored=not args.no_assume_censored,
            time_col=args.time_col,
            event_col=args.event_col,
            factor_cols=args.factor_cols,
            csv_format=args.csv_format,
            col_mapping=col_mapping,
            factor_names=args.factor_names,
            extra_excluded_chambers=extra_excluded,
            log=print,
        )

    print(f"Analysis complete. Results in {result.output_dir}")
    es = result.experiment_summary or {}
    if es:
        print("\nExperiment summary:")
        print(f"  Treatments:  {es.get('n_treatments', '?')}")
        print(f"  Chambers:    {es.get('n_chambers', 'N/A')}")
        print(f"  Total N:     {es.get('n_total', '?')}")
        print(f"  Deaths:      {es.get('n_deaths', '?')}")
        print(f"  Censored:    {es.get('n_censored', '?')} "
              f"({es.get('pct_censored', '?')}%)")
        print(f"  Time range:  {es.get('time_min', '?')} – {es.get('time_max', '?')}")
    return 0


def _cmd_project(args: argparse.Namespace) -> int:
    from pysurvanalysis.domain import Project
    from pysurvanalysis.script_editor import project_actions

    project = Project(Path(args.path))
    name = args.script or "Report pipeline"
    steps = None
    for script in project.scripts():
        if script.get("name") == name:
            steps = list(script.get("steps") or [])
    steps = steps if steps is not None else project_actions.builtin_steps(name)
    if steps is None:
        print(f"No Project Script named {name!r}. Available: "
              f"{', '.join([s['name'] for s in project.scripts()] + project_actions.builtin_names())}")
        return 2
    project_actions.run_script(project, steps, log=print)
    return 0


def _cmd_batch(args: argparse.Namespace) -> int:
    from pysurvanalysis.domain import Batch

    batch = Batch(Path(args.path))
    result = batch.run(args.script, log=print)
    return 1 if result.failures else 0


def _cmd_upgrade(args: argparse.Namespace) -> int:
    from pysurvanalysis.domain import upgrade

    plan = upgrade.plan(Path(args.path), args.type)
    if plan.is_noop:
        print("Nothing to upgrade." + ("\n  " + "\n  ".join(plan.warnings)
                                       if plan.warnings else ""))
        return 0
    print("This upgrade will:")
    for action in plan.actions:
        print(f"  - {action}")
    for warning in plan.warnings:
        print(f"  ! {warning}")
    if args.dry_run:
        print("(dry run — nothing written)")
        return 0
    upgrade.apply(plan)
    print(f"Upgraded {plan.directory}.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pysurvanalysis",
        description="pySurvAnalysis — survival analysis pipeline + apps",
    )
    sub = parser.add_subparsers(dest="cmd")

    for name, summary in (
        ("hub", "Launch the Analysis Hub (default)."),
        ("qc", "Launch the QC Viewer."),
    ):
        sp = sub.add_parser(name, help=summary)
        sp.add_argument("path", nargs="?", help="Optional directory.")

    sp_plots = sub.add_parser("plots", help="Launch the Plot Editor.")
    sp_plots.add_argument("path", help="Experiment Directory.")

    sp_run = sub.add_parser("run", help="Analyse one experiment.")
    _add_run_args(sp_run)

    sp_project = sub.add_parser("project", help="Run a Project Script.")
    sp_project.add_argument("path", help="Project directory.")
    sp_project.add_argument("--script", default=None,
                            help="Project Script name (default: Report pipeline).")

    sp_batch = sub.add_parser("batch", help="Run a Project Script in every Project.")
    sp_batch.add_argument("path", help="Batch directory.")
    sp_batch.add_argument("--script", default=None,
                          help="Project Script name (default: batch.yaml's).")

    sp_upgrade = sub.add_parser("upgrade", help="Upgrade a pre-overhaul directory.")
    sp_upgrade.add_argument("path", help="Directory to upgrade.")
    sp_upgrade.add_argument("--type", default=None,
                            help="Experiment type key to seed the config with.")
    sp_upgrade.add_argument("--dry-run", action="store_true",
                            help="Describe the upgrade without writing.")

    args = parser.parse_args()
    handlers = {
        "qc": _cmd_qc,
        "plots": _cmd_plots,
        "run": _cmd_run,
        "project": _cmd_project,
        "batch": _cmd_batch,
        "upgrade": _cmd_upgrade,
    }
    if args.cmd in handlers:
        sys.exit(handlers[args.cmd](args))
    if args.cmd is None:
        args = argparse.Namespace(path=None)
    sys.exit(_cmd_hub(args))


if __name__ == "__main__":
    main()
