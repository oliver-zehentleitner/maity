### Fixed

- hub: a change of a project's restricted-access set no longer notifies the human who made
  it, as the event's `by` names them, on every path: a setting change, a join exchange, an
  organisation keep and the others. The other humans in the set who are not among the
  members it names are told as before (§6.4, §18.1).
- hub: the notice of a jour fixe slot skipped because nobody could moderate it is listed,
  and mailed, only to a human who keeps the series at read time. Before, a human who no
  longer held `project:admin` kept seeing it for a series of every member, and could be
  mailed it, for its 30 days (§18.1, §20.9).
