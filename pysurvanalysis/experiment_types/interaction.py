"""Interaction Experiment — a 2×2 factorial Experiment Type.

Exactly two user-named factors with exactly two **ordered** levels each. The
first level of each factor is its **Reference Level**: the Cox dummy-coding
baseline, the first cell in every figure, and the baseline in the report's
prose — so the sign of every coefficient, the interaction term included, is
stable and explainable however the levels happen to be named.
"""

from __future__ import annotations

from typing import Any

from ..ui import Category
from ..script_editor.spec import Action, ParamSpec
from .base import ALL_PLOT_DEFS, ExperimentType, ReportSection

_BY_ID = {p.id: p for p in ALL_PLOT_DEFS}


def factor_block(config: dict) -> dict[str, list]:
    """The declared ``factors:`` mapping, order preserved (may be empty)."""
    factors = config.get("factors") or {}
    if not isinstance(factors, dict):
        return {}
    out: dict[str, list] = {}
    for name, levels in factors.items():
        if isinstance(levels, (list, tuple)):
            out[str(name)] = [str(lv) for lv in levels]
        else:
            out[str(name)] = []
    return out


def cell_order(config: dict) -> list[str]:
    """The four treatment labels in declared order (factor-1 outer)."""
    factors = factor_block(config)
    names = list(factors)
    if len(names) != 2:
        return []
    first, second = factors[names[0]], factors[names[1]]
    return [f"{a}/{b}" for a in first for b in second]


def reference_cell(config: dict) -> str | None:
    """The treatment label made of both Reference Levels."""
    cells = cell_order(config)
    return cells[0] if cells else None


