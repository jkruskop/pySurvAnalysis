"""Environment hygiene for the pySurvAnalysis desktop apps.

Vendored from PyTrackingAnalysis (`pytrackinganalysis/gui_env.py`) — the same
toolkit, the same desktop sessions, the same complaint at startup.
"""

from __future__ import annotations

import os

# GNOME/IBus on Wayland manages these through ibus-ui-gtk3. Leaving inherited
# module overrides set can make Qt/GTK complain at app startup.
INPUT_METHOD_ENV_VARS = ("QT_IM_MODULE", "GTK_IM_MODULE")


def sanitize_input_method_environment() -> None:
    """Remove desktop-session input-method overrides before Qt starts."""
    for name in INPUT_METHOD_ENV_VARS:
        os.environ.pop(name, None)


def use_agg_matplotlib() -> None:
    """Pin pyplot to the Agg backend, before anything imports pyplot.

    The Hub runs analyses on worker threads, and those analyses build their
    figures with ``plt.subplots``. With PyQt6 already imported, pyplot
    auto-selects QtAgg — so every worker-thread figure constructed a Qt
    canvas off the main thread, and matplotlib warned "Starting a Matplotlib
    GUI outside of the main thread will likely fail" once per figure (and it
    genuinely can fail). Nothing here needs pyplot's GUI machinery: a figure
    shown in a tab is re-bound explicitly with ``FigureCanvasQTAgg(figure)``
    by the PlotDock and the QC viewer, which works on an Agg-managed figure —
    the standard embedding pattern.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
