### Changed

- hub: who a public page names lives in one module (`public_members`: `Person`,
  `members`, `shown_data`, `holder_data`, `pictured`, `person_data` and
  `shown_pictures`); `team()` is the shown members of that read, split by human,
  in the database's handle order, as before (a PostgreSQL locale orders a hyphen
  differently from Python). The lists of served projects were already set-based
  (`served_of`, since #2077); `/explore` is left as it is until #2227 and #2233
  merge. No page changes: every stored page, its `data` and the public routes'
  answers are the same.