class InteractionExperimentType(ExperimentType):
    key = "interaction"
    label = "Interaction Experiment"
    description = (
        "A 2×2 factorial: two named factors with two ordered levels each "
        "(e.g. Genotype × Treatment). The first level of each factor is its "
        "reference."
    )

    default_global = {
        "time_unit": "days",
        "time_label": "Age (days)",
        "assume_censored": True,
    }

    plot_set = (
        _BY_ID["km_faceted"],
        _BY_ID["km_risk_table"],
        _BY_ID["interaction_lifespan"],
        _BY_ID["hazard_ratio_forest"],
        _BY_ID["log_log"],
    )
    headline_plot_id = "km_faceted"

    action_keys = (
        "km_curves", "log_rank_pairwise", "log_rank_omnibus", "forest_plot",
    )

    # ── configuration ──────────────────────────────────────────────────────

    def scaffold_config(self, minimal: bool = False) -> dict:
        cfg = super().scaffold_config(minimal=minimal)
        if not minimal:
            cfg["factors"] = {
                "Factor1": ["reference_level", "test_level"],
                "Factor2": ["reference_level", "test_level"],
            }
        return cfg

    def validate_config(self, config: dict) -> list[str]:
        problems = super().validate_config(config)
        raw = config.get("factors")
        if raw is None:
            return problems + [
                "An Interaction Experiment needs a `factors:` block naming two "
                "factors with two ordered levels each; the first level of each "
                "is its reference."
            ]
        if not isinstance(raw, dict):
            return problems + ["`factors:` must be a mapping of name → [level, level]."]

        factors = factor_block(config)
        if len(factors) != 2:
            problems.append(
                f"An Interaction Experiment needs exactly 2 factors; "
                f"`factors:` declares {len(factors)} "
                f"({', '.join(factors) or 'none'})."
            )
        for name, levels in factors.items():
            if len(levels) != 2:
                problems.append(
                    f"Factor {name!r} must declare exactly 2 levels, in order "
                    f"(first = reference); it declares {len(levels)}."
                )
            elif levels[0] == levels[1]:
                problems.append(f"Factor {name!r} declares the same level twice.")
        return problems

    def validate_data(self, individual_data, config: dict) -> list[str]:
        problems: list[str] = []
        factors = factor_block(config)
        if len(factors) != 2 or individual_data is None or len(individual_data) == 0:
            return problems
        for name, declared in factors.items():
            if name not in individual_data.columns:
                problems.append(
                    f"Factor {name!r} is declared in `factors:` but is not a "
                    f"column in the data (columns: "
                    f"{', '.join(map(str, individual_data.columns))})."
                )
                continue
            present = {str(v) for v in individual_data[name].dropna().unique()}
            undeclared = sorted(present - set(declared))
            if undeclared:
                problems.append(
                    f"Factor {name!r} has level(s) {', '.join(undeclared)} in the "
                    f"data that are not declared in `factors:` "
                    f"({', '.join(declared)}). Declare them or filter them out."
                )
            missing = [lv for lv in declared if lv not in present]
            if missing:
                problems.append(
                    f"Factor {name!r} declares level(s) {', '.join(missing)} that "
                    f"never appear in the data."
                )
        return problems

    # ── data preparation ───────────────────────────────────────────────────

    def prepare_data(self, individual_data, config: dict):
        """Make the declared level order the *categorical* order.

        Every downstream grouping — treatment iteration, plot legends, Cox
        dummy coding — then follows the declared order, so the reference cell
        is always first.
        """
        import pandas as pd

        factors = factor_block(config)
        if len(factors) != 2 or individual_data is None or len(individual_data) == 0:
            return individual_data

        df = individual_data.copy()
        for name, levels in factors.items():
            if name in df.columns:
                df[name] = pd.Categorical(
                    df[name].astype(str), categories=levels, ordered=True
                )
        cells = [c for c in cell_order(config) if c in set(df["treatment"].astype(str))]
        if cells:
            df["treatment"] = pd.Categorical(
                df["treatment"].astype(str), categories=cells, ordered=True
            )
            df = df.sort_values(["treatment", "time"]).reset_index(drop=True)
        return df

    # ── analyses ───────────────────────────────────────────────────────────

    def run_extra_analyses(self, result, config: dict) -> list[dict]:
        """The factorial battery: the Cox model and its RMST companion.

        Both are part of the *standard* set for this type, not an opt-in tab —
        a 2×2 exists to be tested for interaction.
        """
        from .. import statistics

        names = [n for n in factor_block(config) if n in result.individual_data.columns]
        if len(names) != 2:
            return []
        out: list[dict] = []
        for fn, label in ((statistics.cox_interaction_analysis, "Cox factorial model"),
                          (statistics.rmst_interaction_analysis, "RMST factorial model")):
            try:
                model = fn(result.individual_data, names, names)
            except Exception as exc:  # noqa: BLE001 - a failed model never kills a run
                model = {"error": str(exc), "model_type": label}
            model.setdefault("title", label)
            out.append(model)
        return out

    # ── presentation ───────────────────────────────────────────────────────

    def report_intro(self) -> str | None:
        return (
            "A 2×2 factorial survival experiment. Coefficients are reported "
            "relative to the reference level of each factor (the first level "
            "declared), so the interaction term reads as how the effect of the "
            "second factor differs between the levels of the first."
        )

    def report_sections(self) -> tuple[ReportSection, ...]:
        return (
            ReportSection("summary", "Experiment summary"),
            ReportSection("figures", "Survivorship figures"),
            ReportSection("interaction", "Factorial analysis"),
            ReportSection("lifespan", "Lifespan statistics"),
            ReportSection("tests", "Survival comparisons"),
            ReportSection("quality", "Data quality"),
        )

    def ai_summary_prompt(self) -> str:
        return (
            "Summarize this 2×2 factorial survival experiment. State the main "
            "effect of each factor, then whether the interaction term was "
            "significant and what that means for how the two factors combine. "
            "Coefficients are relative to each factor's reference level. "
            "Summarize only the numbers given to you — never compute, infer, "
            "or speculate beyond them."
        )

    # ── Type Actions ───────────────────────────────────────────────────────

    def extra_actions(self) -> tuple:
        return (
            Action(
                key="faceted_km",
                title="Faceted KM (headline)",
                description="One panel per level of factor 1, curves coloured by factor 2.",
                category=Category.PLOTS,
                icon_name="km",
                params=(ParamSpec("show_ci", "bool", "Show 95% CI", default=False),),
                execute_fn=_exec_faceted_km,
                from_type=True,
            ),
            Action(
                key="interaction_plot",
                title="Lifespan interaction plot",
                description="Median lifespan per cell; non-parallel lines indicate interaction.",
                category=Category.PLOTS,
                icon_name="interaction",
                params=(
                    ParamSpec("metric", "choice", "Metric", default="median",
                              choices=("median", "mean")),
                ),
                execute_fn=_exec_interaction_plot,
                from_type=True,
            ),
            Action(
                key="cox_interaction",
                title="Cox factorial model",
                description=(
                    "Cox PH main-effects vs interaction model, LR omnibus test, "
                    "and the Schoenfeld PH check."
                ),
                category=Category.ANALYZE,
                icon_name="cox",
                params=(),
                execute_fn=_exec_cox_interaction,
                from_type=True,
            ),
            Action(
                key="rmst_interaction",
                title="RMST factorial model",
                description=(
                    "RMST pseudo-value regression with the same 2×2 design — no "
                    "proportional-hazards assumption."
                ),
                category=Category.ANALYZE,
                icon_name="rmst",
                params=(ParamSpec("tau", "float", "τ (0 = auto)", default=0.0,
                                  min=0.0, max=1e6),),
                execute_fn=_exec_rmst_interaction,
                from_type=True,
            ),
        )


