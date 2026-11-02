### Fixed

- ci: a hanging job no longer holds main's ci run for six hours: the database jobs (`hub-sqlite`, `hub-postgresql`, `hub-mariadb`) stop after 90 minutes and the other jobs `ci-ok` waits for after 30; a MariaDB run stopped that way opens or comments on the `ci-red` issue like a red one.
