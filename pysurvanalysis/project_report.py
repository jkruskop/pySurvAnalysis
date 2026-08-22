"""The Project Report — one bound document, one section per Member Experiment.

A Project never pools (ADR-0001), so this binder combines nothing: it reads
each member's *saved* analysis outputs and lays them out one after another,
behind a cover carrying the Member Inventory and the Divergence Note. A member
that has not been analysed yields a "not analysed" section — the report never
silently analyses on the user's behalf.

Members' sections are built by the same ``report_builder`` section functions the
per-experiment report uses, fed by :class:`SavedAnalysis` — a read-only view of
``analysis/`` shaped like an ``AnalysisResult``. One set of section builders,
two sources.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import report_builder as rb
from .report_pkg import model as m
from .report_pkg.render import render


class SavedAnalysis:
    """A member's saved ``analysis/`` directory, shaped like an AnalysisResult.

    Only the attributes the report sections actually read are provided; each is
    loaded lazily so binding a ten-member Project doesn't read forty CSVs it
    will not use.
    """

    def __init__(self, experiment):
        self.experiment = experiment
        self.experiment_type = experiment.type
        self.analysis_dir = experiment.analysis_dir
        self.summary_path = self.analysis_dir / "run_summary.json"
        self.payload: dict[str, Any] = {}
        if self.summary_path.is_file():
            try:
                self.payload = json.loads(self.summary_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - a corrupt summary reads as "not analysed"
                self.payload = {}

    # ── availability ───────────────────────────────────────────────────────

    @property
    def exists(self) -> bool:
        return bool(self.payload)

    # ── AnalysisResult-shaped attributes ───────────────────────────────────

    @property
    def input_file(self) -> Path:
        return Path(self.payload.get("input_file") or self.experiment.name)

    @property
    def factors(self) -> list[str]:
        return list(self.payload.get("factors") or [])

    @property
    def assume_censored(self) -> bool:
        return bool(self.payload.get("assume_censored", True))

    @property
    def exclusion_group(self) -> str | None:
        return self.payload.get("exclusion_group")

    @property
    def excluded_chambers(self) -> set:
        # Identities are not saved, only the count; the quality section reports
        # the count, which is exactly what the stamp promises.
        return set(range(int(self.payload.get("n_excluded") or 0)))

    def n_excluded_applied(self) -> int:
        return int(self.payload.get("n_excluded") or 0)

    @property
    def experiment_summary(self) -> dict:
        keys = ("n_total", "n_deaths", "n_censored", "n_treatments", "n_chambers",
                "time_min", "time_max")
        out = {k: self.payload.get(k) for k in keys}
        total, censored = out.get("n_total"), out.get("n_censored")
        if total and censored is not None:
            out["pct_censored"] = round(100.0 * censored / total, 1)
        return out

    @property
    def omnibus_lr(self) -> dict:
        return self.payload.get("omnibus_lr") or {}

    def _csv(self, *relative: str) -> pd.DataFrame:
        for rel in relative:
            path = self.analysis_dir / rel
            if path.is_file():
                try:
                    return pd.read_csv(path)
                except Exception:  # noqa: BLE001 - an unreadable CSV is an empty table
                    return pd.DataFrame()
        return pd.DataFrame()

    @property
    def summary(self) -> pd.DataFrame:
        return self._csv("data_output/summary.csv")

    @property
    def median_surv(self) -> pd.DataFrame:
        return self._csv("data_output/median_survival.csv")

    @property
    def mean_surv(self) -> pd.DataFrame:
        return self._csv("data_output/mean_survival.csv")

    @property
    def surv_quantiles(self) -> pd.DataFrame:
        return self._csv("statistics/survival_quantiles.csv")

    @property
    def pairwise_lr(self) -> pd.DataFrame:
        return self._csv("statistics/logrank_pairwise.csv")

    @property
    def pairwise_gw(self) -> pd.DataFrame:
        return self._csv("statistics/gehan_wilcoxon_pairwise.csv")

    @property
    def hazard_ratios(self) -> pd.DataFrame:
        return self._csv("statistics/hazard_ratios.csv")

    @property
    def lifespan_stats(self) -> dict:
        return {
            "treatment_stats": self._csv("statistics/lifespan_treatment_stats.csv"),
            "factor_stats": self._csv("statistics/lifespan_factor_stats.csv"),
        }

    @property
    def parametric_models(self) -> dict:
        return {}

    @property
    def cox_analyses(self) -> list[dict]:
        models: list[dict] = []
        for i, meta in enumerate(self.payload.get("factorial_models") or [], 1):
            model = dict(meta)
            coefs = self._csv(f"statistics/factorial_{i:02d}_coefficients.csv")
            if len(coefs):
                model["coefficients"] = coefs
            ph = self._csv(f"statistics/factorial_{i:02d}_ph_test.csv")
            if len(ph):
                model["ph_test"] = ph
            models.append(model)
        return models

    @property
    def figure_paths(self) -> dict[str, Path]:
        plots = self.analysis_dir / "plots"
        return {
            plot_id: plots / filename
            for plot_id, filename in (self.payload.get("figures") or {}).items()
            if (plots / filename).is_file()
        }


# ---------------------------------------------------------------------------
# Cover, inventory, divergence
# ---------------------------------------------------------------------------

def _inventory_table(project, saved: dict[str, SavedAnalysis]) -> m.Table:
    """One row per Member Experiment — the reader's map of the Project."""
    columns = ["Member", "Analysed", "N", "Deaths", "Censored", "Treatments",
               "Factors", "Exclusion group"]
    rows: list[list[str]] = []
    levels: list[m.Level | None] = []
    for member in project.members():
        s = saved[member.name]
        es = s.experiment_summary if s.exists else {}
        rows.append([
            member.name,
            (s.payload.get("analyzed_at") or "yes") if s.exists else "no",
            str(es.get("n_total") or "—"),
            str(es.get("n_deaths") or "—"),
            (f"{es.get('n_censored')} ({es.get('pct_censored')}%)"
             if s.exists and es.get("n_censored") is not None else "—"),
            str(es.get("n_treatments") or "—"),
            ", ".join(s.factors) if s.exists else "—",
            s.exclusion_group or "none",
        ])
        levels.append(m.Level.NEUTRAL if s.exists else m.Level.WARN)
    return m.Table(columns=columns, rows=rows, title="Member inventory",
                   row_levels=levels,
                   caption="Each member is analysed independently; nothing here "
                           "is pooled.")


