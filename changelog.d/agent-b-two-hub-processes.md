### Added

- hub: a test starts two real hub processes on one PostgreSQL and checks across them that a wait wakes from a write on the other, a newer wait supersedes the older, a rate limit counts once and a nonce is refused.