# ---------------------------------------------------------------------------
# Type Action implementations (heavy imports stay inside the functions)
# ---------------------------------------------------------------------------

def _require_data(ctx, action: str):
    if getattr(ctx, "data", None) is None:
        raise RuntimeError(f"{action}: no data loaded — add a 'Load data' step first.")


def _config_of(ctx) -> dict:
    exp = getattr(ctx, "experiment", None)
    return dict(exp.config) if exp is not None else {}


def _exec_faceted_km(params: dict, ctx) -> None:
    from .. import lifetable, plotting

    _require_data(ctx, "faceted_km")
    cfg = _config_of(ctx)
    lts = ctx.lifetables if ctx.lifetables is not None else lifetable.compute_lifetables(ctx.data)
    fig = plotting.plot_km_faceted(
        lts, factor_block(cfg), show_ci=bool(params.get("show_ci", False)),
        time_label=(cfg.get("global") or {}).get("time_label", "Age"),
    )
    ctx.figure("Faceted KM", fig)
    ctx.log("Faceted KM rendered.")


def _exec_interaction_plot(params: dict, ctx) -> None:
    from .. import plotting

    _require_data(ctx, "interaction_plot")
    cfg = _config_of(ctx)
    fig = plotting.plot_lifespan_interaction(
        ctx.data, factor_block(cfg), metric=str(params.get("metric", "median")),
        time_label=(cfg.get("global") or {}).get("time_label", "Age"),
    )
    ctx.figure("Lifespan interaction", fig)
    ctx.log("Interaction plot rendered.")


def _exec_cox_interaction(_params: dict, ctx) -> None:
    from .. import statistics

    _require_data(ctx, "cox_interaction")
    cfg = _config_of(ctx)
    names = list(factor_block(cfg)) or (ctx.factors or [])
    result = statistics.cox_interaction_analysis(ctx.data, names, names)
    if result.get("error"):
        ctx.log(f"Cox factorial model: {result['error']}")
        return
    _log_factorial(ctx, result, "Cox factorial model")


def _exec_rmst_interaction(params: dict, ctx) -> None:
    from .. import statistics

    _require_data(ctx, "rmst_interaction")
    cfg = _config_of(ctx)
    names = list(factor_block(cfg)) or (ctx.factors or [])
    tau = float(params.get("tau") or 0.0) or None
    result = statistics.rmst_interaction_analysis(ctx.data, names, names, tau=tau)
    if result.get("error"):
        ctx.log(f"RMST factorial model: {result['error']}")
        return
    _log_factorial(ctx, result, "RMST factorial model")


def _log_factorial(ctx, result: dict[str, Any], title: str) -> None:
    ctx.log(f"{title}: {result.get('formula', '')}")
    lr = result.get("lr_interaction") or {}
    if lr:
        ctx.log(
            f"  Interaction LR test: chi2={lr.get('statistic', float('nan')):.3f}, "
            f"df={lr.get('df', '?')}, p={lr.get('p_value', float('nan')):.4g}"
        )
    coefs = result.get("coefficients")
    if coefs is not None and len(coefs):
        ctx.log(coefs.to_string(index=False))
    if getattr(ctx, "result", None) is not None:
        ctx.result.cox_analyses.append(result)
