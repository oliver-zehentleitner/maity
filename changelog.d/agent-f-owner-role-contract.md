### Changed

- docs/api.md §3.1, §6.2: the human who owns an agent may change its role after the join with
  `PATCH …/members/{id}`, to a role a member join could give (one of the nine, or a project role
  built on one of them; never `ops` or `proxy`) and while they could create a join for it now; `trust`, `areas` and
  `capabilities` stay `members:admin`. New `forbidden` reasons for this call:
  `member_join_limit` with `details.field: "role"` and `join_rule`.
