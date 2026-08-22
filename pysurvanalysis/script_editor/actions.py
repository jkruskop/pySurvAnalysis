"""Action registry for the visual Script Editor.

Each action wraps an existing function in :mod:`pysurvanalysis` and
exposes its parameters via :class:`ParamSpec` for the inspector form.
The registry mirrors PyTrackingAnalysis's pattern.
"""

from __future__ import annotations

from typing import Any

from ..ui import Category
from .spec import Action, ParamSpec, ProjectRunContext, RunContext  # noqa: F401


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------

def _parse_list(s: Any) -> list:
    if s is None:
        return []
    if isinstance(s, (list, tuple)):
        return list(s)
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _require_data(ctx: RunContext, action: str) -> None:
    if ctx.data is None:
        raise RuntimeError(
            f"{action}: no data loaded — add a 'Load data' step first."
        )


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

def _exec_load_data(params: dict, ctx: RunContext) -> None:
    from .. import data_loader

    # An Experiment Directory is self-describing: its config names the format,
    # the columns, the censoring policy and the Exclusion Group, so nothing has
    # to be guessed from the run context.
    if ctx.experiment is not None:
        data, factors = ctx.experiment.load(extra_excluded=ctx.excluded_chambers)
        ctx.data, ctx.factors = data, factors
        ctx.exclusion_group = ctx.experiment.exclusion_group
        group = f" · exclusion group '{ctx.exclusion_group}'" if ctx.exclusion_group else ""
        ctx.log(
            f"Loaded {len(data)} individuals · {data['treatment'].nunique()} "
            f"treatments · factors={factors}{group}"
        )
        return

    if ctx.project_dir is None:
        raise RuntimeError("load_data: no project directory in context")
    fmt = ctx.input_format or "excel"
    pdir = ctx.project_dir
    target = None
    if fmt == "excel":
        for f in pdir.glob("*.xlsx"):
            target = f
            break
    else:
        for ext in ("*.csv", "*.tsv"):
            for f in pdir.glob(ext):
                target = f
                break
            if target is not None:
                break
    if target is None:
        raise RuntimeError("load_data: no input file found")
    kwargs = dict(
        assume_censored=ctx.assume_censored,
        excluded_chambers=ctx.excluded_chambers or set(),
    )
    if fmt == "csv_long":
        kwargs["csv_format"] = "long"
    elif fmt == "csv_wide":
        if not ctx.wide_factor_names:
            raise RuntimeError(
                "load_data: csv_wide format requires wide_factor_names in the run context"
            )
        kwargs["csv_format"] = "wide"
        kwargs["factor_names"] = ctx.wide_factor_names
    elif fmt == "csv":
        # Auto-detect long vs wide; supply factor_names as a fallback for wide.
        kwargs["csv_format"] = "auto"
        if ctx.wide_factor_names:
            kwargs["factor_names"] = ctx.wide_factor_names
    data, factors = data_loader.load_experiment(target, **kwargs)
    ctx.data = data
    ctx.factors = factors
    ctx.log(
        f"Loaded {len(data)} individuals · {data['treatment'].nunique()} treatments · "
        f"factors={factors}"
    )


def _exec_apply_exclusions(params: dict, ctx: RunContext) -> None:
    from .. import exclusions

    directory = (ctx.experiment.directory if ctx.experiment is not None
                 else ctx.project_dir)
    if directory is None:
        raise RuntimeError("apply_exclusions: no experiment directory in context")
    group = params.get("group", "default")
    chambers = exclusions.chambers_for_group(directory, group)
    ctx.excluded_chambers = (ctx.excluded_chambers or set()) | chambers
    ctx.exclusion_group = group
    ctx.log(f"Applied {len(chambers)} chamber exclusion(s) from group '{group}'.")
    if ctx.data is not None and "chamber" in ctx.data.columns and chambers:
        before = len(ctx.data)
        ctx.data = ctx.data[~ctx.data["chamber"].isin(chambers)].reset_index(drop=True)
        ctx.log(f"  dropped {before - len(ctx.data)} rows from in-memory data.")


def _exec_filter(params: dict, ctx: RunContext) -> None:
    _require_data(ctx, "filter")
    factor = (params.get("factor") or "").strip()
    value = (params.get("value") or "").strip()
    if not factor:
        raise RuntimeError("filter: 'factor' is required")
    if factor not in ctx.data.columns:
        raise RuntimeError(f"filter: unknown column {factor!r}")
    before = len(ctx.data)
    ctx.data = ctx.data[ctx.data[factor].astype(str) == value].reset_index(drop=True)
    ctx.log(f"filter: kept {len(ctx.data)}/{before} rows where {factor}={value!r}")


