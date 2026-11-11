### Changed

- hub: every call authenticates on the async engine (`deps._resolve` through
  `AsyncConnection.run_sync`) instead of a thread of the pool: one thread hop fewer for every
  call (tsk-v874y63b4z8p, PR 2). The authentication transaction is unchanged; on a server
  database it now takes one of the async engine's connections (`MAITY_DB_ASYNC_POOL_SIZE`).
- hub: `MAITY_DB_ASYNC_POOL_SIZE` defaults to 8 of each process's pool share, but at most half
  of it, instead of 2: the default 16 splits 8 + 8, a pool of 8 gives 4 + 4, two workers on it
  2 + 2 each. Still carved out of `MAITY_DB_POOL_SIZE`, so the hub asks the database for no more
  connections than before, and the sync engine keeps the rest and the whole overflow. A value
  that is set still holds up to all but one of a process's share.
- hub: the `stats` line also names the async engine's pool (`async_pool_open`,
  `async_pool_checked_out`, `async_pool_max`), counted on a file SQLite too.
- hub: the process's nonce window (SQLite, MariaDB) drops expired nonces oldest first from a
  queue in expiry order, at most 64 per call, instead of walking every live nonce on each call
  once it holds more than 10,000; the authentication runs on the event loop now, where that walk,
  or dropping a whole expired burst at once, would hold every other request of the process.
