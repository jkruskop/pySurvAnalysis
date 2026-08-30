# pySurvAnalysis

Survival/demography analysis pipeline and desktop UI for lifespan experiments
(DLife Excel workbooks and CSV/TSV cohorts). This glossary fixes the domain
language; it is not a spec.

Structurally modelled on PyTrackingAnalysis (Batch → Project → Experiment,
tile-strip Hub, two-level scripting, Experiment Types, publication figures),
with one deliberate divergence: **Projects here never pool.**

## Language

**Batch**:
A directory with at least one Project anywhere beneath it. Discovery is
**recursive and prunes at each Project** (ADR-0009): the walk descends until
it finds a Project — `project.yaml` plus at least one Member Experiment — and
never looks inside one, because a Project's subdirectories are its members by
definition. Projects therefore need not be immediate children, and grouping
folders (`Sept2026/`, `Archive/2025/`) are transparent. Purely a processing
convenience for running many Projects unattended; it holds no analysis of its
own and never combines results. A Batch may contain Batches — whichever is
selected is the one that runs, and a nested `batch.yaml` is named in the log
and ignored.
_Avoid_: study, collection, batch root

**Batch Project**:
One Project a Batch Run can target, identified by its **key** — its POSIX path
relative to the Batch root (`Sept2026/ProjA`; a top-level Project is just
`ProjA`, so every `batch.yaml` written before discovery went recursive still
resolves). Deliberately *not* called a member: at this level "member" would
collide with **Member Experiment** one level down, and "a member with four
members" is a sentence this codebase must not be able to write. It is the word
the sister app uses for the same thing; the collision is why we diverge.
_Avoid_: member, batch member, replicate

**Blocked Member**:
A Member Experiment a run cannot use as it stands: a directory holding data
with no `survival_config.yaml`, a config with no data file, or an **ambiguous**
one holding several candidate files where the loader refuses to guess. Each
reason names its own fix — scaffold the config, supply the data, or name one
with `data_file:`. Blocked is a property of the Member Experiment, never of
the Project: a Project with four healthy members and one blocked member runs
the four. Blocked members are named before a Batch Run starts and again in its
summary — being reported is the whole point, and a run is never refused
because of one (a stale folder must not stop ten Projects at 2am). There is no
"unfiled" state here: the loader searches `data/` **and** the directory root,
so a file at either is already found (ADR-0009 diverging from the sister app,
whose loader reads `data/` alone and which therefore also *files* recordings).
_Avoid_: invalid member, broken member (nothing is broken — the run just
cannot use it yet), unfiled

**Batch Preflight**:
The modal a Batch Run always opens first: the discovered Projects with their
keys, usable-member counts and blocked members, each blocked member offering
the action that clears it, then Run or Cancel. Shown even when nothing is
wrong, because with recursive discovery the folder you picked no longer says
what will run, and that target list is the one thing no other surface states.
Unchecking a Project means "do not touch this one"; a Project repaired inside
the preflight joins the run, since the repair is what made it runnable.
_Avoid_: batch dialog, confirmation

**Project**:
A directory with a `project.yaml` at its root whose immediate subdirectories
holding a `survival_config.yaml` are its **Member Experiments** — a set of
independently analyzed experiments addressing one question in slightly
different ways. A Project never pools its members. A Project is never also a
Batch: its subdirectories are its members, so a `project.yaml` nested inside
one does not make a second Project (ADR-0009).
_Avoid_: batch parent, parent directory

**Project Defaults**:
The `defaults:` section of `project.yaml` — a seed and template inherited by
Member Experiments unless a member overrides it (design factors, quality
criteria, plotting conventions). It is *not* an authority: the only value
hard-validated across members is the **Experiment Type**. Divergence in
factors, levels, treatments or chamber counts is legal and merely reported.
_Avoid_: design (the PyTrackingAnalysis term, which IS an authority and
implies pooling)

