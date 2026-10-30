### Added

- hub: every PostgreSQL connection sets `application_name` (`maity-hub`, `maity-hub-health` for the readiness probe, `maity-hub-cli` for `migrate` and the other commands), so `pg_stat_activity` shows who holds it