def _exec_km(params: dict, ctx: RunContext) -> None:
    from .. import lifetable, plotting

    _require_data(ctx, "km_curves")
    if ctx.lifetables is None:
        ctx.lifetables = lifetable.compute_lifetables(ctx.data)
    treatments = _parse_list(params.get("treatments")) or None
    show_ci = bool(params.get("show_ci", True))
    if params.get("with_risk_table"):
        fig = plotting.plot_km_with_risk_table(
            ctx.lifetables, show_ci=show_ci, treatments=treatments,
        )
    else:
        fig = plotting.plot_km_curves(
            ctx.lifetables, show_ci=show_ci, treatments=treatments,
        )
    ctx.figure("KM curves", fig)


def _exec_nelson_aalen(params: dict, ctx: RunContext) -> None:
    from .. import lifetable, plotting

    _require_data(ctx, "nelson_aalen")
    if ctx.lifetables is None:
        ctx.lifetables = lifetable.compute_lifetables(ctx.data)
    treatments = _parse_list(params.get("treatments")) or None
    fig = plotting.plot_nelson_aalen(ctx.lifetables, treatments=treatments)
    ctx.figure("Nelson-Aalen", fig)


def _exec_hazard(params: dict, ctx: RunContext) -> None:
    from .. import lifetable, plotting

    _require_data(ctx, "hazard")
    if ctx.lifetables is None:
        ctx.lifetables = lifetable.compute_lifetables(ctx.data)
    if params.get("smoothed"):
        fig = plotting.plot_smoothed_hazard(
            ctx.lifetables, sigma=float(params.get("sigma", 2.0)),
        )
    else:
        fig = plotting.plot_hazard(ctx.lifetables)
    ctx.figure("Hazard rate", fig)


def _exec_mortality(_params: dict, ctx: RunContext) -> None:
    from .. import lifetable, plotting

    _require_data(ctx, "mortality")
    if ctx.lifetables is None:
        ctx.lifetables = lifetable.compute_lifetables(ctx.data)
    ctx.figure("Mortality (qx)", plotting.plot_mortality(ctx.lifetables))


def _exec_forest(_params: dict, ctx: RunContext) -> None:
    from .. import plotting, statistics

    _require_data(ctx, "forest_plot")
    hr = statistics.pairwise_hazard_ratios(ctx.data)
    if hr is None or len(hr) == 0:
        ctx.log("forest_plot: no pairwise hazard ratios to display.")
        return
    ctx.figure("Hazard-ratio forest", plotting.plot_hazard_ratio_forest(hr))


def _exec_logrank_pairwise(_params: dict, ctx: RunContext) -> None:
    from .. import statistics

    _require_data(ctx, "log_rank_pairwise")
    res = statistics.pairwise_logrank(ctx.data)
    ctx.log("Pairwise log-rank tests:")
    ctx.log(res.to_string(index=False))


def _exec_logrank_omnibus(_params: dict, ctx: RunContext) -> None:
    from .. import statistics

    _require_data(ctx, "log_rank_omnibus")
    res = statistics.logrank_multi(ctx.data)
    ctx.log("Omnibus log-rank: " + ", ".join(f"{k}={v}" for k, v in res.items()))


def _exec_gehan_wilcoxon(_params: dict, ctx: RunContext) -> None:
    from .. import statistics

    _require_data(ctx, "gehan_wilcoxon")
    res = statistics.pairwise_gehan_wilcoxon(ctx.data)
    ctx.log("Pairwise Gehan-Wilcoxon tests:")
    ctx.log(res.to_string(index=False))


def _exec_cox(params: dict, ctx: RunContext) -> None:
    from .. import statistics

    _require_data(ctx, "cox_ph")
    selected = _parse_list(params.get("factors")) or (ctx.factors or [])
    factors = ctx.factors or selected
    include_inter = bool(params.get("include_interactions", True))
    res = statistics.cox_interaction_analysis(
        ctx.data, factors=factors, selected_factors=selected,
    )
    if "error" in res:
        ctx.log(f"cox_ph: {res['error']}")
        return
    ctx.log(
        f"Cox PH — n={res.get('n_subjects')} events={res.get('n_events')} "
        f"AIC={res.get('AIC'):.2f} C={res.get('concordance'):.3f}"
    )
    coefs = res.get("coefficients")
    if coefs is not None and len(coefs):
        if not include_inter:
            coefs = coefs[~coefs["covariate"].astype(str).str.contains(":", regex=False)]
        ctx.log(coefs.to_string(index=False))
    lr = res.get("lr_interaction")
    if lr:
        ctx.log(f"LR interaction: chi2={lr.get('chi2')}, df={lr.get('df')}, p={lr.get('p_value')}")


