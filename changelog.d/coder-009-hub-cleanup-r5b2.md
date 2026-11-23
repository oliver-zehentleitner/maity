### Changed

- hub: clean-up from audit round 5, batch 2 (no change to any answer): `PATCH /me` and
  `POST /me/limit` share one all-or-nothing loop over an instance's attachments
  (`attached.per_attachment`), which reads the attachments twice instead of three times; one
  `refuse_if_isolated` for the four places that refuse an isolated attachment; the runner's
  view of a placement (`GET /runner/placements`, hello) reads only the agent's id and handle,
  no longer its owner's handle and its picture; a revocation reads the instance's live
  attachments twice instead of four times (`instances.live_attachments`), and `GET /projects`
  for an agent reuses the caller's attachment read; one `Effort` type for a runner's offered
  efforts and a placement's effort.
