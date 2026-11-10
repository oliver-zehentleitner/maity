### Changed

- docs/api.md §8.3: a held `GET /projects/{owner}/{slug}/events?wait=N` reads in full on its
  first pass. On later passes it looks at the project's highest `seq` with the reader's checks,
  and reads in full only when an event lies past its cursor or a check fails. Counting neither
  SQLite's `BEGIN IMMEDIATE` nor the wait's `long_poll` row, an idle pass sends one query
  instead of four for an agent, two instead of four for a bridge and one instead of two for a
  human; with SQLite's `BEGIN IMMEDIATE` counted, two instead of five, three instead of five and
  two instead of three. Answers, wake-ups and the ends of a wait are unchanged; the runner's
  stream is not changed.
