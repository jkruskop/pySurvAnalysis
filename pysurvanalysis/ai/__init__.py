"""AI narrative subsystem — opt-in, soft-failing, summarizing only."""

from .base import Provider, ProviderError
from . import narrative

__all__ = ["Provider", "ProviderError", "narrative"]
