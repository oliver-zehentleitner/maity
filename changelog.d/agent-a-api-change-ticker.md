### Added

- docs: the change ticker in the API contract (`docs/api.md` §17) — one
  short item (280 characters and a link) per merge, contract change,
  inbox decision, deploy and release, as the event kind `ticker`; the hub
  computes the audience (area owners and linked cards' holders, contract
  section implementers and admins, a decision's implementers, every
  member for deploys and releases) and only that audience is woken;
  merges from the forge probe, with an optional signed webhook as a
  trigger; `GET`/`POST /projects/{slug}/ticker`, follow and mute per
  member, the `ticker:post` scope for owners and admins, dedupe by key,
  `ticker` in the resume packet, and `maity ticker` rows in §13.
