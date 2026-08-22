# Shared UI and scripting code is duplicated, with a drift manifest

The generic layers this overhaul needs — `ui/` (theme, widgets, zoom, icons),
`script_editor/`, the report block model, the tile strip, `pubfigures.py` —
all exist in PyTrackingAnalysis. We copy them rather than extract a shared
package. Extraction is the theoretically right answer and was rejected for two
concrete reasons: the apps' dependency floors already conflict
(pySurvAnalysis pins `pandas>=3.0.2`, PyTrackingAnalysis `>=2.2.3`), and their
domains have diverged in ways that reach into this code — no pooling,
standalone-first, and type-contributed Hub buttons, none of which exist
upstream. The cost is drift, which is already happening: the `ui/` and
`script_editor/` copies in the two repos differ by 40–60% in size today.

To make that cost visible rather than silent, `MIRRORED.md` lists every
duplicated file with its upstream path and the commit it was copied at, so
drift is reviewable and a future extraction is mechanical.
