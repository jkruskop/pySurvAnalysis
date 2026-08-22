"""The Experiment Directory — one cohort, analysed on its own.

``survival_config.yaml`` at the root marks it; the input workbook/CSV sits at
the root or in ``data/``; every output goes to ``analysis/``; QC state lives in
``qc/``; publication figures land in ``figures/``. An Experiment Directory is
either standalone or a **Member Experiment** of a Project (ADR-0003) — nothing
about the object changes between those two cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config as cfgmod

DATA_SUFFIXES = (".xlsx", ".csv", ".tsv")

#: Sidecar CSVs that live beside the data and must never be mistaken for it.
NON_DATA_NAMES = frozenset({"remove_chambers.csv"})


def is_data_file(path: Path) -> bool:
    """True for a plausible input file (not a sidecar, not an Excel lock file)."""
    return (
        path.is_file()
        and path.suffix.lower() in DATA_SUFFIXES
        and path.name.lower() not in NON_DATA_NAMES
        and not path.name.startswith("~$")
    )


class ExperimentError(RuntimeError):
    """A problem that prevents an Experiment Directory being used."""


@dataclass
class ExperimentStatus:
    """What the Hub's members table and the Project Report's inventory show."""

    name: str
    analyzed: bool = False
    n_total: int | None = None
    n_deaths: int | None = None
    n_censored: int | None = None
    n_treatments: int | None = None
    factors: tuple[str, ...] = ()
    type_key: str = "custom"
    exclusion_group: str | None = None
    n_excluded: int = 0
    analyzed_at: str | None = None
    problems: tuple[str, ...] = ()


class SurvivalExperiment:
    """One Experiment Directory, its config resolved and its type in hand."""

    def __init__(self, directory: str | Path, defaults: dict | None = None,
                 project: Any = None):
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir():
            raise ExperimentError(f"Not a directory: {self.directory}")
        self.raw_config = cfgmod.load_config(self.directory)
        self.defaults = dict(defaults or {})
        self.config = cfgmod.merge_defaults(self.raw_config, self.defaults)
        self.project = project
        from ..experiment_types import type_for_config

        self.type = type_for_config(self.config)

        # Populated by :meth:`load`.
        self.data = None
        self.factors: list[str] = []
        self.result = None

    # ── identity ───────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.directory.name

    @property
    def is_configured(self) -> bool:
        return cfgmod.config_path(self.directory).is_file()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SurvivalExperiment {self.name} type={self.type.key}>"

    # ── paths ──────────────────────────────────────────────────────────────

    @property
    def config_path(self) -> Path:
        return cfgmod.config_path(self.directory)

    @property
    def data_dir(self) -> Path:
        return self.directory / "data"

    @property
    def analysis_dir(self) -> Path:
        return self.directory / "analysis"

    @property
    def qc_dir(self) -> Path:
        return self.directory / "qc"

    @property
    def figures_dir(self) -> Path:
        return self.directory / "figures"

    @property
    def specs_path(self) -> Path:
        return self.directory / cfgmod.SPECS_FILENAME

    def ensure_dirs(self) -> None:
        for d in (self.analysis_dir, self.qc_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ── the input file ─────────────────────────────────────────────────────

    def data_file(self) -> Path:
        """The input workbook/CSV.

        A ``data_file:`` key in the config wins; otherwise ``data/`` is searched
        before the directory root. Exactly one candidate must survive — an
        ambiguous directory is an error naming what it found, never a silent
        pick.
        """
        named = self.config.get("data_file")
        if named:
            candidate = Path(named)
            if not candidate.is_absolute():
                candidate = self.directory / candidate
            if not candidate.is_file():
                raise ExperimentError(
                    f"{self.name}: `data_file: {named}` does not exist "
                    f"(looked at {candidate})."
                )
            return candidate

        for base in (self.data_dir, self.directory):
            if not base.is_dir():
                continue
            found = sorted(p for p in base.iterdir() if is_data_file(p))
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                raise ExperimentError(
                    f"{self.name}: {len(found)} data files in {base.name or '.'} "
                    f"({', '.join(p.name for p in found)}). Name one with "
                    f"`data_file:` in {cfgmod.CONFIG_FILENAME}."
                )
        raise ExperimentError(
            f"{self.name}: no .xlsx/.csv/.tsv found in {self.directory} or its "
            f"data/ subdirectory."
        )

    def has_data(self) -> bool:
        try:
            self.data_file()
        except ExperimentError:
            return False
        return True

    # ── configuration ──────────────────────────────────────────────────────

    @property
    def exclusion_group(self) -> str | None:
        return cfgmod.exclusion_group(self.config)

    def excluded_chambers(self) -> set:
        from .. import exclusions

        group = self.exclusion_group
        if not group:
            return set()
        return exclusions.chambers_for_group(self.directory, group)

    def scripts(self) -> list[dict]:
        """Experiment Scripts: the member's own, then the Project's central set."""
        own = cfgmod.scripts_of(self.raw_config, "scripts")
        if self.project is None:
            return own
        central = self.project.experiment_scripts()
        names = {s["name"] for s in own}
        return own + [s for s in central if s["name"] not in names]

    def validate(self) -> list[str]:
        """Config-level problems (no data is loaded)."""
        problems = list(cfgmod.validate_config(self.config))
        if not self.has_data():
            problems.append(
                f"No input data file found in {self.directory.name} "
                f"(looked in data/ and the directory root)."
            )
        return problems

    # ── loading and analysis ───────────────────────────────────────────────

    def load(self, extra_excluded: set | None = None):
        """Load the individual-level frame, type preparation applied."""
        from .. import data_loader

        opts = cfgmod.input_options(self.config)
        path = self.data_file()
        excluded = set(self.excluded_chambers()) | set(extra_excluded or set())
        if path.suffix.lower() == ".xlsx":
            excluded |= set(data_loader.load_chamber_flags(path))

        fmt = str(opts.get("format", "auto"))
        csv_format = "auto" if fmt in {"auto", "excel"} else fmt
        data, factors = data_loader.load_experiment(
            path,
            assume_censored=self.type.resolve_assume_censored(self.config),
            excluded_chambers=excluded,
            time_col=str(opts.get("time_col") or "Age"),
            event_col=str(opts.get("event_col") or "Event"),
            factor_cols=opts.get("factor_cols"),
            csv_format=csv_format,
            col_mapping=opts.get("col_mapping"),
            factor_names=opts.get("factor_names"),
        )
        data = self.type.prepare_data(data, self.config)
        self.data, self.factors = data, factors
        return data, factors

    def run_analysis(self, log=None, extra_excluded: set | None = None):
        """Run the type's battery and write everything under ``analysis/``."""
        from .. import pipeline

        self.ensure_dirs()
        result = pipeline.run_analysis(
            self.data_file(),
            output_dir=self.analysis_dir,
            experiment=self,
            extra_excluded_chambers=set(extra_excluded or set())
            | set(self.excluded_chambers()),
            log=log,
        )
        self.result = result
        self.data = result.individual_data
        self.factors = result.factors
        return result

    # ── status ─────────────────────────────────────────────────────────────

    def status(self) -> ExperimentStatus:
        """A cheap, filesystem-only summary — never loads the raw data."""
        import json

        st = ExperimentStatus(
            name=self.name,
            type_key=self.type.key,
            exclusion_group=self.exclusion_group,
        )
        try:
            st.problems = tuple(self.validate())
        except Exception as exc:  # noqa: BLE001 - a broken config must still list
            st.problems = (str(exc),)

        summary_path = self.analysis_dir / "run_summary.json"
        if summary_path.is_file():
            try:
                payload = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                payload = {}
            st.analyzed = True
            st.n_total = payload.get("n_total")
            st.n_deaths = payload.get("n_deaths")
            st.n_censored = payload.get("n_censored")
            st.n_treatments = payload.get("n_treatments")
            st.factors = tuple(payload.get("factors") or ())
            st.analyzed_at = payload.get("analyzed_at")
            st.n_excluded = int(payload.get("n_excluded") or 0)
            st.exclusion_group = payload.get("exclusion_group", st.exclusion_group)
        return st
