"""Chamber exclusion groups for pySurvAnalysis projects.

Exclusions are stored in ``remove_chambers.csv`` in the project directory.
Each row names a *group*, a chamber id, and an optional note. Different
groups let different scripts (or manual hub runs) apply different
exclusion sets from the same dataset.

CSV format::

    group,chamber,note
    default,3,low N — early deaths only
    default,7,
    review_v2,12,suspicious survival

Modeled on pyflic's ``base/exclusions.py``; the only difference is the
absence of a ``dfm_id`` column — survival projects don't have DFMs.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

_FILENAME = "remove_chambers.csv"
_QC_SUBDIR = "qc"


def exclusions_path(experiment_dir: str | Path) -> Path:
    """Where an Experiment Directory's exclusion file lives.

    Canonically ``qc/remove_chambers.csv``. A pre-overhaul directory keeps its
    copy at the root; that copy is honoured for reading but new writes go to
    ``qc/`` (see :mod:`pysurvanalysis.domain.upgrade`).
    """
    base = Path(experiment_dir)
    qc = base / _QC_SUBDIR / _FILENAME
    if qc.is_file():
        return qc
    legacy = base / _FILENAME
    if legacy.is_file():
        return legacy
    return qc
_FIELDNAMES = ["group", "chamber", "note"]


def _coerce_chamber(value: object) -> object:
    """Best-effort chamber coercion: int when it parses, str otherwise."""
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return s


def read_exclusions(project_dir: str | Path) -> dict[str, list]:
    """Read ``remove_chambers.csv`` and return ``{group: [chamber, ...]}``.

    Returns an empty dict if the file does not exist or cannot be parsed.
    Chamber lists are sorted (numerically when possible).
    """
    path = exclusions_path(project_dir)
    if not path.exists():
        return {}
    result: dict[str, list] = {}
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                group = str(row.get("group", "") or "").strip()
                if not group:
                    continue
                chamber = _coerce_chamber(row.get("chamber"))
                if chamber is None:
                    continue
                bucket = result.setdefault(group, [])
                if chamber not in bucket:
                    bucket.append(chamber)
    except Exception:  # noqa: BLE001
        return {}
    for group in result:
        try:
            result[group] = sorted(result[group], key=lambda x: (isinstance(x, str), x))
        except TypeError:
            result[group] = sorted(map(str, result[group]))
    return result


def list_groups(project_dir: str | Path) -> list[str]:
    """Return group names in the order they first appear in the CSV."""
    path = exclusions_path(project_dir)
    if not path.exists():
        return []
    seen: list[str] = []
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                group = str(row.get("group", "") or "").strip()
                if group and group not in seen:
                    seen.append(group)
    except Exception:  # noqa: BLE001
        return []
    return seen


def write_exclusions(
    project_dir: str | Path,
    group: str,
    chambers: Iterable,
    notes: dict | None = None,
) -> Path:
    """Write/update one named *group* in ``remove_chambers.csv``.

    All rows for *group* are replaced with the entries in *chambers*. Rows
    for all other groups are preserved unchanged. If *chambers* is empty,
    all rows for *group* are removed.

    Parameters
    ----------
    project_dir:
        Experiment Directory (the file lives in its ``qc/`` subdirectory).
    group:
        Name of the exclusion group to update (e.g. ``"default"``).
    chambers:
        Iterable of chamber ids (int or str) — the complete desired
        exclusion set for this group.
    notes:
        Optional ``{chamber: note_text}`` for per-entry notes.

    Returns
    -------
    Path
        Absolute path to the written ``remove_chambers.csv``.
    """
    path = exclusions_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    notes = notes or {}

    existing_rows: list[dict] = []
    if path.exists():
        try:
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if str(row.get("group", "") or "").strip() != group:
                        existing_rows.append(dict(row))
        except Exception:  # noqa: BLE001
            existing_rows = []

    chambers_list = list(chambers)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for row in existing_rows:
            writer.writerow({k: row.get(k, "") for k in _FIELDNAMES})
        for chamber in chambers_list:
            note = notes.get(chamber, "")
            writer.writerow({"group": group, "chamber": chamber, "note": note})
    return path.resolve()


def chambers_for_group(project_dir: str | Path, group: str) -> set:
    """Convenience: return the set of chambers excluded by *group*."""
    return set(read_exclusions(project_dir).get(group, []))
