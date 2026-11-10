### Changed

- hub: a lost savepoint on MariaDB is run again only when a deadlock caused it, and the log line of a database failure names the error behind it (`behind=`); a lock wait timeout (`1205`) is no longer listed as retryable, which it never was in effect
