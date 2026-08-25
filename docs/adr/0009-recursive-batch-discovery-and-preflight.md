# Batch discovery is recursive, and a Batch Run is confirmed in a preflight

Ported from PyTrackingAnalysis's ADR-0011 (2026-08-24), which this app's Batch
level was modelled on. Supersedes the structural half of ADR-0007's Batch
definition: Projects need not be immediate children.

## Context

Experimenters do not keep Projects in one flat folder. They keep
`Sept2026/ProjA`, `Archive/2025/ProjC`, a `pilot/` beside a `final/` — and a
Batch was one `iterdir`, so pointing the Hub at the folder that actually holds
the work found nothing. Splitting a tree into flat batch folders to satisfy
the tool is the wrong direction of accommodation.

Two other things pull the same way. A Project whose members were never given a
`survival_config.yaml` is invisible to the batch list, so it fails at load an
hour into an unattended run. And with recursion, the folder someone picked no
longer says what will run — a Batch Run rewrites `analysis/` in every Project
it reaches, and until now nothing stated that list before it started.

## Decision

- **Discovery is recursive and prunes at each Project.** A **Batch** is a
  directory with at least one Project anywhere beneath it. The walk descends
  until it finds a Project — `project.yaml` plus at least one Member
  Experiment — and never looks inside one, because a Project's subdirectories
  are its members by definition. An archived copy carrying its own
  `project.yaml` inside a Project therefore cannot become a second Project,
  and no Experiment Directory can be analysed twice in one run. Grouping
  folders are transparent. The walk does not follow symlinks, skips
  dot-directories, and reports unreadable ones rather than dropping them.

- **A Project is keyed by its path relative to the Batch root.**
  `Sept2026/ProjA`; a top-level Project is still just `ProjA`, so every
  existing `batch.yaml` and `run(project_names=…)` call keeps working
  untouched. Leaf names were rejected: two `ProjA`s under different parents
  collide, and disambiguating only on collision makes a key change when an
  unrelated Project is added elsewhere in the tree — silently invalidating a
  designation that named it.

- **The level word is "Project", never "Member".** Upstream calls a Batch's
  children Members; here **Member Experiment** is a *Project's* child and is
  the load-bearing term of ADR-0001 (a Project binds independent analyses; it
  has no replicates). What a Batch Run targets is a **Batch Project**, and
  `BatchProject.members` are its Member Experiments. Reusing "member" across
  both levels would have made "a member with four members" a sentence this
  codebase could write.

- **A `project.yaml` directory with no Member Experiment is judged by what is
  under it.** Treating the marker alone as a stop would let one stray file
  hide every Project beneath it — exactly the mistake recursion exists to
  tolerate. `project_kind` returns `project` (prune here), `unconfirmed`
  (experiment-shaped children, none runnable: descend first, and only call it
  a Project if nothing real turns up below), `marker` (walk through, and say
  so in the log), or `""`. A stray `survival_config.yaml` gets the same
  treatment: descend first, stop only if nothing turns up.

- **One predicate, for the library and the UI alike.** `is_batch_dir` is
  `bool(discover(...)["projects"])` and not a cheaper lookalike. An earlier
  short-circuit asking `is_project_dir` at the root disagreed with the walk's
  stricter test, so a batch folder carrying a stray or legacy `project.yaml`
  enumerated its Projects perfectly and then showed an empty, dead panel. The
  cost is carried by caching the walk on the `Batch` object, with an explicit
  **Rescan** for changes made outside the app.

- **Blocked is a property of the Member Experiment, never of the Project.** A
  **Blocked Member** is one a run cannot use: a directory holding data with no
  `survival_config.yaml`, a config with no data, or an **ambiguous** directory
  holding several candidate files. A Project with four healthy members and one
  blocked member runs the four. Blocked members are named before the run and
  again in its summary; a run is **never refused** because of one — a stale
  folder must not stop ten Projects at 2am. A Project with *no* usable member
  starts unchecked, since it can only produce a failure.

