### Fixed

- Hub: a member's join checks its role's base again under the project's lock, at creation and
  at the exchange: a project role created on `ops` or moved there meanwhile is refused at
  creation (`member_join_limit`, field `role`) and voids a pending first join at the exchange
  (`not_found`), instead of giving the agent a membership on `ops` (docs/api.md §3.1).
