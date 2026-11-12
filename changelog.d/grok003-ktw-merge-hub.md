### Added

- hub: the project setting `why_merge_children` (§6.1). It is a boolean that
  reads `true` for new and existing projects without anything written to
  them; `false` is stored, `null` restores the default, anything else is
  `not_a_boolean`. A human with `project:admin` sets it, no agent does
  (`humans_only`), every member reads it with the project, and a change of
  what it reads as emits `project_updated`. The dashboard does not read it
  yet; the merged Why view follows in its own pull request.
