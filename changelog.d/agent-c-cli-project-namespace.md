### Changed

- cli: project routes are `/projects/<owner>/<slug>/…` (§6.25); the state keeps the project's
  `full_name`, refreshed by every `maity resume`, and a state from before the namespace reads
  it once from `GET /me`; `client_outdated` (426) prints the minimum version and the upgrade
  line; `maity resume` shows the full name and names `<owner>/<slug>` in its read-more hints
- cli runner: the project namespace (§6.25, §15.5). Placements need a full name and a `project_id`;
  clones live at `<workspaces>/<project_id>/<clone>` and tmux sessions are named by the id, so a
  rename or transfer keeps the clone; a clone recorded before the namespace under its slug is
  taken over in place for the same agent; `limits.projects` takes full names only, matched
  against the current name and `project_aliases`; the status file lists `project_id`

### Fixed

- hub: migration 0060 creates `project_alias` with the `utf8mb4_bin` collation on MariaDB too (the `mariadb_` table options beside the `mysql_` ones); before, MariaDB refused its foreign keys (errno 150)
