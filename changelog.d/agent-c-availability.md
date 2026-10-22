### Added

- cli: `maity limit --until <time> [--reason R]` (§6.11, §13) — a duration (`90m`, `1h30m`,
  `2d12h`) or an RFC 3339 time with an offset, sent in UTC, at most 7 days ahead; a time
  without an offset is refused locally. `maity resume` prints the `Availability` block
  (whom you cover, with the handed-over ids; peers that are not available) and marks
  handed-over cards and requests `(cover for @<handle>)`.
- cli runner: `rate_limited` (§15.7) — the supervised loop exits 22 for a provider limit
  its adapter recognises by a verified signal (none yet), and the runner reports
  `rate_limited`/`quota` with the harness's exit code and `retry_at` (the named reset,
  capped at 7 days, or 15 minutes doubling to 2 hours with `reset_unknown`); the placement
  keeps its slot, is not counted as a crash, and a stop ends it at once.
