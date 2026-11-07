### Changed

- docs/api.md §3.1, §6.2: the human who owns an agent may change its role after the join with
  `PATCH …/members/{id}`, within the nine roles a member join allows (never `ops`, `proxy` or a
  project role) and while they could create a join for it now; `trust`, `areas` and
  `capabilities` stay `members:admin`. New `forbidden` reasons for this call:
  `member_join_limit` with `details.field: "role"` and `join_rule`.
