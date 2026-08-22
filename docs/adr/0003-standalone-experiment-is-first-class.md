# A standalone Experiment Directory opens without a Project

PyTrackingAnalysis's ADR-0008 requires a Project to load anything: the
replicates table is the single way to load an experiment, which is what killed
the competing Load button that used to disagree with it. That justification is
specific to pooling — a lone recording there has no Combined Analysis and
little reason to exist alone. Here the app's entire history is one folder with
one workbook, `pysurvanalysis run <file>` is a first-class path, and with no
pooling a Project buys a standalone experiment nothing. So selecting a
directory holding a `survival_config.yaml` loads it, and the Project tile dims
to "standalone experiment"; selecting a Project shows the members table and
loading happens by double-click. There is still exactly one way to load per
selection kind, so ADR-0008's actual disease — two entry points disagreeing
about the current subject — does not recur. Tools offers "wrap in a Project"
for when a standalone grows siblings.
