# Publication figures are plotnine, with the at-risk counts inside the ggplot

Publication Figures are rendered by plotnine, matching PyTrackingAnalysis, so
the Plot Spec / Plot Style model, the Plot Editor, the themes and the SVG/PDF
export behave identically across the two apps. This was a real trade-off:
survivorship figures are step functions with censor ticks and a number-at-risk
table, and `plotting.py` already solves all three in matplotlib
(`plot_km_with_risk_table`). Symmetry with the sister app won.

The at-risk table is the part the grammar does not have. Rather than compose
two ggplots (patchworklib, or figure surgery that breaks on plotnine upgrades),
the counts are drawn as a `geom_text` layer in a reserved band below the
curves, made by expanding the y-limits and suppressing that region's
gridlines — the **At-Risk Band**. A Publication Figure therefore stays one
grammar object, so faceting, theming and vector export need no composition
step. Plot Style carries `risk_table` and `risk_table_times`. The matplotlib
two-axes construction remains what the Hub preview and QC Viewer draw.
