### Fixed

- hub: `POST /runner/hello` and `PATCH /runner` take the confinement `sandbox` (§15.3), which
  the CLI advertises for `codex`. Before, the hub refused the hello of every runner whose
  configuration lists codex (`invalid`), and the runner stopped. A test keeps the values the
  CLI can advertise inside the hub's, and the hub's equal to the contract's.
- web: Runners shows a codex tool as "without a command allowlist: its OS sandbox is the only
  boundary", or "…, and its OS sandbox is off" when the runner reports it off.
