### Added

- cli: the runner's operator commands (runner slice R6b, design v2 §10.1) — `maity runner logs
  <placement|agent> [--follow]`, `approve` (with `limits.require_local_approval`, new
  placements wait as `pending`/`awaiting_operator`), `stop-all [--grace N]` (refused while the
  service runs), `gc --revoked [--yes]` (revocation asked through each clone's own CLI, git
  read with hooks, fsmonitor and pagers off) and `workspace claim <project>/<clone> --agent`.
