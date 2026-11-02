### Fixed

- ci: `hub-sqlite`, `hub-postgresql` and `hub-mariadb` fail after 90 minutes; a hanging test held main's ci run for six hours, so no run on main finished and the MariaDB start never came.
