# Every project.yaml ships a Project Script named `batch`

Ported from PyTrackingAnalysis's ADR-0009 amendment (2026-08-22), which this
app's Batch level was modelled on.

The default Batch Run was invisible. Creating a Project wrote a `scripts:`
block naming it "Report pipeline" after the built-in it was copied from, and a
Batch with no `batch.yaml` fell back to that built-in in code — so a user
reading their `project.yaml` could not tell what a Batch Run would do here,
and the name did not say that this was the script it would run.

`Project.create` now seeds `scripts:` with a script named **`batch`**, carrying
a `notes:` line saying where it came from. It is named for what it *is* — the
script a Batch Run executes in this Project — because naming it after the
built-in hid that. It is written into the file, so it is visible in the Script
Editor, editable, and renameable. A `project.yaml` with no `scripts:` key is
seeded on the next write; an authored block is left untouched, because an
empty list is a deliberate deletion and re-seeding it would undo the edit.

**No designation means "each Project's own script", and there is no implicit
fallback.** `resolve_designated_script(None, …)` takes the Project's script
named `batch`, else its first authored script. A Project whose `scripts:` is
empty **does not run**: it fails that Project with a message naming the Script
Editor, and the Batch Run continues. The built-ins stay resolvable *by name* —
an explicit designation is a user choice, never a silent substitution — and
stay in both Hub pickers. The Batch panel's picker leads with "Each project's
own 'batch' script (default)", which stores no designation, so `batch.yaml`
still appears only once someone deliberately designates one script for all.

Resolution order for a named designation is the Batch's central
`project_scripts:` first, then the Project's own `scripts:`, then the built-ins
— central first, so one recipe in `batch.yaml` really does serve every Project.

`render_publication_figures` skips a member with no saved `plots:` rather than
rendering the Experiment Type's default Specs. The action runs unattended
inside a Batch Run, and nobody asked for default-spec figures; Specs are
authored down, in the member's own `plot_specs.yaml` (ADR-0005). The built-in
Report pipeline drops the step up front when no member has curated Specs, so
the run says so before it starts.

The sister app's companion change — folding `run_all_analyses` and
`build_combined_analysis` into `project_report` so a project action mirrors a
Project-card button — has no counterpart here: neither action exists, because
Projects never pool (ADR-0001). The rule it states does hold: this app's
`project_report` action and the Project card's Project report button already
run the same thing.