**Member Experiment**:
An Experiment that belongs to a Project — analyzed entirely on its own,
related to its siblings by the *question* they address rather than by an
identical design. The Hub's Experiments card offers five ways to get one,
answering two different questions (ADR-0010). **What state is the folder in?**
— it does not exist (**Create experiment…**), its directory is in the Project
but has no config (**Initialize existing directory…**), or it is a member
already (the table, and **Experiment configs…** for the bulk view). **Where
does it come from?** — ADR-0008's two ways in from outside, and the Hub keeps
them strictly outside: an existing directory copied in (**Add directory**
refuses a folder already in the Project, naming Initialize instead), or one
built around a single DLife workbook (moved in if it was already loose in the
Project tree, copied otherwise).
_Avoid_: replicate (implies same-design repeats and pooling — the very thing
this app does not do), arm, variant

**Experiment Directory**:
One cohort's directory — `survival_config.yaml` at its root, the input
workbook/CSV at the root or in `data/`, all outputs in `analysis/`, QC state
in `qc/` — either standalone or as a Member Experiment inside a Project.
_Avoid_: project directory (the pre-overhaul name), results folder,
`<stem>_results/` (the superseded output convention)

**Experiment Type**:
A named bundle that constrains an Experiment — the expected input shape, the
time unit and axis label, the censoring policy, the default quality criteria,
the set of analyses that run, the **Plot Set**, and the report sections. It is
the top-level thing a scientist chooses; everything else is derived or
constrained from it. All Member Experiments of a Project share one.
_Avoid_: assay, protocol, template

**Standard Lifespan**:
The baseline Experiment Type: a DLife census workbook of chambers/vials scored
to death, assumed censoring on, the full plot and statistics battery.

**Interaction Experiment**:
An Experiment Type for a 2×2 factorial — exactly two user-named factors with
exactly two ordered levels each (e.g. Genotype × Treatment). Its standard
analysis is the factorial battery (Cox main-effects vs interaction model with
the LR omnibus and Schoenfeld PH test, plus the RMST pseudo-value companion),
and it carries its own Plot Set. A factor with ≠2 levels, or a level present
in the data but not declared, is a load error.
_Avoid_: factorial design (the design is 2×2; the *type* is the bundle),
2x2 experiment

**Reference Level**:
The first level listed for a factor in an Interaction Experiment's `factors:`
block. It is the Cox dummy-coding baseline, the first cell in every plot, and
the baseline in the report's prose, so the sign of every coefficient — the
interaction term included — is stable and explainable regardless of how the
levels are named.
_Avoid_: control, baseline level, first group

**Custom Experiment**:
The absence of a chosen Experiment Type — today's freeform mode, where all
discovered factors get the full battery. A config with no `experiment_type`
key IS a Custom Experiment.
_Avoid_: generic, freeform, none, untyped

**Plot Set**:
The ordered list of figures an Experiment Type produces as its standard
output — what the report embeds and what the Plot Editor offers. Standard
Lifespan's is the general survivorship battery; an Interaction Experiment's is
the faceted KM (its **Headline Figure**), the four-cell KM with at-risk
counts, the lifespan interaction plot, the Cox forest including the
interaction term, and the log-log PH diagnostic.
_Avoid_: plot list, figure set

**Headline Figure**:
The one figure of a Plot Set that states the experiment's primary result —
the faceted KM for an Interaction Experiment. It leads the report and is the
default plot the Plot Editor opens.
_Avoid_: main plot, key figure

**Publication Figure**:
A hand-curated, journal-ready vector figure (SVG with editable text, or PDF)
rendered by plotnine from a Plot Spec + Plot Style — distinct from the
matplotlib figures the Hub previews and the QC Viewer draws. It is **authored
in the Plot Editor and rendered from the Project panel**, and nowhere else:
a Spec belongs to one experiment (ADR-0005), while rendering walks every
member, so the two actions have different subjects and do not share a card.
The Plots tile holds only the Type Actions the loaded Experiment Type
contributes.
_Avoid_: report figure, plot export

