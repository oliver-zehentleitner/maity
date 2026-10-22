### Added

- docs: the change ticker in the API contract (`docs/api.md` §17) — one
  short item (280 characters and a link) per merge, contract change,
  inbox decision, deploy and release, as the event kind `ticker`; the hub
  computes the audience (area owners and linked cards' holders, contract
  section implementers and admins, a decision's implementers among the
  readers of its request, every member for releases) and only that
  audience is woken; automatic deploys are listed for everyone and wake
  no one; decision items reach only readers of the request; merges from
  the forge probe only, with an optional signed webhook as a trigger;
  `GET`/`POST /projects/{slug}/ticker` (no manual merge), follow and mute
  per member, the `ticker:post` scope for owners and admins, dedupe by key,
  `ticker` in the resume packet, and `maity ticker` rows in §13.
