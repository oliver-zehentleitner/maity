### Changed

- hub: every call authenticates on the async engine (`deps._resolve` through
  `AsyncConnection.run_sync`) instead of a thread of the pool: one thread hop fewer for every
  call (tsk-v874y63b4z8p, PR 2). The authentication transaction is unchanged; on a server
  database it now takes one of the async engine's connections (`MAITY_DB_ASYNC_POOL_SIZE`).
- hub: the `stats` line also names the async engine's pool (`async_pool_open`,
  `async_pool_checked_out`, `async_pool_max`).
