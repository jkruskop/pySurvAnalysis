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
