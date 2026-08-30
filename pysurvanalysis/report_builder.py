"""Build report blocks from analysis results.

This module is the only place that turns numbers into a document. It emits the
backend-agnostic blocks of :mod:`pysurvanalysis.report_pkg.model`, so the PDF
and the markdown are provably the same report — and an Experiment Type's
``report_sections()`` decides which sections appear and in what order.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .report_pkg import model as m
from .report_pkg.render import render


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_pvalue(p: Any) -> str:
    try:
        value = float(p)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(value):
        return "—"
    if value < 0.0001:
        return "<0.0001"
    return f"{value:.4f}"


def significance_stars(p: Any) -> str:
    try:
        value = float(p)
    except (TypeError, ValueError):
        return ""
    if pd.isna(value):
        return ""
    if value < 0.001:
        return "***"
    if value < 0.01:
        return "**"
    if value < 0.05:
        return "*"
    return "ns"


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(f):
        return "—"
    return f"{f:.{digits}f}"


def _level_for_p(p: Any) -> m.Level:
    try:
        value = float(p)
    except (TypeError, ValueError):
        return m.Level.NEUTRAL
    if pd.isna(value):
        return m.Level.NEUTRAL
    return m.Level.OK if value < 0.05 else m.Level.NEUTRAL


def dataframe_table(df: pd.DataFrame, title: str | None = None,
                    caption: str | None = None, digits: int = 3,
                    max_rows: int = 200) -> m.Table | None:
    """A Table block from a DataFrame, cells pre-stringified."""
    if df is None or len(df) == 0:
        return None
    frame = df.head(max_rows)
    columns = [str(c) for c in frame.columns]
    rows: list[list[str]] = []
    for _, row in frame.iterrows():
        cells = []
        for value in row:
            if isinstance(value, float):
                cells.append(_num(value, digits))
            else:
                cells.append("—" if value is None else str(value))
        rows.append(cells)
    note = caption
    if len(df) > max_rows:
        extra = f"Showing the first {max_rows} of {len(df)} rows."
        note = f"{caption} {extra}" if caption else extra
    return m.Table(columns=columns, rows=rows, title=title, caption=note)


def figure_block(path: Path, title: str | None = None,
                 caption: str | None = None) -> m.Figure | None:
    """Load a saved PNG into a Figure block (``None`` when it is missing)."""
    p = Path(path)
    if not p.is_file():
        return None
    return m.Figure(data=p.read_bytes(), fmt=p.suffix.lstrip(".").lower() or "png",
                    width_in=6.5, height_in=4.2, title=title, caption=caption)


# ---------------------------------------------------------------------------
# Experiment-level sections
# ---------------------------------------------------------------------------

def _cover(result, name: str) -> m.Cover:
    exp_type = result.experiment_type
    es = result.experiment_summary or {}
    meta: list[tuple[str, str]] = [
        ("Experiment type", getattr(exp_type, "label", "Custom Experiment")),
        ("Data file", result.input_file.name),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Factors", ", ".join(result.factors) or "none"),
        ("Treatments", str(es.get("n_treatments", "?"))),
        ("Individuals", str(es.get("n_total", "?"))),
        ("Deaths", str(es.get("n_deaths", "?"))),
        ("Censored", f"{es.get('n_censored', '?')} ({es.get('pct_censored', '?')}%)"),
    ]
    group = getattr(result, "exclusion_group", None)
    applied = (result.n_excluded_applied() if hasattr(result, "n_excluded_applied")
               else len(result.excluded_chambers or set()))
    listed = len(result.excluded_chambers or set())
    if group and applied:
        exclusion_text = f"{group} — {applied} chamber(s) removed"
    elif group:
        exclusion_text = (f"{group} — no chambers removed "
                          f"({listed} listed, none present in this data)"
                          if listed else f"{group} — nothing listed")
    elif applied:
        exclusion_text = f"none declared ({applied} removed by the workbook)"
    else:
        exclusion_text = "none"
    meta.append(("Exclusion group", exclusion_text))
    meta.append(("Censoring policy",
                 "unaccounted individuals censored" if result.assume_censored
                 else "unaccounted individuals ignored"))

    status: list[m.StatusLine] = []
    omnibus = result.omnibus_lr or {}
    p = omnibus.get("p_value")
    if p is not None:
        level = m.Level.OK if _level_for_p(p) is m.Level.OK else m.Level.NEUTRAL
        verdict = ("treatments differ" if _level_for_p(p) is m.Level.OK
                   else "no overall difference detected")
        status.append(m.StatusLine(
            f"Omnibus log-rank: {verdict} (p = {format_pvalue(p)}).", level))
    return m.Cover(
        title=getattr(exp_type, "report_title", lambda n: n)(name),
        subtitle=exp_type.report_intro() or "",
        metadata=meta,
        status=status or None,
    )


def _section_summary(result) -> list:
    blocks: list = []
    table = dataframe_table(result.summary, title="Per-treatment summary")
    if table:
        blocks.append(table)
    es = result.experiment_summary or {}
    if es:
        blocks.append(m.Paragraph(
            f"Observation window {_num(es.get('time_min'))}–"
            f"{_num(es.get('time_max'))}, {es.get('n_chambers', 'N/A')} chamber(s)."
        ))
    return blocks


#: Raster resolution for a curated figure placed in the report — the sister
#: app's report figures render at the same, and a page needs more than the
#: preview's screen resolution.
_REPORT_FIGURE_DPI = 200


def _curated_figure(result, plot_id: str, specs, title: str,
                    caption: str | None):
    """The Publication Figure curated for *plot_id*, as a report block — or
    ``None`` when nothing is curated for it, or rendering it failed.

    A curated figure outranks the analysis's own matplotlib PNG: the whole
    point of curating in the Plot Editor is that THIS is the figure the
    experiment is meant to be seen through, and a report showing a different
    one beside it would be two figures disagreeing about one result. The
    default stays as the fallback, never the other way round.
    """
    from . import pubfigures

    experiment = getattr(result, "experiment", None)
    if experiment is None or specs is None:
        return None
    spec = specs.get(pubfigures._SPEC_ALIASES.get(plot_id, plot_id))
    if spec is None:
        return None
    try:
        style = pubfigures.resolve_style(spec.style, experiment)
        frame = pubfigures.data_for(experiment, spec)
        if frame.empty:
            return None
        figure = pubfigures.build_ggplot(frame, spec, style)
        data = pubfigures.render_png_bytes(figure, style, dpi=_REPORT_FIGURE_DPI)
    except Exception:  # noqa: BLE001 - a broken curation must not sink the report
        return None
    return m.Figure(
        data=data, fmt="png",
        width_in=float(style.width_mm) / 25.4,
        height_in=float(style.height_mm) / 25.4,
        title=f"{title} — curated figure",
        caption=caption,
    )


def _section_figures(result) -> list:
    from . import plot_registry, pubfigures

    blocks: list = []
    paths = getattr(result, "figure_paths", {}) or {}
    exp_type = result.experiment_type
    headline = getattr(exp_type, "headline_plot_id", None)
    order = [headline] + [pid for pid in paths if pid != headline] if headline in paths \
        else list(paths)

    ## What the Plot Editor curated for this experiment's container, read
    ## once. None (not {}) when there is no experiment to ask, so the loop
    ## below cannot mistake "unknown" for "nothing curated".
    experiment = getattr(result, "experiment", None)
    specs = None
    if experiment is not None:
        try:
            specs = pubfigures.adopt_legacy_member_specs(experiment).plots
        except Exception:  # noqa: BLE001
            specs = None

    placed: set[str] = set()
    for plot_id in order:
        path = paths.get(plot_id)
        if path is None:
            continue
        try:
            registry_spec = plot_registry.get(plot_id)
        except KeyError:
            continue
        label = registry_spec.label + (" — headline figure" if plot_id == headline else "")

        ## The two default KM figures are one curated figure (the at-risk band
        ## is a Style toggle there), so a curated km_curves stands in for BOTH
        ## and the second default is dropped rather than shown beside it.
        curated_id = pubfigures._SPEC_ALIASES.get(plot_id, plot_id)
        if curated_id in placed:
            continue
        block = _curated_figure(result, plot_id, specs, label,
                                registry_spec.caption)
        if block is not None:
            placed.add(curated_id)
        else:
            block = figure_block(path, title=label, caption=registry_spec.caption)
        if block:
            blocks.append(block)
    return blocks


def _section_lifespan(result) -> list:
    blocks: list = []
    for df, title in ((result.median_surv, "Median survival"),
                      (result.mean_surv, "Mean survival")):
        table = dataframe_table(df, title=title)
        if table:
            blocks.append(table)
    stats = result.lifespan_stats or {}
    if isinstance(stats, dict):
        for key, title in (("treatment_stats", "Lifespan statistics by treatment"),
                           ("factor_stats", "Lifespan statistics by factor level")):
            table = dataframe_table(stats.get(key), title=title)
            if table:
                blocks.append(table)
    table = dataframe_table(result.surv_quantiles, title="Survival quantiles")
    if table:
        blocks.append(table)
    return blocks


def _section_tests(result) -> list:
    blocks: list = []
    omnibus = result.omnibus_lr or {}
    if omnibus:
        blocks.append(m.Table(
            columns=["Test", "chi²", "df", "p", ""],
            rows=[[
                "Omnibus log-rank",
                _num(omnibus.get("chi2") or omnibus.get("test_statistic")
                     or omnibus.get("statistic")),
                str(omnibus.get("df") or omnibus.get("degrees_of_freedom") or "—"),
                format_pvalue(omnibus.get("p_value")),
                significance_stars(omnibus.get("p_value")),
            ]],
            title="Overall comparison",
        ))
    for df, title in ((result.pairwise_lr, "Pairwise log-rank"),
                      (result.pairwise_gw, "Pairwise Gehan-Wilcoxon"),
                      (result.hazard_ratios, "Pairwise hazard ratios")):
        table = dataframe_table(df, title=title)
        if table:
            if "p_value" in getattr(df, "columns", []):
                table.row_levels = [_level_for_p(v) for v in df["p_value"].head(200)]
            blocks.append(table)
    return blocks


def _section_interaction(result) -> list:
    """The factorial models — the Interaction Experiment's reason to exist."""
    blocks: list = []
    for model in result.cox_analyses or []:
        title = model.get("title") or model.get("model_type", "Factorial model")
        if model.get("error"):
            blocks.append(m.Paragraph(f"**{title}** could not be fitted: "
                                      f"{model['error']}"))
            continue
        blocks.append(m.Heading(title, level=2))
        formula = model.get("formula")
        if formula:
            blocks.append(m.Paragraph(f"Model: `{formula}`"))
        meta = []
        for key, label in (("n_subjects", "n"), ("n_events", "events"),
                           ("concordance", "concordance"), ("AIC", "AIC")):
            if model.get(key) is not None:
                meta.append(f"{label} = {_num(model[key])}")
        if meta:
            blocks.append(m.Paragraph(", ".join(meta) + "."))

        lr = model.get("lr_interaction") or {}
        if lr:
            p = lr.get("p_value")
            blocks.append(m.Table(
                columns=["Test", "chi²", "df", "p", ""],
                rows=[["Interaction (LR, vs main-effects model)",
                       _num(lr.get("statistic")), str(lr.get("df", "—")),
                       format_pvalue(p), significance_stars(p)]],
                row_levels=[_level_for_p(p)],
                caption=("A significant interaction means the effect of one "
                         "factor depends on the level of the other."),
            ))
        coefs = model.get("coefficients")
        table = dataframe_table(coefs, title="Coefficients",
                                caption="Relative to each factor's reference level.")
        if table is not None:
            if isinstance(coefs, pd.DataFrame) and "p_value" in coefs.columns:
                table.row_levels = [_level_for_p(v) for v in coefs["p_value"].head(200)]
            blocks.append(table)
        ph = model.get("ph_test")
        table = dataframe_table(
            ph, title="Proportional-hazards check (Schoenfeld residuals)",
            caption="Small p-values indicate the PH assumption is violated.")
        if table is not None:
            blocks.append(table)
    return blocks


