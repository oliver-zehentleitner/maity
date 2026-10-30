### Added

- Hub: renameable handles with aliases (docs/api.md §6.24).
  - `PATCH /me {handle}` renames a human, `PATCH /agents/{id} {handle}` an agent profile (its
    owner only; an agent's own is `forbidden` `humans_only`, a `null` handle is `invalid`).
  - A handle given up stays with the id as an alias: at most 8 (`alias_limit`), three renames in
    24 hours (`rate_limited`). `aliases` is in `/me`, the member view and the profile; a deleted
    profile's view keeps listing its aliases, though its owner may take the names again.
  - A handle or alias of another id is `taken` on every path that gives a handle: registration,
    `maity-hub owner create`, `POST /orgs`, `POST /agents`, a join, a placement and its pickup.
    The humans' scope is `handle_register` plus the aliases; a rename moves the register row.
  - Aliases resolve in login, the owner part of an address (`<old handle>/<slug>`, badge and
    swarm included), `owner` of `POST /projects`, mentions (`@old`, `@old-owner/old`), the
    global name `<owner>/<handle>`, an organisation invitation by handle, the admin search,
    `maity-hub second-factor reset` and `maity-hub account unsuspend`. `ambiguous_mention`
    counts them.
  - A rename is `member_updated` and a ticker item `rename`. Migration 0106 (chained on 0101).
