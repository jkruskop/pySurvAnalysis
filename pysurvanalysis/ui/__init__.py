"""Shared themed-UI primitives for pySurvAnalysis Qt apps.

Vendored from PyTrackingAnalysis with ``Ptrack*`` objectNames renamed to
``Psurv*`` so the QSS rules don't collide if the projects share a process.
"""

from .icons import icon
from .theme import (Category, ThemeMode, apply_theme, category_color, current_mode,
                    resolved_mode, surface_colors)
from .widgets import ActionButton, Card, OutputLog, PlotDock, SidebarNav, TopBar
from .zoom import ZoomableImageView, ZoomableMarkdownView, ZoomableTextView

__all__ = [
    "ActionButton",
    "Card",
    "Category",
    "OutputLog",
    "PlotDock",
    "SidebarNav",
    "ThemeMode",
    "TopBar",
    "ZoomableImageView",
    "ZoomableMarkdownView",
    "ZoomableTextView",
    "apply_theme",
    "category_color",
    "current_mode",
    "icon",
    "resolved_mode",
    "surface_colors",
]
