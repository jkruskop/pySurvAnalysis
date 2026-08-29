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

**Upstream baseline:** `PyTrackingAnalysis@8e41914` (2026-08-27), raised from
`@07199a6` by the Project/Experiment creation pass below, itself raised from
`@5499e8a` by the recursive-discovery and UI pass. The `batch`-script rules
(ADR-0007) were re-checked against `@4008526`.

| File here | Upstream path | Relationship |
|---|---|---|
| `pysurvanalysis/report_pkg/model.py` | `pytrackinganalysis/report/model.py` | **verbatim** (module path renamed) |
| `pysurvanalysis/report_pkg/render.py` | `pytrackinganalysis/report/render.py` | verbatim + a `markdown` backend entry |
| `pysurvanalysis/report_pkg/backends/reportlab_backend.py` | same | was verbatim (module path renamed); now + `_start_page`, which collapses consecutive page breaks. Upstream carries the same hazard — a `SectionDivider` emits its own leading `PageBreak` — but no upstream caller writes one in front of a divider, so it has never produced the blank page it produced here. **Worth backporting** |
| `pysurvanalysis/report_pkg/backends/markdown_backend.py` | — | **new here**; a second backend over the same blocks |
| `pysurvanalysis/apps/_hub_tiles.py` | `pytrackinganalysis/apps/_hub_tiles.py` | was verbatim (`Ptrack*` objectNames → `Psurv*`); now + the full dim treatment (background/title/icon), `TilePanel._content_height`, and `TilePanel.cards()` so the Hub can dim a whole panel |
| `pysurvanalysis/ui/theme.py` | `pytrackinganalysis/ui/theme.py` | vendored earlier; + `surface_colors()`, `Category.AI`, card-label QSS |
| `pysurvanalysis/ui/widgets.py` | `pytrackinganalysis/ui/widgets.py` | vendored earlier; Card paints from `surface_colors()` and now has `set_dimmed`/`restyle`; OutputLog has `append_stream`/`clear_log`; PlotDock has the clear bar. No Errors tab here, so the bar has two buttons rather than three |
| `pysurvanalysis/gui_env.py` | `pytrackinganalysis/gui_env.py` | **verbatim** — same toolkit, same Wayland/IBus complaint at startup |
| `pysurvanalysis/ui/icons.py` | `pytrackinganalysis/ui/icons.py` | vendored earlier; survival-specific glyphs added |
| `pysurvanalysis/ui/zoom.py` | `pytrackinganalysis/ui/zoom.py` | vendored earlier; has since grown locally |
| `pysurvanalysis/script_editor/{canvas,inspector,palette,window}.py` | same | vendored earlier; `window.py` is now level-aware, `palette.py` rebuildable |
| `pysurvanalysis/apps/hub.py` | `pytrackinganalysis/apps/hub.py` | **structure ported, body rewritten** — same tile strip and panel model, survival domain, type-contributed Analyze cards; now also the cached recursive scan, batch table with keys/status/red rows/context menu, card dimming, always-lit Batch and Project tiles, tab suppression, stream logging, and the Create/Load ∥ Experiments card pair with a button per state (ADR-0010) |
| `pysurvanalysis/apps/plot_editor.py` | `pytrackinganalysis/apps/plot_editor.py` | **structure ported** — same Spec/Style editing model, experiment-level (ADR-0005); `ColorButton` (alpha-aware, "none" = transparent) and the wheel-transparent `_NoWheelSpin`/`_NoWheelCombo`/`_NoWheelFontCombo` are **near-verbatim**. The style form is grouped into four Cards rather than one QGroupBox column, and the preview renders at widget resolution × device pixel ratio (upstream's is fixed-DPI) |
| `pysurvanalysis/pubfigures.py` | `pytrackinganalysis/pubfigures.py` | **reimplemented** on the same Spec/Style contract for survivorship curves + the At-Risk Band (ADR-0004). `resolve_font_family` is **verbatim**; the per-element font sizes, `text_color`, `line_pt`, `strip_style`/`strip_bg`/`panel_bg` and the outlined-point treatment (`fill` = series, `color` = edge, `stroke` = weight) follow upstream's `PlotStyle`/`_theme_for` field for field. `step_expand` and `point_data` are local — a step curve has knots where a jittered dot plot has none. Now also `ProjectSpecs`/`load_project_specs`/`save_project_specs` — upstream's single project-root `plot_specs.yaml`, adopted here (ADR-0005 amendment) with `specs_root` falling back to a standalone experiment's own directory, plus a `PlotKind` table dispatching the whole Plot Set (series / forest / distribution / interaction) where upstream has one figure shape. `render_all` follows upstream's curated-only rule, but stricter: an empty `plots:` renders nothing here, where upstream falls back to every plot type |
| `pysurvanalysis/script_editor/project_actions.py` | `pytrackinganalysis/script_editor/project_actions.py` | **reimplemented**; no pooling actions, adds the type-registry hard error |
| `pysurvanalysis/domain/batch.py` | `pytrackinganalysis/batch.py` | **reimplemented** on the same contract — structural Batch, lazy `batch.yaml`, `resolve_designated_script` central→own→built-in, no implicit fallback (ADR-0007); now also the recursive walk, `project_kind`, relative-path keys, scoped `run()` (ADR-0009 ← upstream ADR-0011) |
| `pysurvanalysis/domain/layout.py` | `pytrackinganalysis/layout.py` | **structure ported, body rewritten** — same `classify`/`members_in` contract and the same "decide with the loader's own rule" principle, but this loader accepts data at the root *or* `data/`, so there is no Unfiled Recording and none of the filing machinery. Its blocked set is no-config / no-data / ambiguous; `initializable_dirs` came across for the Initialize picker, with an added `<stem>_figures` suffix rule this app's report backend needs |
| `pysurvanalysis/apps/project_dialogs.py` | `ProjectInfoDialog` + `ExperimentConfigsDialog` in `pytrackinganalysis/apps/hub.py` | **structure ported, body rewritten** — same shared-dialog-for-three-ways-in shape and the same bulk config table. Its group box edits Project Defaults (a seed) rather than a shared design (an authority), so it has no design-conformance half; its bulk dialog offers "Set data file…" where upstream offers a Config Editor, and "Edit config…" hands the YAML to the desktop. Lives in its own module rather than at the bottom of `hub.py` |
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

### The 2026-08-27 pass (`@07199a6`..`@8e41914`)

Upstream's `Project_Experiment_Updates` reorganised both creation surfaces
around **the three states a folder can be in** — it is one already, it does
not exist, its directory exists but its marker file does not — with the
editor for the open one as a fourth button and Validate on its own full-width
row. Ported: that layout at both levels, the shared create/initialize/edit
dialog, the bulk per-experiment configs dialog, the `Config` column and
`missing` rows in the members table, the double-click-to-scaffold offer, the
type check run *before* a copied config is written, and `initializable_dirs`.
The result is [ADR-0010](docs/adr/0010-three-states-not-three-origins.md),
which explains how the new state buttons sit beside ADR-0008's origin
buttons rather than replacing them.

Not ported: the filing half of upstream's Initialize (there is nothing to
file here — see below), and its "shared design (enforced on every replicate)"
framing, which ADR-0001 forbids.

