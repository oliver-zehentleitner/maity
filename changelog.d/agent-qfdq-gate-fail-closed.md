### Fixed

- ci: the release gate tells whether a hub-mariadb run had to run
  `hub-mariadb-11-8` from git, not from the workflow file: a run whose
  workflow commit comes after the commit that added the job (#2022) needs
  it green. Before, a layout of `hub-mariadb.yml` its reader did not know
  read as a file from before the job and let 11.4 count alone. A history
  git cannot answer from (a shallow checkout, a missing commit), or a
  `hub-mariadb*` job the gate does not know, stops the gate.
- hub: the reserved-word test also judges the tables of `create_foreign_key`,
  `create_primary_key`, `create_check_constraint`, `drop_constraint` and
  `drop_index(table_name=)`, the target of a `ForeignKey` and the
  `refcolumns` of a `ForeignKeyConstraint` (string or tuple), and names
  written through `sa.schema.conv`.
