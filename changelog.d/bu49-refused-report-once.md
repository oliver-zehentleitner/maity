### Added

- hub: the `harness_refused` detail `codex_host_too_old` (docs/api.md §15.7): a Codex
  placement on an ssh target whose `maity` is too old for the Codex launch-write op.

### Fixed

- cli: the runner no longer sends a placement report the hub refused as `invalid` again on
  every tick. When only its `detail` was refused, it sends the report once more with
  `detail: null` and the same `seq`; any other `invalid` it logs once and drops, and the next
  change reports afresh. A report that met no answer, `429`, a `5xx` or a maintenance window
  is still sent again on the next tick (§15.8).
- cli: the runner's refusal of a Codex placement on an ssh host whose `maity` is too old now
  reports the detail `codex_host_too_old`, so the reason reaches the hub and not only the
  runner's log.
