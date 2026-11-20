### Fixed

- ci: the release gate stops when it cannot read the jobs of `hub-mariadb.yml`
  at a run's commit, or reads no `hub-mariadb` job there, instead of reading
  the 11.8 job as one the file predates and letting 11.4 count alone; also
  when the run lists a `hub-mariadb*` job it did not read from the file. It
  now also reads a comment after `jobs:`, quoted job keys and any indent;
  `jobs:` must be the last top-level key of `hub-mariadb.yml`.
- hub: the reserved-word test also judges the tables of `create_foreign_key`,
  `create_primary_key`, `create_check_constraint`, `drop_constraint` and
  `drop_index(table_name=)`, the target of a `ForeignKey` and the
  `refcolumns` of a `ForeignKeyConstraint` (string or tuple), and names
  written through `sa.schema.conv`.
