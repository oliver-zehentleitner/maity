### Fixed

- hub: the readiness probe on MariaDB stops waiting for a hung statement after 5 s (the driver's `read_timeout`), as on PostgreSQL
