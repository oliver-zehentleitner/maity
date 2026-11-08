### Fixed

- `maity-hub migrate` on PostgreSQL retries after it deadlocks with the running hub or does not
  get a lock within 5 s (`lock_timeout`): the chain stays one transaction and is run again from
  the start, up to five attempts; after the last one it fails as before and says the revision the
  schema stayed at (tsk-cvxtjnep4bqj).
