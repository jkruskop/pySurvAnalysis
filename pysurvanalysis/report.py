"""Generate analysis reports in Markdown and HTML formats.

The Markdown report includes embedded images (base64) when converted to HTML,
making it a self-contained document suitable for sharing.
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np

from . import plotting

if TYPE_CHECKING:
    from .pipeline import AnalysisResult


def _fig_to_base64(fig: plt.Figure) -> str:
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


def _fig_to_file(fig: plt.Figure, path: Path) -> None:
    """Save figure to file and close it."""
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _format_pvalue(p: float) -> str:
    """Format a p-value for display."""
    if p < 0.0001:
        return f"{p:.2e}"
    return f"{p:.4f}"


def _significance_stars(p: float) -> str:
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


def generate_markdown(result: "AnalysisResult", output_dir: Path) -> str:
    """Generate a complete Markdown analysis report.

    Plots are saved as PNG files in a ``plots/`` subdirectory and referenced
    by relative path in the Markdown.
    """
    plots_dir = output_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []

    lines.append("# Survival Analysis Report")
    lines.append("")

    # ── Experiment summary block ───────────────────────────────────────────
    es = getattr(result, "experiment_summary", {})
    lines.append("**Input file:** `{}`  ".format(result.input_file.name))
    lines.append("**Treatment factors:** {}  ".format(", ".join(result.factors)))
    treatments = sorted(result.individual_data["treatment"].unique())
    lines.append("**Number of treatment groups:** {}  ".format(len(treatments)))
    lines.append("**Total individuals:** {}  ".format(len(result.individual_data)))
    if es:
        n_dead = es.get("n_deaths", "?")
        n_cens = es.get("n_censored", "?")
        pct_cens = es.get("pct_censored", "?")
        t_min = es.get("time_min", "?")
        t_max = es.get("time_max", "?")
        n_ch = es.get("n_chambers")
        if n_ch is not None:
            lines.append(f"**Chambers:** {n_ch}  ")
        lines.append(f"**Deaths / Censored:** {n_dead} / {n_cens} ({pct_cens}% censored)  ")
        lines.append(f"**Observation window:** {t_min} – {t_max} hours  ")

    is_excel = result.input_file.suffix.lower() == ".xlsx"
    if is_excel:
        ac = getattr(result, "assume_censored", True)
        ac_label = ("Yes — unaccounted individuals added as right-censored at last census time"
                    if ac else
                    "No — cohort size = sum of observed deaths + explicit censored per chamber")
        lines.append(f"**Assume unobserved individuals censored:** {ac_label}  ")
    lines.append("")

    # ── Excluded chambers ──────────────────────────────────────────────────
    excl = getattr(result, "excluded_chambers", set())
    if excl:
        sorted_excl = sorted(excl, key=lambda x: (str(type(x).__name__), x))
        lines.append("> **Note — Excluded chambers:** "
                     f"{', '.join(str(c) for c in sorted_excl)}")
        lines.append("")

    # ── 1. Sample Summary ──────────────────────────────────────────────────
    lines.append("## 1. Sample Summary")
    lines.append("")
    lines.append("| Treatment | N | Deaths | Censored | % Censored |")
    lines.append("|-----------|---|--------|----------|------------|")
    for _, row in result.summary.iterrows():
        lines.append(
            f"| {row['treatment']} | {row['n_individuals']} | {row['n_deaths']} "
            f"| {row['n_censored']} | {row['pct_censored']}% |"
        )
    lines.append("")

    # ── 2. Survival Time Estimates ─────────────────────────────────────────
    lines.append("## 2. Survival Time Estimates")
    lines.append("")

    lines.append("### Median Survival Time")
    lines.append("")
    lines.append("| Treatment | Median Survival (hours) |")
    lines.append("|-----------|------------------------|")
    for _, row in result.median_surv.iterrows():
        val = (f"{row['median_survival']:.1f}"
               if not np.isnan(row["median_survival"]) else "Not reached")
        lines.append(f"| {row['treatment']} | {val} |")
    lines.append("")

    lines.append("### Restricted Mean Survival Time (RMST)")
    lines.append("")
    if len(result.mean_surv) > 0:
        t_restrict = result.mean_surv["restriction_time"].iloc[0]
        lines.append(f"*Restricted to t = {t_restrict:.1f} hours*")
        lines.append("")
        lines.append("| Treatment | RMST (hours) |")
        lines.append("|-----------|-------------|")
        for _, row in result.mean_surv.iterrows():
            val = f"{row['rmst']:.1f}" if not np.isnan(row["rmst"]) else "N/A"
            lines.append(f"| {row['treatment']} | {val} |")
    lines.append("")

    # ── 2b. Survival Quantiles ─────────────────────────────────────────────
    sq = getattr(result, "surv_quantiles", None)
    if sq is not None and len(sq) > 0:
        lines.append("### Survival Quantiles")
        lines.append("")
        lines.append("*Time (hours) at which survival drops to the given fraction.*")
        lines.append("")
        quantile_cols = [c for c in sq.columns if c != "treatment"]
        header = "| Treatment | " + " | ".join(quantile_cols) + " |"
        sep = "|-----------|" + "|".join(["---"] * len(quantile_cols)) + "|"
        lines.append(header)
        lines.append(sep)
        for _, row in sq.iterrows():
            vals = []
            for col in quantile_cols:
                v = row[col]
                vals.append(f"{v:.1f}" if not np.isnan(v) else "NR")
            lines.append(f"| {row['treatment']} | " + " | ".join(vals) + " |")
        lines.append("")

    # ── 3. Lifespan Statistics ─────────────────────────────────────────────
    ls = result.lifespan_stats
    if ls:
        ts = ls.get("treatment_stats")
        fs = ls.get("factor_stats")
        has_top_pct = ts is not None and "top_10pct_mean" in ts.columns

        if ts is not None and len(ts) > 0:
            lines.append("### Lifespan by Treatment")
            lines.append("")
            if has_top_pct:
                lines.append("| Treatment | N | Deaths | Mean (RMST) | Median | Top 10% Mean | Top 5% Mean |")
                lines.append("|-----------|---|--------|-------------|--------|--------------|-------------|")
            else:
                lines.append("| Treatment | N | Deaths | Mean (RMST) | Median |")
                lines.append("|-----------|---|--------|-------------|--------|")
            for _, row in ts.iterrows():
                mean_s = f"{row['mean_rmst']:.1f}" if not np.isnan(row["mean_rmst"]) else "N/A"
                med_s = f"{row['median']:.1f}" if not np.isnan(row["median"]) else "Not reached"
                base = f"| {row['group']} | {int(row['n'])} | {int(row['n_deaths'])} | {mean_s} | {med_s}"
                if has_top_pct:
                    t10 = f"{row['top_10pct_mean']:.1f}" if not np.isnan(row.get("top_10pct_mean", np.nan)) else "N/A"
                    t5 = f"{row['top_5pct_mean']:.1f}" if not np.isnan(row.get("top_5pct_mean", np.nan)) else "N/A"
                    lines.append(f"{base} | {t10} | {t5} |")
                else:
                    lines.append(f"{base} |")
            lines.append("")

        if fs is not None and len(fs) > 0:
            has_top_pct_f = "top_10pct_mean" in fs.columns
            lines.append("### Lifespan by Factor Level (pooled)")
            lines.append("")
            if has_top_pct_f:
                lines.append("| Factor Level | N | Deaths | Mean (RMST) | Median | Top 10% Mean | Top 5% Mean |")
                lines.append("|--------------|---|--------|-------------|--------|--------------|-------------|")
            else:
                lines.append("| Factor Level | N | Deaths | Mean (RMST) | Median |")
                lines.append("|--------------|---|--------|-------------|--------|")
            for _, row in fs.iterrows():
                mean_s = f"{row['mean_rmst']:.1f}" if not np.isnan(row["mean_rmst"]) else "N/A"
                med_s = f"{row['median']:.1f}" if not np.isnan(row["median"]) else "Not reached"
                base = f"| {row['group']} | {int(row['n'])} | {int(row['n_deaths'])} | {mean_s} | {med_s}"
                if has_top_pct_f:
                    t10 = f"{row['top_10pct_mean']:.1f}" if not np.isnan(row.get("top_10pct_mean", np.nan)) else "N/A"
                    t5 = f"{row['top_5pct_mean']:.1f}" if not np.isnan(row.get("top_5pct_mean", np.nan)) else "N/A"
                    lines.append(f"{base} | {t10} | {t5} |")
                else:
                    lines.append(f"{base} |")
            lines.append("")

    # ── 4. Kaplan–Meier Curves ────────────────────────────────────────────
    lines.append("## 3. Kaplan–Meier Survival Curves")
    lines.append("")

    _save_if_missing(lambda: plotting.plot_km_curves(result.lifetables),
                     plots_dir / "kaplan_meier.png")
    lines.append("![Kaplan-Meier Survival Curves](plots/kaplan_meier.png)")
    lines.append("")

    _save_if_missing(lambda: plotting.plot_km_with_risk_table(result.lifetables),
                     plots_dir / "km_with_risk_table.png")
    lines.append("### KM Curves with Number-at-Risk Table")
    lines.append("")
    lines.append("![KM with Risk Table](plots/km_with_risk_table.png)")
    lines.append("")

    # ── 5. Nelson-Aalen ───────────────────────────────────────────────────
    lines.append("## 4. Nelson–Aalen Cumulative Hazard")
    lines.append("")
    lines.append("*Complementary non-parametric estimator of the cumulative hazard H(t). "
                 "Shaded bands show 95% confidence intervals.*")
    lines.append("")
    _save_if_missing(lambda: plotting.plot_nelson_aalen(result.lifetables),
                     plots_dir / "nelson_aalen.png")
    lines.append("![Nelson-Aalen Cumulative Hazard](plots/nelson_aalen.png)")
    lines.append("")

    # ── 6. PH Assumption Check ─────────────────────────────────────────────
    lines.append("## 5. Proportional Hazards Assumption Check")
    lines.append("")
    lines.append("*Log(−log S(t)) vs log(t). Parallel lines support the PH assumption.*")
    lines.append("")
    _save_if_missing(lambda: plotting.plot_log_log(result.lifetables),
                     plots_dir / "log_log_diagnostic.png")
    lines.append("![Log-Log Diagnostic](plots/log_log_diagnostic.png)")
    lines.append("")

    # ── 7. Cumulative Events ───────────────────────────────────────────────
    lines.append("## 6. Cumulative Events")
    lines.append("")
    _save_if_missing(lambda: plotting.plot_cumulative_events(result.lifetables),
                     plots_dir / "cumulative_events.png")
    lines.append("![Cumulative Events](plots/cumulative_events.png)")
    lines.append("")

    # ── 8. Hazard Rate ─────────────────────────────────────────────────────
    lines.append("## 7. Hazard Rate")
    lines.append("")
    _save_if_missing(lambda: plotting.plot_hazard(result.lifetables),
                     plots_dir / "hazard_rate.png")
    lines.append("![Hazard Rate](plots/hazard_rate.png)")
    lines.append("")

    _save_if_missing(lambda: plotting.plot_smoothed_hazard(result.lifetables),
                     plots_dir / "smoothed_hazard.png")
    lines.append("### Smoothed Hazard Rate")
    lines.append("")
    lines.append("![Smoothed Hazard Rate](plots/smoothed_hazard.png)")
    lines.append("")

    # ── 9. Survival Distribution ───────────────────────────────────────────
    lines.append("## 8. Survival Time Distribution")
    lines.append("")
    _save_if_missing(lambda: plotting.plot_survival_distribution(result.individual_data),
                     plots_dir / "survival_distribution.png")
    lines.append("![Survival Distribution](plots/survival_distribution.png)")
    lines.append("")

    # ── 10. Mortality ─────────────────────────────────────────────────────
    lines.append("## 9. Interval Mortality (qx)")
    lines.append("")
    _save_if_missing(lambda: plotting.plot_mortality(result.lifetables),
                     plots_dir / "mortality_qx.png")
    lines.append("![Interval Mortality](plots/mortality_qx.png)")
    lines.append("")

    # ── 11. Number at Risk ─────────────────────────────────────────────────
    lines.append("## 10. Number at Risk")
    lines.append("")
    _save_if_missing(lambda: plotting.plot_number_at_risk(result.lifetables),
                     plots_dir / "number_at_risk.png")
    lines.append("![Number at Risk](plots/number_at_risk.png)")
    lines.append("")

    # ── 12. Defined Plots (Excel) ──────────────────────────────────────────
    defined_plots = getattr(result, "defined_plots", [])
    sec_offset = 11
    if defined_plots:
        lines.append(f"## {sec_offset}. Defined Plots (from DefinedPlots sheet)")
        lines.append("")
        for i, (plot_name, treatment_list) in enumerate(defined_plots, 1):
            valid = [t for t in treatment_list if t in result.lifetables["treatment"].unique()]
            heading = plot_name if plot_name else f"Plot {i}"
            if not valid:
                lines.append(f"### {heading}")
                lines.append("*No valid treatments found for this plot.*")
                lines.append("")
                continue
            fname = f"defined_plot_{i:02d}.png"
            fpath = plots_dir / fname
            _save_if_missing(
                lambda lt=result.lifetables, v=valid, pn=plot_name: plotting.plot_km_curves(lt, treatments=v, title=pn),
                fpath,
            )
            lines.append(f"### {heading}")
            lines.append("")
            lines.append(f"![{heading}](plots/{fname})")
            lines.append("")
        sec_offset += 1

    # ── 13. Omnibus Log-Rank ───────────────────────────────────────────────
    lines.append(f"## {sec_offset}. Omnibus Log-Rank Test")
    lines.append("")
    lr = result.omnibus_lr
    lines.append(f"- **Chi-square statistic:** {lr['chi2']}")
    lines.append(f"- **Degrees of freedom:** {lr['df']}")
    lines.append(f"- **p-value:** {_format_pvalue(lr['p_value'])} {_significance_stars(lr['p_value'])}")
    lines.append("")
    conclusion = ("*Statistically significant differences in survival among treatment groups.*"
                  if lr["p_value"] < 0.05
                  else "*No statistically significant differences in survival among treatment groups.*")
    lines.append(conclusion)
    lines.append("")
    sec_offset += 1

    # ── 14. Pairwise Log-Rank ──────────────────────────────────────────────
    lines.append(f"## {sec_offset}. Pairwise Log-Rank Tests (Bonferroni corrected)")
    lines.append("")
    if len(result.pairwise_lr) > 0:
        lines.append("| Comparison | Chi² | p-value | p (Bonferroni) | Sig. |")
        lines.append("|------------|-------|---------|----------------|------|")
        for _, row in result.pairwise_lr.iterrows():
            lines.append(
                f"| {row['group1']} vs {row['group2']} "
                f"| {row['chi2']:.4f} "
                f"| {_format_pvalue(row['p_value'])} "
                f"| {_format_pvalue(row['p_bonferroni'])} "
                f"| {_significance_stars(row['p_bonferroni'])} |"
            )
    lines.append("")
    sec_offset += 1

    # ── 15. Gehan-Wilcoxon Tests ───────────────────────────────────────────
    pairwise_gw = getattr(result, "pairwise_gw", None)
    if pairwise_gw is not None and len(pairwise_gw) > 0:
        lines.append(f"## {sec_offset}. Gehan-Wilcoxon Weighted Log-Rank Tests")
        lines.append("")
        lines.append("*Gehan-Wilcoxon test uses number-at-risk as weights, emphasising "
                      "early differences in survival.*")
        lines.append("")
        lines.append("| Comparison | Chi² | p-value | p (Bonferroni) | Sig. |")
        lines.append("|------------|-------|---------|----------------|------|")
        for _, row in pairwise_gw.iterrows():
            lines.append(
                f"| {row['group1']} vs {row['group2']} "
                f"| {row['chi2']:.4f} "
                f"| {_format_pvalue(row['p_value'])} "
                f"| {_format_pvalue(row['p_bonferroni'])} "
                f"| {_significance_stars(row['p_bonferroni'])} |"
            )
        lines.append("")
        sec_offset += 1

    # ── 16. Hazard Ratios ──────────────────────────────────────────────────
    lines.append(f"## {sec_offset}. Hazard Ratio Estimates")
    lines.append("")
    if len(result.hazard_ratios) > 0:
        lines.append("*Hazard ratios estimated from log-rank O/E method. HR > 1 → higher risk in first group.*")
        lines.append("")
        lines.append("| Comparison | HR | 95% CI |")
        lines.append("|------------|-----|--------|")
        for _, row in result.hazard_ratios.iterrows():
            if np.isnan(row["hazard_ratio"]):
                lines.append(f"| {row['group1']} vs {row['group2']} | N/A | N/A |")
            else:
                lines.append(
                    f"| {row['group1']} vs {row['group2']} "
                    f"| {row['hazard_ratio']:.3f} "
                    f"| ({row['hr_ci_lo']:.3f}, {row['hr_ci_hi']:.3f}) |"
                )
        lines.append("")

    # Hazard ratio forest plot
    _save_if_missing(lambda: plotting.plot_hazard_ratio_forest(result.hazard_ratios),
                     plots_dir / "hazard_ratio_forest.png")
    lines.append("![Hazard Ratio Forest Plot](plots/hazard_ratio_forest.png)")
    lines.append("")
    sec_offset += 1

    # ── 17. Parametric Models ──────────────────────────────────────────────
    pm = getattr(result, "parametric_models", {})
    aic_df = pm.get("aic_comparison")
    best_pm = pm.get("best_model_per_treatment", {})
    if aic_df is not None and len(aic_df) > 0:
        lines.append(f"## {sec_offset}. Parametric Survival Models (AIC Comparison)")
        lines.append("")
        lines.append("*Weibull, Log-Normal, and Log-Logistic AFT models fitted per treatment. "
                      "Lower AIC indicates better fit.*")
        lines.append("")
        lines.append("| Treatment | Model | AIC | Log-Likelihood | Median Survival |")
        lines.append("|-----------|-------|-----|----------------|-----------------|")
        for _, row in aic_df.iterrows():
            best_marker = " ✓" if best_pm.get(row["treatment"]) == row["model"] else ""
            median_str = f"{row['median_survival']:.1f}" if not np.isnan(row.get("median_survival", np.nan)) else "N/A"
            lines.append(
                f"| {row['treatment']} | {row['model']}{best_marker} "
                f"| {row['aic']:.1f} "
                f"| {row['log_likelihood']:.2f} "
                f"| {median_str} |"
            )
        lines.append("")
        lines.append("*✓ = best-fitting model (lowest AIC) for that treatment.*")
        lines.append("")
        sec_offset += 1

    # ── 18. Lifetable Excerpt ──────────────────────────────────────────────
    lines.append(f"## {sec_offset}. Lifetable (First 10 Rows per Treatment)")
    lines.append("")
    for treatment in treatments:
        grp = result.lifetables[result.lifetables["treatment"] == treatment].head(10)
        lines.append(f"### {treatment}")
        lines.append("")
        lines.append("| Time | n_at_risk | Deaths | Censored | lx | qx | px | hx | SE(KM) | H(t) NA |")
        lines.append("|------|-----------|--------|----------|-----|-----|-----|-----|--------|---------|")
        for _, row in grp.iterrows():
            na_h = row.get("na_H", 0.0)
            lines.append(
                f"| {row['time']:.1f} | {row['n_at_risk']} | {row['n_deaths']} "
                f"| {row['n_censored']} | {row['lx']:.4f} | {row['qx']:.4f} "
                f"| {row['px']:.4f} | {row['hx']:.6f} | {row['se_km']:.4f} "
                f"| {na_h:.4f} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("*Report generated by pySurvAnalysis v0.3.0*")
    lines.append("")

    return "\n".join(lines)


def _save_if_missing(fig_factory, path: Path) -> None:
    """Generate and save a plot only if the file does not yet exist."""
    if not path.exists():
        try:
            fig = fig_factory()
            _fig_to_file(fig, path)
        except Exception:
            pass


def _render_coef_table_md(coefs: "pd.DataFrame", section_type: str, is_rmst: bool) -> list[str]:
    """Render a coefficient table section in markdown."""
    import pandas as pd

    subset = coefs[coefs["term_type"] == section_type]
    if len(subset) == 0:
        return []

    label_map = {
        "intercept": "Intercept",
        "main_effect": "Main Effects",
        "interaction": "Interaction Effects",
    }
    lines: list[str] = []
    lines.append(f"#### {label_map.get(section_type, section_type)}")
    lines.append("")

    if is_rmst:
        lines.append("| Covariate | Coef (hours) | SE | t | p-value | 95% CI (hours) |")
        lines.append("|-----------|-------------|----|----|---------|----------------|")
        for _, row in subset.iterrows():
            p_str = _format_pvalue(row["p_value"])
            sig = _significance_stars(row["p_value"])
            lines.append(
                f"| {row['covariate']} "
                f"| {row['coef']:.2f} "
                f"| {row['se']:.2f} "
                f"| {row['z']:.3f} "
                f"| {p_str} {sig} "
                f"| ({row['coef_lo']:.2f}, {row['coef_hi']:.2f}) |"
            )
    else:
        lines.append("| Covariate | Coef | HR | SE | z | p-value | 95% CI (HR) |")
        lines.append("|-----------|------|----|----|---|---------|-------------|")
        for _, row in subset.iterrows():
            p_str = _format_pvalue(row["p_value"])
            sig = _significance_stars(row["p_value"])
            lines.append(
                f"| {row['covariate']} "
                f"| {row['coef']:.4f} "
                f"| {row['HR']:.4f} "
                f"| {row['se']:.4f} "
                f"| {row['z']:.3f} "
                f"| {p_str} {sig} "
                f"| ({row['HR_lo']:.3f}, {row['HR_hi']:.3f}) |"
            )
    lines.append("")
    return lines


_REPORT_FOOTER = "---\n*Report generated by pySurvAnalysis v0.3.0*\n"
_INTERACTION_SECTION_HEADER = "## Factorial Interaction Analyses"


def _interaction_factor_lines(result: dict) -> list[str]:
    """Markdown lines describing factors and level filters for one analysis."""
    lines: list[str] = []
    selected = result.get("factors_selected") or result.get("factors_used")
    if selected:
        lines.append(f"**Factors in model:** {', '.join(selected)}  ")
    filters = result.get("factor_level_filters")
    if filters:
        parts = [
            f"{factor}={', '.join(levels)}"
            for factor, levels in sorted(filters.items())
            if levels
        ]
        if parts:
            lines.append(f"**Level filters:** {'; '.join(parts)}  ")
    if result.get("input_file"):
        lines.append(f"**Data file:** `{result['input_file']}`  ")
    return lines


def _format_interaction_metadata_txt(result: dict) -> str:
    """Plain-text metadata for a single Cox/RMST run."""
    model = result.get("model_type", "cox_ph")
    selected = result.get("factors_selected") or result.get("factors_used", [])
    lines = [
        f"Model: {model}",
        f"Input file: {result.get('input_file', 'N/A')}",
        f"Factors in model: {', '.join(selected) if selected else 'N/A'}",
        "Level filters:",
    ]
    for factor, levels in sorted((result.get("factor_level_filters") or {}).items()):
        lines.append(f"  {factor}: {', '.join(levels) if levels else '(none)'}")
    lines.extend([
        f"Formula: {result.get('formula', 'N/A')}",
        f"N subjects: {result.get('n_subjects', 'N/A')}",
        f"N events: {result.get('n_events', 'N/A')}",
    ])
    if model == "rmst_pseudo":
        lines.append(f"Tau (hours): {result.get('tau', 'N/A')}")
    else:
        for key in ("concordance", "AIC", "log_likelihood"):
            if result.get(key) is not None:
                lines.append(f"{key}: {result[key]}")
    return "\n".join(lines)


def _merge_interaction_md_into_report(report_path: Path, interaction_md: str) -> None:
    """Replace or append the interaction-analyses section in an existing report."""
    content = report_path.read_text(encoding="utf-8")
    if _INTERACTION_SECTION_HEADER in content:
        head = content.split(_INTERACTION_SECTION_HEADER, 1)[0].rstrip()
    elif _REPORT_FOOTER in content:
        head = content.split(_REPORT_FOOTER, 1)[0].rstrip()
    else:
        head = content.rstrip()

    if _REPORT_FOOTER in content:
        new_content = f"{head}\n\n{interaction_md.rstrip()}\n\n{_REPORT_FOOTER}"
    else:
        new_content = f"{head}\n\n{interaction_md.rstrip()}\n"
    report_path.write_text(new_content, encoding="utf-8")


def save_interaction_analyses(output_dir: Path, analyses: list[dict]) -> list[Path]:
    """Write Cox/RMST interaction results to ``statistics/`` under *output_dir*.

    Creates per-run coefficient/metadata CSV/TXT files and a combined
    ``interaction_analyses.md``.  If ``report.md`` already exists in
    *output_dir*, its interaction section is updated in place.
    """
    output_dir = Path(output_dir)
    stats_dir = output_dir / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    md = generate_cox_markdown(analyses)
    if md:
        md_path = stats_dir / "interaction_analyses.md"
        md_path.write_text(md, encoding="utf-8")
        saved.append(md_path)

    for i, result in enumerate(analyses, 1):
        prefix = "rmst" if result.get("model_type") == "rmst_pseudo" else "cox_ph"
        run_tag = f"{prefix}_{i:02d}"

        meta_path = stats_dir / f"{run_tag}_metadata.txt"
        meta_path.write_text(_format_interaction_metadata_txt(result), encoding="utf-8")
        saved.append(meta_path)

        coefs = result.get("coefficients")
        if coefs is not None and len(coefs):
            coef_path = stats_dir / f"{run_tag}_coefficients.csv"
            coefs.to_csv(coef_path, index=False)
            saved.append(coef_path)

        ph = result.get("ph_test")
        if ph is not None and len(ph):
            ph_path = stats_dir / f"{run_tag}_ph_test.csv"
            ph.to_csv(ph_path, index=False)
            saved.append(ph_path)

        lr = result.get("lr_interaction")
        if isinstance(lr, dict) and lr:
            lr_path = stats_dir / f"{run_tag}_lr_interaction.json"
            lr_path.write_text(json.dumps(lr, indent=2), encoding="utf-8")
            saved.append(lr_path)

    report_path = output_dir / "report.md"
    if report_path.is_file() and md:
        _merge_interaction_md_into_report(report_path, md)
        saved.append(report_path)

    return saved


def generate_cox_markdown(cox_analyses: list[dict]) -> str:
    """Generate markdown sections for Cox and RMST interaction analyses."""
    if not cox_analyses:
        return ""

    lines: list[str] = []
    lines.append("## Factorial Interaction Analyses")
    lines.append("")

    for i, result in enumerate(cox_analyses, 1):
        model_type = result.get("model_type", "cox_ph")
        is_rmst = model_type == "rmst_pseudo"
        type_label = "RMST Pseudo-Value Regression" if is_rmst else "Cox Proportional Hazards"
        factors_str = ", ".join(result.get("factors_used", []))

        lines.append(f"### Analysis {i} [{type_label}]: {factors_str}")
        lines.append("")
        factor_lines = _interaction_factor_lines(result)
        lines.extend(factor_lines)
        if factor_lines:
            lines.append("")

        if "error" in result:
            lines.append(f"**Error:** {result['error']}")
            lines.append("")
            continue

        lines.append(f"**Model formula:** `{result.get('formula', 'N/A')}`  ")
        lines.append(f"**N subjects:** {result.get('n_subjects', 'N/A')}  ")
        lines.append(f"**N events (deaths):** {result.get('n_events', 'N/A')}  ")

        if is_rmst:
            lines.append(f"**Restriction time (tau):** {result.get('tau', 'N/A')} hours  ")
            lines.append(f"**Overall RMST:** {result.get('rmst_overall', 'N/A')} hours  ")
            lines.append(f"**R-squared:** {result.get('r_squared', 'N/A')}  ")
            if result.get("f_statistic") is not None:
                lines.append(f"**F-statistic:** {result['f_statistic']}  ")
            if result.get("f_p_value") is not None:
                p = result["f_p_value"]
                lines.append(
                    f"**F-test p-value:** {_format_pvalue(p)} {_significance_stars(p)}  "
                )
        else:
            if result.get("concordance") is not None:
                lines.append(f"**Concordance index:** {result['concordance']}  ")
            if result.get("AIC") is not None:
                lines.append(f"**AIC (partial):** {result['AIC']}  ")
            if result.get("log_likelihood") is not None:
                lines.append(f"**Log-likelihood:** {result['log_likelihood']}  ")
            if result.get("log_likelihood_ratio_p") is not None:
                p = result["log_likelihood_ratio_p"]
                lines.append(
                    f"**Likelihood ratio test p-value:** "
                    f"{_format_pvalue(p)} {_significance_stars(p)}  "
                )
        lines.append("")

        coefs = result.get("coefficients")
        if coefs is not None and len(coefs) > 0:
            for section_type in ("intercept", "main_effect", "interaction"):
                lines.extend(_render_coef_table_md(coefs, section_type, is_rmst))

        if result.get("warnings"):
            lines.append("**Warnings:**")
            for w in result["warnings"]:
                lines.append(f"- {w}")
            lines.append("")

        if not is_rmst:
            lines.append("#### Omnibus LR Interaction Test")
            lines.append("")
            lines.append("*Compares main-effects Cox model vs. interaction Cox model.*")
            lines.append("")
            lr = result.get("lr_interaction")
            if lr is None:
                lines.append("*Not applicable — no interaction terms; only one factor selected.*")
                lines.append("")
            else:
                p = lr["p_value"]
                p_str = _format_pvalue(p)
                sig = _significance_stars(p)
                interaction_cols = ", ".join(lr.get("interaction_cols", []))
                conclusion = ("Significant interaction detected" if p < 0.05
                              else "No significant interaction detected")
                lines.append(f"| | Value |")
                lines.append(f"|---|---|")
                lines.append(f"| Interaction terms | {interaction_cols} |")
                lines.append(f"| Log-likelihood (main effects) | {lr['ll_main']} |")
                lines.append(f"| Log-likelihood (interaction) | {lr['ll_interaction']} |")
                lines.append(f"| LR statistic | {lr['lr_stat']:.4f} |")
                lines.append(f"| Degrees of freedom | {lr['df']} |")
                lines.append(f"| p-value | {p_str} {sig} |")
                lines.append(f"| Concordance (main model) | {lr['concordance_main']} |")
                lines.append("")
                lines.append(f"*{conclusion} (p {'<' if p < 0.05 else '≥'} 0.05).*")
                lines.append("")

            lines.append("#### Proportional Hazards Assumption (Schoenfeld Residuals)")
            lines.append("")
            ph = result.get("ph_test")
            if ph is None:
                lines.append("*PH assumption test could not be computed — see warnings above.*")
                lines.append("")
            else:
                lines.append("| Covariate | Test Statistic | p-value | |")
                lines.append("|-----------|---------------|---------|---|")
                all_ok = True
                for _, row in ph.iterrows():
                    p = row.get("p_value", float("nan"))
                    sig = _significance_stars(p)
                    if p < 0.05:
                        all_ok = False
                    p_str = _format_pvalue(p)
                    ts = row.get("test_statistic", float("nan"))
                    lines.append(
                        f"| {row.get('covariate', '?')} "
                        f"| {ts:.4f} "
                        f"| {p_str} "
                        f"| {sig} |"
                    )
                lines.append("")
                if all_ok:
                    lines.append("*PH assumption appears satisfied for all covariates (p ≥ 0.05).*")
                else:
                    lines.append("*Warning: PH assumption may be violated for marked covariate(s). "
                                 "Consider a stratified model or time-varying coefficients.*")
                lines.append("")

    return "\n".join(lines)


def generate_report(result: "AnalysisResult", output_dir: Path) -> Path:
    """Generate Markdown report and save to output directory.

    Includes any accumulated Cox/RMST interaction analyses.
    Returns the path to the generated report file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    md_content = generate_markdown(result, output_dir)

    cox_analyses = getattr(result, "cox_analyses", [])
    if cox_analyses:
        cox_md = generate_cox_markdown(cox_analyses)
        if cox_md:
            footer = "---\n*Report generated by pySurvAnalysis v0.3.0*\n"
            if footer in md_content:
                md_content = md_content.replace(footer, cox_md + "\n" + footer)
            else:
                md_content += "\n" + cox_md + "\n"

    report_path = output_dir / "report.md"
    report_path.write_text(md_content, encoding="utf-8")

    return report_path
