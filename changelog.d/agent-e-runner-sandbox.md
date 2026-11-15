### Fixed

- hub: `POST /runner/hello` and `PATCH /runner` take the confinement `sandbox` (§15.3), which
  the CLI advertises for `codex`. Before, the hub refused the hello of every runner whose
  configuration lists codex (`invalid`), and the runner stopped. A test keeps the values the
  CLI can advertise inside the hub's, and the hub's equal to the contract's; it runs in CI's
  contract job, which a change of the CLI's capabilities now starts too.
- docs: docs/runners.md says that a runner with codex needs a hub of 0.1.0a8 or newer.
- web: Runners shows a codex tool as "without a command allowlist: its OS sandbox is the only
  boundary", or "…, and its OS sandbox is off" when the runner reports it off.
