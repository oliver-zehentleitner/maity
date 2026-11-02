### Fixed

- hub tests: `test_online_uses_canonical_presence` waits with the new `listening.written()` until the close of a wait has reached the database, so on PostgreSQL the badge read right after it no longer finds the wait's row (304 instead of 200).
