"""``survival_config.yaml`` — read, write, merge, validate.

The config is the authority for everything that used to be UI state: the input
format, the time/event columns, the censoring policy, the active **Exclusion
Group**, the Experiment Type, and (for an Interaction Experiment) the declared
factors and their ordered levels.

Unknown keys ride through a write untouched, so a config edited by a future
version of the app — or by hand — is never silently truncated.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = "survival_config.yaml"
PROJECT_FILENAME = "project.yaml"
BATCH_FILENAME = "batch.yaml"
SPECS_FILENAME = "plot_specs.yaml"

#: Sections merged key-by-key when a Member Experiment inherits Project
#: Defaults. Anything else is replaced wholesale by the member's value.
_DEEP_SECTIONS = ("global", "input", "exclusions")

DEFAULT_INPUT: dict[str, Any] = {
    "format": "auto",          # auto | excel | long | wide
    "time_col": "Age",
    "event_col": "Event",
    "factor_cols": None,
    "factor_names": None,
    "col_mapping": None,
}


def config_path(directory: str | Path) -> Path:
    return Path(directory) / CONFIG_FILENAME


def is_experiment_dir(directory: str | Path) -> bool:
    """True when *directory* is an Experiment Directory (has the marker file).

    ``os.path.isfile``, not ``Path.is_file`` — the latter propagates
    ``PermissionError`` on Python 3.13, and this predicate is called over
    arbitrary trees by the recursive Batch walk. A directory nobody can read
    is "not an experiment", which the walk then reports; it must never be an
    exception out of a structural test.
    """
    return os.path.isfile(config_path(directory))


def load_config(directory: str | Path) -> dict:
    """Read a directory's ``survival_config.yaml`` (``{}`` when absent)."""
    path = config_path(directory)
    if not path.is_file():
        return {}
    return read_yaml(path)


def read_yaml(path: str | Path) -> dict:
    """Read a YAML mapping, returning ``{}`` for an empty or absent file."""
    p = Path(path)
    if not p.is_file():
        return {}
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{p} must contain a YAML mapping, got {type(data).__name__}.")
    return data


def write_yaml(path: str | Path, data: dict) -> Path:
    """Write a YAML mapping, preserving key order."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, indent=2,
                       default_flow_style=False, allow_unicode=True)
    return p.resolve()


def save_config(directory: str | Path, config: dict) -> Path:
    return write_yaml(config_path(directory), config)


def merge_defaults(member: dict, defaults: dict | None) -> dict:
    """Resolve a member config against its Project's ``defaults:``.

    Project Defaults are a *seed and template*, not an authority (ADR-0001):
    anything the member states wins, and the deep sections merge key-by-key so
    a member can override one setting without restating the section.
    """
    resolved = copy.deepcopy(defaults or {})
    member = member or {}
    for key, value in member.items():
        if key in _DEEP_SECTIONS and isinstance(value, dict) \
                and isinstance(resolved.get(key), dict):
            merged = dict(resolved[key])
            merged.update(value)
            resolved[key] = merged
        else:
            resolved[key] = copy.deepcopy(value)
    return resolved


def input_options(config: dict) -> dict:
    """The ``input:`` section with defaults filled in."""
    opts = dict(DEFAULT_INPUT)
    section = (config or {}).get("input") or {}
    if isinstance(section, dict):
        opts.update({k: v for k, v in section.items() if v is not None
                     or k in DEFAULT_INPUT})
    return opts


def exclusion_group(config: dict) -> str | None:
    """The active Exclusion Group, or ``None`` when exclusions are off.

    The group is configuration, never UI state — the same input and config
    always give the same result, and the name is stamped on every output.
    """
    section = (config or {}).get("exclusions") or {}
    if not isinstance(section, dict):
        return None
    group = section.get("group")
    if group is None or str(group).strip() == "":
        return None
    return str(group).strip()


def scripts_of(config: dict, key: str = "scripts") -> list[dict]:
    """The saved step lists under *key* (``[]`` when absent or malformed)."""
    scripts = (config or {}).get(key) or []
    if not isinstance(scripts, list):
        return []
    return [s for s in scripts if isinstance(s, dict) and s.get("name")]


def validate_config(config: dict) -> list[str]:
    """Problems with a resolved config, type-specific checks included."""
    from ..experiment_types import type_for_config

    problems: list[str] = []
    if not isinstance(config, dict):
        return ["Config must be a YAML mapping."]

    try:
        exp_type = type_for_config(config)
    except ValueError as exc:
        return [str(exc)]

    fmt = input_options(config).get("format", "auto")
    if fmt not in {"auto", "excel", "long", "wide"}:
        problems.append(
            f"`input.format` must be auto, excel, long or wide (got {fmt!r})."
        )
    section = config.get("exclusions")
    if section is not None and not isinstance(section, dict):
        problems.append("`exclusions:` must be a mapping, e.g. `{group: default}`.")

    problems.extend(exp_type.validate_config(config))
    return problems