def _divergence_blocks(project) -> list:
    divergences = project.divergences()
    if not divergences:
        return [m.Paragraph(
            "No divergence detected between members: they declare the same "
            "factors, levels, censoring policy and exclusion group."
        )]
    blocks: list = [m.Paragraph(
        "Members of this Project differ in the ways listed below. Divergence is "
        "expected — these experiments address one question in slightly different "
        "ways — and no result in this report combines across them."
    )]
    blocks.append(m.Table(
        columns=["Aspect", "How members differ"],
        rows=[[d.aspect, d.detail] for d in divergences],
        title="Divergence note",
        row_levels=[m.Level.WARN] * len(divergences),
    ))
    return blocks


def build_project_report(project, narrative: dict[str, str] | None = None) -> m.Report:
    """The bound document: cover, inventory, divergence, then member sections."""
    saved = {mem.name: SavedAnalysis(mem) for mem in project.members()}
    analysed = [n for n, s in saved.items() if s.exists]

    report = m.Report(title=project.name)
    status = [m.StatusLine(
        f"{len(analysed)} of {len(saved)} member experiment(s) analysed.",
        m.Level.OK if saved and len(analysed) == len(saved) else m.Level.WARN,
    )] if saved else [m.StatusLine("This Project has no Member Experiments yet.",
                                   m.Level.WARN)]
    report.add(m.Cover(
        title=f"{project.name} — Project Report",
        subtitle=project.question,
        metadata=[
            ("Experiment type", project.type.label),
            ("Members", str(len(saved))),
            ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Path", str(project.directory)),
        ],
        status=status,
    ))

    report.add(m.SectionDivider("Members"))
    if saved:
        report.add(_inventory_table(project, saved))
    report.extend(_divergence_blocks(project))

    if narrative and narrative.get("__across__"):
        report.add(m.Heading("Across members", level=2))
        report.add(m.Paragraph(narrative["__across__"]))
        report.add(m.Paragraph(
            "*Qualitative summary only — no statistic in this report combines "
            "members.*"
        ))

    for member in project.members():
        s = saved[member.name]
        report.add(m.PageBreak())
        report.add(m.SectionDivider(member.name,
                                    subtitle=member.type.label))
        if not s.exists:
            report.add(m.Paragraph(
                f"**{member.name} has not been analysed.** Run its analysis and "
                f"rebuild this report; nothing was computed on its behalf here."
            ))
            problems = member.validate()
            if problems:
                report.add(m.Table(
                    columns=["Problem"], rows=[[p] for p in problems],
                    row_levels=[m.Level.ERROR] * len(problems),
                    title="Why it cannot be analysed as configured",
                ))
            continue

        if narrative and narrative.get(member.name):
            report.add(m.Paragraph(narrative[member.name]))

        for section in member.type.report_sections():
            builder = rb._SECTION_BUILDERS.get(section.key)
            if builder is None:
                continue
            try:
                blocks = builder(s)
            except Exception as exc:  # noqa: BLE001 - one bad section, not one bad report
                blocks = [m.Paragraph(f"*{section.title} could not be rebuilt from "
                                      f"the saved analysis: {exc}*")]
            if not blocks:
                continue
            report.add(m.Heading(section.title, level=1))
            report.extend(blocks)

    return report


def write_project_report(project, formats: tuple[str, ...] = ("pdf", "md"),
                         narrative: dict[str, str] | None = None,
                         log=None) -> dict[str, Path]:
    """Render the Project Report into the Project root. Returns ``{fmt: path}``."""
    emit = log or (lambda _m: None)
    report = build_project_report(project, narrative=narrative)
    written: dict[str, Path] = {}
    stem = project.directory.name

    if "pdf" in formats:
        target = project.directory / f"{stem}_report.pdf"
        try:
            render(report, str(target), backend="reportlab")
            written["pdf"] = target
            emit(f"Wrote {target}")
        except Exception as exc:  # noqa: BLE001 - markdown must still be written
            emit(f"PDF report failed ({exc}); writing markdown only.")
    if "md" in formats:
        target = project.directory / f"{stem}_report.md"
        render(report, str(target), backend="markdown")
        written["md"] = target
        emit(f"Wrote {target}")
    return written
