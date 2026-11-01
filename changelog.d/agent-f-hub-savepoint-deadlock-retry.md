### Fixed

- hub: a deadlock inside a savepoint on MariaDB is run again like any other deadlock, instead of answering `503 database_unavailable`; the log line of a database failure also gives the driver's number
