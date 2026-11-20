### Fixed

- ci: the release gate stops when it cannot read the jobs of `hub-mariadb.yml`
  at a run's commit, or reads no `hub-mariadb` job there, instead of reading
  the 11.8 job as one the file predates and letting 11.4 count alone. It now
  also reads a comment after `jobs:`, quoted job keys and any indent.
- hub: the reserved-word test also judges the tables of `create_foreign_key`,
  `create_primary_key`, `create_check_constraint`, `drop_constraint` and
  `drop_index(table_name=)`, a `ForeignKey("table.column")` target and names
  written through `sa.schema.conv`.
