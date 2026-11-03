### Changed

- hub tests: when the cleanup between tests on PostgreSQL waits too long for a lock (a test left a connection open in a transaction), it now names the sessions holding the locks, with their last statement, ends them, and fails only that one test. Before, every later test of that worker failed again after 60 s.
- hub: when the listening registry stops, it always drops the writes still queued, also when its writer is still in a write; in tests the next app's writer wrote them into its own database.
