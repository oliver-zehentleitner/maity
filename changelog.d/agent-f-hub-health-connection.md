### Added

- hub: `MAITY_DB_STATEMENT_TIMEOUT` (30 s) and `MAITY_DB_IDLE_IN_TRANSACTION_TIMEOUT` (60 s) are set on every PostgreSQL connection of the serving hub; 0 turns one off, and `maity-hub migrate` and the other commands take none

### Changed

- hub: `GET /api/v1/health` reads the database over a connection of its own outside the pool (a server database; connect and statement timeout 5 s), so a pool that is used up no longer fails the readiness probe