def _exec_rmst(params: dict, ctx: RunContext) -> None:
    from .. import statistics

    _require_data(ctx, "rmst")
    selected = _parse_list(params.get("factors")) or (ctx.factors or [])
    factors = ctx.factors or selected
    tau = params.get("tau")
    try:
        tau_val = float(tau) if tau not in (None, "", 0, 0.0) else None
    except (TypeError, ValueError):
        tau_val = None
    res = statistics.rmst_interaction_analysis(
        ctx.data, factors=factors, selected_factors=selected, tau=tau_val,
    )
    if "error" in res:
        ctx.log(f"rmst: {res['error']}")
        return
    ctx.log(f"RMST regression — tau={res.get('tau')}")
    coefs = res.get("coefficients")
    if coefs is not None and len(coefs):
        ctx.log(coefs.to_string(index=False))


def _exec_parametric(_params: dict, ctx: RunContext) -> None:
    from .. import statistics

    _require_data(ctx, "parametric_aft")
    res = statistics.fit_parametric_models(ctx.data)
    if not res:
        ctx.log("parametric_aft: no models fit.")
        return
    for family, summary in res.items():
        ctx.log(f"{family}: {summary}")


def _exec_chamber_qc(params: dict, ctx: RunContext) -> None:
    from .. import lifetable, plotting

    _require_data(ctx, "chamber_overlay_qc")
    if "chamber" not in ctx.data.columns:
        ctx.log("chamber_overlay_qc: data has no chamber column — skipping.")
        return
    treatment = (params.get("treatment") or "").strip()
    pcl = lifetable.compute_lifetables_per_chamber(ctx.data)
    if not treatment:
        treatments = sorted(pcl["treatment"].unique())
        for t in treatments:
            ctx.figure(
                f"QC chamber overlay: {t}",
                plotting.plot_chamber_overlay_km(pcl, t, excluded_chambers=ctx.excluded_chambers),
            )
    else:
        ctx.figure(
            f"QC chamber overlay: {treatment}",
            plotting.plot_chamber_overlay_km(pcl, treatment, excluded_chambers=ctx.excluded_chambers),
        )


def _exec_run_analysis(params: dict, ctx: RunContext) -> None:
    """Run the Experiment Type's whole battery and write ``analysis/``."""
    if ctx.experiment is None:
        raise RuntimeError(
            "run_analysis: no experiment loaded — this action needs an "
            "Experiment Directory."
        )
    result = ctx.experiment.run_analysis(
        log=ctx.log, extra_excluded=ctx.excluded_chambers,
    )
    ctx.result = result
    ctx.data = result.individual_data
    ctx.factors = result.factors
    ctx.lifetables = result.lifetables
    ctx.log(f"Analysis written to {result.output_dir}")


def _exec_render_publication_figures(params: dict, ctx: RunContext) -> None:
    from .. import pubfigures

    if ctx.experiment is None:
        raise RuntimeError(
            "render_publication_figures: no experiment loaded."
        )
    fmt = str(params.get("format") or "svg")
    written = pubfigures.render_all(ctx.experiment, fmt=fmt, log=ctx.log)
    ctx.log(f"{len(written)} publication figure(s) in {ctx.experiment.figures_dir}")


