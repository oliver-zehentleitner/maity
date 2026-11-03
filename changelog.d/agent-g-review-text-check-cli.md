### Added

- CLI: `maity say --type review_result` checks the message's text before it sends: a file and line,
  a name in a code span (at the head or on the default branch) and an object hash must be there,
  and the section under `## Ran` and fenced blocks are left out. A text that names something that is
  not there is not sent (exit 1), with one line per name (docs/api.md §8.4).

### Changed

- docs/api.md §8.4: a path in a code span that is no file still passes as text in a file (routes),
  an object hash needs a digit, and a hub id is `[a-z]+-[0-9a-z]{12}`.