## Not mirrored — deliberate divergences

* **No pooling anywhere.** `Project` has no combined analysis, no pooled
  statistics, no mixed model (ADR-0001).
* **Standalone experiments load without a Project** (ADR-0003), inverting the
  sister app's ADR-0008.
* **Experiment Types contribute Hub buttons and script actions** (ADR-0002).
  This idea originates here; upstream has a fixed registry because it has one
  Experiment Type. It is the first thing to backport.
* **Styles are per-figure, not a named shared library.** Upstream's styles
  are named and reusable, with one `default_style` many plots reference; here
  each saved figure carries a style under its own name, and reuse is the
  explicit *Copy style from…*. Direct experience showed the shared object was
  a trap: editing one plot's look silently restyled every other plot
  referencing the same name. `default_style` survives as the seed for a
  figure's first edit, and old files that reference it still resolve.
* **The style vocabulary differs where the figure does.** Upstream styles a
  jittered dot/box plot: `jitter_width`, `mean_style`, `mean_color`, `geom`,
  `p_value_pt`, `facet_width_mm`/`facet_height_mm`. Here the equivalents are
  curve decisions — `point_at` (which knots carry a marker), `censor_shape`
  and `censor_color`, `ci_alpha`, `grid`, and the At-Risk Band's own size and
  times. `point_size`/`point_alpha`/`point_stroke`/`point_fill` and the
  outlined-point mechanics are shared with upstream exactly.
* **The Plot Editor opens on a member; the curation is the Project's**
  (ADR-0005 as amended, matching upstream's project-root `plot_specs.yaml`).
  A member supplies the preview's data; Specs and Styles save to the
  container. Rendering is project-level — its button lives on the Project
  panel and nowhere else, and the Plots tile carries only the Type Actions
  the loaded Experiment Type contributes.
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
* **No Config Editor for a member, so no "Edit config…" window.** Upstream
  needs a whole window for `tracking_config.yaml` — a rig and its per-region
  treatments are not hand-editable. A `survival_config.yaml` is a dozen lines,
  so the Experiment configs dialog hands it to the desktop's own YAML editor
  and offers **Set data file…** in the slot upstream gives the editor. That
  repair (naming one of several candidates in `data_file:`) has no upstream
  counterpart at all, because upstream's ambiguous state is unrepairable.
* **The Experiments card has five buttons where upstream's has three**
  (ADR-0010). The three state buttons are upstream's; the two below the
  divider are ADR-0008's ways a member arrives from *outside* the Project,
  which upstream has no need for — its replicates are always made in place.
* **Project Defaults are edited as a seed, never as a design.** Upstream's
  `ProjectInfoDialog` edits an authority: facet cutoffs, phase names, counting
  regions and `design.global` keys every replicate is hard-validated against,
  and its copy-config check refuses anything that disagrees. Here the same
  dialog edits `defaults:`, only the Experiment Type is enforced, and
  `Project.type_problems_for` deliberately passes a config whose factors and
  levels diverge (ADR-0001).
* **Upstream's `script_editor/palette.py` height fix does not apply.** That
  fix un-clips a wrapped description inside a custom tile widget; this palette
  is a plain `QListWidget` of one-line items with the description in the
  tooltip, so there is no clipping to fix.

## Keeping this honest

When you copy something new across, add a row. When you edit a file marked
*verbatim*, change its relationship to describe the edit — a row that claims
"verbatim" while the file has diverged is worse than no row at all.
