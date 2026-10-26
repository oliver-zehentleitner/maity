### Fixed

- hub: the notifications long-poll no longer derives every item again each half second
  while it holds. It compares a few aggregates first (each project's highest event, the
  account records, the read and chat marks) and runs the full answer only when one of them
  moved. At most four full notification answers or marks run at once per hub, so they
  cannot take the connection pool from every other call. Two `POST /me/notifications/read`
  of the same items at once no longer fail on the key: the marks are written in one
  statement that skips existing rows, at READ COMMITTED; chat marks likewise.

### Added

- hub: `MAITY_DB_POOL_SIZE` and `MAITY_DB_MAX_OVERFLOW` (defaults 5 and 10, as before) size
  the server database's connection pool. The hub runs no more request threads than the
  two together.
