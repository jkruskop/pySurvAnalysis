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

**Upstream baseline:** `PyTrackingAnalysis@07199a6` (2026-08-24), raised from
`@5499e8a` by the recursive-discovery and UI pass below. The `batch`-script
rules (ADR-0007) were re-checked against `@4008526`.

| File here | Upstream path | Relationship |
|---|---|---|
| `pysurvanalysis/report_pkg/model.py` | `pytrackinganalysis/report/model.py` | **verbatim** (module path renamed) |
| `pysurvanalysis/report_pkg/render.py` | `pytrackinganalysis/report/render.py` | verbatim + a `markdown` backend entry |
| `pysurvanalysis/report_pkg/backends/reportlab_backend.py` | same | **verbatim** (module path renamed) |
| `pysurvanalysis/report_pkg/backends/markdown_backend.py` | — | **new here**; a second backend over the same blocks |
| `pysurvanalysis/apps/_hub_tiles.py` | `pytrackinganalysis/apps/_hub_tiles.py` | was verbatim (`Ptrack*` objectNames → `Psurv*`); now + the full dim treatment (background/title/icon), `TilePanel._content_height`, and `TilePanel.cards()` so the Hub can dim a whole panel |
| `pysurvanalysis/ui/theme.py` | `pytrackinganalysis/ui/theme.py` | vendored earlier; + `surface_colors()`, `Category.AI`, card-label QSS |
| `pysurvanalysis/ui/widgets.py` | `pytrackinganalysis/ui/widgets.py` | vendored earlier; Card paints from `surface_colors()` and now has `set_dimmed`/`restyle`; OutputLog has `append_stream`/`clear_log`; PlotDock has the clear bar. No Errors tab here, so the bar has two buttons rather than three |
| `pysurvanalysis/gui_env.py` | `pytrackinganalysis/gui_env.py` | **verbatim** — same toolkit, same Wayland/IBus complaint at startup |
| `pysurvanalysis/ui/icons.py` | `pytrackinganalysis/ui/icons.py` | vendored earlier; survival-specific glyphs added |
| `pysurvanalysis/ui/zoom.py` | `pytrackinganalysis/ui/zoom.py` | vendored earlier; has since grown locally |
| `pysurvanalysis/script_editor/{canvas,inspector,palette,window}.py` | same | vendored earlier; `window.py` is now level-aware, `palette.py` rebuildable |
| `pysurvanalysis/apps/hub.py` | `pytrackinganalysis/apps/hub.py` | **structure ported, body rewritten** — same tile strip and panel model, survival domain, type-contributed Analyze cards; now also the cached recursive scan, batch table with keys/status/red rows/context menu, card dimming, always-lit Batch and Project tiles, tab suppression, and stream logging |
| `pysurvanalysis/apps/plot_editor.py` | `pytrackinganalysis/apps/plot_editor.py` | **structure ported** — same Spec/Style editing model, experiment-level (ADR-0005) |
| `pysurvanalysis/pubfigures.py` | `pytrackinganalysis/pubfigures.py` | **reimplemented** on the same Spec/Style contract for survivorship curves + the At-Risk Band (ADR-0004) |
| `pysurvanalysis/script_editor/project_actions.py` | `pytrackinganalysis/script_editor/project_actions.py` | **reimplemented**; no pooling actions, adds the type-registry hard error |
| `pysurvanalysis/domain/batch.py` | `pytrackinganalysis/batch.py` | **reimplemented** on the same contract — structural Batch, lazy `batch.yaml`, `resolve_designated_script` central→own→built-in, no implicit fallback (ADR-0007); now also the recursive walk, `project_kind`, relative-path keys, scoped `run()` (ADR-0009 ← upstream ADR-0011) |
| `pysurvanalysis/domain/layout.py` | `pytrackinganalysis/layout.py` | **structure ported, body rewritten** — same `classify`/`members_in` contract and the same "decide with the loader's own rule" principle, but this loader accepts data at the root *or* `data/`, so there is no Unfiled Recording and none of the filing machinery. Its blocked set is no-config / no-data / ambiguous |
| `pysurvanalysis/apps/batch_preflight.py` | `pytrackinganalysis/apps/batch_preflight.py` | **structure ported** — same always-shown review modal, tree of Projects → blocked children, reason-matched repair, Rescan, derive-don't-remember check state. Repairs differ (scaffold a config, name a `data_file:`); no Removal Sheet section |

### The 2026-08-24 pass (`@5499e8a`..`@07199a6`)

Ported: recursive Batch discovery with pruning and relative-path keys, the
Blocked-Experiment concept, the always-shown preflight, the scoped run and its
coverage-aware summary, `StatusTile`'s full dim treatment (background, title
*and* icon), `TilePanel._content_height`, `Card.set_dimmed`/`restyle`,
`OutputLog.append_stream`, the `PlotDock` clear bar, the suppress-tabs switch,
neutral buttons within a panel, "View reports", project-wide YAML validation,
and the panel-flow changes (double-click a member → Analyze; double-click a
Batch row → Project).

## Not mirrored — deliberate divergences

* **No pooling anywhere.** `Project` has no combined analysis, no pooled
  statistics, no mixed model (ADR-0001).
* **Standalone experiments load without a Project** (ADR-0003), inverting the
  sister app's ADR-0008.
* **Experiment Types contribute Hub buttons and script actions** (ADR-0002).
  This idea originates here; upstream has a fixed registry because it has one
  Experiment Type. It is the first thing to backport.
* **Plot Editor is experiment-level, Styles resolve upward** (ADR-0005).
* **No Unfiled Recording, and no filing.** Upstream's loader reads `data/`
  alone, so a recording loose at the experiment root is a repairable blocked
  state and its preflight moves the file. `SurvivalExperiment.data_file`
  searches `data/` *and then* the root, so that state cannot arise here
  (ADR-0009). Roughly half of upstream's `layout.py` — `plan_filing`,
  `file_recording`, `extra_files/`, the YAML-exemption rule protecting
  sidecars from being swept into `data/` — has no counterpart.
* **No Removed Regions and no Removal Sheet** (upstream ADR-0010). The unit
  there is a tracking region and the sidecar is new machinery; here the
  **Exclusion Group** (`qc/remove_chambers.csv`, active group named in
  `survival_config.yaml`) already removes chambers from the analysis
  population and is already stamped on every output. What *was* taken across
  is ADR-0010's **stale rule**: a member whose active Exclusion Group differs
  from the one stamped on its saved run reads "re-run needed" rather than
  showing a date, because those results describe a population nobody asked
  for. The bulk-authoring half (a spreadsheet at the Batch root writing down
  into each member) is the part still worth having, and is not built.
* **No Batch AI narrative.** Upstream synthesises the Projects'
  `ai_narrative.md` files into one at the Batch root. It is a synthesis, not a
  pooling, so ADR-0001 does not forbid it — but this app's AI Narrative is a
  Project-level artifact with no fixed-name companion to glob for, so the
  prerequisite is missing. Worth building on top of one.
* **Upstream's `script_editor/palette.py` height fix does not apply.** That
  fix un-clips a wrapped description inside a custom tile widget; this palette
  is a plain `QListWidget` of one-line items with the description in the
  tooltip, so there is no clipping to fix.

## Keeping this honest

When you copy something new across, add a row. When you edit a file marked
*verbatim*, change its relationship to describe the edit — a row that claims
"verbatim" while the file has diverged is worse than no row at all.
