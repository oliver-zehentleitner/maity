### Fixed

- hub: migrations and notification positions work on MariaDB 11.7 and newer:
  the column `notification_position.vector`, a reserved word there, is
  quoted in the table and in migration `0034`. Up to 0.1.0a10, `maity-hub
  migrate` failed on a new database on MariaDB 11.7+, and on an existing one
  storing a notification position failed. Upgrade the hub before the MariaDB
  server.

### Added

- ci: `hub-mariadb` also runs the migrations, the schema checks and the
  notification tests on MariaDB 11.8 LTS.
- docs: the supported database versions (`docs/install/README.md`, Database
  versions): MariaDB 11.4 LTS and 11.8 LTS.
