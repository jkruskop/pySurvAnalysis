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

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import config as cfgmod
from .experiment import SurvivalExperiment, is_data_file


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
    """True when *directory* carries a ``project.yaml``.

    ``os.path.isfile`` for the same reason as
    :func:`config.is_experiment_dir`: a structural predicate the recursive
    Batch walk runs over every directory it meets must answer "no" for an
    unreadable one, not raise.
    """
    return os.path.isfile(Path(directory) / cfgmod.PROJECT_FILENAME)


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
        """Subdirectories that could become members but hold no config yet.

        One walk, not two: :func:`layout.initializable_dirs` answers exactly
        this question for the Hub's *Initialize existing directory…* picker,
        and a second implementation here would be free to disagree with the
        picker about what the Project can still adopt.
        """
        from . import layout as layout_mod

        return [item.directory for item in
                layout_mod.initializable_dirs(self.directory)]

    def unconfigured_dirs(self) -> list[str]:
        """Names of :meth:`candidate_dirs` — the third state a folder can be
        in, and the one the members table cannot show by itself."""
        return [d.name for d in self.candidate_dirs()]

    def member_dir(self, name: str) -> Path:
        """Where a member of this Project called *name* would live.

        *name* is joined onto the Project directory, so it must be a single
        folder name: a separator or a ``..`` in it would place the member —
        and its ``data/`` — outside the Project entirely.
        """
        if not name or name != Path(name).name or name in (".", ".."):
            raise ProjectError(
                f"{name!r} is not a member name — it must be a single folder "
                f"name inside the project.")
        return self.directory / name

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

    def type_problems_for(self, config: dict, label: str = "config") -> list[str]:
        """Why *config* could not be a member of this Project (empty = it can).

        Exactly one rule, and the same one :meth:`validate` enforces every
        time the Project loads (ADR-0001): a member must share the Project's
        Experiment Type. Differing factors, levels and censoring policy are
        **Divergence** — legal, declared on the report — so they are not
        checked here; refusing them would enforce a uniformity this Project
        deliberately does not have.

        Nor are ordinary config problems: an unusable ``input.format`` makes a
        member fail, but it does not stop the *Project* loading, so it is
        something to report after the write rather than grounds to refuse one.
        This answers "can this be a member", and nothing else.

        Used before a config is copied over a scaffold, so a file that would
        make the Project refuse to load is never written in the first place.
        """
        from ..experiment_types import type_for_config

        try:
            expected = self.type
        except ValueError as exc:
            return [f"this Project's own type is unusable: {exc}"]
        try:
            actual = type_for_config(config)
        except ValueError as exc:
            return [f"{label}: {exc}"]
        if actual.key != expected.key:
            return [f"{label} is a {actual.label} but the Project's type is "
                    f"{expected.label}. Every Member Experiment must share it "
                    f"— the type selects the analyses, the Plot Set and the "
                    f"report sections."]
        return []

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
        ## A file with no `scripts:` key at all predates the seeded default
        ## (or was hand-written): give it one on the next write so every
        ## Project ships a visible, editable run. An existing block is never
        ## touched — an empty list is a deliberate deletion, and re-seeding it
        ## would undo the user's edit.
        if "scripts" not in self.config:
            self.config["scripts"] = [default_project_script()]
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
            "scripts": [default_project_script()],
            "experiment_scripts": [],
        }
        cfgmod.write_yaml(path, body)
        return Project(d)

    def adopt_directory(self, source: str | Path) -> SurvivalExperiment:
        """Take an existing experiment directory into this Project.

        *source* must hold a ``data/`` subdirectory with a DLife workbook in
        it. A directory that is not already a direct child of the Project is
        **copied** in — the Project owns its members, and analysing a folder
        that lives somewhere else would write outputs outside the Project.
        A directory with no ``survival_config.yaml`` gets a default one from
        the Project's Experiment Type.
        """
        import shutil

        from .. import data_loader

        src = Path(source).expanduser().resolve()
        if not src.is_dir():
            raise ProjectError(f"{src} is not a directory.")
        if src == self.directory:
            raise ProjectError("That is the Project directory itself.")
        if src in self.directory.parents:
            ## Copying an ancestor of the Project into the Project would copy
            ## the Project into itself.
            raise ProjectError(f"{src} contains this Project.")
        if is_project_dir(src):
            raise ProjectError(f"{src.name} is a Project, not an experiment "
                               f"directory.")

        data_dir = src / "data"
        if not data_dir.is_dir():
            raise ProjectError(f"{src.name} has no data/ subdirectory.")
        candidates = [p for p in sorted(data_dir.iterdir()) if is_data_file(p)]
        workbooks = [p for p in candidates if p.suffix.lower() == ".xlsx"]
        if not workbooks:
            raise ProjectError(f"No .xlsx file in {src.name}/data.")

        chosen, problems = None, []
        for book in workbooks:
            found = data_loader.validate_dlife_workbook(book)
            if not found:
                chosen = book
                break
            problems = problems or found
        if chosen is None:
            raise ProjectError("; ".join(problems))

        if src.parent == self.directory:
            dest = src                       # already a member's home: adopt in place
        else:
            dest = self.directory / src.name
            if dest.exists():
                raise ProjectError(f"{dest} already exists.")
            shutil.copytree(src, dest)

        if not cfgmod.is_experiment_dir(dest):
            config = self._member_config_for(dest / "data" / chosen.name)
            if len(candidates) > 1:
                ## More than one data file: name the one that was validated,
                ## or loading the member is ambiguous.
                config["data_file"] = f"data/{chosen.name}"
            cfgmod.save_config(dest, config)
        self._members = None
        return SurvivalExperiment(dest, defaults=self.defaults, project=self)

    def adopt_data_file(self, source: str | Path, *,
                        name: str | None = None) -> SurvivalExperiment:
        """Scaffold a Member Experiment around one DLife workbook.

        The member is named after the file (``cohort_a.xlsx`` →
        ``cohort_a/``), the file lands in its ``data/``, and a default config
        comes from the Project's Experiment Type. A file already inside the
        Project is **moved** rather than copied — it was loose in the tree,
        and leaving a copy behind would make the Project ambiguous about which
        one is the member's data.
        """
        import shutil

        from .. import data_loader

        src = Path(source).expanduser().resolve()
        problems = data_loader.validate_dlife_workbook(src)
        if problems:
            raise ProjectError("; ".join(problems))

        member_name = (name or src.stem).strip()
        if not member_name:
            raise ProjectError(f"{src.name} has no usable base name.")
        dest = self.directory / member_name
        target = dest / "data" / src.name
        inside = self.directory in src.parents

        if target.exists() and target.samefile(src):
            pass                              # already where it belongs
        elif dest.exists():
            raise ProjectError(f"{dest} already exists.")
        else:
            target.parent.mkdir(parents=True)
            if inside:
                shutil.move(str(src), str(target))
            else:
                shutil.copy2(src, target)

        if not cfgmod.is_experiment_dir(dest):
            cfgmod.save_config(dest, self._member_config_for(target))
        self._members = None
        return SurvivalExperiment(dest, defaults=self.defaults, project=self)

    def _member_config_for(self, data_file: Path) -> dict:
        """A config for a member built around *data_file*.

        Minimal on purpose (as in :meth:`add_member`) — everything the
        Project's ``defaults:`` supplies is inherited — plus the two things
        only the file itself can say: how to read it, and whether its
        PrivateData sheet turns off assumed censoring.
        """
        from . import upgrade as upgrade_mod

        config = self.type.scaffold_config(minimal=True)
        sniffed = upgrade_mod.sniff_config(data_file, self.type_key)
        if sniffed.get("input"):
            config["input"] = sniffed["input"]
        assume = (sniffed.get("global") or {}).get("assume_censored")
        inherited = (self.defaults.get("global") or {}).get("assume_censored", True)
        if assume is not None and bool(assume) != bool(inherited):
            config.setdefault("global", {})["assume_censored"] = bool(assume)
        return config

    def add_member(self, name: str, *, config: dict | None = None) -> SurvivalExperiment:
        """Scaffold a new Member Experiment from the Project Defaults.

        *name* is a single folder name inside the Project. It is joined onto
        the Project directory, so a separator or a ``..`` in it would write a
        config — and a ``data/`` folder — outside the Project entirely.
        """
        d = self.member_dir(name)
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
def default_project_script() -> dict:
    """The Project Script a new ``project.yaml`` is seeded with — the
    ``batch`` script a Batch Run executes here (see
    :mod:`pysurvanalysis.script_editor.project_actions`)."""
    from ..script_editor.project_actions import default_project_script as seed

    return seed()
