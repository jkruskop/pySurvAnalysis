"""The Project — a binder of independent Member Experiments (ADR-0001).

A directory with ``project.yaml`` at its root whose immediate subdirectories
holding a ``survival_config.yaml`` are its Member Experiments. A Project never
pools: there is no combined analysis, no pooled statistic, no mixed model. Its
products are a shared **Plot Style** library, two script levels, and a Project
Report that binds one independent section per member.

``defaults:`` is a seed and template, not an authority. Exactly one thing is
validated across members: they all share the Project's **Experiment Type**,
because the type selects the analyses, the Plot Set and the report sections.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import config as cfgmod
from .experiment import SurvivalExperiment


class ProjectError(RuntimeError):
    """A problem that prevents a Project being loaded or run."""


@dataclass(frozen=True)
class Divergence:
    """One way in which Member Experiments differ.

    Divergence is legal here (members address one question different ways),
    which is exactly why the Project Report must declare it.
    """

    aspect: str          # "factors" | "levels" | "treatments" | "censoring" | …
    detail: str

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.aspect}: {self.detail}"


def is_project_dir(directory: str | Path) -> bool:
    return (Path(directory) / cfgmod.PROJECT_FILENAME).is_file()


def find_project_root(directory: str | Path) -> Path | None:
    """The Project a directory belongs to: itself, or its parent."""
    d = Path(directory).resolve()
    if is_project_dir(d):
        return d
    if is_project_dir(d.parent):
        return d.parent
    return None


class Project:
    """A loaded Project: its defaults, its members, its scripts and styles."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()
        path = self.directory / cfgmod.PROJECT_FILENAME
        if not path.is_file():
            raise ProjectError(
                f"{self.directory} is not a Project — no {cfgmod.PROJECT_FILENAME}. "
                f"Create one with the Hub's Create/Load card."
            )
        self.config = cfgmod.read_yaml(path)
        self._members: list[SurvivalExperiment] | None = None

    # ── identity ───────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return str(self.config.get("name") or self.directory.name)

    @property
    def question(self) -> str:
        """The one-line question the members address, shown on the report cover."""
        return str(self.config.get("question") or "")

    @property
    def config_path(self) -> Path:
        return self.directory / cfgmod.PROJECT_FILENAME

    @property
    def specs_path(self) -> Path:
        return self.directory / cfgmod.SPECS_FILENAME

    @property
    def report_path(self) -> Path:
        return self.directory / f"{self.directory.name}_report.pdf"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Project {self.name} members={len(self.member_dirs())}>"

    # ── defaults and type ──────────────────────────────────────────────────

    @property
    def defaults(self) -> dict:
        """Project Defaults — the seed inherited by members."""
        d = self.config.get("defaults") or {}
        return dict(d) if isinstance(d, dict) else {}

    @property
    def type_key(self) -> str | None:
        """The Experiment Type every member must share (``None`` = Custom)."""
        return self.defaults.get("experiment_type")

    @property
    def type(self):
        from ..experiment_types import get_type

        return get_type(self.type_key)

    # ── members ────────────────────────────────────────────────────────────

    def member_dirs(self) -> list[Path]:
        """Immediate subdirectories holding a ``survival_config.yaml``."""
        if not self.directory.is_dir():
            return []
        return sorted(
            d for d in self.directory.iterdir()
            if d.is_dir() and cfgmod.is_experiment_dir(d)
        )

    def candidate_dirs(self) -> list[Path]:
        """Subdirectories that could become members but hold no config yet."""
        skip = {"analysis", "qc", "data", "figures", "__pycache__"}
        return sorted(
            d for d in self.directory.iterdir()
            if d.is_dir() and not cfgmod.is_experiment_dir(d)
            and d.name not in skip and not d.name.startswith(".")
        )

    def members(self, reload: bool = False) -> list[SurvivalExperiment]:
        if self._members is None or reload:
            self._members = [
                SurvivalExperiment(d, defaults=self.defaults, project=self)
                for d in self.member_dirs()
            ]
        return list(self._members)

    def member(self, name: str) -> SurvivalExperiment:
        for m in self.members():
            if m.name == name:
                return m
        raise ProjectError(
            f"{self.name} has no member named {name!r}. Members: "
            f"{', '.join(m.name for m in self.members()) or 'none'}."
        )

    def __iter__(self) -> Iterator[SurvivalExperiment]:
        return iter(self.members())

    # ── validation ─────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """The one hard cross-member rule, plus each member's own problems.

        Differing factors, levels, treatments and chamber counts are *not*
        errors — they are reported as Divergence instead.
        """
        problems: list[str] = []
        try:
            expected = self.type
        except ValueError as exc:
            return [f"{cfgmod.PROJECT_FILENAME}: {exc}"]

        for member in self.members():
            try:
                actual = member.type
            except ValueError as exc:
                problems.append(f"{member.name}: {exc}")
                continue
            if actual.key != expected.key:
                problems.append(
                    f"{member.name} is a {actual.label} but the Project's type is "
                    f"{expected.label}. Every Member Experiment must share the "
                    f"Project's Experiment Type — it selects the analyses, the "
                    f"Plot Set and the report sections."
                )
            problems.extend(f"{member.name}: {p}" for p in member.validate())
        return problems

    def divergences(self) -> list[Divergence]:
        """Where members differ — declared on the Project Report, never fatal."""
        members = self.members()
        if len(members) < 2:
            return []

        out: list[Divergence] = []
        factor_sets: dict[str, tuple[str, ...]] = {}
        censoring: dict[str, bool] = {}
        groups: dict[str, str | None] = {}
        for m in members:
            declared = (m.config.get("factors") or {})
            names = tuple(str(k) for k in declared) if isinstance(declared, dict) else ()
            if not names:
                st = m.status()
                names = st.factors
            factor_sets[m.name] = names
            censoring[m.name] = m.type.resolve_assume_censored(m.config)
            groups[m.name] = m.exclusion_group

        distinct = {v for v in factor_sets.values() if v}
        if len(distinct) > 1:
            out.append(Divergence(
                "factors",
                "; ".join(f"{n}: {', '.join(v) or 'unknown'}"
                          for n, v in factor_sets.items()),
            ))

        level_sets: dict[str, dict[str, tuple[str, ...]]] = {}
        for m in members:
            declared = m.config.get("factors") or {}
            if isinstance(declared, dict):
                level_sets[m.name] = {
                    str(k): tuple(str(x) for x in (v or []))
                    for k, v in declared.items()
                }
        all_factor_names = {f for lv in level_sets.values() for f in lv}
        for factor in sorted(all_factor_names):
            seen = {n: lv.get(factor) for n, lv in level_sets.items() if factor in lv}
            if len({v for v in seen.values() if v}) > 1:
                out.append(Divergence(
                    "levels",
                    f"{factor} — " + "; ".join(
                        f"{n}: {', '.join(v)}" for n, v in seen.items() if v),
                ))

        if len(set(censoring.values())) > 1:
            out.append(Divergence(
                "censoring",
                "; ".join(f"{n}: {'assumed' if v else 'not assumed'}"
                          for n, v in censoring.items()),
            ))
        if len({g for g in groups.values()}) > 1:
            out.append(Divergence(
                "exclusion group",
                "; ".join(f"{n}: {g or 'none'}" for n, g in groups.items()),
            ))
        return out

    # ── scripts ────────────────────────────────────────────────────────────

    def scripts(self) -> list[dict]:
        """Project Scripts saved in ``project.yaml``."""
        return cfgmod.scripts_of(self.config, "scripts")

    def experiment_scripts(self) -> list[dict]:
        """The central Experiment Scripts one recipe serves every member from."""
        return cfgmod.scripts_of(self.config, "experiment_scripts")

    def save(self) -> Path:
        return cfgmod.write_yaml(self.config_path, self.config)

    # ── creation ───────────────────────────────────────────────────────────

    @staticmethod
    def create(directory: str | Path, *, name: str | None = None,
               question: str = "", type_key: str | None = None,
               defaults: dict | None = None, overwrite: bool = False) -> "Project":
        """Write a ``project.yaml`` and return the loaded Project."""
        from ..experiment_types import get_type

        d = Path(directory).resolve()
        d.mkdir(parents=True, exist_ok=True)
        path = d / cfgmod.PROJECT_FILENAME
        if path.is_file() and not overwrite:
            raise ProjectError(f"{path} already exists.")

        exp_type = get_type(type_key)
        seed = dict(defaults or {})
        seed.setdefault("global", dict(exp_type.default_global))
        if not exp_type.is_custom:
            seed = {"experiment_type": exp_type.key, **seed}
        body = {
            "name": name or d.name,
            "question": question,
            "defaults": seed,
            "scripts": [DEFAULT_PROJECT_SCRIPT],
            "experiment_scripts": [],
        }
        cfgmod.write_yaml(path, body)
        return Project(d)

    def add_member(self, name: str, *, config: dict | None = None) -> SurvivalExperiment:
        """Scaffold a new Member Experiment from the Project Defaults."""
        d = self.directory / name
        d.mkdir(parents=True, exist_ok=True)
        if not cfgmod.is_experiment_dir(d):
            body = dict(config or {})
            if not body:
                # Minimal on purpose: everything the Project's `defaults:`
                # already supplies is inherited, so editing the Project keeps
                # reaching this member.
                body = self.type.scaffold_config(minimal=True)
                missing = [k for k in ("factors",)
                           if k in self.type.scaffold_config() and k not in self.defaults]
                for key in missing:
                    body[key] = self.type.scaffold_config()[key]
            cfgmod.save_config(d, body)
        (d / "data").mkdir(exist_ok=True)
        self._members = None
        return SurvivalExperiment(d, defaults=self.defaults, project=self)


#: Written into every new ``project.yaml``. A Batch Run executes this copy by
#: default, so zero authoring already means "report on every Project".
DEFAULT_PROJECT_SCRIPT = {
    "name": "Report pipeline",
    "steps": [
        {"action": "run_in_experiments", "script": "Standard analysis"},
        {"action": "render_publication_figures"},
        {"action": "project_report"},
    ],
}
