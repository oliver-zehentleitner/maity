### Added

- Hub: the human who owns an agent may change its role with `PATCH …/members/{id}` `{"role"}`
  without `members:admin`, while they could create a join for it now, to a role a member join
  could give (docs/api.md §3.1 "The owner changes the role"). Otherwise the call is `forbidden`
  with `member_join_limit` (field `role`) or `join_rule`. Other fields from such an owner stay
  `members:admin`.
