### Changed

- docs/api.md §8.3: a held `GET /projects/{owner}/{slug}/events?wait=N` reads in full on its
  first pass. On later passes it looks at the project's highest `seq` with the reader's checks,
  and reads only when an event lies past its cursor. An idle wait costs one statement a pass
  instead of about four. Answers, wake-ups and the ends of a wait are unchanged; the runner's
  stream is not changed.