**Plot Style**:
One figure's look, **owned by that figure**: saving a figure writes its spec
and its style together, under the figure's own name, so editing the mortality
plot's line width never restyles the KM curves. A shared look is applied
deliberately, with the Figure card's *Copy style from…* (another figure, or
any named style in the file). Edited in the Plot Editor's four style cards: **canvas and type** (size,
theme, font family, base size, a per-element point size for title / axis
titles / ticks / legend / strips, and one text colour for all of them),
**curves and points** (curve width, the separate weight of the axis
furniture, markers on the curve with their shape, size, opacity, fill and
outline, censor ticks, the confidence band), **panels and legend** (panel
fill and border, gridlines, facet-strip style and fill, legend position, the
At-Risk Band's size and times), and **colours** (a per-curve assignment, over
a fallback cycle). Every per-element size defaults to 0 = *follow the base*,
so a style that sets only `base_size` still scales as one thing. Axis
**limits** are Spec fields, not Style: pinning a range is a per-figure
editorial decision, optional per axis behind a checkbox.
_Avoid_: theme (a plotnine theme is one field inside a style), shared default
style (the superseded model — `default_style` survives only as the seed for a
figure's first edit)

**Plot Spec**:
One Publication Figure's content decisions — axis labels, treatment and facet
inclusion/order/display names, axis limits, reference line — plus the name of
the Plot Style it uses. Specs and Styles live together in **one
`plot_specs.yaml` at the container** (the Project, or a standalone Experiment
Directory) — ADR-0005 as amended: the curation is the project default, and
every member renders with it. The whole Plot Set is curatable, not just the
KM curves; each plot's kind gates which Style features apply to it. Only
figures **saved into** `plot_specs.yaml` are rendered — "Save Project
default" writes one spec (and the Style it names) at a time, so a render
produces the curated figures and nothing else. A curated figure also
**outranks the analysis's own figure in the reports** (as in the sister app):
the member report and the Project Report show a curated plot through its
Spec + Style, at 200 dpi, and fall back to the default matplotlib figure only
for plots nothing was curated for — a curated `km_curves` stands in for both
default KM figures, since the at-risk band is a Style toggle there.
_Avoid_: plot config, settings, per-member spec (the superseded layout)

**At-Risk Band**:
The number-at-risk counts drawn as a `geom_text` layer in a reserved band
below the curves *inside the same ggplot*, rather than as a separate axes.
Keeps a Publication Figure one grammar object, so faceting, theming and
vector export need no figure composition.
_Avoid_: risk table (the matplotlib two-axes construction in `plotting.py`,
which remains what the Hub preview and QC Viewer use)

**Analysis Hub**:
The main app: a two-tier tile strip. The ribbon is exactly **Batch ·
Project · Experiment** (one width, 220% of the old tile size), each showing
only live status, with the status readout filling the rest of the strip and
a full-width output/plots area below. There is no Tools tile: every tool it
held duplicated a control that lives where the work is (Validate YAMLs on
the Project card — which also validates a loaded standalone — Clear output
on the output area, Create/Initialize on the Create/Load card). The **Experiment tile** fronts the five
experiment-level surfaces — **QC · Analyze · Plots · Scripts · AI**, QC first
because you decide what to exclude before you analyse it — as sub-tiles in
its panel: all five wait on the same loaded experiment, and five dimmed
ribbon chips said that five times over. A sub-tile opens the panel it
always had, anchored under the Experiment tile; the Experiment tile itself is
the one tile that is disabled (not merely dimmed) with nothing loaded, since
its panel holds no fixer control, only the four gates. All controls live in a tile's anchored panel, one open at a time.
The Analyze tile's cards are contributed by the loaded experiment's
**Experiment Type**. The selection names the working container — a Batch, a
Project, or a standalone Experiment Directory; a Member Experiment is loaded
by double-clicking its row in the Project panel's members table. The Project
panel is three cards deep: **Create/Load** (the ways into a Project, plus
Validate YAMLs), **Experiments** (the members table and the ways to make one),
and **Actions** (report, view, plot editor) over the Project **Scripts** card.
_Avoid_: sidebar card column (the pre-overhaul layout), Load tile (absorbed:
input format, time/event columns and censoring policy now live in
`survival_config.yaml`)

**Type Action**:
A Hub button, and the script action mirroring it, contributed by an
Experiment Type rather than by the core — `cox_interaction` and
`interaction_plot` for an Interaction Experiment, say. The action registry at
each level is *core ∪ type*. A script step naming an action outside that
union is a hard error: the script refuses to start, and in a Batch Run that
Project is logged, counted as a failure, and the Batch continues.
_Avoid_: plugin, extension, custom action

**Experiment Script**:
A saved, re-runnable step list of experiment-level actions. Lives in an
Experiment Directory's `survival_config.yaml` `scripts:` — or, for Member
Experiments, centrally in the Project's `experiment_scripts:` section, where
one recipe serves every member without being copied. Because all members
share one Experiment Type, the palette resolves cleanly from the Project.
_Avoid_: recipe, macro, pipeline

**Project Script**:
A saved step list of project-level actions in `project.yaml` `scripts:` —
same shape and visual editor as an Experiment Script, separate registry.
The only bridge down is `run_in_experiments`, which runs a named Experiment
Script in every Member Experiment (or just those named in its `only:` list),
continue-on-error.

**`batch` script**:
The Project Script every `project.yaml` is created with (ADR-0007), named for
what it is: the one a Batch Run executes in this Project unless another is
designated. Written into the file rather than kept in code, so it is visible,
editable and renameable. A Project whose `scripts:` is empty does not run.
_Avoid_: default script (says nothing about when it runs)

**`Standard analysis` script**:
The Experiment Script every `survival_config.yaml` is created with (ADR-0007
amendment) — the one a Project's `batch` script names in
`run_in_experiments`, so a Batch Run works on a fresh Project with nothing
authored. Seeded on the file's first write when it has no `scripts:` key at
all, and left alone once the block exists (an empty list is a deletion).
Resolution by name is the Project's central `experiment_scripts:`, then the
member's own file, then the in-code built-in — the last only so a config
written before the default was seeded still runs.
_Avoid_: default script, built-in (it lives in the file, not in code)

**Batch Run**:
One execution of a designated Project Script in every **checked** Project of a
Batch, continue-on-error with per-Project log prefixes. The checked set is
confirmed in the **Batch Preflight** and nothing outside it is touched.
`batch.yaml` holds the designation and a central `project_scripts:` section.
**No designation means each Project runs its own `batch` script** — resolution
for a named one is central `project_scripts:`, then the Project's own
`scripts:`, then the built-ins; a name that resolves nowhere fails that
Project, and the run continues. The summary carries a usable/total member
ratio per Project, so "succeeded" cannot be read as "analysed everything".

**Project Report**:
`<project>/<project>_report.pdf`: a cover carrying the project's question, a
**Member Inventory** table (each member's N, deaths, % censored, factors and
levels, treatments, analysis date), a **Divergence Note** stating where members
differ, then one independent section per Member Experiment built from that
member's *saved* analysis outputs. A member that has not been analyzed yields a
"not analyzed" section rather than being silently analyzed.
_Avoid_: combined report, pooled report

**Divergence Note**:
The Project Report's statement of where Member Experiments differ in factors,
levels, treatments or chamber counts. Divergence is legal here, which is
exactly why it must be declared to the reader.

**AI Narrative**:
An optional, AI-written summary attached to a report: one paragraph per Member
Experiment from that member's own numbers, plus a closing qualitative
"across members" paragraph on agreement and disagreement, captioned as
non-statistical. The AI *summarizes* the pipeline's analysis; it never performs
its own, and no numbers are ever combined. A derivative of a run — re-running
the analysis deletes it.
_Avoid_: AI analysis, AI interpretation, meta-analysis

**Exclusion Group**:
A named set of chambers removed from analysis, stored in `qc/remove_chambers.csv`.
The **active** group is configuration (`exclusions: {group: ...}` in
`survival_config.yaml`), not UI state, and its name is stamped on every report
and Run Summary — so the same input and config always give the same result.
The stamp reports what the group *actually removed*: a cohort with no chamber
identities (a CSV) records the group in force and zero removals rather than
claiming exclusions that could not have happened.
_Avoid_: filter, exclusion set, removed vials

**Chamber**:
One vial/container of individuals, the unit of the DLife census and the unit
an Exclusion Group removes. Individuals within a chamber share a treatment.
_Avoid_: vial, cage, replicate

**Assumed Censoring**:
The DLife convention that individuals unaccounted for at the end of a census
are treated as right-censored rather than dead. A per-experiment policy, set by
the Experiment Type's default and overridable in `survival_config.yaml`.

**Initialize**:
Give a directory that already exists the marker file that makes it a Project
or a Member Experiment, keeping its own name and contents — `project.yaml` at
the Project level, `survival_config.yaml` one level down. The third of the
three states a folder can be in (ADR-0010): **Open** wants the marker already
there, **Create** makes the directory too, and Initialize is the one for a
directory you already have. Distinct from **Upgrade**, which rewrites an old
*layout* into the current one; initializing writes a marker and moves nothing.
_Avoid_: adopt (reserved for ADR-0008's two ways a member arrives from
outside the Project, which copy or move data), convert, import

**Upgrade**:
The pre-overhaul → current layout rewrite (`domain/upgrade.py`): move a root
`remove_chambers.csv` into `qc/`, sniff a config for an adopted workbook. No
longer a Hub button — the Create/Load card's Initialize covers promoting old
directories, and `sniff_config` keeps serving adoption — so `plan`/`apply`
survive as library code only.
_Avoid_: migration (overloaded), conversion

**Run Summary**:
`analysis/run_summary.json` — the small record of one analysis run (counts,
factors, the Exclusion Group and how many chambers it actually removed, the
figures written, the omnibus test, and each factorial model's headline
numbers). The Hub's members table and the Project Report read it instead of
re-analysing, which is what makes a bound Project Report cheap and what makes
"not analysed" a visible state rather than an inferred one.
_Avoid_: cache, manifest

**Minimal Member Config**:
What **Create experiment…** writes: the least a Member Experiment must state
itself,
with everything the Project's `defaults:` supplies left out. A member that
restates a default freezes it — later edits to the Project stop reaching that
member — so scaffolds stay minimal on purpose.
_Avoid_: template config, full config

## Relationships

- A **Batch** contains many **Projects**, at any depth; a **Project** contains
  many **Member Experiments**; each Member Experiment is an **Experiment
  Directory**. As a Batch Run target a Project is a **Batch Project**, named by
  its key.
- An Experiment Directory may also stand alone, with no Project above it.
- A **Blocked Member** belongs to the Member Experiment level, so a Project is
  never blocked — it just has fewer members the run can use.
- Every Member Experiment of a Project shares that Project's **Experiment
  Type** — the only value validated across members.
- An **Experiment Type** owns a **Plot Set** (one of whose figures is the
  **Headline Figure**), an analysis battery, report sections, and its
  **Type Actions**.
- A **Plot Spec** lives with an Experiment Directory and names a **Plot Style**
  that lives with the Project.
- A **Project Report** binds one section per Member Experiment; it never
  combines their numbers.

## Example dialogue

> **Dev:** "Two members of this Project have different genotypes in them. Do I
> validate that, or pool them by treatment?"
> **Domain expert:** "Neither — they're **Member Experiments**, not replicates.
> They ask the same question two ways. Analyse each one alone and say in the
> **Divergence Note** that they differ."
> **Dev:** "So what does the Project actually enforce?"
> **Domain expert:** "Just the **Experiment Type**. If one's an **Interaction
> Experiment** and the other's a **Standard Lifespan**, there's no coherent
> Plot Set or Analyze panel to offer, so that's an error. Everything else in
> `defaults:` is a starting point, not a rule."
> **Dev:** "One folder in there has the workbook but nobody wrote it a config.
> Does that fail the Project?"
> **Domain expert:** "No — that's a **Blocked Member**. The Project runs the
> members it can and the run tells me which one it skipped, before it starts
> and again at the end. If it refused the whole Project I'd lose a night's
> analysis over one folder somebody forgot."

## Flagged ambiguities

- "replicate" was used for a Project's children while also stating those
  children differ in design and are never pooled — resolved: they are
  **Member Experiments**; "replicate" is reserved for nothing in this repo.
- Output paths were a function of the data filename (`<stem>_results/`) —
  resolved: fixed `analysis/`, so no path helper has to discover the data
  file first and renaming a workbook cannot orphan results.
- A 2×2's reference levels were implicit (alphabetical / `drop_first`) —
  resolved: **Reference Level** is the first declared level, making every
  coefficient's sign stable.
- "Load" named both an input-format dialog and the act of making an
  experiment current — resolved: format is configuration
  (`survival_config.yaml`), loading is a selection/double-click.
- "Member" was about to name both a Batch's Projects (following the sister
  app) and a Project's experiments — resolved: a Batch's children are **Batch
  Projects**; "member" belongs to the Project→Experiment level alone.
