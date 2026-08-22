"""Orchestrate the full survival analysis pipeline.

This module ties together data loading, lifetable computation, statistical
tests, plotting, and report generation into a single ``run_analysis`` call.

Supports two invocation modes:
  * **Project directory mode** — pass a directory path; the single ``.xlsx``
    file inside is auto-discovered.  Outputs are written to organised
    subdirectories (``plots/``, ``statistics/``, ``data_output/``).
  * **Direct file mode** — pass a path to an ``.xlsx``, ``.csv``, or ``.tsv``
    file directly (original behaviour; backwards-compatible).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from . import data_loader, lifetable, plotting, statistics


class AnalysisResult:
    """Container for all analysis outputs."""

    def __init__(
        self,
        input_file: Path,
        output_dir: Path,
        factors: list[str],
        individual_data: pd.DataFrame,
        lifetables: pd.DataFrame,
        summary: pd.DataFrame,
        median_surv: pd.DataFrame,
        mean_surv: pd.DataFrame,
        pairwise_lr: pd.DataFrame,
        omnibus_lr: dict,
        hazard_ratios: pd.DataFrame,
        lifespan_stats: dict | None = None,
        assume_censored: bool = True,
        excluded_chambers: set | None = None,
        defined_plots: list[list[str]] | None = None,
        # New fields
        pairwise_gw: pd.DataFrame | None = None,
        parametric_models: dict | None = None,
        surv_quantiles: pd.DataFrame | None = None,
        experiment_summary: dict | None = None,
        nelson_aalen: pd.DataFrame | None = None,
    ):
        self.input_file = input_file
        self.output_dir = output_dir
        self.factors = factors
        self.individual_data = individual_data
        self.lifetables = lifetables
        self.summary = summary
        self.median_surv = median_surv
        self.mean_surv = mean_surv
        self.pairwise_lr = pairwise_lr
        self.omnibus_lr = omnibus_lr
        self.hazard_ratios = hazard_ratios
        self.lifespan_stats = lifespan_stats or {}
        self.assume_censored = assume_censored
        self.excluded_chambers: set = excluded_chambers or set()
        self.defined_plots: list[list[str]] = defined_plots or []
        self.cox_analyses: list[dict] = []
        #: The Experiment Directory this run belongs to, when there is one.
        self.experiment: Any = None
        #: The Experiment Type that chose the battery and the Plot Set.
        self.experiment_type: Any = None
        #: The active Exclusion Group's name, stamped on every output.
        self.exclusion_group: str | None = None
        #: plot id → saved figure path, in the Plot Set's order.
        self.figure_paths: dict[str, Path] = {}
        # New analysis results
        self.pairwise_gw: pd.DataFrame = pairwise_gw if pairwise_gw is not None else pd.DataFrame()
        self.parametric_models: dict = parametric_models or {}
        self.surv_quantiles: pd.DataFrame = surv_quantiles if surv_quantiles is not None else pd.DataFrame()
        self.experiment_summary: dict = experiment_summary or {}
        self.nelson_aalen: pd.DataFrame = nelson_aalen if nelson_aalen is not None else pd.DataFrame()

    def has_chambers(self) -> bool:
        """True when the input carries real chamber identities.

        CSV cohorts do not, so an Exclusion Group naming chambers cannot have
        removed anything from them — and must not be reported as if it had.
        """
        if self.individual_data is None or "chamber" not in self.individual_data:
            return False
        return not self.individual_data["chamber"].astype(str).eq("N/A").all()

    def n_excluded_applied(self) -> int:
        """How many excluded chambers this input could actually have."""
        return len(self.excluded_chambers or set()) if self.has_chambers() else 0


def _discover_xlsx(project_dir: Path) -> Path:
    """Find the single .xlsx file in a project directory.

    Raises
    ------
    FileNotFoundError
        If no .xlsx file is found.
    ValueError
        If more than one .xlsx file is found.
    """
    xlsx_files = list(project_dir.glob("*.xlsx"))
    if len(xlsx_files) == 0:
        raise FileNotFoundError(
            f"No .xlsx file found in project directory: {project_dir}"
        )
    if len(xlsx_files) > 1:
        raise ValueError(
            f"Multiple .xlsx files found in {project_dir}: "
            f"{[f.name for f in xlsx_files]}. "
            "Place exactly one .xlsx file in the project directory."
        )
    return xlsx_files[0]


def run_analysis(
    input_path: str | Path,
    output_dir: Optional[str | Path] = None,
    assume_censored: bool = True,
    # CSV-specific parameters
    time_col: str = "Age",
    event_col: str = "Event",
    factor_cols: list[str] | None = None,
    csv_format: str = "auto",
    col_mapping: list[dict] | None = None,
    factor_names: list[str] | None = None,
    factor_levels: dict[str, list] | None = None,
    # Extra chamber ids to exclude on top of any Excel ChamberFlags sheet.
    extra_excluded_chambers: set | None = None,
    # New: an Experiment Directory drives everything from its config.
    experiment: "Any" = None,
    log=None,
) -> AnalysisResult:
    """Run the complete survival analysis pipeline.

    Two ways in:

    * **Experiment mode** — pass ``experiment`` (a
      :class:`~pysurvanalysis.domain.experiment.SurvivalExperiment`). Its
      ``survival_config.yaml`` supplies the input format, the censoring policy,
      the active Exclusion Group and the **Experiment Type**, which in turn
      decides the Plot Set and the extra analyses. Outputs go to ``analysis/``.
    * **Direct mode** — pass a file (or a directory holding one ``.xlsx``) and
      the explicit keyword arguments. The experiment is treated as a Custom
      Experiment: every factor, the full battery, every figure.

    Returns an :class:`AnalysisResult` with everything computed.
    """
    from .experiment_types import CUSTOM

    emit = log or (lambda _m: None)
    exp_type = experiment.type if experiment is not None else CUSTOM
    config = dict(experiment.config) if experiment is not None else {}

    # ── Resolve the input file ─────────────────────────────────────────────
    if experiment is not None:
        input_path = experiment.data_file()
    else:
        input_path = Path(input_path)
        if input_path.is_dir():
            input_path = _discover_xlsx(input_path)
    input_path = Path(input_path)

    # ── Output directory ───────────────────────────────────────────────────
    # An Experiment Directory always writes to analysis/; direct mode keeps the
    # legacy <stem>_results/ convention so old command lines behave the same.
    if output_dir is None:
        output_dir = (experiment.analysis_dir if experiment is not None
                      else input_path.parent / f"{input_path.stem}_results")
    output_dir = Path(output_dir)
    plots_dir = output_dir / "plots"
    data_dir = output_dir / "data_output"
    stats_dir = output_dir / "statistics"
    for d in (output_dir, plots_dir, data_dir, stats_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── Exclusions ─────────────────────────────────────────────────────────
    excluded_chambers: set = set()
    defined_plots: list[list[str]] = []
    if input_path.suffix.lower() == ".xlsx":
        excluded_chambers = data_loader.load_chamber_flags(input_path)
        defined_plots = data_loader.load_defined_plots(input_path)
    if extra_excluded_chambers:
        excluded_chambers = set(excluded_chambers) | set(extra_excluded_chambers)

    exclusion_group = None
    if experiment is not None:
        from .domain import config as cfgmod

        exclusion_group = cfgmod.exclusion_group(config)

    # ── Load ───────────────────────────────────────────────────────────────
    if experiment is not None:
        from .domain import config as cfgmod

        opts = cfgmod.input_options(config)
        fmt = str(opts.get("format", "auto"))
        assume_censored = exp_type.resolve_assume_censored(config)
        time_col = str(opts.get("time_col") or time_col)
        event_col = str(opts.get("event_col") or event_col)
        factor_cols = opts.get("factor_cols", factor_cols)
        factor_names = opts.get("factor_names", factor_names)
        col_mapping = opts.get("col_mapping", col_mapping)
        csv_format = "auto" if fmt in {"auto", "excel"} else fmt

    emit(f"Loading {input_path.name}…")
    individual_data, factors = data_loader.load_experiment(
        input_path,
        assume_censored=assume_censored,
        excluded_chambers=excluded_chambers,
        time_col=time_col,
        event_col=event_col,
        factor_cols=factor_cols,
        csv_format=csv_format,
        col_mapping=col_mapping,
        factor_names=factor_names,
        factor_levels=factor_levels,
    )

    # The type may reorder levels so the Reference Level leads every grouping.
    individual_data = exp_type.prepare_data(individual_data, config)
    data_problems = exp_type.validate_data(individual_data, config)
    if data_problems:
        raise ValueError(
            f"{input_path.name} does not match its {exp_type.label} declaration:\n  - "
            + "\n  - ".join(data_problems)
        )

    # ── Compute ────────────────────────────────────────────────────────────
    emit("Computing lifetables and summary statistics…")
    lifetables = lifetable.compute_lifetables(individual_data)
    summary = statistics.summary_statistics(individual_data)
    median_surv = lifetable.median_survival(lifetables)
    mean_surv = lifetable.mean_survival(individual_data)

    emit("Running survival comparisons…")
    pairwise_lr = statistics.pairwise_logrank(individual_data)
    omnibus_lr = statistics.logrank_multi(individual_data)
    pairwise_gw = statistics.pairwise_gehan_wilcoxon(individual_data)
    hazard_ratios = statistics.pairwise_hazard_ratios(individual_data)
    lifespan_stats = lifetable.lifespan_statistics(
        individual_data, factors, assume_censored=assume_censored,
    )
    surv_quantiles = lifetable.survival_quantiles(lifetables)
    try:
        parametric_models = statistics.fit_parametric_models(individual_data)
    except Exception:  # noqa: BLE001 - a non-converging AFT fit never kills a run
        parametric_models = {}
    exp_summary = statistics.experiment_summary(individual_data)

    result = AnalysisResult(
        input_file=input_path,
        output_dir=output_dir,
        factors=factors,
        individual_data=individual_data,
        lifetables=lifetables,
        summary=summary,
        median_surv=median_surv,
        mean_surv=mean_surv,
        pairwise_lr=pairwise_lr,
        omnibus_lr=omnibus_lr,
        hazard_ratios=hazard_ratios,
        lifespan_stats=lifespan_stats,
        assume_censored=assume_censored,
        excluded_chambers=excluded_chambers,
        defined_plots=defined_plots,
        pairwise_gw=pairwise_gw,
        parametric_models=parametric_models,
        surv_quantiles=surv_quantiles,
        experiment_summary=exp_summary,
    )
    result.experiment = experiment
    result.experiment_type = exp_type
    result.exclusion_group = exclusion_group
    result.figure_paths = {}

    # ── Type-specific analyses ─────────────────────────────────────────────
    extra = exp_type.run_extra_analyses(result, config)
    if extra:
        emit(f"Running the {exp_type.label} battery…")
        result.cox_analyses.extend(extra)

    # ── Save tabular outputs ───────────────────────────────────────────────
    lifetables.to_csv(data_dir / "lifetables.csv", index=False)
    individual_data.to_csv(data_dir / "individual_data.csv", index=False)
    summary.to_csv(data_dir / "summary.csv", index=False)
    median_surv.to_csv(data_dir / "median_survival.csv", index=False)
    mean_surv.to_csv(data_dir / "mean_survival.csv", index=False)
    for key, frame in (lifespan_stats or {}).items():
        if hasattr(frame, "to_csv") and len(frame):
            frame.to_csv(stats_dir / f"lifespan_{key}.csv", index=False)
    for i, model in enumerate(result.cox_analyses, 1):
        coefs = model.get("coefficients")
        if coefs is not None and hasattr(coefs, "to_csv") and len(coefs):
            coefs.to_csv(stats_dir / f"factorial_{i:02d}_coefficients.csv", index=False)
        ph = model.get("ph_test")
        if ph is not None and hasattr(ph, "to_csv") and len(ph):
            ph.to_csv(stats_dir / f"factorial_{i:02d}_ph_test.csv", index=False)
    surv_quantiles.to_csv(stats_dir / "survival_quantiles.csv", index=False)
    if len(pairwise_lr) > 0:
        pairwise_lr.to_csv(stats_dir / "logrank_pairwise.csv", index=False)
    if len(pairwise_gw) > 0:
        pairwise_gw.to_csv(stats_dir / "gehan_wilcoxon_pairwise.csv", index=False)
    if len(hazard_ratios) > 0:
        hazard_ratios.to_csv(stats_dir / "hazard_ratios.csv", index=False)

    # ── Figures: the type's Plot Set, in its order ─────────────────────────
    from . import plot_registry

    plot_ids = list(exp_type.plot_ids()) or plot_registry.available()
    emit(f"Rendering {len(plot_ids)} figure(s)…")
    for plot_id in plot_ids:
        try:
            fig = plot_registry.build(plot_id, result)
        except Exception as exc:  # noqa: BLE001 - one bad figure never kills a run
            emit(f"  {plot_id}: skipped ({exc})")
            continue
        if fig is None:
            continue
        path = plots_dir / plot_registry.get(plot_id).filename
        _plot_and_save(fig, path)
        result.figure_paths[plot_id] = path

    for i, (plot_name, treatment_list) in enumerate(defined_plots, 1):
        valid = [t for t in treatment_list
                 if t in set(lifetables["treatment"].astype(str))]
        if not valid:
            continue
        fig_dp = plotting.plot_km_curves(lifetables, treatments=valid, title=plot_name)
        _plot_and_save(fig_dp, plots_dir / f"defined_plot_{i:02d}.png")

    # ── Report and run summary ─────────────────────────────────────────────
    from . import report_builder

    report_builder.write_experiment_report(result, output_dir)
    _write_run_summary(result, output_dir)

    import matplotlib.pyplot as mpl_plt

    mpl_plt.close("all")
    emit(f"Analysis complete — {output_dir}")
    return result


def _jsonable(value):
    """Reduce a stats dict to JSON-safe scalars (DataFrames are saved as CSV)."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()
                if not hasattr(v, "to_csv")}
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001 - a numpy array is not a scalar
            return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _write_run_summary(result: AnalysisResult, output_dir: Path) -> None:
    """A small JSON the Hub and the Project Report read instead of re-analysing.

    The Exclusion Group and the number of chambers it removed are stamped here
    and on every report, so a saved result always says what was excluded.
    """
    import json
    from datetime import datetime

    es = result.experiment_summary or {}
    payload = {
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "input_file": result.input_file.name,
        "experiment_type": getattr(result.experiment_type, "key", "custom"),
        "factors": list(result.factors),
        "n_total": es.get("n_total"),
        "n_deaths": es.get("n_deaths"),
        "n_censored": es.get("n_censored"),
        "n_treatments": es.get("n_treatments"),
        "n_chambers": es.get("n_chambers"),
        "time_min": es.get("time_min"),
        "time_max": es.get("time_max"),
        "assume_censored": bool(result.assume_censored),
        "exclusion_group": getattr(result, "exclusion_group", None),
        "n_excluded": result.n_excluded_applied(),
        "n_excluded_listed": len(result.excluded_chambers or set()),
        "figures": {k: str(v.name) for k, v in
                    getattr(result, "figure_paths", {}).items()},
        "omnibus_lr": _jsonable(result.omnibus_lr),
        # Enough of each factorial model to rebuild its report section from
        # disk; the coefficient tables sit beside it as CSVs.
        "factorial_models": [
            {
                "title": mdl.get("title") or mdl.get("model_type"),
                "model_type": mdl.get("model_type"),
                "formula": mdl.get("formula"),
                "error": mdl.get("error"),
                "n_subjects": mdl.get("n_subjects"),
                "n_events": mdl.get("n_events"),
                "concordance": mdl.get("concordance"),
                "AIC": mdl.get("AIC"),
                "lr_interaction": _jsonable(mdl.get("lr_interaction")),
            }
            for mdl in (result.cox_analyses or [])
        ],
    }
    (Path(output_dir) / "run_summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


def _plot_and_save(fig, path: Path, dpi: int = 150) -> None:
    """Save a matplotlib figure and close it."""
    import matplotlib.pyplot as mpl_plt
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    mpl_plt.close(fig)
