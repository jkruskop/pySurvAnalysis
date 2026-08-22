"""Centralised icon factory for pySurvAnalysis.

Wraps ``qtawesome`` so glyph names live in one file and tinting follows the
active theme + category color. Use ``icon("load")`` for a category icon, or
``icon("fa5s.folder")`` for an explicit qtawesome name.
"""

from __future__ import annotations

import qtawesome as qta
from PyQt6.QtGui import QIcon

from .theme import Category, category_color, resolved_mode

# Logical name → (qtawesome glyph, default Category for tinting).
_GLYPHS: dict[str, tuple[str, Category | None]] = {
    # Navigation / sidebar
    "home":          ("fa5s.home",                 Category.NEUTRAL),
    "project":       ("fa5s.folder-open",          Category.NEUTRAL),
    "run":           ("fa5s.bolt",                 Category.LOAD),
    "plots":         ("fa5s.chart-bar",            Category.PLOTS),
    "qc":            ("fa5s.search",               Category.QC),
    "scripts":       ("fa5s.scroll",               Category.SCRIPTS),
    "tools":         ("fa5s.tools",                Category.TOOLS),
    "batch":         ("fa5s.layer-group",          Category.NEUTRAL),
    "experiment":    ("fa5s.flask",                Category.NEUTRAL),
    "analyze":       ("fa5s.microscope",           Category.ANALYZE),
    "ai":            ("fa5s.robot",                Category.AI),
    "settings":      ("fa5s.cog",                  Category.NEUTRAL),
    "theme_dark":    ("fa5s.moon",                 Category.NEUTRAL),
    "theme_light":   ("fa5s.sun",                  Category.NEUTRAL),
    # Actions
    "load":          ("fa5s.download",             Category.LOAD),
    "remove":        ("fa5s.minus-circle",         Category.LOAD),
    "script":        ("fa5s.play",                 Category.SCRIPTS),
    "csv":           ("fa5s.file-csv",             Category.LOAD),
    "excel":         ("fa5s.file-excel",           Category.LOAD),
    "compare":       ("fa5s.code-branch",          Category.ANALYZE),
    "pdf":           ("fa5s.file-pdf",             Category.ANALYZE),
    "plot":          ("fa5s.chart-line",           Category.PLOTS),
    "lint":          ("fa5s.spell-check",          Category.TOOLS),
    "clear":         ("fa5s.trash-alt",            Category.TOOLS),
    "refresh":       ("fa5s.sync-alt",             Category.TOOLS),
    "config":        ("fa5s.sliders-h",            Category.TOOLS),
    "report":        ("fa5s.file-alt",             Category.ANALYZE),
    # Survival-specific
    "km":            ("fa5s.chart-line",           Category.PLOTS),
    "hazard":        ("fa5s.heartbeat",            Category.PLOTS),
    "risk":          ("fa5s.shield-alt",           Category.PLOTS),
    "forest":        ("fa5s.tree",                 Category.PLOTS),
    "logrank":       ("fa5s.balance-scale",        Category.ANALYZE),
    "cox":           ("fa5s.project-diagram",      Category.ANALYZE),
    "rmst":          ("fa5s.calculator",           Category.ANALYZE),
    "parametric":    ("fa5s.wave-square",          Category.ANALYZE),
    "chamber":       ("fa5s.th",                   Category.QC),
    "filter":        ("fa5s.filter",               Category.LOAD),
    "factors":       ("fa5s.tags",                 Category.LOAD),
    # File menu
    "open":          ("fa5s.folder-open",          Category.NEUTRAL),
    "save":          ("fa5s.save",                 Category.LOAD),
    "save_as":       ("fa5s.file-export",          Category.LOAD),
    "new":           ("fa5s.file",                 Category.NEUTRAL),
    # Misc
    "warning":       ("fa5s.exclamation-triangle", Category.QC),
    "info":          ("fa5s.info-circle",          Category.NEUTRAL),
    "play":          ("fa5s.play",                 Category.LOAD),
    "stop":          ("fa5s.stop",                 Category.QC),
    "browse":        ("fa5s.ellipsis-h",           Category.NEUTRAL),
    "add":           ("fa5s.plus-circle",          Category.LOAD),
    "up":            ("fa5s.chevron-up",           Category.NEUTRAL),
    "down":          ("fa5s.chevron-down",         Category.NEUTRAL),
    "menu":          ("fa5s.ellipsis-v",           Category.NEUTRAL),
    "delete":        ("fa5s.times-circle",         Category.QC),
    "check":         ("fa5s.check-circle",         Category.ANALYZE),
    "upgrade":       ("fa5s.level-up-alt",         Category.TOOLS),
    "figures":       ("fa5s.image",                Category.PLOTS),
    "interaction":   ("fa5s.random",               Category.PLOTS),
    "validate":      ("fa5s.clipboard-check",      Category.TOOLS),
}


def _tint_for(category: Category | None) -> str:
    if category is None:
        return "#cbd5e1" if resolved_mode() == "dark" else "#334155"
    return category_color(category)


def icon(name: str, category: Category | None = None) -> QIcon:
    """Return a themed QIcon for *name*.

    *name* is either a logical key (``"load"``) or an explicit qtawesome
    glyph (``"fa5s.folder-open"``). *category* overrides the default tint
    registered for that key.
    """
    if name in _GLYPHS:
        glyph, default_category = _GLYPHS[name]
    else:
        glyph, default_category = name, None
    color = _tint_for(category if category is not None else default_category)
    return qta.icon(glyph, color=color)
