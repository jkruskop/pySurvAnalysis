"""Provider-agnostic contract for the AI narrative.

A provider turns a prompt plus a text digest into prose. It never sees raw
data and never computes anything: the digest it receives is already the
pipeline's own output, which is what keeps the promise that the AI
*summarizes* the analysis and does not perform its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ProviderError(RuntimeError):
    """A provider could not produce text — never fatal to a report."""


@dataclass
class Provider:
    """Base class: a name, a model, and a ``complete`` method."""

    name: str = "base"
    env_key: str = ""
    models: tuple[str, ...] = ()
    model: str = ""

    def __post_init__(self) -> None:
        if not self.model and self.models:
            self.model = self.models[0]

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.env_key) or None

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, max_tokens: int = 1600) -> str:
        raise NotImplementedError


def load_dotenv_if_present(start: str | None = None) -> None:
    """Load a ``.env`` so a key can live beside the project, not in the shell."""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # noqa: BLE001 - python-dotenv is optional at runtime
        return
    path = find_dotenv(usecwd=True) if start is None else start
    if path:
        load_dotenv(path, override=False)
