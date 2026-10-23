### Added

- docs/api.md §8.8: `GET /projects/{slug}/messages` — the project's messages (every type but
  `chat`) as one listing, newest first with `before=`/`after=` starting points and cursor paging,
  a repeatable `type` filter, the readable set of `GET /events`, redacted messages as tombstones,
  mentions and attachment metadata; §12 index row and a planned `maity messages` in §13.
