# pySurvAnalysis

Survival and demography analysis for lifespan experiments — a headless
pipeline plus a PyQt6 desktop UI, for DLife census workbooks and CSV/TSV
cohorts.

Structurally a sibling of [PyTrackingAnalysis](../PyTrackingAnalysis): the same
Batch → Project → Experiment layout, the same tile-strip Hub, the same
two-level scripting and publication-figure system. One deliberate difference
runs through everything: **a Project here never pools its members.**

## The three levels

```
Batch/                          a folder of Projects (structural; batch.yaml optional)
└── Project/                    project.yaml — defaults, scripts, shared Plot Styles
    ├── rep_a/                  a Member Experiment
    │   ├── survival_config.yaml    the authority for this cohort
    │   ├── data/                   the workbook or CSV
    │   ├── analysis/               every output, incl. run_summary.json
    │   ├── qc/                     remove_chambers.csv
    │   ├── figures/                vector Publication Figures
    │   └── plot_specs.yaml         this member's Plot Specs
    └── rep_b/
```

A Project's members are analysed **independently** — they address one question
in slightly different ways, so combining them would be meaningless. The Project
Report binds one section per member behind a member inventory and an explicit
divergence note. An Experiment Directory also works perfectly well on its own,
with no Project above it.

See [CONTEXT.md](CONTEXT.md) for the glossary and [docs/adr/](docs/adr/) for the
six decisions that shaped this.

## Install

```bash
uv sync
```

## Use

```bash
# The Hub (default)
uv run python main.py [path]

# Analyse one experiment: an Experiment Directory, or a bare data file
uv run python main.py run path/to/rep_a
uv run python main.py run cohort.csv --format long

# Run a Project Script, then the same across a whole Batch
uv run python main.py project path/to/Project --script "Report pipeline"
uv run python main.py batch   path/to/Batch

# Turn a pre-overhaul folder into an Experiment Directory (nothing is deleted)
uv run python main.py upgrade path/to/old_folder --dry-run

# The other two apps
uv run python main.py qc    path/to/rep_a
uv run python main.py plots path/to/rep_a
```

## Experiment Types

An Experiment Type is the top-level thing you choose. It decides the expected
input, the time unit, the censoring policy, which analyses run, which figures
are produced, and which buttons the Hub offers.

| Type | What it is |
|---|---|
| **Standard Lifespan** | A census-scored cohort: the full survivorship battery and demographic-rate figures. |
| **Interaction Experiment** | A 2×2 factorial. Two named factors, two **ordered** levels each — the first is the reference. Runs the Cox main-effects-vs-interaction model with its LR test and PH check, plus the RMST companion; its headline figure is the faceted KM. |
| **Custom Experiment** | No `experiment_type` key at all: every factor, the whole battery, nothing withheld. |

A minimal Interaction config:

```yaml
experiment_type: interaction
factors:
  Genotype:  [wCS, mDilp235bx]   # wCS is the reference
  Density:   ["20x", "40x"]      # 20x is the reference
input:
  format: excel
exclusions:
  group: default
```

## Scripting

Two levels, one visual editor, separate registries.

* **Experiment Scripts** live in `survival_config.yaml` `scripts:` (or centrally
  in the Project's `experiment_scripts:`). Their palette is *core ∪ type*: a
  step naming an action the type does not provide is a hard error, so a script
  refuses to start rather than silently skipping analysis.
* **Project Scripts** live in `project.yaml` `scripts:`. The only bridge
  downward is `run_in_experiments`, which runs a named Experiment Script in
  every member.
* A **Batch Run** executes one designated Project Script in every Project,
  continue-on-error.

## Publication figures

The Plot Editor (`main.py plots <experiment>`) renders survivorship figures
with plotnine from a **Plot Spec** + **Plot Style**, and exports SVG/PDF with
editable text. Styles live at the Project so every member's figures match;
Specs live with the experiment because members' treatments differ. The
number-at-risk counts are drawn inside the plot as an **At-Risk Band**, keeping
each figure a single grammar object.

## Reports

One backend-agnostic block model, two renderers: `<name>_report.pdf` via
reportlab and `report.md` via the markdown backend, so the two can never
disagree. An opt-in AI narrative adds a paragraph per member plus a labelled,
explicitly qualitative across-members paragraph — it summarizes the saved
numbers and never computes its own.

## Tests

```bash
uv run pytest
```

The suite covers the structural layer — discovery, defaults resolution, type
validation, script registries, spec resolution, exclusion stamping, report
block assembly, and UI state. It deliberately does not re-test lifelines' math.
