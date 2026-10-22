### Added

- cli: the runner's operator commands (runner slice R6b, design v2 §10.1) — `maity runner logs
  <placement|agent> [--follow]`, `approve` (with `limits.require_local_approval`, new
  placements wait as `pending`/`awaiting_operator`), `stop-all [--grace N]` (refused while the
  service runs), `gc --revoked [--yes]` (revocation asked through each clone's own CLI,
  active placements asked of the hub, git run only in a clone whose `.git` has a plain
  clone's entries of the expected types (no `commondir`, attributes, submodules, alternates
  or symlinks) and whose configuration has a
  plain clone's keys, pinned to that clone without the operator's `GIT_*`, nothing removed that git could not
  read; `--yes` with the service stopped) and `workspace claim <project>/<clone> --agent`.
