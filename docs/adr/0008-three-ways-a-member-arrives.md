# A member arrives three ways, and the Project always owns its data

The Project card had one "Add member…", which scaffolded an empty directory.
Everything else — a folder from a collaborator, a workbook sitting in a
downloads directory, a file dropped loose in the project tree — had to be
arranged by hand in a file manager before the Hub could see it. Real members
arrive in three shapes, so the card offers three buttons:

- **Add directory** takes an existing experiment directory. It must hold a
  `data/` subdirectory with an .xlsx that validates as a DLife workbook
  (`data_loader.validate_dlife_workbook`: Design and RawData sheets, the
  columns each needs, at least one factor after `StartTime`). A directory that
  is not already a direct child of the Project is **copied** in.
- **Create directory** is the old behaviour, unchanged: name a directory, get
  a `data/` folder and a default config to fill.
- **Add experiment** builds a member around one workbook: the member is named
  after the file's base name, the file lands in its `data/`, and a default
  config is written. A file already inside the Project tree is **moved**, not
  copied.

**Copy in, never reference.** A member analysed in place from outside the
Project would write `analysis/`, `qc/` and `figures/` outside the Project, so
a Project Report would bind sections that live somewhere else and a Batch Run
would touch directories nobody listed. The Project owns its members' data.

**Move when it was already ours.** A workbook loose in the Project tree is
already the Project's; copying it would leave two files with equal claim to
being a member's data, and `Experiment.data_file()` refuses an ambiguous
directory rather than guessing. Moving keeps exactly one.

**An adopted config is minimal, like a scaffolded one.** It records only what
the file itself can say — `input:` format, and `assume_censored` when the
workbook's PrivateData sheet disagrees with the Project's default. Everything
else stays inherited from `defaults:`, so later edits to the Project keep
reaching an adopted member (the rule `add_member` already followed). A
directory that arrives with its own `survival_config.yaml` keeps it untouched.

Adoption never overwrites: a destination that already exists is an error
naming it, not a merge.

## Amended by [ADR-0010](0010-three-states-not-three-origins.md)

Two of these three still stand as written. **Create directory** was never
really an origin — "there is no folder yet" is a *state* — so it is now called
**Create experiment…** and sits with the other two state buttons, where it
refuses a name whose folder already exists instead of adopting whatever is in
it. **Add directory** and **Add experiment** are unchanged, and keep their
place on the card under a divider: they are the two ways in from *outside* the
Project, and everything above the divider stays inside it.
