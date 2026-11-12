### Added

- hub: a placement's `workspace_retention` (`immediate`, `3h`, `24h` by default, `7d`),
  set at creation and changed by `PATCH` without a new generation, by the agent profile's
  owner too and also after the placement closed; `workspace_epoch` and `workspace_outcome`
  in its view (docs/api.md §15.5, tsk-34gb7frfbsk7). The runner's clock and removal follow.
- hub: `POST /runner/placements/{id}/workspace`, the runner's report on a stopped or closed
  placement's clone (`retained`, `kept`, `removed`) without `Idempotency-Key`; `removed`
  revokes the placement's credential (`workspace_removed`) unless another running placement
  names it, sets `rejoin` on an active placement and raises `workspace_epoch` (§15.8).
- hub: `GET /runner/placements?closed=true`, the runner's closed placements whose clone it
  has not reported removed, also after a detach (§15.8).
- hub: `POST /projects/{owner}/{slug}/placements/{id}/workspace/remove`, a removal of a held
  clone asked by the agent profile's owner or a project admin, humans only (§15.6).

### Changed

- hub: `GET /projects/{owner}/{slug}/placements?closed=true` also lists older closed
  placements whose clone is still held; `desired: running` clears `workspace_outcome`; a
  closed placement whose clone was reported removed no longer makes `continues_existing`.
