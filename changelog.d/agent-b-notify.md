### Added

- hub: on PostgreSQL a long-poll wakes when another replica writes: `events.emit` sends
  `pg_notify('maity_events', '<project>:<seq>')` in the writing transaction, and each hub process
  listens on one connection outside the pool; a lost connection wakes every waiter once (spread
  over 2 s) and is opened again. New optional `MAITY_DIRECT_DATABASE_URL` for that connection past
  a pooler (hub/context/replicas.md 387c2409, points 1 and 2).

### Fixed

- hub: a rate count given back for work that did not happen returns to the window it was counted
  in (`Limiter.place`/`release` with a count; `give_back` is gone), `Limiter.blocked` answers as
  `hit` would when the previous window is weighted, and a count over a limit is refused as a
  programming error instead of answered with a `Retry-After` that never comes true.
