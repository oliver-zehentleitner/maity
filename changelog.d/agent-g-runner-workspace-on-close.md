### Added

- contract: §15.5, a runner removes a placement's clone after the placement closes, so the clones of agents that
  no longer run there do not fill the disk. A stop, a start, a restart, a rejoin and an adoption keep it. The
  runner removes it only for a placement the hub lists as closed (`GET /runner/placements?closed=true`), under the
  checks of `maity runner gc`; uncommitted or untracked files, unpushed commits and stashes keep it. It reports
  the outcome with `POST /runner/placements/{id}/workspace`, shown as the placement's `workspace_outcome` and in
  `maity runner status`; a removed clone's credential is revoked (`workspace_removed`). `maity runner check`
  warns when the workspaces' file system is low on space.