- **There is no "unfiled recording" here, and nothing to file.** This is the
  deliberate divergence from ADR-0011. Upstream's loader reads `data/` alone,
  so a DTrack export loose at the experiment root is a repairable blocked
  state and the preflight moves it. `SurvivalExperiment.data_file` searches
  `data/` **and then the directory root**, so a workbook at either is already
  found — CONTEXT.md has said so since the overhaul. Porting the filing
  machinery would have added a fix for a state this app cannot enter.

- **Ambiguity is a block with a real fix.** More than one candidate file in
  the base the loader would search is where `data_file()` raises rather than
  guessing, so the classifier must not guess either. Unlike upstream's
  equivalent it has a one-click repair: write `data_file:` into that member's
  config. It is offered one member at a time and never in bulk — which file is
  the experiment is a question only the experimenter can answer.

- **Run batch opens a preflight, always.** One modal listing the discovered
  Projects with their relative-path keys, usable-member counts, and every
  blocked member with its reason and the action that clears it; then Run or
  Cancel. It is shown even when nothing is wrong, because with recursive
  discovery the target list is no longer obvious from the folder you picked,
  and that list is the one thing no other surface states.

- **A Project repaired inside the preflight joins the run.** Check state is
  derived from what the user actually said plus what the Project can do *now*,
  never from the previous check column: scaffolding a config is what *makes* a
  Project runnable, so re-deriving "unchecked" from the pre-repair state would
  exclude the very Project the user had just fixed.

- **Scaffolding goes through the Project's own path.** The preflight calls
  `Project.add_member`, so a repaired member inherits the Project Defaults. A
  config written any other way would restate them, and a member that restates
  a default freezes it (ADR: Minimal Member Config).

- **Unchecking a Project means "do not touch this one".** `Batch.run` takes
  the confirmed key list and visits nothing else. Recursion surfaces Projects
  the user may not have known were there, so scoping is not decoration.

- **Only the selected Batch's `batch.yaml` governs.** A nested grouping folder
  may be a Batch in its own right and carry its own designation; it is ignored
  and named in the run log. Resolution is already three steps (central
  `project_scripts:` → the Project's own `scripts:` → built-ins) and a fourth
  that depended on where the user clicked would be unmemorable.

- **The run summary states coverage, not just success.** Each outcome carries
  a usable/total member ratio, and the summary line names every Project that
  completed while skipping members — so "succeeded" can no longer be read as
  "analysed everything".

## Consequences

- `batch.yaml` files written after this change may contain path-shaped keys;
  older flat ones keep working, and a key is stable as long as the folder is
  not moved within the Batch.
- A Batch can now contain Batches. Whichever one is selected is the one that
  runs; nesting has no other meaning.
- Discovery, blocked status and repair are batch-level concerns but
  experiment-level facts, so the same classifier feeds the Project surfaces:
  **Validate YAMLs** reports blocked members, where a member with no config
  was previously invisible.

## Corrected while implementing

Each of these is a pre-existing bug the recursive walk reached, not drift.

- **`is_project_dir` and `is_experiment_dir` raised on an unreadable
  directory.** `Path.is_file()` propagates `PermissionError` on Python 3.13,
  where `os.path.isfile` returns False. A structural predicate the walk runs
  over every directory it meets must answer "no" for one it cannot read, or a
  single locked folder takes down the whole scan. `is_data_file` had the same
  exposure and now stats last, and tolerantly.
- **`Project.add_member` joined an unchecked name onto the Project
  directory**, so a separator or a `..` in it wrote a config — and a `data/`
  folder — outside the Project. It now requires a single folder name.
- **A symlinked copy of a member was counted twice**, so the same cohort would
  be analysed under two names and bound into the Project Report twice.
  `layout.members_in` de-duplicates by real path.
- **The Hub's members table read a cached member list.** `Project.members()`
  caches, and every Hub surface reads through it, so after a config write the
  table went on showing the state the Project was loaded with. `_refresh_all`
  re-reads from disk first — which is what makes "re-run needed" visible at
  all.
