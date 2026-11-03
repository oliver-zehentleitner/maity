### Changed

- hub tests: when the cleanup between tests on PostgreSQL times out, it now ends only the client sessions of the suite's own role that hold a lock on the tables it empties or on the sequences they own; when it finds none, its message says so; a session on another table, in another database or of another role is left alone, and one that cannot be ended is named without keeping the others from being ended. The README states that the test database is the suite's alone.
