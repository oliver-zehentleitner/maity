### Fixed

- `maity-hub migrate` on PostgreSQL no longer fails when it deadlocks with the running hub. The
  chain stays one transaction, its session has a 5 s `lock_timeout`, and after a deadlock or a
  lock timeout the whole chain is run again, up to five attempts. A run that gives up says the
  revision the schema stayed at (tsk-cvxtjnep4bqj).
