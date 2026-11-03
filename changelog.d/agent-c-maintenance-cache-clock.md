### Fixed

- hub tests: the maintenance window's 5 s cache no longer expires on its own during a test, so a statement-counting test on a slow runner stops seeing the window read again (+2 on PostgreSQL, +3 on SQLite). The cache's clock is `maintenance.monotonic`, held still by the test fixture.
