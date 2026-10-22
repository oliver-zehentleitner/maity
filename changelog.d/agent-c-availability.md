### Added

- cli: `maity limit --until <time> [--reason R]` (§6.12, §13) — a duration (`90m`, `1h30m`,
  `2d12h`) or an RFC 3339 time with an offset, sent in UTC, at most 7 days ahead; a time
  without an offset is refused locally. `maity resume` prints the `Availability` block
  (whom you cover, with the handed-over ids; peers that are not available) and marks
  handed-over cards and requests `(cover for @<handle>)`.
- cli runner: `rate_limited` (§15.7) — the supervised loop exits 22 for a provider limit
  its adapter recognises by a verified signal (none yet), and the runner reports
  `rate_limited`/`quota`/`reset_unknown` with the harness's exit code (read from a regular
  file on the agents' side, bounded, as their user) and `retry_at` 15 minutes doubling to 2
  hours, the row starting over after a session that ran longer than `quick_exit`; the
  placement keeps its slot and takes it back at the restart, is not counted as a crash,
  and a stop ends it at once.
