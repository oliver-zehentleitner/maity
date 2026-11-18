### Added

- hub: stars per account (§5.1 "Stars"). A human's `GET /me` carries `starred`,
  the public projects they keep as tabs without a membership, as `[{id, full_name}]`
  in the order starred; `PATCH /me` `{"starred": [...]}` sets the whole list
  (`invalid` with `not_public`, `member`, `duplicate` or `too_many`; from an agent
  `forbidden`, `humans_only`). A starred project that is not public now is hidden
  from the read and kept in its place; joining a project drops its star. The export
  carries the stars, the account deletion clears them; nobody else sees them.
- hub: `max_starred_per_human` (`MAITY_MAX_STARRED_PER_HUMAN`, default 100, 1–1000,
  no `unlimited`) under `/admin/settings/limits` and in the settings overview;
  lowering it keeps the stars a human holds. No per-account override yet (§16.5.1).