def _section_quality(result) -> list:
    blocks: list = []
    applied = (result.n_excluded_applied() if hasattr(result, "n_excluded_applied")
               else len(result.excluded_chambers or set()))
    excluded = sorted(map(str, result.excluded_chambers or set())) if applied else []
    group = getattr(result, "exclusion_group", None)
    if excluded:
        blocks.append(m.Paragraph(
            f"{len(excluded)} chamber(s) excluded"
            + (f" via group **{group}**" if group else "")
            + f": {', '.join(excluded)}."
        ))
    else:
        blocks.append(m.Paragraph("No chambers were excluded from this analysis."))
    models = result.parametric_models or {}
    if models:
        rows = [[str(k), _num(v.get("AIC")) if isinstance(v, dict) else _num(v)]
                for k, v in models.items()]
        blocks.append(m.Table(columns=["Parametric model", "AIC"], rows=rows,
                              title="Parametric model fits"))
    return blocks


_SECTION_BUILDERS = {
    "summary": _section_summary,
    "figures": _section_figures,
    "lifespan": _section_lifespan,
    "tests": _section_tests,
    "interaction": _section_interaction,
    "quality": _section_quality,
}


def build_experiment_report(result, name: str | None = None) -> m.Report:
    """The block document for one Experiment Directory's analysis."""
    exp = getattr(result, "experiment", None)
    label = name or (exp.name if exp is not None else result.input_file.stem)
    exp_type = result.experiment_type
    report = m.Report(title=label)
    report.add(_cover(result, label))

    for section in exp_type.report_sections():
        builder = _SECTION_BUILDERS.get(section.key)
        if builder is None:
            continue
        blocks = builder(result)
        if not blocks:
            continue
        report.add(m.SectionDivider(section.title))
        report.extend(blocks)
    return report


def write_experiment_report(result, output_dir: str | Path,
                            formats: tuple[str, ...] = ("pdf", "md")) -> dict[str, Path]:
    """Render the experiment report. Returns ``{format: path}``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    exp = getattr(result, "experiment", None)
    stem = exp.name if exp is not None else result.input_file.stem
    report = build_experiment_report(result)

    written: dict[str, Path] = {}
    if "pdf" in formats:
        target = out / f"{stem}_report.pdf"
        try:
            render(report, str(target), backend="reportlab")
            written["pdf"] = target
        except Exception:  # noqa: BLE001 - markdown must still be written
            pass
    if "md" in formats:
        target = out / "report.md"
        render(report, str(target), backend="markdown")
        written["md"] = target
    return written
