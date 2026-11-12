### Added

- contract: §15.5, a runner removes a placement's clone once the placement has stopped (or closed) for its
  `workspace_retention`: `immediate`, `3h`, `24h` (the default) or `7d`, set with the placement. A start within
  that time continues in the same clone. The runner removes a clone only on the hub's word, under the checks of
  `maity runner gc`; uncommitted or untracked files, unpushed commits and stashes keep it however long the
  retention. It reports `retained` (with the deadline and the size), `removed` or `kept` with
  `POST /runner/placements/{id}/workspace`, shown as the placement's `workspace_outcome`; the owner can have a
  kept clone removed by hand (`POST …/placements/{id}/workspace/remove`). A removed clone's credential is revoked
  (`workspace_removed`) and the next start joins anew. `maity runner check` warns when the workspaces' file system
  is low on space.
