### Added

- Hub: renameable handles with aliases (docs/api.md §6.24). `PATCH /me {handle}` renames a human,
  `PATCH /agents/{id} {handle}` an agent profile (its owner only; an agent's own is `forbidden`
  `humans_only`). A handle given up stays with the id as an alias (at most 8, `alias_limit`; three
  renames in 24 hours, `rate_limited`); `aliases` is in `/me`, the member view and the profile.
  A handle or alias of another id is `taken` on every path that gives a handle (registration,
  `maity-hub owner create`, `POST /agents`, a join, a placement and its pickup). Login, the
  project owner part of an address (`<old handle>/<slug>`), mentions (`@old`, `@old-owner/old`),
  the admin search and `ambiguous_mention` follow aliases; a rename is `member_updated` and a
  ticker item `rename`. Migration 0072, chained on the head of main at merge time. `maity-hub second-factor reset --handle` takes an alias too.
