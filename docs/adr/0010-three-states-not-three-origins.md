# A button per state a folder can be in, at both levels

[ADR-0008](0008-three-ways-a-member-arrives.md) gave the Project card three
buttons, one per *origin*: a folder from a collaborator, a workbook in a
downloads directory, an empty directory to fill. That answered "where did this
member come from". It never answered the question people actually arrive with,
which is "I have this folder — now what?"

The gap showed up as a folder sitting inside a Project with no
`survival_config.yaml`. It is not a member, so nothing in the Hub could see
it: not the members table, not the Project Report, not a Batch Run. **Add
directory** would not take it either — that button demands a `data/`
subdirectory holding a workbook that validates, which is a different and much
narrower thing than "a folder in my Project I have not configured yet". The
only route was a file manager and a hand-written YAML.

So the Hub now has **a button per state**, at both levels, mirroring
PyTrackingAnalysis's Create/Load and Experiments cards:

|                     | it is one already | it does not exist  | its directory exists, its marker does not |
|---------------------|-------------------|--------------------|-------------------------------------------|
| **Project**         | Open project…     | Create project…    | Initialize existing directory…            |
| **Member Experiment** | the members table | Create experiment… | Initialize existing directory…            |

Plus, on each card, the editor for the thing that is open: **Edit config…**
for the Project's `project.yaml`, **Experiment configs…** for the members'.
**Validate YAMLs** sits full width below the Project grid, because it is not a
fifth way in — it is the check you run over the Project that is open.

**Edit config… only ever edits.** It first flipped to *Create config…* on a
directory with no `project.yaml`, and wrote one — which is precisely what
**Initialize existing directory…** does. Two controls with one behaviour made
the card look like it had four ways in when it has three, so the fourth button
is now disabled until a Project is open, and says so by naming the button that
does the creating.

**ADR-0008's three buttons are not replaced; two of them survive as what they
always were.** *Where does it come from* is a real question, just a different
one, and the two buttons that answer it — **Add directory** and **Add
experiment** — reach outside the Project where the three above never do. They
sit under their own divider on the Experiments card for exactly that reason.
The third, `Add member`/`Create directory`, *was* the state question all
along; it is now called **Create experiment…** and refuses a name whose folder
already exists rather than quietly adopting whatever is in it. That refusal is
the point of splitting the states: the two cases want different behaviour, and
one button doing both had to guess which the user meant.

**The unconfigured state is listed, not just repairable.** The members table
gained a **Config** column and now shows those folders as `missing`, in the
same red the Batch table uses for a Blocked Member. A table showing only
members says a half-set-up Project is a complete one. Double-clicking such a
row offers to scaffold its config, because the row is one write away from
being a member and sending the user hunting for a button is worse.

## What "initialize" does *not* do here

Upstream's equivalent also **files**: a DTrack export loose at the experiment
root is moved into `data/` before the config is written, because its loader
reads `data/` alone. There is nothing to file here — `data_file` searches
`data/` *and then* the directory root (ADR-0009) — so initializing writes the
config and moves nothing. What it does do that upstream cannot is settle the
one state a scaffold leaves blocked: a directory holding several candidate
files is asked which one is the experiment, and the answer goes into
`data_file:` where the next run reads it.

## The project.yaml editor, and what it is not

Three of the four ways into a Project share one dialog, because the design
half is identical and only the directory and the name differ. It edits the
name, the question, the Experiment Type and the Project Defaults, and it
**carries through everything it does not own** — `scripts:`,
`experiment_scripts:`, a key from a future version — the same promise
`config.py` makes about unknown keys.

Its group box is labelled *Project Defaults — seeded into every new member*,
never "shared design". Upstream's dialog edits an authority every replicate is
hard-validated against; this one edits a seed (ADR-0001). That difference is
why **Copy config from…** checks a copied config against the Experiment Type
and nothing else: differing factors and levels are Divergence, declared on the
report, and refusing them would enforce a uniformity the Project deliberately
does not have.

**There is no Config Editor for a member.** Upstream has a whole window for
`tracking_config.yaml` because a rig and its region treatments are not
hand-editable; a `survival_config.yaml` is a dozen lines. **Edit config…** in
the Experiment configs dialog hands the file to the desktop's own editor. A
half-built form that silently dropped the keys it did not know would be worse
than the text file.
