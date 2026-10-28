### Fixed

- hub: migration 0060 creates `project_alias` with the `utf8mb4_bin` collation on MariaDB too (the `mariadb_` table options beside the `mysql_` ones); before, MariaDB refused its foreign keys (errno 150)
