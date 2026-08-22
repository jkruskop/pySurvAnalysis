# Mirrored files

pySurvAnalysis duplicates generic UI and scripting code from
[PyTrackingAnalysis](../PyTrackingAnalysis) rather than sharing a package
(see [ADR-0006](docs/adr/0006-duplicate-not-shared-package.md)). Duplication
is the cheaper option today — the two apps' dependency floors conflict
(`pandas>=3.0.2` here, `>=2.2.3` there) and their domains have diverged — but
its cost is drift, and drift that nobody can see is drift nobody fixes.

This file makes it visible. Each row records what was copied, from where, and
at which upstream commit, so a future extraction into a shared package is
mechanical rather than archaeological.

**Upstream baseline:** `PyTrackingAnalysis@5499e8a` (2026-08-22)

| File here | Upstream path | Relationship |
|---|---|---|
| `pysurvanalysis/report_pkg/model.py` | `pytrackinganalysis/report/model.py` | **verbatim** (module path renamed) |
| `pysurvanalysis/report_pkg/render.py` | `pytrackinganalysis/report/render.py` | verbatim + a `markdown` backend entry |
| `pysurvanalysis/report_pkg/backends/reportlab_backend.py` | same | **verbatim** (module path renamed) |
| `pysurvanalysis/report_pkg/backends/markdown_backend.py` | — | **new here**; a second backend over the same blocks |
| `pysurvanalysis/apps/_hub_tiles.py` | `pytrackinganalysis/apps/_hub_tiles.py` | **verbatim** (`Ptrack*` objectNames → `Psurv*`) |
| `pysurvanalysis/ui/theme.py` | `pytrackinganalysis/ui/theme.py` | vendored earlier; + `surface_colors()`, `Category.AI`, card-label QSS |
| `pysurvanalysis/ui/widgets.py` | `pytrackinganalysis/ui/widgets.py` | vendored earlier; Card now paints from `surface_colors()` |
| `pysurvanalysis/ui/icons.py` | `pytrackinganalysis/ui/icons.py` | vendored earlier; survival-specific glyphs added |
| `pysurvanalysis/ui/zoom.py` | `pytrackinganalysis/ui/zoom.py` | vendored earlier; has since grown locally |
| `pysurvanalysis/script_editor/{canvas,inspector,palette,window}.py` | same | vendored earlier; `window.py` is now level-aware, `palette.py` rebuildable |
| `pysurvanalysis/apps/hub.py` | `pytrackinganalysis/apps/hub.py` | **structure ported, body rewritten** — same tile strip and panel model, survival domain, type-contributed Analyze cards |
| `pysurvanalysis/apps/plot_editor.py` | `pytrackinganalysis/apps/plot_editor.py` | **structure ported** — same Spec/Style editing model, experiment-level (ADR-0005) |
| `pysurvanalysis/pubfigures.py` | `pytrackinganalysis/pubfigures.py` | **reimplemented** on the same Spec/Style contract for survivorship curves + the At-Risk Band (ADR-0004) |
| `pysurvanalysis/script_editor/project_actions.py` | `pytrackinganalysis/script_editor/project_actions.py` | **reimplemented**; no pooling actions, adds the type-registry hard error |

## Not mirrored — deliberate divergences

* **No pooling anywhere.** `Project` has no combined analysis, no pooled
  statistics, no mixed model (ADR-0001).
* **Standalone experiments load without a Project** (ADR-0003), inverting the
  sister app's ADR-0008.
* **Experiment Types contribute Hub buttons and script actions** (ADR-0002).
  This idea originates here; upstream has a fixed registry because it has one
  Experiment Type. It is the first thing to backport.
* **Plot Editor is experiment-level, Styles resolve upward** (ADR-0005).

## Keeping this honest

When you copy something new across, add a row. When you edit a file marked
*verbatim*, change its relationship to describe the edit — a row that claims
"verbatim" while the file has diverged is worse than no row at all.
