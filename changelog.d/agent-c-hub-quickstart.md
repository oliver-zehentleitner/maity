### Added

- hub: `maity-hub quickstart` for a personal hub on SQLite. It runs `migrate` on a
  new, empty database, `owner create` while there is no human (the handle defaults
  to the login name), and then `serve`. A database behind the current schema, or a
  database URL other than SQLite, is refused. `serve` and `quickstart` now print the
  dashboard's address as their last line, once the hub listens.
