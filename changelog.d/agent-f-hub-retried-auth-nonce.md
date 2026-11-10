### Fixed

- hub: on SQLite and MariaDB a signed request whose authentication is run again after a deadlock no longer answers `401 nonce_reused`
