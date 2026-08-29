# Plot Styles live at the Project, Plot Specs live at the Experiment

With no pooling there is no pooled figure, so PyTrackingAnalysis's single
project-root `plot_specs.yaml` and Project-level-only Plot Editor do not
transfer. Members may carry different factors and treatments, so one Spec —
which names treatment display names, ordering and inclusion — cannot apply to
all of them; but the *look* should absolutely be identical across every figure
in a Project. We therefore split the file by what varies: the Project's
`plot_specs.yaml` owns `styles:` and `default_style:`, each Experiment
Directory's own `plot_specs.yaml` owns `plots:`, and a Spec's style name
resolves upward — member file, then project file, then built-in default.
Figures render to `<experiment>/figures/`, and the Plot Editor is
experiment-level, a deliberate inversion of the sister app.

## Amended 2026-08-28: Specs moved to the Project too

The split lasted until the Plot Editor grew to cover the whole Plot Set and
the Project gained a **project default** for figures. In practice the Spec's
content decisions — axis labels, treatment display names and order, the
reference line — are exactly the things a Project wants *identical across
members*, for the same reason the Styles are: the members address one question
and their figures sit side by side. Holding one Spec per member meant curating
the same figure N times, and a member added later started from defaults.

So this app now matches the sister app after all: **one `plot_specs.yaml` at
the container** (the Project — or the standalone Experiment Directory itself,
which ADR-0003 requires and the sister app never has to handle), holding
`default_style`, `styles:` and `plots:`. The Plot Editor still *opens on* a
member, because a preview needs that member's data, but what it edits and
saves is the Project's curation.

What survives of the original decision:

* **Figures still render per member**, into `<experiment>/figures/` — there is
  still no pooled figure (ADR-0001).
* **A member with different treatments still gets a correct figure**: a Spec
  names treatments for inclusion/order/display, and `series_data` ignores
  names the member's data does not have, so the shared Spec degrades to "every
  treatment, cycle colours" exactly as an unedited one would.
* **Legacy per-member Specs are adopted, not ignored** — lifted into the
  container on first contact, losing to an explicit container Spec for the
  same plot id (`adopt_legacy_member_specs`).
