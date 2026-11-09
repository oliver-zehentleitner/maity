### Changed

- contract, hub: a runner's `join_failed` report takes any of the hub's error codes as its
  `detail` (`docs/api.md` §15.7), in the form `^[a-z][a-z0-9_]{0,63}$`. Any other text is still
  `invalid`, and the other detail lists stay closed.

### Fixed

- cli: `maity runner serve` reports a failed join with the hub's reason instead of `detail: null`:
  the pickup's or the join's error code, and for a `forbidden` the rule that refused
  (`instance_quota`, `member_join_limit`, `member_agents_max`, …). A pickup's 404 still carries
  no detail.
- cli: `maity runner serve` prints one line to stderr for each new state of a placement, with its
  reason, detail and generation, and never a URL or a code.
