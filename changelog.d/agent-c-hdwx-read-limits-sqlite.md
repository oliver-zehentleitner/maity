### Changed

- hub: on SQLite, the read routes of cards, card history and notes, the overview, the swarm,
  the request lists and the probe no longer take the database's write lock. A read and a
  write of the same instance no longer wait for each other, and two reads run side by side.
  A transaction that only reads is opened as such and cannot write. PostgreSQL and
  MySQL/MariaDB are unchanged.
