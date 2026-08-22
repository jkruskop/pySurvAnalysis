# An Experiment Type contributes Hub buttons and script actions

PyTrackingAnalysis has a fixed action registry per level because it has only
one Experiment Type; the question of who owns an action never arose. With two
real types here (Standard Lifespan and Interaction Experiment) it does: an
Interaction Experiment's `cox_interaction` and `interaction_plot` are
meaningless for a plain lifespan cohort. The registry at each level is
therefore **core ∪ type** — core holds what every type has (load, exclusions,
QC, publication figures, report), the type contributes the rest — and a Hub
panel's cards are built from the same union, so a button and its script action
are the same thing declared once.

A script step naming an action outside that union is a **hard error: the script
refuses to start.** The rejected alternative was to flag it in validation and
then skip-and-count at runtime, which would let one shared script survive a
Batch of mixed-type Projects. We chose the hard error because a silently
skipped analysis step produces a report that looks complete and is not.
Continue-on-error still lives one level up: in a Batch Run the refusing
Project is logged, counted as a failure, and the Batch moves on.
