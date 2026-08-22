"""Upgrade — turning a pre-overhaul directory into an Experiment Directory.

Non-destructive by contract. It writes ``survival_config.yaml`` seeded by
sniffing the data file, imports ``survival_scripts.yaml`` into the config's
``scripts:``, copies ``remove_chambers.csv`` into ``qc/``, and never touches an
existing ``<stem>_results/`` folder. Nothing is deleted, nothing is moved: the
old artefacts stay exactly where they are and new runs simply write to
``analysis/``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import config as cfgmod
from .experiment import is_data_file

LEGACY_SCRIPTS_FILENAME = "survival_scripts.yaml"
LEGACY_EXCLUSIONS_FILENAME = "remove_chambers.csv"


@dataclass
class UpgradePlan:
    """What an upgrade would do — shown to the user before anything is written."""

    directory: Path
    data_file: Path | None = None
    proposed_config: dict = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not self.actions


def needs_upgrade(directory: str | Path) -> bool:
    """True for a directory that holds survival data but no config yet."""
    d = Path(directory)
    if not d.is_dir() or cfgmod.is_experiment_dir(d):
        return False
    if (d / LEGACY_SCRIPTS_FILENAME).is_file():
        return True
    if (d / LEGACY_EXCLUSIONS_FILENAME).is_file():
        return True
    if any(d.glob("*_results")):
        return True
    return bool(_data_candidates(d))


def _data_candidates(directory: Path) -> list[Path]:
    out: list[Path] = []
    for base in (directory / "data", directory):
        if base.is_dir():
            out.extend(sorted(p for p in base.iterdir() if is_data_file(p)))
        if out:
            break
    return out


def sniff_config(data_file: Path | None, type_key: str | None = None) -> dict:
    """Seed a config from what the data file itself reveals.

    Excel workbooks are self-describing (the Design sheet names the factors),
    so only the type's defaults are needed. A CSV has to be probed for its
    shape and column names, which is exactly what the loader's own detector
    does — reused here rather than reimplemented.
    """
    from ..experiment_types import get_type

    exp_type = get_type(type_key)
    config = exp_type.scaffold_config()
    if data_file is None:
        return config

    suffix = data_file.suffix.lower()
    if suffix == ".xlsx":
        config["input"] = {"format": "excel"}
        try:
            from .. import data_loader

            assume = data_loader.read_assume_censored(data_file)
            config.setdefault("global", {})["assume_censored"] = bool(assume)
        except Exception:  # noqa: BLE001 - a missing PrivateData sheet is normal
            pass
        return config

    if suffix in {".csv", ".tsv"}:
        fmt = "long"
        try:
            from .. import data_loader

            fmt = data_loader.detect_csv_format(data_file, time_col="Age",
                                                event_col="Event")
        except Exception:  # noqa: BLE001 - fall back to the documented default
            pass
        config["input"] = {"format": fmt, "time_col": "Age", "event_col": "Event"}
    return config


def plan(directory: str | Path, type_key: str | None = None) -> UpgradePlan:
    """Describe the upgrade without performing it."""
    d = Path(directory).resolve()
    p = UpgradePlan(directory=d)

    if cfgmod.is_experiment_dir(d):
        p.warnings.append(
            f"{d.name} already has {cfgmod.CONFIG_FILENAME} — nothing to upgrade."
        )
        return p

    candidates = _data_candidates(d)
    if len(candidates) == 1:
        p.data_file = candidates[0]
    elif len(candidates) > 1:
        p.data_file = candidates[0]
        p.warnings.append(
            f"{len(candidates)} data files found "
            f"({', '.join(c.name for c in candidates)}); the config will name "
            f"{candidates[0].name}. Edit `data_file:` to choose another."
        )
    else:
        p.warnings.append(
            "No .xlsx/.csv/.tsv found — the config will be written with type "
            "defaults only, and you will need to add the data file."
        )

    p.proposed_config = sniff_config(p.data_file, type_key)
    if p.data_file is not None and len(candidates) > 1:
        p.proposed_config["data_file"] = p.data_file.name
    p.actions.append(f"write {cfgmod.CONFIG_FILENAME}")

    legacy_scripts = d / LEGACY_SCRIPTS_FILENAME
    if legacy_scripts.is_file():
        scripts = cfgmod.scripts_of(cfgmod.read_yaml(legacy_scripts), "scripts")
        if scripts:
            p.proposed_config["scripts"] = scripts
            p.actions.append(
                f"import {len(scripts)} script(s) from {LEGACY_SCRIPTS_FILENAME} "
                f"(the file is left in place)"
            )

    legacy_excl = d / LEGACY_EXCLUSIONS_FILENAME
    if legacy_excl.is_file():
        p.actions.append(f"copy {LEGACY_EXCLUSIONS_FILENAME} into qc/")
        from .. import exclusions

        groups = exclusions.list_groups(d)
        if groups:
            p.proposed_config["exclusions"] = {"group": groups[0]}
            p.actions.append(f"set the active exclusion group to {groups[0]!r}")

    results = sorted(d.glob("*_results"))
    if results:
        p.warnings.append(
            f"Existing results ({', '.join(r.name for r in results)}) are left "
            f"untouched; new runs write to analysis/."
        )
    p.actions.append("create analysis/ and qc/")
    return p


def apply(plan_or_dir, type_key: str | None = None) -> UpgradePlan:
    """Perform an upgrade. Accepts a :class:`UpgradePlan` or a directory."""
    p = plan_or_dir if isinstance(plan_or_dir, UpgradePlan) \
        else plan(plan_or_dir, type_key)
    if p.is_noop:
        return p

    d = p.directory
    (d / "analysis").mkdir(exist_ok=True)
    (d / "qc").mkdir(exist_ok=True)

    legacy_excl = d / LEGACY_EXCLUSIONS_FILENAME
    target = d / "qc" / LEGACY_EXCLUSIONS_FILENAME
    if legacy_excl.is_file() and not target.exists():
        shutil.copy2(legacy_excl, target)

    cfgmod.save_config(d, p.proposed_config)
    return p