def _exec_report(params: dict, ctx: RunContext) -> None:
    from .. import report_builder
    from ..pipeline import run_analysis

    if ctx.experiment is not None:
        result = ctx.result
        if result is None:
            result = ctx.experiment.run_analysis(
                log=ctx.log, extra_excluded=ctx.excluded_chambers)
            ctx.result = result
        else:
            report_builder.write_experiment_report(result, result.output_dir)
        ctx.log(f"Report: {result.output_dir}")
        return

    if ctx.project_dir is None:
        raise RuntimeError("report: no experiment or directory in context")
    out = params.get("output_dir") or None
    result = run_analysis(
        input_path=str(ctx.project_dir),
        output_dir=out,
        assume_censored=ctx.assume_censored,
        extra_excluded_chambers=ctx.excluded_chambers or set(),
    )
    ctx.log(f"Saved: {result.output_dir / 'report.md'}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

POOL: dict[str, Action] = {
    "load_data": Action(
        key="load_data",
        title="Load data",
        description="Load the project's data file (Excel, CSV-long, or CSV-wide).",
        category=Category.LOAD,
        icon_name="load",
        params=(),
        execute_fn=_exec_load_data,
    ),
    "apply_exclusions": Action(
        key="apply_exclusions",
        title="Apply exclusions",
        description="Exclude chambers from a remove_chambers.csv group.",
        category=Category.LOAD,
        icon_name="filter",
        params=(
            ParamSpec("group", "string", "Group", default="default"),
        ),
        execute_fn=_exec_apply_exclusions,
    ),
    "filter": Action(
        key="filter",
        title="Filter rows",
        description="Keep only rows where factor == value.",
        category=Category.LOAD,
        icon_name="filter",
        params=(
            ParamSpec("factor", "factor", "Factor"),
            ParamSpec("value", "string", "Value"),
        ),
        execute_fn=_exec_filter,
    ),
    "km_curves": Action(
        key="km_curves",
        title="KM curves",
        description="Plot Kaplan-Meier survival curves.",
        category=Category.PLOTS,
        icon_name="km",
        params=(
            ParamSpec("treatments", "list", "Treatments (blank = all)"),
            ParamSpec("show_ci", "bool", "Show 95% CI", default=True),
            ParamSpec("with_risk_table", "bool", "With risk table", default=False),
        ),
        execute_fn=_exec_km,
    ),
    "nelson_aalen": Action(
        key="nelson_aalen",
        title="Nelson-Aalen",
        description="Cumulative hazard plot.",
        category=Category.PLOTS,
        icon_name="hazard",
        params=(
            ParamSpec("treatments", "list", "Treatments (blank = all)"),
        ),
        execute_fn=_exec_nelson_aalen,
    ),
    "hazard_plot": Action(
        key="hazard_plot",
        title="Hazard rate",
        description="Instantaneous hazard rate (raw or smoothed).",
        category=Category.PLOTS,
        icon_name="hazard",
        params=(
            ParamSpec("smoothed", "bool", "Smoothed", default=False),
            ParamSpec("sigma", "float", "Smoothing σ", default=2.0, min=0.1, max=20.0,
                      enabled_when="smoothed"),
        ),
        execute_fn=_exec_hazard,
    ),
    "mortality": Action(
        key="mortality",
        title="Mortality (qx)",
        description="Interval mortality rate.",
        category=Category.PLOTS,
        icon_name="plot",
        params=(),
        execute_fn=_exec_mortality,
    ),
    "forest_plot": Action(
        key="forest_plot",
        title="Hazard-ratio forest",
        description="Forest plot of pairwise hazard ratios.",
        category=Category.PLOTS,
        icon_name="forest",
        params=(),
        execute_fn=_exec_forest,
    ),
    "log_rank_pairwise": Action(
        key="log_rank_pairwise",
        title="Log-rank pairwise",
        description="Mantel-Cox log-rank test for every treatment pair.",
        category=Category.ANALYZE,
        icon_name="logrank",
        params=(),
        execute_fn=_exec_logrank_pairwise,
    ),
    "log_rank_omnibus": Action(
        key="log_rank_omnibus",
        title="Log-rank omnibus",
        description="K-sample log-rank test across all treatments.",
        category=Category.ANALYZE,
        icon_name="logrank",
        params=(),
        execute_fn=_exec_logrank_omnibus,
    ),
    "gehan_wilcoxon": Action(
        key="gehan_wilcoxon",
        title="Gehan-Wilcoxon pairwise",
        description="Wilcoxon-style weighted log-rank for every pair.",
        category=Category.ANALYZE,
        icon_name="logrank",
        params=(),
        execute_fn=_exec_gehan_wilcoxon,
    ),
    "cox_ph": Action(
        key="cox_ph",
        title="Cox PH (interactions)",
        description="Cox proportional hazards with full-factorial interactions.",
        category=Category.ANALYZE,
        icon_name="cox",
        params=(
            ParamSpec("factors", "factors", "Factors (blank = all)"),
            ParamSpec("include_interactions", "bool", "Include interactions", default=True),
        ),
        execute_fn=_exec_cox,
    ),
    "rmst": Action(
        key="rmst",
        title="RMST regression",
        description="RMST pseudo-value regression with full-factorial interactions.",
        category=Category.ANALYZE,
        icon_name="rmst",
        params=(
            ParamSpec("factors", "factors", "Factors (blank = all)"),
            ParamSpec("include_interactions", "bool", "Include interactions", default=True),
            ParamSpec("tau", "float", "τ (hours, 0 = auto)", default=0.0, min=0.0, max=1e6),
        ),
        execute_fn=_exec_rmst,
    ),
    "parametric_aft": Action(
        key="parametric_aft",
        title="Parametric AFT models",
        description="Fit Weibull, log-normal, and log-logistic AFT models.",
        category=Category.ANALYZE,
        icon_name="parametric",
        params=(),
        execute_fn=_exec_parametric,
    ),
    "chamber_overlay_qc": Action(
        key="chamber_overlay_qc",
        title="Chamber QC overlay",
        description="Per-chamber KM overlay (one figure per treatment).",
        category=Category.QC,
        icon_name="chamber",
        params=(
            ParamSpec("treatment", "string", "Treatment (blank = all)"),
        ),
        execute_fn=_exec_chamber_qc,
    ),
    "report": Action(
        key="report",
        title="Generate report",
        description=(
            "Write the experiment report (PDF and markdown) from the current "
            "analysis, running it first if nothing has been computed yet."
        ),
        category=Category.TOOLS,
        icon_name="report",
        params=(
            ParamSpec("output_dir", "path", "Output dir (blank = project)"),
        ),
        execute_fn=_exec_report,
    ),
}

POOL["run_analysis"] = Action(
    key="run_analysis",
    title="Run analysis",
    description=(
        "Run the Experiment Type's whole battery — its analyses and its Plot "
        "Set — and write everything under analysis/."
    ),
    category=Category.ANALYZE,
    icon_name="analyze",
    params=(),
    execute_fn=_exec_run_analysis,
)
POOL["render_publication_figures"] = Action(
    key="render_publication_figures",
    title="Render publication figures",
    description="Write the vector Publication Figures from plot_specs.yaml.",
    category=Category.PLOTS,
    icon_name="figures",
    params=(
        ParamSpec("format", "choice", "Format", default="svg",
                  choices=("svg", "pdf", "png")),
    ),
    execute_fn=_exec_render_publication_figures,
)


# ---------------------------------------------------------------------------
# core ∪ type (ADR-0002)
#
# The core holds what every Experiment Type has; the type contributes the rest,
# and a Hub button and its script action are the same declaration. A step
# naming an action outside the union is a hard error — see :func:`validate_steps`.
# ---------------------------------------------------------------------------

CORE_KEYS: tuple[str, ...] = (
    "load_data",
    "apply_exclusions",
    "filter",
    "run_analysis",
    "chamber_overlay_qc",
    "render_publication_figures",
    "report",
)


def registry_for(exp_type=None) -> dict[str, Action]:
    """The actions available to *exp_type*: core ∪ type.

    A Custom Experiment (or no type at all) gets everything in the pool — the
    absence of a type is the absence of a constraint.
    """
    core = {k: POOL[k] for k in CORE_KEYS if k in POOL}
    if exp_type is None or getattr(exp_type, "is_custom", False):
        merged = dict(POOL)
        merged.update(core)
        return merged

    registry = dict(core)
    for key in (exp_type.action_keys or ()):
        if key in POOL:
            registry[key] = POOL[key]
    for action in exp_type.extra_actions():
        registry[action.key] = action
    return registry


def validate_steps(steps, exp_type=None) -> list[str]:
    """Problems that must stop a run before its first step executes.

    Unknown actions are a hard error rather than a skip: a silently skipped
    analysis step produces a report that looks complete and is not.
    """
    registry = registry_for(exp_type)
    label = getattr(exp_type, "label", "Custom Experiment")
    problems: list[str] = []
    for i, step in enumerate(steps or [], 1):
        key = (step or {}).get("action")
        if not key:
            problems.append(f"Step {i} has no action.")
        elif key not in registry:
            problems.append(
                f"Step {i} uses action {key!r}, which a {label} does not provide. "
                f"Available: {', '.join(sorted(registry))}."
            )
    return problems


#: Backwards-compatible view: every action this build knows about.
ACTIONS: dict[str, Action] = dict(POOL)
