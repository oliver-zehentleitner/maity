### Changed

- hub: every call authenticates on the async engine (`deps._resolve` through
  `AsyncConnection.run_sync`) instead of a thread of the pool: one thread hop fewer for every
  call (tsk-v874y63b4z8p, PR 2). The authentication transaction is unchanged; on a server
  database it now takes one of the async engine's connections (`MAITY_DB_ASYNC_POOL_SIZE`).
- hub: `MAITY_DB_ASYNC_POOL_SIZE` defaults to 8 instead of 2, still carved out of
  `MAITY_DB_POOL_SIZE`: with the default 16 the sync engine keeps 8 and the whole overflow, and
  the hub asks the database for no more connections than before. A pool below 9 gives the async
  engine all but one of it.
- hub: the `stats` line also names the async engine's pool (`async_pool_open`,
  `async_pool_checked_out`, `async_pool_max`), counted on a file SQLite too.
- hub: the process's nonce window (SQLite, MariaDB) drops the expired nonces oldest first from a
  queue in expiry order instead of walking every live nonce on each call once it holds more than
  10,000; the authentication runs on the event loop now, where that walk would have held every
  other request of the process.
