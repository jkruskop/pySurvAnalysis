# A Project binds independent analyses; it never pools them

pySurvAnalysis takes its Batch → Project → Experiment structure from
PyTrackingAnalysis, but rejects that app's central premise: there, a Project is
a set of replicates of one design and its whole point is the Combined Analysis
(stacked summaries, pooled tests, a linear mixed model over an experiment
random effect). Here a Project's **Member Experiments** address one question in
slightly different ways, so pooling them would be scientifically meaningless.
We therefore keep the structure and delete the combining: no combined summary
CSVs, no pooled statistics, no mixed model, no pooled figures. The **Project
Report** is one bound PDF whose body is an independent section per member,
built from that member's own saved analysis outputs, preceded by a member
inventory and an explicit divergence note — because divergence between members
is now legal, and therefore the thing a reader most needs told.

## Consequences

- `project.yaml`'s design authority is demoted to **Project Defaults**: a seed
  and template for member configs, with exactly one hard cross-member
  validation — all members share an **Experiment Type**, because the type
  selects the analyses, the Plot Set and the report sections. Differing
  factors, levels, treatments and chamber counts are legal and merely reported.
- A member that has not been analyzed yields a "not analyzed" section; the
  report never silently analyzes on the user's behalf.
- The only cross-member synthesis anywhere in the app is prose: the AI
  narrative's closing paragraph, explicitly captioned as qualitative and
  non-statistical.
