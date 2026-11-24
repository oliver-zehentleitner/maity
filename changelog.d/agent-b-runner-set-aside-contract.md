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
  `detail: workspace_set_aside` (§15.7; a refused report or a failed rename is
  `workspace_in_use` with `workspace_set_aside_failed`). `set_aside` is the runner's own report,
  like `removed`: no member right is checked, it stops nothing, and a credential revoked before
  keeps that revocation, so after one only the agent profile's owner may undo, the rejoin still
  waits for that owner (§15.6). A failed rename keeps the hub's state, and the next start
  reports `set_aside` again at the new epoch; a taken name gets `-2`, `-3`, …, never an
  overwrite. A set-aside clone is removed by hand, named by `maity runner status` with its
  unsaved count, counted by git with the clone's configuration and hooks ignored, as gc's;
  `gc --revoked` does not take it yet (tsk-nnv2dg7j3bd4). Every other path in the other layout
  stays `workspace_in_use`. Not built yet (tsk-9f69y1hr1m6z).
