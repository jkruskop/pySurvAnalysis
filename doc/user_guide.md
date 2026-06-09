# pySurvAnalysis — User Guide

## Table of Contents

1. [Overview](#overview)
2. [Getting Started](#getting-started)
   - [Prerequisites](#prerequisites)
   - [Clone the Repository](#clone-the-repository)
   - [Install uv](#install-uv)
   - [Create the Environment and Install Dependencies](#create-the-environment-and-install-dependencies)
   - [Updating the Environment](#updating-the-environment)
3. [Running the Software](#running-the-software)
   - [Interactive UI](#interactive-ui)
   - [Headless (Command-Line) Mode](#headless-command-line-mode)
4. [Input Data Formats](#input-data-formats)
   - [DLife Excel Workbook (.xlsx)](#dlife-excel-workbook-xlsx)
   - [CSV / TSV — Long Format](#csv--tsv--long-format)
   - [CSV / TSV — Wide Ragged Format](#csv--tsv--wide-ragged-format)
5. [DLife-Specific Features](#dlife-specific-features)
   - [Assumed Censoring](#assumed-censoring)
   - [Excluded Vials (ChamberFlags)](#excluded-vials-chamberflags)
   - [Defined Plots (DefinedPlots)](#defined-plots-definedplots)
6. [Interactive UI Walkthrough](#interactive-ui-walkthrough)
7. [Analyses Performed](#analyses-performed)
8. [Output Directory Contents](#output-directory-contents)
9. [Headless CLI Reference](#headless-cli-reference)

---

## Overview

pySurvAnalysis is a Python survival analysis pipeline that accepts experimental lifespan data and produces a complete analysis including:

- Kaplan-Meier survival curves
- Lifetables (actuarial statistics)
- Median and restricted mean survival time (RMST)
- Log-rank tests (omnibus and pairwise with Bonferroni correction)
- Hazard ratio estimates
- Cox proportional hazards regression with interaction testing
- RMST regression on pseudo-values (OLS)
- Lifespan distributional statistics (mean, median, top-percentile means)

It accepts two classes of input: **DLife Excel workbooks** (census-level data from the DLife data-collection software) and **individual-level CSV/TSV files**.

---

## Getting Started

### Prerequisites

- Python 3.13 or later
- [uv](https://github.com/astral-sh/uv) — fast Python package manager
- Git
- A system-level Qt installation is **not** required; PyQt6 bundles its own Qt libraries.

### Clone the Repository

```bash
git clone https://github.com/PletcherLab/pySurvAnalysis
cd pySurvAnalysis
```

### Install uv

If you do not already have `uv` installed, the recommended one-line installation is:

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Alternatively, install via pip in any existing Python environment:

```bash
pip install uv
```

Verify the installation:

```bash
uv --version
```

### Create the Environment and Install Dependencies

From the repository root, let `uv` create a virtual environment and install all dependencies declared in `pyproject.toml`:

```bash
uv sync
```

This creates a `.venv/` directory in the project root and installs:

| Package | Purpose |
|---------|---------|
| `lifelines` | Kaplan-Meier fitting, log-rank tests, Cox PH, PH assumption tests |
| `matplotlib` | All plots |
| `numpy` | Numerical operations |
| `openpyxl` | Reading DLife `.xlsx` workbooks |
| `pandas` | Data wrangling |
| `pyqt6` | Interactive graphical user interface |
| `scipy` | Statistical distributions |
| `statsmodels` | OLS for RMST pseudo-value regression |

### Updating the Environment

When the project dependencies change (e.g. after a `git pull`), bring the environment up to date with:

```bash
uv sync
```

To upgrade all packages to their latest compatible versions:

```bash
uv sync --upgrade
```

---

## Running the Software

All commands are run from the repository root.  The `uv run` prefix ensures the project's virtual environment is used without needing to activate it manually.

### Interactive UI

Launch the graphical application with no arguments:

```bash
uv run python main.py
```

Open a file immediately on launch:

```bash
uv run python main.py path/to/experiment.xlsx
uv run python main.py path/to/data.csv
```

### Headless (Command-Line) Mode

Run a complete analysis and write all outputs to disk without opening the UI:

```bash
# Excel workbook
uv run python main.py --headless path/to/experiment.xlsx

# CSV, auto-detect columns
uv run python main.py --headless path/to/data.csv

# CSV, specify column names explicitly
uv run python main.py --headless path/to/data.csv \
    --time-col Age \
    --event-col Event \
    --factor-cols IRS1 Foxo

# Custom output directory
uv run python main.py --headless path/to/data.csv --output-dir results/my_run
```

Results are written to `<stem>_results/` next to the input file by default (e.g. `experiment_results/`).

---

## Input Data Formats

### DLife Excel Workbook (.xlsx)

DLife exports a multi-sheet workbook.  pySurvAnalysis reads the following sheets:

#### RawData sheet

One row per **chamber per census time point**.  Required columns:

| Column | Description |
|--------|-------------|
| `AgeH` | Age in hours at the census time |
| `Chamber` | Chamber (vial) identifier |
| `IntDeaths` | Deaths observed since the previous census |
| `Censored` | Individuals removed (censored) at this time point |

#### Design sheet

One row per **chamber**.  Required columns:

| Column | Description |
|--------|-------------|
| `Chamber` | Chamber identifier (must match RawData) |
| `SampleSize` | Number of individuals that started in this chamber |
| `StartTime` | Time at which the cohort was initiated |
| `<Factor1>`, `<Factor2>`, … | Treatment factor columns — all columns after `StartTime` are automatically detected as factors |

Factor columns hold the level of each treatment factor for that chamber.  Any number of factors is supported, though interaction analyses (Cox / RMST) work best with two.

#### PrivateData sheet (optional)

Single-row configuration table.  Currently reads:

| Column | Values | Default |
|--------|--------|---------|
| `AssumeCensored` | `1` (True) or `0` (False) | `1` |

#### ChamberFlags sheet (optional)

One row per chamber that has special handling.  pySurvAnalysis reads:

| Column | Description |
|--------|-------------|
| `Chamber` | Chamber identifier |
| `Excluded` | `1` = exclude this chamber from all analyses |

#### DefinedPlots sheet (optional)

One **column** per custom KM plot to generate.  Layout:

| Row | Content |
|-----|---------|
| Row 1 | Plot name (used as title and in the UI dropdown) |
| Rows 2–5 | Reserved / ignored |
| Row 6+ | Treatment labels, one per row.  Only the text before the first comma is used. An empty cell ends the list for that column. |

Each column produces one additional KM plot containing only the listed treatment groups.

---

### CSV / TSV — Long Format

One row per individual.  Columns:

| Column | Default name | Description |
|--------|-------------|-------------|
| Time | `Age` | Survival time (any consistent unit) |
| Event | `Event` | `1` = died, `0` = right-censored |
| Factor(s) | any name(s) | One column per treatment factor |

Example:

```
Age,Event,Genotype,Diet
994,1,WT,AL
659,1,WT,AL
234,0,IRS1KO,DR
1201,1,IRS1KO,DR
```

Auto-detection: if the file contains columns matching the `--time-col` and `--event-col` names (default `Age` and `Event`), the format is identified as long automatically.  All remaining columns become factor columns unless `--factor-cols` is specified.

In the **UI**, opening a `.csv` or `.tsv` file shows a column-mapping dialog.  The dialog pre-selects common column names (`Age` or `Time` for time; `Event` or `Status` for event) but all assignments can be changed before proceeding.

---

### CSV / TSV — Wide Ragged Format

One **column** per (factor-level combination × event status) group.  Columns contain survival times for all individuals in that group.  Columns may have different lengths (ragged).

Example with two factors (IRS1: on/off, Foxo: on/off):

```
IRS1_on_Foxo_on_death,IRS1_on_Foxo_on_censor,IRS1_off_Foxo_on_death,...
994,1450,800,...
659,,720,...
1201,,,...
```

Column names must encode the factor levels and event status in a way that can be inferred automatically, or an explicit mapping must be provided.

**Auto-inference** (headless): column names are scanned for tokens matching the factor levels and for event/censored keywords (`death`, `died`, `event` for event=1; `censored`, `censor`, `alive` for event=0).

**Explicit mapping** (headless): supply a YAML file via `--col-mapping`:

```yaml
- column: col_name_1
  factor1_level: "on"
  factor2_level: "on"
  event: 1
- column: col_name_2
  factor1_level: "on"
  factor2_level: "on"
  event: 0
# ... one entry per column
```

Wide format requires exactly two factors.

---

## DLife-Specific Features

### Assumed Censoring

DLife records census counts (how many died, how many were removed) but does not always account for every individual in the `SampleSize` explicitly at every time point.  The **Assume Censored** setting controls how the gap is handled:

- **Checked (default):** Any individual in `SampleSize` that is not accounted for by observed deaths or explicit censoring events is added as a right-censored observation at the last census time for that chamber.  This is the correct assumption when flies simply remained alive past the final observation and their fate was unknown at the time of data entry.

- **Unchecked:** The cohort size is inferred entirely from the sum of observed deaths and censored events.  No additional individuals are added.  Use this when you are confident that all fates are explicitly recorded.

In the **UI**, the "Assume Censored" checkbox appears in the toolbar.  Toggling it reruns the full analysis automatically.  In headless mode, pass `--no-assume-censored` to disable the assumption.

The censoring assumption in use is stated clearly at the top of `report.md`.

### Excluded Vials (ChamberFlags)

Any chamber with `Excluded = 1` in the `ChamberFlags` sheet is **completely omitted** from all analyses — lifetable construction, log-rank tests, KM plots, and all derived statistics.  The excluded chamber IDs are listed prominently in `report.md` and (when present) as a banner at the top of the Statistics tab in the UI.

### Defined Plots (DefinedPlots)

Each column in the `DefinedPlots` sheet generates one additional KM plot showing only the listed subset of treatment groups.  These plots are useful for comparing specific subsets without re-running the analysis.

- In the **UI**: a "Defined Plots" tab appears automatically when defined plots are found.  A dropdown at the top of the tab lets you switch between plots.
- In **headless mode** and in `report.md`: a dedicated "Defined Plots" section is added between the standard KM plots and the log-rank section, with one subsection per defined plot.

---

## Interactive UI Walkthrough

The UI is organized into a set of tabs along the top of the main window.

### Opening a File

Use **File → Open** (or `Ctrl+O`) to browse for an experiment file.  The supported types are `.xlsx`, `.csv`, and `.tsv`.

- **Excel files** load immediately.  The `PrivateData` sheet is read to pre-set the Assume Censored checkbox.
- **CSV/TSV files** show the **Column Mapping Dialog** before loading.  Set the time column, event column, and factor columns, then click OK.

After loading, the full analysis runs in a background thread.  A progress indicator is shown in the status bar.

### Treatment Selector

A checkable list in the left panel lets you show or hide individual treatment groups on the Plots tabs.  Deselecting treatments narrows the view without re-running statistics.

### Tabs

| Tab | Contents |
|-----|----------|
| **KM Curves** | Interactive Kaplan-Meier survival curves for selected treatments |
| **Hazard Rate** | Smoothed hazard rate over time |
| **Mortality (qx)** | Interval mortality (probability of dying within each interval) |
| **Number at Risk** | Number of individuals remaining at risk at each time point |
| **Lifetable** | Full actuarial lifetable; sortable by treatment |
| **Statistics** | Sample summary, median/mean survival, log-rank tests, hazard ratios, lifespan statistics |
| **Cox / Interactions** | Factorial interaction analyses — see below |
| **Defined Plots** | Custom KM plots from the DefinedPlots sheet (Excel only; hidden when not applicable) |

### Cox / Interactions Tab

This tab lets you run two types of factorial interaction analysis on the fly.  Select one or more factors from the list and click a button:

**Cox PH** — fits a Cox proportional hazards model with main effects and all pairwise interaction terms.  The results panel shows:

1. **Coefficient table** — each term's log-hazard ratio, hazard ratio, standard error, z-statistic, p-value, and 95% CI.
2. **Omnibus LR Interaction Test** — compares a main-effects-only model against the full interaction model using a likelihood-ratio test.  This answers the question "is there evidence of any interaction?" with a single p-value.
3. **Proportional Hazards Assumption** — Schoenfeld residuals test for each covariate.  Significant results (p < 0.05) suggest the hazard ratio for that covariate is not constant over time, violating the Cox PH assumption.

**RMST** — fits an OLS regression on jackknife pseudo-values of restricted mean survival time.  Coefficients are in hours (difference in mean survival time).  This method does **not** assume proportional hazards and is appropriate when the PH assumption is violated.

Each time you click Cox or RMST, the new analysis is appended to the log and written under `<stem>_results/statistics/`.  Files include the factors in the model, active level filters, coefficients, and (for Cox) PH and LR interaction tests.  If `report.md` already exists, its interaction section is updated in place.  You can run multiple analyses with different factor selections and all results accumulate.

### Exporting Reports

Use **File → Export Report** to save a fresh copy of the full Markdown report (including any Cox/RMST analyses) to a directory of your choice.

---

## Analyses Performed

| Analysis | Method | Notes |
|----------|--------|-------|
| Kaplan-Meier curves | Nelson-Åalen / KM estimator | One curve per treatment group |
| Lifetable | Actuarial (interval-censored approximation) | `lx`, `qx`, `px`, `hx`, `se_km` per time point |
| Median survival | KM-based (time at S(t) = 0.5) | "Not reached" when fewer than half the cohort has died |
| RMST | Area under the KM curve up to a common maximum observed time | All groups restricted to the same τ |
| Omnibus log-rank | Kruskal-Wallis generalization of log-rank | Chi-square, df, p-value |
| Pairwise log-rank | Two-sample Mantel-Cox | Bonferroni-corrected p-values for all pairs |
| Hazard ratio | Log-rank O/E method | Approximate; use Cox for adjusted estimates |
| Lifespan statistics | Per-treatment and per-factor-level pooled | Mean (RMST), median, top-10% mean, top-5% mean |
| Cox PH (interaction) | `lifelines.CoxPHFitter` | Main-effects model + full interaction model; LR omnibus test |
| PH assumption | Schoenfeld residuals | `lifelines.statistics.proportional_hazard_test` |
| RMST regression | OLS on jackknife pseudo-values | Via `statsmodels`; intercept + main effects + interactions |

---

## Output Directory Contents

Results are written to `<input_stem>_results/` next to the input file, or to the directory specified via `--output-dir`.  The directory has the following structure:

```
<stem>_results/
  report.md              — Full analysis report (Markdown)
  plots/
    kaplan_meier.png     — KM survival curves (all treatments)
    hazard_rate.png      — Hazard rate over time
    mortality_qx.png     — Interval mortality (qx)
    number_at_risk.png   — Number at risk
    defined_plot_01.png  — First defined plot (DLife only, if present)
    defined_plot_02.png  — Second defined plot (if present)
    ...
  statistics/
    logrank_pairwise.csv — Pairwise log-rank (from full pipeline)
    interaction_analyses.md — Cox/RMST runs from the Hub (accumulated)
    cox_ph_01_metadata.txt  — Factors, level filters, formula (per run)
    cox_ph_01_coefficients.csv
    cox_ph_01_ph_test.csv   — Schoenfeld residuals (Cox only)
    cox_ph_01_lr_interaction.json
    rmst_02_metadata.txt    — RMST runs use the same naming pattern
    ...
  data_output/
    lifetables.csv       — Full actuarial lifetable
    individual_data.csv  — Expanded individual-level data
```

### report.md

A complete Markdown document containing all analysis results.  Sections:

1. **Header** — input file name, factor names, treatment count, total individuals, censoring assumption (Excel only), excluded chambers notice (if any).
2. **Sample Summary** — per-treatment count of individuals, deaths, and censored observations.
3. **Survival Time Estimates** — median survival and RMST table.
4. **Lifespan by Treatment** — mean (RMST), median, top-10% mean, top-5% mean per treatment.
5. **Lifespan by Factor Level** — same statistics pooled across factor levels (e.g. all `IRS1=on` individuals regardless of Foxo status).
6. **Kaplan-Meier Survival Curves** — embedded image reference.
7. **Hazard Rate Over Time** — embedded image reference.
8. **Interval Mortality (qx)** — embedded image reference.
9. **Number at Risk** — embedded image reference.
10. **Defined Plots** — one subsection per defined plot (DLife only; section omitted when no defined plots exist).
11. **Omnibus Log-Rank Test** — chi-square statistic, degrees of freedom, p-value, and plain-language conclusion.
12. **Pairwise Log-Rank Tests** — table of all pairwise comparisons with raw and Bonferroni-corrected p-values.
13. **Hazard Ratio Estimates** — log-rank O/E hazard ratios with 95% CIs for all pairs.
14. **Lifetable Excerpt** — first 10 rows of the lifetable for each treatment.
15. **Factorial Interaction Analyses** — one subsection per Cox or RMST run from the UI's Cox/Interactions tab (section omitted when no interaction analyses have been run).

The report file is rewritten from scratch each time a Cox or RMST analysis is run from the UI, so it always reflects the current accumulated set of results.

### plots/kaplan_meier.png

Kaplan-Meier survival curves for all treatment groups, with a shaded 95% confidence band and a step-function style.  Groups are color-coded and labeled in the legend.

### plots/hazard_rate.png

Smoothed hazard rate h(t) over time derived from the lifetable, one line per treatment.

### plots/mortality_qx.png

Interval mortality q(x): the conditional probability of dying within each interval given survival to the start of that interval.

### plots/number_at_risk.png

Number of individuals remaining at risk at each observed event time, one line per treatment.

### plots/defined_plot_NN.png

KM survival curves restricted to the subset of treatments listed in column N of the `DefinedPlots` sheet.  The title comes from row 1 of that column.

### data_output/lifetables.csv

The full actuarial lifetable, one row per (treatment, time) combination.  Columns:

| Column | Description |
|--------|-------------|
| `treatment` | Treatment label |
| `time` | Census time (hours) |
| `n_at_risk` | Number of individuals at risk at the start of this interval |
| `n_deaths` | Observed deaths at this time |
| `n_censored` | Individuals censored at this time |
| `lx` | Survival probability at time `t` (Kaplan-Meier estimate) |
| `qx` | Conditional probability of death in the interval |
| `px` | Conditional probability of survival through the interval |
| `hx` | Hazard rate at time `t` |
| `se_km` | Greenwood standard error of the KM estimate |

### data_output/individual_data.csv

The individual-level data used for all analyses, one row per individual.  For DLife Excel inputs this is the result of expanding census counts; for CSV inputs this is the data as provided (possibly after format conversion).  Columns:

| Column | Description |
|--------|-------------|
| `time` | Age at death or censoring |
| `event` | `1` = death, `0` = right-censored |
| `chamber` | Source chamber ID (DLife) or `"N/A"` (CSV) |
| `treatment` | Combined factor label, e.g. `"WT/AL"` |
| `<factor1>` | Level of the first factor for this individual |
| `<factor2>` | Level of the second factor (if present) |
| … | Additional factor columns |

---

## Headless CLI Reference

```
usage: main.py [-h] [--headless] [--output-dir DIR]
               [--no-assume-censored]
               [--time-col COL] [--event-col COL]
               [--factor-cols COL [COL ...]]
               [--format {auto,long,wide}]
               [--col-mapping YAML_FILE]
               [--factor-names FACTOR1 FACTOR2]
               [input_file]

Positional arguments:
  input_file            Input file: .xlsx, .csv, or .tsv

Options:
  --headless            Run without the UI and exit when done
  --output-dir DIR, -o  Output directory (default: <stem>_results/)
  --no-assume-censored  Excel only: treat cohort size as sum of observed
                        deaths + censored (no implicit right-censoring)

CSV-specific options:
  --time-col COL        Column name for survival time (default: Age)
  --event-col COL       Column name for event indicator 0/1 (default: Event)
  --factor-cols COL …   Factor column names; auto-detected if omitted
  --format {auto,long,wide}
                        CSV format hint (default: auto)
  --col-mapping YAML    Path to YAML file for explicit wide-format column
                        mapping
  --factor-names F1 F2  The two factor names for wide-format CSV
```

### Examples

```bash
# DLife Excel workbook, default settings
uv run python main.py --headless experiment.xlsx

# DLife Excel, do not assume unaccounted individuals are censored
uv run python main.py --headless experiment.xlsx --no-assume-censored

# Long-format CSV, auto-detect columns
uv run python main.py --headless lifespan_data.csv

# Long-format CSV, explicit columns
uv run python main.py --headless lifespan_data.csv \
    --time-col Age --event-col Event --factor-cols IRS1 Foxo

# Wide-format CSV with auto-inferred column mapping
uv run python main.py --headless wide_data.csv \
    --format wide --factor-names IRS1 Foxo

# Wide-format CSV with explicit YAML mapping
uv run python main.py --headless wide_data.csv \
    --format wide --factor-names IRS1 Foxo \
    --col-mapping col_mapping.yaml

# Specify a custom output directory
uv run python main.py --headless experiment.xlsx \
    --output-dir /path/to/my_results
```
