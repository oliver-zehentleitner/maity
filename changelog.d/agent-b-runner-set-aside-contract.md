### Changed

- contract: a runner start that finds the same agent's clone of the other layout at the clone's
  path (a plain clone where antigravity needs a workspace folder, or the reverse), after a new
  placement on that runner and clone or a changed `harness`, sets it aside instead of failing
  with `workspace_in_use` (§15.5). The runner first reports the new workspace state `set_aside`
  (§15.8): the hub revokes the old credential with the new reason `workspace_set_aside` (§10),
  sets `rejoin` and raises `workspace_epoch`; with no credential it revokes nothing, and a
  credential another running placement names is `conflict` (`credential_in_use`). Then the
  runner renames the clone whole to `<workspaces>/<project_id>/.replaced-<time>-<clone>`,
  deleting nothing and running no git there, makes a new clone and joins anew, reported with
  `detail: workspace_set_aside` (§15.7). `set_aside` follows the same owner rule as revoke
  (§15.6). The set-aside clone is kept as a stopped clone is. Every other path in the other
  layout stays `workspace_in_use`. Not built yet (tsk-9f69y1hr1m6z).
